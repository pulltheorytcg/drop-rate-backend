"""Restore an independently pinned operational-shadow SQLite snapshot locally.

No cloud client, PostgreSQL connection, import, live routing or financial write.
This verifies the existing nine-table shadow, not all 150 source relations,
R2 object bytes, a real D1 restore or production recovery.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from d1_operational_source_stage import ORDER, TARGETS, _map_row, sha
from d1_operational_snapshot_replay import instant, plan_inventory

ROOT = Path(__file__).resolve().parents[1]
BASE_DDL = ROOT / "database/cloudflare_d1/0001_operational_shadow.sql"
REPLAY_DDL = ROOT / "database/cloudflare_d1/0002_operational_shadow_replay.sql"
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE_BYTES = 64_000_000
MAX_RESTORED_ROWS = 100_000
MAX_GENERATIONS = 32
REPLAY_TABLES = {
    "ops_shadow_replay_checkpoints", "ops_shadow_inventory_replay",
    "ops_shadow_replay_daily_budget", "ops_shadow_replay_head",
}
UNMAPPED_TABLES = (
    "ops_shadow_reservations", "ops_shadow_payout_requests",
    "ops_shadow_shopify_item_links", "ops_shadow_audit_events",
)


class RestoreGuard(ValueError):
    """Aggregate-only failure; never embed private row values."""


def _objects(conn):
    return {r["name"]: (r["type"], r["sql"]) for r in conn.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE name GLOB 'ops_shadow_*'")}


def _schema(conn):
    other = conn.execute("SELECT name,type FROM sqlite_master WHERE name NOT GLOB 'ops_shadow_*' "
                         "AND name NOT GLOB 'sqlite_*'").fetchall()
    if any(r["name"] not in {"_cf_KV", "d1_migrations"} or r["type"] != "table" for r in other):
        raise RestoreGuard("Snapshot contains an unexpected non-shadow schema object")
    actual = _objects(conn)
    replay_present = REPLAY_TABLES.intersection(actual)
    if replay_present and replay_present != REPLAY_TABLES:
        raise RestoreGuard("Incomplete replay schema; no restore receipt")
    with closing(sqlite3.connect(":memory:")) as expected:
        expected.row_factory = sqlite3.Row
        expected.executescript(BASE_DDL.read_text())
        if replay_present:
            expected.executescript(REPLAY_DDL.read_text())
        if actual != _objects(expected):
            raise RestoreGuard("Shadow schema or protection differs from tracked DDL")
    return sorted(name for name, (kind, _) in actual.items() if kind == "table")


def _fingerprint(conn, tables):
    result = {}
    total = 0
    for table in tables:
        # Identifiers come ONLY from the exact tracked-schema comparison above.
        columns = [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        order = ",".join('"' + c + '"' for c in columns)
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            count += 1
            total += 1
            if total > MAX_RESTORED_ROWS:
                raise RestoreGuard("Local restore row bound exceeded")
            digest.update(json.dumps(tuple(row), ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode() + b"\n")
        result[table] = (count, digest.hexdigest())
    return result


def _source_records(conn, name, generation):
    table, columns = TARGETS[name]
    selected = ",".join('"' + c + '"' for c in columns)
    rows = [dict(r) for r in conn.execute(
        f'SELECT {selected} FROM "{table}" WHERE generation_id=? ORDER BY id',
        (generation,))]
    captured = []
    for row in rows:
        raw, digest = row["source_row_json"], row["source_row_sha256"]
        if (not isinstance(raw, str) or len(raw.encode()) > 1_000_000
                or not isinstance(digest, str) or not SHA.fullmatch(digest)
                or sha(raw) != digest):
            raise RestoreGuard("Restored private source payload hash mismatch")
        try:
            record = json.loads(raw)
            if not isinstance(record, dict) or record.get("id") != row["id"]:
                raise ValueError()
            mapped = _map_row(name, generation, record, raw, digest, {})
        except (ValueError, TypeError, KeyError):
            raise RestoreGuard("Restored source structure or identity invalid") from None
        if (json.dumps(tuple(row[c] for c in columns), allow_nan=False)
                != json.dumps(mapped, allow_nan=False)):
            raise RestoreGuard("Restored typed fields differ from original source JSON")
        captured.append((row["id"], record, raw, digest))
    return captured


def _verify_generation(conn, generation):
    captured = {name: _source_records(conn, name, generation) for name in ORDER}
    receipts = [dict(r) for r in conn.execute(
        "SELECT * FROM ops_shadow_table_receipts WHERE generation_id=?", (generation,))]
    if (len(receipts) != len(ORDER)
            or {(r["source_schema"], r["source_table"]) for r in receipts}
            != {("tcg", name) for name in ORDER}):
        raise RestoreGuard("Nine-table receipt scope incomplete")
    for receipt in receipts:
        records = captured[receipt["source_table"]]
        digest = sha("".join(key + ":" + row_sha + "\n" for key, _, _, row_sha in records))
        if (receipt["exact_source_rows"] != len(records)
                or receipt["exact_staged_rows"] != len(records)
                or receipt["source_sha256"] != digest or receipt["staged_sha256"] != digest):
            raise RestoreGuard("Restored source count or table checksum differs from receipt")
    users = {r[1]["user_id"] for r in captured["owner_memberships"]}
    identities = [dict(r) for r in conn.execute(
        "SELECT * FROM ops_shadow_identity_map WHERE generation_id=?", (generation,))]
    if ({r["legacy_user_id"] for r in identities} != users
            or any(any(r[k] is not None for k in ("external_subject", "provider", "verified_at"))
                   for r in identities)):
        raise RestoreGuard("Restored legacy identity scope differs or contains hosted mappings")
    expected_links = {r[1]["catalogue_id"] for r in captured["inventory_items"]}
    links = [dict(r) for r in conn.execute(
        "SELECT catalogue_id,reference_manifest_sha256 FROM ops_shadow_catalogue_links "
        "WHERE generation_id=?", (generation,))]
    if ({r["catalogue_id"] for r in links} != expected_links
            or any(not SHA.fullmatch(r["reference_manifest_sha256"]) for r in links)):
        raise RestoreGuard("Restored canonical catalogue-link scope invalid")
    # FKs alone do not establish same-owner lineage across otherwise valid IDs.
    lineage_sql = (
        "SELECT 1 FROM ops_shadow_order_items s JOIN ops_shadow_inventory i "
        "ON i.generation_id=s.generation_id AND i.id=s.inventory_id "
        "WHERE s.generation_id=? AND s.owner_id<>i.owner_id LIMIT 1",
        "SELECT 1 FROM ops_shadow_refunds r JOIN ops_shadow_order_items s "
        "ON s.generation_id=r.generation_id AND s.id=r.order_item_id "
        "WHERE r.generation_id=? AND (r.owner_id<>s.owner_id OR "
        "r.order_id<>s.order_id OR r.inventory_id<>s.inventory_id) LIMIT 1",
        "SELECT 1 FROM ops_shadow_ledger l JOIN ops_shadow_order_items s "
        "ON s.generation_id=l.generation_id AND s.id=l.order_item_id "
        "WHERE l.generation_id=? AND (l.owner_id<>s.owner_id OR l.order_id IS NOT s.order_id) LIMIT 1",
    )
    if any(conn.execute(sql, (generation,)).fetchone() for sql in lineage_sql):
        raise RestoreGuard("Restored owner or original-sale lineage mismatch")
    totals = {}
    for _, record, _, _ in captured["financial_ledger_entries"]:
        key = (record["owner_id"], record["currency"])
        totals[key] = totals.get(key, 0) + record["amount_minor"]
    actual = {(r["owner_id"], r["currency"]): r["total"] for r in conn.execute(
        "SELECT owner_id,currency,SUM(amount_minor) AS total FROM ops_shadow_ledger "
        "WHERE generation_id=? GROUP BY owner_id,currency", (generation,))}
    if actual != totals:
        raise RestoreGuard("Restored owner/currency ledger balance mismatch")
    return captured


def _verify_replay(conn, generations, captured, expected_generation):
    if not REPLAY_TABLES.issubset(_objects(conn)):
        return 0
    checkpoints = {r["generation_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM ops_shadow_replay_checkpoints")}
    for generation, checkpoint in checkpoints.items():
        parent = checkpoint["parent_generation_id"]
        seen = {generation}
        cursor = parent
        while cursor in checkpoints:
            if cursor in seen:
                raise RestoreGuard("Replay checkpoint cycle")
            seen.add(cursor)
            cursor = checkpoints[cursor]["parent_generation_id"]
        if (parent not in captured or generation not in captured
                or generations[parent]["state"] not in {"STAGING", "PARITY_VERIFIED"}
                or generations[generation]["source_schema_sha256"]
                != generations[parent]["source_schema_sha256"]):
            raise RestoreGuard("Replay parent or verified source scope missing")
        stamp = instant(checkpoint["captured_at"])
        if (stamp < instant(generations[parent]["source_captured_at"])
                or checkpoint["captured_at"] != generations[generation]["source_captured_at"]
                or not isinstance(checkpoint["source_snapshot"], str)
                or not 0 < len(checkpoint["source_snapshot"]) <= 10000):
            raise RestoreGuard("Replay capture high-water mark invalid")
        source = captured[generation]["inventory_items"]
        prior = [{"id": key, "source_row_sha256": digest, "source_row_json": raw}
                 for key, _, raw, digest in captured[parent]["inventory_items"]]
        allowed = {key for _, record, _, _ in source for key in record}
        journal, _, version_root = plan_inventory(source, prior, allowed)
        columns = ("inventory_id", "prior_sha256", "source_sha256", "prior_version",
                   "source_version", "classification", "changed_columns_json")
        actual = [tuple(r[c] for c in columns) for r in conn.execute(
            "SELECT * FROM ops_shadow_inventory_replay WHERE generation_id=? ORDER BY inventory_id",
            (generation,))]
        if (actual != sorted(journal) or checkpoint["changed_records"] != len(journal)
                or checkpoint["inventory_version_root"] != version_root
                or checkpoint["plan_sha256"] != sha(json.dumps(journal, separators=(",", ":")))):
            raise RestoreGuard("Replay journal or checkpoint digest mismatch")
    if conn.execute("SELECT 1 FROM ops_shadow_inventory_replay j WHERE NOT EXISTS "
                    "(SELECT 1 FROM ops_shadow_replay_checkpoints c "
                    "WHERE c.generation_id=j.generation_id) LIMIT 1").fetchone():
        # A journal without its checkpoint is a valid interrupted stage, but it
        # cannot be certified as a complete replay. Preserve it, fail closed.
        raise RestoreGuard("Interrupted replay journal requires same-source recovery")
    heads = [dict(r) for r in conn.execute("SELECT * FROM ops_shadow_replay_head")]
    if heads:
        head = heads[0]
        generation = head["generation_id"]
        if (len(heads) != 1 or generation != expected_generation
                or generation not in checkpoints
                or generations[generation]["state"] != "PARITY_VERIFIED"
                or head["captured_at"] != checkpoints[generation]["captured_at"]):
            raise RestoreGuard("Restored replay head or high-water mark mismatch")
    elif checkpoints:
        raise RestoreGuard("Replay checkpoints exist without a verified head")
    budgets = [dict(r) for r in conn.execute("SELECT * FROM ops_shadow_replay_daily_budget")]
    for budget in budgets:
        if (budget["parent_generation_id"] not in generations
                or not re.fullmatch(r"src-[0-9a-f]{32}", budget["generation_id"])
                or instant(budget["captured_at"]).date().isoformat() != budget["utc_day"]
                or not 1 <= budget["logical_rows_reserved"] <= 2500
                or not 0 < len(budget["source_snapshot"]) <= 10000):
            raise RestoreGuard("Restored daily reservation invalid")
    for generation, checkpoint in checkpoints.items():
        reserved = [r for r in budgets if r["generation_id"] == generation]
        if (len(reserved) != 1
                or any(reserved[0][field] != checkpoint[field] for field in (
                    "parent_generation_id", "captured_at", "source_snapshot"))):
            raise RestoreGuard("Replay checkpoint lost its original daily reservation")
    return len(checkpoints)


def restore_database(source, restored, expected_generation_sha256):
    """Copy to an EMPTY disposable SQLite connection; never accept a D1 client."""
    if (not isinstance(source, sqlite3.Connection) or not isinstance(restored, sqlite3.Connection)
            or source is restored or not SHA.fullmatch(expected_generation_sha256)):
        raise RestoreGuard("Local SQLite connections and an independent generation pin required")
    source.row_factory = restored.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only=ON")
    if restored.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
        raise RestoreGuard("Restore destination must be empty")
    tables = _schema(source)
    before = _fingerprint(source, tables)
    source.backup(restored, pages=64)
    restored.execute("PRAGMA foreign_keys=ON")
    if (_schema(restored) != tables or _fingerprint(restored, tables) != before
            or [r[0] for r in restored.execute("PRAGMA integrity_check")] != ["ok"]
            or restored.execute("PRAGMA foreign_key_check").fetchone()):
        raise RestoreGuard("Restored schema, contents, integrity or references differ")
    if any(restored.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
           for table in UNMAPPED_TABLES):
        raise RestoreGuard("Snapshot contains data outside reviewed nine-table restore scope")
    generations = {r["generation_id"]: dict(r) for r in restored.execute(
        "SELECT * FROM ops_shadow_generations")}
    expected_generation = "src-" + expected_generation_sha256[:32]
    if (not 0 < len(generations) <= MAX_GENERATIONS
            or expected_generation not in generations
            or generations[expected_generation]["source_manifest_sha256"] != expected_generation_sha256
            or generations[expected_generation]["state"] not in {"STAGING", "PARITY_VERIFIED"}):
        raise RestoreGuard("Pinned verified source generation absent")
    captured = {}
    quarantined = 0
    checkpoint_ids = set()
    if REPLAY_TABLES.issubset(_objects(restored)):
        checkpoint_ids = {r[0] for r in restored.execute(
            "SELECT generation_id FROM ops_shadow_replay_checkpoints")}
    for generation, row in generations.items():
        if (not SHA.fullmatch(row["source_manifest_sha256"])
                or generation != "src-" + row["source_manifest_sha256"][:32]
                or not SHA.fullmatch(row["source_schema_sha256"])):
            raise RestoreGuard("Restored generation identity or schema hash invalid")
        if row["state"] == "REJECTED" and generation not in checkpoint_ids:
            quarantined += 1
            continue
        captured[generation] = _verify_generation(restored, generation)
    checkpoints = _verify_replay(restored, generations, captured, expected_generation)
    return {
        "status": "LOCAL_OPERATIONAL_SHADOW_RESTORE_VERIFIED_NOT_REMOTE_D1",
        "generation_sha256": expected_generation_sha256,
        "verified_tables": list(ORDER),
        "row_counts": {name: len(captured[expected_generation][name]) for name in ORDER},
        "verified_generations": len(captured), "quarantined_generations_preserved": quarantined,
        "verified_replay_checkpoints": checkpoints,
        "owner_currency_balances_preserved": True,
        "source_postgres_writes": 0, "remote_d1_reads": 0, "remote_d1_writes": 0,
        "local_disposable_restore_only": True, "full_source_manifest_recomputed": False,
        "all_150_relations_restored": False, "r2_artwork_bytes_verified": False,
        "real_d1_restore_verified": False, "production_cutover": False,
        "gate_a_complete": False, "gate_h_complete": False,
    }


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def drill(snapshot, expected_file_sha256, expected_generation_sha256):
    snapshot = Path(snapshot).resolve(strict=True)
    if (not SHA.fullmatch(expected_file_sha256) or not snapshot.is_file()
            or not 0 < snapshot.stat().st_size <= MAX_FILE_BYTES
            or any(Path(str(snapshot) + suffix).exists() for suffix in ("-wal", "-journal"))
            or _file_sha(snapshot) != expected_file_sha256):
        raise RestoreGuard("Complete bounded snapshot and independent file checksum required")
    # Immutable mode is appropriate ONLY for a completed standalone backup,
    # not a running SQLite database or a file missing its WAL sidecar.
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
        with closing(sqlite3.connect(":memory:")) as restored:
            report = restore_database(source, restored, expected_generation_sha256)
    if _file_sha(snapshot) != expected_file_sha256:
        raise RestoreGuard("Source snapshot changed during restore drill")
    report["snapshot_file_sha256"] = expected_file_sha256
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-file-sha256", required=True)
    parser.add_argument("--expected-generation-sha256", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(drill(args.snapshot, args.expected_file_sha256,
                               args.expected_generation_sha256), sort_keys=True))
    except Exception as exc:
        raise SystemExit("Local shadow restore did not verify: " + type(exc).__name__) from None


if __name__ == "__main__":
    main()
