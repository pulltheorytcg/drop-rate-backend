"""Real Cloudflare D1 connectivity + tiny SYNTHETIC R2 shadow projection only.

Called by a single protected main-branch GitHub Actions run. Does not read real
catalogues, Supabase, payments, secrets from files, Shopify, or R2 credentials.
Creates at most one uniquely named synthetic D1 database, never deletes one.
No user transactions, ownership, production environment or price publication.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

# This script runs in the repository root with PYTHONPATH=backend:tools.
from app import d1_shadow_catalogue as shadow
from app import r2_first_catalogue as codec
from d1_remote_catalogue_pilot import D1Client, PilotError


SOURCE = "https://mtgjson.com/api/v5/AllPrintings.json.xz"
SCOPE = ("mtgjson", "MAGIC_THE_GATHERING", "English")
MAX_VISIBLE_D1_DATABASES_BEFORE_PILOT = 7


def synthetic_snapshot(*, count=18, revision="stage1-synthetic", renamed=False):
    """Create and checksum-test R2 parts locally; no remote R2 access."""
    if type(count) is not int or not 1 <= count <= 60:
        raise PilotError("Invalid bounded synthetic source count")
    rows = []
    for i in range(count):
        uid = f"11111111-1111-5111-8111-{i:012d}"
        rows.append({
            "provider": SCOPE[0], "system_code": SCOPE[1], "language": SCOPE[2],
            "provider_id": f"mtgjson:{uid}:nonfoil", "product_type": "CARD",
            "name": ("Revised " if renamed else "Sample ") + str(i),
            "set_id": "SYNTH", "set_name": "Synthetic Only",
            "card_number": str(i), "rarity": "common", "finish": "nonfoil",
            "release_date": "2026-01-01", "source_url": SOURCE,
            "details": {"cardmarket_product_id": str(110000+i)},
        })
    bundle = codec.prepare_catalogue(
        rows, provider=SCOPE[0], system_code=SCOPE[1], language=SCOPE[2],
        source_url=SOURCE, source_revision=revision,
        permission_ref="https://mtgjson.com/license/",
    )
    # Reconstruct the checksummed R2 parts before accepting any projection.
    snap = codec.Snapshot(bundle.manifest)
    for raw, part in zip(bundle.parts, bundle.manifest["parts"], strict=True):
        snap._append(codec._parse_part(raw, part, SCOPE))
    snap._finish()
    return snap


def query_one(client, database_id, sql, params=()):
    answer, _ = client.query(database_id, sql, params)
    return answer.get("results", [])


def schema(client, database_id):
    for statement in shadow.SCHEMA.split(";"):
        if statement.strip():
            query_one(client, database_id, statement)


def stage(client, database_id, projection, *, partial=False):
    if not partial:
        query_one(client, database_id, shadow.generation_statement(projection)["sql"],
                  shadow.generation_statement(projection)["params"])
    statements = list(shadow.insert_statements(projection))
    selected = statements[:1] if partial else statements
    for item in selected:
        query_one(client, database_id, item["sql"], item["params"])


def activate(client, database_id, projection):
    item = shadow.activation_statement(projection)
    query_one(client, database_id, item["sql"], item["params"])
    rows = query_one(client, database_id,
        "select manifest_sha from shadow_active_partitions where provider=? and system_code=? and language=?",
        SCOPE)
    return rows[0]["manifest_sha"] if rows else None


def verify_exact(client, database_id, projection):
    rows = query_one(client, database_id, shadow.LIVE_CARD_SQL, (*SCOPE, 60, 0))
    if len(rows) != projection.expected_rows:
        raise PilotError("D1 readback count differs from verified R2 reference source")
    if [r["card_key"] for r in rows] != sorted(r[1] for r in projection.rows):
        raise PilotError("D1 printing identities differ from verified R2 source")
    if {r["provider_id"] for r in rows} != {r[5] for r in projection.rows}:
        raise PilotError("D1 source IDs differ from verified R2 source")
    return True


def execute(account_id, token, run_id, run_attempt):
    if not re.fullmatch(r"[0-9]{1,20}", run_id) or not re.fullmatch(r"[0-9]{1,6}", run_attempt):
        raise PilotError("Only an identified GitHub Actions run can create synthetic D1")
    client = D1Client(account_id, token)
    existing = client.list_databases()
    result = {"account_access_verified": True, "existing_d1_databases": len(existing),
              "synthetic_only": True, "production_writes": 0,
              "supabase_writes": 0, "r2_writes": 0, "shopify_writes": 0}
    if len(existing) > MAX_VISIBLE_D1_DATABASES_BEFORE_PILOT:
        return {**result, "status":"INSPECT_OK_DATABASE_LIMIT_GUARD_BLOCKED_PILOT"}
    name = f"drop-rate-d1-synthetic-{run_id}-{run_attempt}"
    if any(db.get("name") == name for db in existing):
        raise PilotError("Existing synthetic database name; refusing any mutation")
    database_id = client.create_synthetic_database(name)
    # Database is intentionally retained for independent inspection.
    result.update(database_name=name, database_uuid=database_id)
    schema(client, database_id)
    with synthetic_snapshot() as first, synthetic_snapshot(
        revision="stage1-synthetic-v2", renamed=True
    ) as second:
        first_projection = shadow.from_verified_snapshot(first)
        second_projection = shadow.from_verified_snapshot(second)
        query_one(client, database_id, shadow.generation_statement(first_projection)["sql"],
                  shadow.generation_statement(first_projection)["params"])
        before = list(shadow.insert_statements(first_projection))
        query_one(client, database_id, before[0]["sql"], before[0]["params"])
        if activate(client, database_id, first_projection) is not None:
            raise PilotError("Incomplete D1 shadow generation became public")
        for item in before[1:]:
            query_one(client, database_id, item["sql"], item["params"])
        if activate(client, database_id, first_projection) != first_projection.manifest_sha:
            raise PilotError("Complete D1 shadow generation did not publish")
        verify_exact(client, database_id, first_projection)
        query_one(client, database_id, shadow.generation_statement(second_projection)["sql"],
                  shadow.generation_statement(second_projection)["params"])
        second_batches = list(shadow.insert_statements(second_projection))
        query_one(client, database_id, second_batches[0]["sql"], second_batches[0]["params"])
        if activate(client, database_id, second_projection) != first_projection.manifest_sha:
            raise PilotError("Incomplete update displaced valid R2 generation")
        for item in second_batches[1:]:
            query_one(client, database_id, item["sql"], item["params"])
        if activate(client, database_id, second_projection) != second_projection.manifest_sha:
            raise PilotError("Fully loaded second generation did not become active")
        verify_exact(client, database_id, second_projection)
        if activate(client, database_id, first_projection) != first_projection.manifest_sha:
            raise PilotError("Immutable R2/D1 catalogue rollback failed")
        verify_exact(client, database_id, first_projection)
    return {**result, "status": "SYNTHETIC_REMOTE_D1_SHADOW_VERIFIED",
            "synthetic_catalogue_rows":18,
            "source_manifests_tested":2,
            "integrity_guard_passed":True, "partial_publication_blocked":True,
            "complete_generation_activated":True, "rollback_verified":True,
            "note":"This is remote D1, NOT a live R2 import or full migration."}


def main():
    try:
        result=execute(
            os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            os.environ.get("CLOUDFARE_D1_PILOT_TOKEN", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
            os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        )
    except (PilotError, shadow.ProjectionError) as exc:
        # Never print provider/token response bodies or stack traces with secrets.
        print("D1 shadow pilot failed safely: " + str(exc), file=sys.stderr)
        return 1
    Path("d1-shadow-pilot-report.json").write_text(json.dumps(result,sort_keys=True,indent=2) + "\n")
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
