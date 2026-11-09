"""Actual local SQLite backup/restore and existing replay; synthetic rows only."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import d1_operational_restore_drill as restore
import d1_operational_source_stage as stage
import d1_operational_snapshot_replay as replay
from test_d1_operational_source_stage import FakeCloudflareD1, fixtures, job


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(stage, "FLOORS", {name: 1 for name in stage.TABLES})
    monkeypatch.setattr(job, "FLOORS", {name: 1 for name in stage.TABLES})
    db = FakeCloudflareD1()
    data = fixtures()
    schema = {name: [{"column": key, "type": "fixture"} for key in rows[0][1]]
              for name, rows in data.items()}
    catalogue = {"c1": "a" * 64}
    result = stage.stage(db, data, schema, catalogue, captured_at="2026-11-06T12:00:00+00:00")
    path = tmp_path / "private-shadow.sqlite"

    def save():
        db.con.commit()
        with sqlite3.connect(path) as destination:
            db.con.backup(destination)
        return restore._file_sha(path)

    save()
    yield db, data, schema, catalogue, result["generation_sha256"], path, save
    db.con.close()


def changed(data):
    result = copy.deepcopy(data)
    obj = result["inventory_items"][0][1]
    obj.update(version=2, market_value_minor=123)
    raw = json.dumps(obj, separators=(",", ":"))
    result["inventory_items"] = [(obj["id"], obj, raw, stage.sha(raw))]
    return result


def metadata():
    return {"captured_at": "2026-11-08T12:00:00+00:00", "source_snapshot": "100:102:101"}


def test_restore_copies_all_nine_tables_without_modifying_source_or_disclosing_private_rows(snapshot):
    _, _, _, _, manifest, path, _ = snapshot
    before = path.read_bytes()
    report = restore.drill(path, restore._file_sha(path), manifest)
    assert path.read_bytes() == before
    assert report["status"] == "LOCAL_OPERATIONAL_SHADOW_RESTORE_VERIFIED_NOT_REMOTE_D1"
    assert report["verified_tables"] == list(stage.ORDER)
    assert report["row_counts"] == dict.fromkeys(stage.ORDER, 1)
    assert report["owner_currency_balances_preserved"] is True
    assert report["remote_d1_reads"] == report["remote_d1_writes"] == report["source_postgres_writes"] == 0
    for flag in ("full_source_manifest_recomputed", "all_150_relations_restored",
                 "r2_artwork_bytes_verified", "real_d1_restore_verified",
                 "production_cutover", "gate_a_complete", "gate_h_complete"):
        assert report[flag] is False
    public = json.dumps(report)
    for private in ('"o1"', '"i1"', "Founder", "source_row_json", "store.myshopify.com"):
        assert private not in public


@pytest.mark.parametrize("change,message", [
    ("UPDATE ops_shadow_inventory SET market_value_minor=999", "typed fields"),
    ("UPDATE ops_shadow_inventory SET source_row_json='{}'", "payload hash"),
    ("UPDATE ops_shadow_table_receipts SET exact_source_rows=2,exact_staged_rows=2", "checksum"),
    ("UPDATE ops_shadow_table_receipts SET source_sha256='" + "b" * 64 + "',staged_sha256='" + "b" * 64 + "'", "checksum"),
    ("DELETE FROM ops_shadow_table_receipts WHERE source_table='inventory_items'", "receipt scope"),
    ("DROP TRIGGER ops_shadow_sale_owner_match", "schema or protection"),
    ("CREATE TABLE unrelated_private_data(value)", "unexpected non-shadow"),
    ("INSERT INTO ops_shadow_identity_map(generation_id,legacy_user_id) SELECT generation_id,'foreign-user' FROM ops_shadow_generations", "identity scope"),
    ("UPDATE ops_shadow_identity_map SET external_subject='hosted-subject',provider='issuer',verified_at='2026-11-08'", "hosted mappings"),
])
def test_corrupt_backup_fails_even_when_its_new_file_checksum_is_explicitly_pinned(snapshot, change, message):
    db, _, _, _, manifest, path, save = snapshot
    db.con.execute(change)
    digest = save()
    with pytest.raises(restore.RestoreGuard, match=message):
        restore.drill(path, digest, manifest)


def test_broken_reference_is_detected_on_restored_database(snapshot):
    db, _, _, _, manifest, path, save = snapshot
    db.con.commit()
    db.con.execute("PRAGMA foreign_keys=OFF")
    db.con.execute("DELETE FROM ops_shadow_inventory")
    digest = save()
    with pytest.raises(restore.RestoreGuard, match="references"):
        restore.drill(path, digest, manifest)


def test_data_outside_nine_table_scope_is_not_silently_certified(snapshot):
    db, _, _, _, manifest, path, save = snapshot
    db.con.execute("INSERT INTO ops_shadow_audit_events(generation_id,id,occurred_at,actor,action,"
                   "entity_type,entity_id,source_row_sha256) SELECT generation_id,1,"
                   "'2026-11-06','private-actor','UPDATE','inventory','i1',? FROM ops_shadow_generations",
                   ("a" * 64,))
    digest = save()
    with pytest.raises(restore.RestoreGuard, match="outside reviewed"):
        restore.drill(path, digest, manifest)


def test_file_and_generation_must_match_independent_pins(snapshot):
    _, _, _, _, manifest, path, _ = snapshot
    with pytest.raises(restore.RestoreGuard, match="file checksum"):
        restore.drill(path, "0" * 64, manifest)
    with pytest.raises(restore.RestoreGuard, match="generation absent"):
        restore.drill(path, restore._file_sha(path), "0" * 64)


def test_running_wal_database_is_not_a_standalone_backup(snapshot):
    _, _, _, _, manifest, path, _ = snapshot
    Path(str(path) + "-wal").write_bytes(b"unfinished")
    with pytest.raises(restore.RestoreGuard, match="Complete bounded"):
        restore.drill(path, restore._file_sha(path), manifest)


def test_restore_preserves_verified_replay_head_journal_budget_and_original_generation(snapshot):
    db, data, schema, catalogue, original, path, save = snapshot
    result = replay.replay(db, changed(data), schema, catalogue, metadata(), apply=True)
    digest = save()
    report = restore.drill(path, digest, result["generation_sha256"])
    assert report["verified_generations"] == 2
    assert report["verified_replay_checkpoints"] == 1
    assert report["quarantined_generations_preserved"] == 0
    # A previous generation cannot substitute for the independently pinned head.
    with pytest.raises(restore.RestoreGuard, match="head or high-water"):
        restore.drill(path, digest, original)


@pytest.mark.parametrize("mutation,message", [
    ("UPDATE ops_shadow_inventory_replay SET prior_version=0", "journal or checkpoint"),
    ("UPDATE ops_shadow_replay_checkpoints SET captured_at='2026-11-05T12:00:00Z'", "high-water"),
    ("UPDATE ops_shadow_replay_checkpoints SET parent_generation_id=generation_id", "cycle"),
    ("UPDATE ops_shadow_replay_head SET captured_at='2026-11-09T12:00:00Z'", "high-water"),
    ("UPDATE ops_shadow_replay_daily_budget SET utc_day='2026-11-09'", "reservation"),
    ("DELETE FROM ops_shadow_replay_daily_budget", "original daily reservation"),
])
def test_replay_corruption_blocks_restore_receipt(snapshot, mutation, message):
    db, data, schema, catalogue, _, path, save = snapshot
    result = replay.replay(db, changed(data), schema, catalogue, metadata(), apply=True)
    db.con.execute(mutation)
    digest = save()
    with pytest.raises(restore.RestoreGuard, match=message):
        restore.drill(path, digest, result["generation_sha256"])


def test_interrupted_stage_restores_then_existing_replay_resumes_on_disposable_copy(snapshot, monkeypatch):
    db, data, schema, catalogue, original, path, save = snapshot
    new = changed(data)
    insert = replay._insert_rows

    def interrupted(*args, **kwargs):
        if args[2] == "ops_shadow_inventory_replay":
            raise OSError("synthetic lost acknowledgement")
        return insert(*args, **kwargs)

    monkeypatch.setattr(replay, "_insert_rows", interrupted)
    with pytest.raises(OSError):
        replay.replay(db, new, schema, catalogue, metadata(), apply=True)
    digest = save()
    monkeypatch.setattr(replay, "_insert_rows", insert)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as restored:
            report = restore.restore_database(source, restored, original)
            assert report["quarantined_generations_preserved"] == 1
            replica = object.__new__(FakeCloudflareD1)
            replica.con = restored
            result = replay.replay(replica, new, schema, catalogue, metadata(), apply=True)
            assert result["status"] == "INVENTORY_REPLAY_SNAPSHOT_PARITY_VERIFIED"
            assert replay.replay(replica, new, schema, catalogue, metadata(), apply=True)["status"] == "INVENTORY_REPLAY_ALREADY_VERIFIED"
            assert restored.execute("SELECT count(*) FROM ops_shadow_replay_daily_budget").fetchone()[0] == 1
            assert restored.execute("SELECT count(*) FROM ops_shadow_generations").fetchone()[0] == 2
    assert restore._file_sha(path) == digest


def test_nonempty_destination_is_never_overwritten(snapshot):
    _, _, _, _, manifest, path, _ = snapshot
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as restored:
            restored.execute("CREATE TABLE keep_me(value)")
            restored.execute("INSERT INTO keep_me VALUES('untouched')")
            with pytest.raises(restore.RestoreGuard, match="must be empty"):
                restore.restore_database(source, restored, manifest)
            assert restored.execute("SELECT value FROM keep_me").fetchone()[0] == "untouched"


def test_cli_error_does_not_expose_private_snapshot_path(snapshot):
    _, _, _, _, manifest, path, _ = snapshot
    command = [sys.executable, str(restore.ROOT / "tools/d1_operational_restore_drill.py"),
               "--snapshot", str(path), "--expected-file-sha256", "0" * 64,
               "--expected-generation-sha256", manifest]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "Local shadow restore did not verify: RestoreGuard"
    assert str(path) not in result.stderr
