"""Explicit overlap acquisition cannot widen identity, resume or write scope."""
import json
from uuid import UUID, uuid4

import pytest

from app import reference_asking_backfill as worker
from scripts.backfill_reference_asking import arguments
from test_reference_asking_backfill import (
    ACTOR, NOW, Connection, ready, reference, report, run_now, sql_dependencies,
)


def test_missing_only_scope_is_byte_compatible_with_previous_run_receipts():
    assert worker.acquisition_scope() == report()["scope"]
    assert worker.acquisition_scope(include_priced=False) == report()["scope"]


def test_exact_selection_is_canonical_and_does_not_modify_input():
    a, b = worker.cursor_for(reference("a")), worker.cursor_for(reference("b"))
    keys = [b, a, b]
    scope = worker.acquisition_scope(include_priced=True, reference_keys=keys)
    assert scope == {"system_code": None, "language": None,
                     "include_priced": True, "reference_keys": [a, b]}
    assert keys == [b, a, b]


@pytest.mark.parametrize("keys", [[], "all", ["query"], [["TCGdex", "POKEMON_TCG", "English"]],
    [["TCGdex", "FIGURES", "English", "1"]], [["TCGdex", "POKEMON_TCG", "English", " 1"]],
    [["TCGdex", "POKEMON_TCG", "English", "1\n2"]],
    [["TCGdex", "POKEMON_TCG", "English", None]],
    [worker.cursor_for(reference(str(i))) for i in range(26)]])
def test_invalid_or_unbounded_selection_rejected_before_database(keys):
    with pytest.raises(ValueError):
        run_now(worker.backfill_reference_asking(None, ACTOR, reference_keys=keys))


def test_oversized_durable_selection_is_rejected():
    keys = [["p" * 512, "POKEMON_TCG", "English", str(i) * 200] for i in range(8)]
    with pytest.raises(ValueError, match="too large"):
        worker.normalize_reference_keys(keys)


@pytest.mark.parametrize("value", [1, "true", None])
def test_overlap_mode_requires_an_actual_boolean(value):
    with pytest.raises(ValueError, match="boolean"):
        run_now(worker.backfill_reference_asking(None, ACTOR, include_priced=value))


@pytest.mark.parametrize("filters", [{"system_code": "ONE_PIECE_CARD_GAME"}, {"language": "Japanese"}])
def test_exact_targets_cannot_silently_override_filters(filters):
    with pytest.raises(ValueError, match="conflicts"):
        worker.acquisition_scope(reference_keys=[worker.cursor_for(reference())], **filters)


@pytest.mark.parametrize("include_priced", [False, True])
def test_candidate_query_binds_mode_and_exact_keys_without_interpolation(sql_dependencies, include_priced):
    key = worker.cursor_for(reference("quoted'identifier"))
    scope = worker.acquisition_scope(include_priced=include_priced, reference_keys=[key])
    class CandidateConnection(Connection):
        async def fetch(self, sql, *params):
            self.query, self.params = sql, params
            return []
    connection = CandidateConnection()
    run_now(worker.SqlBackfillStore(connection, ACTOR).candidates(None, scope, 7))
    assert connection.params == ("", "", "", "", 7, None, None, include_priced, [key])
    assert "quoted'identifier" not in connection.query
    assert "$8::boolean and a.provider_id is null" in connection.query
    assert "jsonb_array_elements($9::jsonb)" in connection.query
    assert "target_key->>0,target_key->>1,target_key->>2,target_key->>3" in connection.query


def test_priced_reference_writes_asking_evidence_only_in_explicit_overlap_mode(sql_dependencies):
    ref = reference()
    current = dict(ref, needs_price=False, has_current_asking=False)
    for include_priced in (False, True):
        connection = Connection(current)
        state = report(apply=True)
        state["scope"] = worker.acquisition_scope(include_priced=include_priced)
        result = run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).result(state, ref, ready(ref)))
        assert result["stats"]["written"] == int(include_priced)
        assert connection.committed == (["history", "cache"] if include_priced else [])


@pytest.mark.parametrize("asking", [True, None])
def test_overlap_mode_requires_proven_absence_of_current_asking(sql_dependencies, asking):
    ref = reference()
    current = dict(ref, needs_price=False, has_current_asking=asking)
    connection = Connection(current)
    state = report(apply=True)
    state["scope"] = worker.acquisition_scope(include_priced=True)
    result = run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).result(state, ref, ready(ref)))
    assert connection.committed == [] and result["stats"]["written"] == 0
    assert result["rejections"]["CURRENT_EVIDENCE_ALREADY_AVAILABLE"] == 1


def test_overlap_mode_keeps_identity_race_guard(sql_dependencies):
    ref = reference()
    connection = Connection(dict(ref, needs_price=False, has_current_asking=False, name="Changed"))
    state = report(apply=True)
    state["scope"] = worker.acquisition_scope(include_priced=True)
    result = run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).result(state, ref, ready(ref)))
    assert connection.committed == []
    assert result["rejections"]["REFERENCE_IDENTITY_CHANGED"] == 1


@pytest.mark.parametrize("change", ["include_priced", "reference_keys"])
def test_resume_cannot_change_overlap_mode_or_target_selection(sql_dependencies, change):
    prior = report()
    prior["scope"] = worker.acquisition_scope(reference_keys=[worker.cursor_for(reference())])
    scope = dict(prior["scope"])
    scope[change] = True if change == "include_priced" else [worker.cursor_for(reference("2"))]
    run_id = UUID(prior["run_id"])
    connection = Connection({"id": run_id, "actor_user_id": ACTOR, "report": prior,
                             "status": "RUNNING", "budget_day": NOW.date(), "requests": 3})
    with pytest.raises(worker.BackfillStop, match="RESUME_SCOPE_OR_MODE_CHANGED"):
        run_now(worker.SqlBackfillStore(connection, ACTOR, clock=lambda: NOW).open_run(
            uuid4(), run_id, apply=False, scope=scope, digest=prior["benchmark_digest"], limit=25))


def test_cli_accepts_explicit_overlap_sample_and_keeps_defaults():
    key = worker.cursor_for(reference())
    args = arguments(["--from-settings", "--include-priced", "--reference-key", json.dumps(key)])
    assert args.include_priced is True and args.reference_key == [key] and not args.run
    defaults = arguments(["--from-settings"])
    assert defaults.include_priced is False and defaults.reference_key is None


@pytest.mark.parametrize("value", ["not-json", "null", "[]", '["TCGdex","POKEMON_TCG","English"]'])
def test_cli_rejects_invalid_exact_keys(value):
    with pytest.raises(SystemExit) as error:
        arguments(["--from-settings", "--reference-key", value])
    assert error.value.code == 2
