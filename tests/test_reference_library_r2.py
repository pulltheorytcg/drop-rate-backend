"""Verified R2 reference-library count paths; private source stays live SQL."""
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import reference_library as library
from app import reference_library_r2 as r2
from app.catalogue_r2_index import SharedReferenceIndex


def shared():
    sets = [
        dict(provider="TCGdex", system_code="POKEMON_TCG", language="English",
             set_id="base", name="Base", release_date="2025-01-01"),
        dict(provider="TCGdex", system_code="POKEMON_TCG", language="English",
             set_id="future", name="Future", release_date="2028-01-01"),
        dict(provider="TCGdex", system_code="POKEMON_TCG", language="Japanese",
             set_id="empty", name="Empty", release_date=None),
        dict(provider="Bandai", system_code="ONE_PIECE_CARD_GAME", language="English",
             set_id="op", name="One Piece", release_date="2025-01-01"),
    ]
    cards = [dict(provider="TCGdex", system_code="POKEMON_TCG", language="English",
                  set_id="base", provider_id=variant)
             for variant in ("001", "001-holo")]
    cards += [dict(provider="TCGdex", system_code="POKEMON_TCG", language="English",
                   set_id="future", provider_id="future-001")]
    # Defensive LEFT JOIN matching: a corrupt orphan must never count.
    cards += [dict(provider="TCGdex", system_code="POKEMON_TCG", language="English",
                   set_id="orphan", provider_id="orphan")]
    return {"reference_sets": sets, "reference_cards": cards}


def snapshot():
    rows = shared()
    return SimpleNamespace(generation=7, manifest_digest="verified", rows=rows,
                           scope_index=SharedReferenceIndex.build(rows))


def metadata_rows():
    return [dict(**s, refreshed_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                 release_status="UPCOMING" if s["set_id"] == "future" else
                 "UNKNOWN" if s["release_date"] is None else "RELEASED")
            for s in shared()["reference_sets"]]


def test_r2_counts_keep_all_variants_future_sets_empty_sets_and_orphans_out():
    s = snapshot()
    groups = r2.build_coverage_counts(s.rows, date(2026, 11, 2))
    english = groups[("POKEMON_TCG", "TCGdex", "English")]
    assert (english["sets"], english["cards"], english["upcoming_cards"]) == (2, 3, 1)
    assert groups[("POKEMON_TCG", "TCGdex", "Japanese")]["cards"] == 0
    assert groups[("ONE_PIECE_CARD_GAME", "Bandai", "English")]["sets"] == 1
    pages = r2.indexed_set_page(metadata_rows(), s)
    assert [p["indexed_cards"] for p in pages] == [2, 1, 0, 0]
    assert pages[1]["release_status"] == "UPCOMING"
    assert pages[0]["refreshed_at"] == metadata_rows()[0]["refreshed_at"]


@pytest.mark.asyncio
async def test_coverage_reads_current_refresh_time_from_sql_and_requires_matching_groups():
    class Connection:
        async def fetch(self, query):
            assert query == r2.COVERAGE_METADATA_SQL
            return [dict(system_code=group[0], provider=group[1], language=group[2],
                         refreshed_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                         source_today=date(2026, 11, 2))
                    for group in sorted(r2.build_coverage_counts(shared(), date(2026, 11, 2)))]
    rows = await r2.indexed_coverage(Connection(), snapshot())
    assert rows[0]["refreshed_at"].tzinfo == timezone.utc
    assert sum(r["cards"] for r in rows) == 3

    class MissingGroup(Connection):
        async def fetch(self, query):
            return (await super().fetch(query))[:-1]
    with pytest.raises(ValueError, match="differ"):
        await r2.indexed_coverage(MissingGroup(), snapshot())


@pytest.mark.asyncio
async def test_sets_handler_uses_verified_r2_counts_and_falls_back_if_generation_changes(monkeypatch):
    s = snapshot()
    calls = []
    records = metadata_rows()[:2]
    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield
        async def fetch(self, query, *args):
            calls.append(query)
            if query == library.SETS_R2_SQL:
                return records
            assert query == library.SETS_SQL
            return [dict(row, indexed_cards=99) for row in records]
    @asynccontextmanager
    async def scoped(*args):
        yield Connection()
    monkeypatch.setattr(library, "user_connection", scoped)
    monkeypatch.setenv("TCG_R2_REFERENCE_LIBRARY_READ_ENABLED", "true")
    reads = iter((s, s))
    async def current(*args):
        return next(reads)
    monkeypatch.setattr(library.catalogue_r2_live, "read", current)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None)),
                              state=SimpleNamespace(request_id="r2-test"))
    user = SimpleNamespace(user_id=uuid4())
    result = await library.library_sets(request, user, "POKEMON_TCG", "", 1, 0)
    assert result["items"][0]["indexed_cards"] == 2
    assert result["has_more"] is True
    assert calls == [library.SETS_R2_SQL]

    calls.clear()
    reads = iter((s, None))
    result = await library.library_sets(request, user, "POKEMON_TCG", "", 1, 0)
    assert result["items"][0]["indexed_cards"] == 99
    assert calls == [library.SETS_R2_SQL, library.SETS_SQL]

    calls.clear()
    monkeypatch.setenv("TCG_R2_REFERENCE_LIBRARY_READ_ENABLED", "false")
    result = await library.library_sets(request, user, "POKEMON_TCG", "", 1, 0)
    assert result["items"][0]["indexed_cards"] == 99
    assert calls == [library.SETS_SQL]


@pytest.mark.asyncio
async def test_coverage_handler_falls_back_to_source_sql_on_r2_group_mismatch(monkeypatch):
    s = snapshot()
    calls = []
    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield
        async def fetch(self, query, *args):
            calls.append(query)
            if query == r2.COVERAGE_METADATA_SQL:
                return [dict(system_code="INVALID", provider="Nobody", language="English",
                             source_today=date(2026, 11, 2), refreshed_at=None)]
            if query == library.COVERAGE_SQL:
                return [dict(system_code="POKEMON_TCG", provider="TCGdex",
                             language="English", sets=2, cards=3, upcoming_cards=1,
                             refreshed_at=datetime(2026, 11, 2, tzinfo=timezone.utc))]
            assert "select distinct on (source)" in query
            return []
    @asynccontextmanager
    async def scoped(*args):
        yield Connection()
    async def current(*args):
        return s
    monkeypatch.setattr(library, "user_connection", scoped)
    monkeypatch.setattr(library.catalogue_r2_live, "read", current)
    monkeypatch.setenv("TCG_R2_REFERENCE_LIBRARY_READ_ENABLED", "true")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None)),
                              state=SimpleNamespace(request_id="r2-test"))
    result = await library.library_coverage(request, SimpleNamespace(user_id=uuid4()))
    pokemon = next(row for row in result["games"] if row["system_code"] == "POKEMON_TCG")
    assert pokemon["sources"][0]["cards"] == 3
    assert library.COVERAGE_SQL in calls


@pytest.mark.asyncio
async def test_coverage_handler_uses_r2_counts_when_publication_remains_current(monkeypatch):
    s = snapshot()
    calls = []
    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield
        async def fetch(self, query, *args):
            calls.append(query)
            if query == r2.COVERAGE_METADATA_SQL:
                groups = sorted(r2.build_coverage_counts(s.rows, date(2026, 11, 2)))
                return [dict(system_code=key[0], provider=key[1], language=key[2],
                             refreshed_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                             source_today=date(2026, 11, 2)) for key in groups]
            assert "select distinct on (source)" in query
            return []
    @asynccontextmanager
    async def scoped(*args):
        yield Connection()
    async def current(*args):
        return s
    monkeypatch.setenv("TCG_R2_REFERENCE_LIBRARY_READ_ENABLED", "true")
    monkeypatch.setattr(library, "user_connection", scoped)
    monkeypatch.setattr(library.catalogue_r2_live, "read", current)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None)),
                              state=SimpleNamespace(request_id="r2-test"))
    result = await library.library_coverage(request, SimpleNamespace(user_id=uuid4()))
    pokemon = next(row for row in result["games"] if row["system_code"] == "POKEMON_TCG")
    assert sum(row["cards"] for row in pokemon["sources"]) == 3
    assert sum(row["upcoming_cards"] for row in pokemon["sources"]) == 1
    assert library.COVERAGE_SQL not in calls
