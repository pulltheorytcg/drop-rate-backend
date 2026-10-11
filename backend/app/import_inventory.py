"""Shared physical-copy writer for legacy and incremental import entry points."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg


def json_object(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Stored import record must be an object")
    return value


async def lock_import_owner(connection: asyncpg.Connection, owner_id: UUID) -> None:
    # Transaction lock, not an UPDATE privilege on the ownership table.
    await connection.fetchval(
        "select pg_advisory_xact_lock(hashtextextended('tcg.collection.import:' || $1::uuid::text,0))",
        owner_id,
    )


async def create_draft_copies(connection: asyncpg.Connection, *, candidates: list,
                              owner_id: UUID, batch_id: UUID, adapter: str) -> int:
    created = 0
    for candidate in candidates:
        normalized = json_object(candidate["normalized_record"])
        raw = json_object(candidate["raw_record"])
        for copy_number in range(1, candidate["quantity"] + 1):
            inventory_id = uuid4()
            await connection.execute(
                """insert into tcg.inventory_items(
                    id,inventory_code,catalogue_id,owner_id,acquisition_cost_minor,
                    currency,condition,seal_status,grading_company,grade,
                    certificate_number,language,identity_confirmed,status,notes,
                    import_batch_id,source_row,source_copy,source_record
                ) values($1,$2,$3,$4,$5,'GBP',$6,$7,$8,$9,$10,$11,
                         false,'DRAFT','',$12,$13,$14,$15::jsonb)""",
                inventory_id,f"INV-{inventory_id.hex.upper()}",candidate["catalogue_id"],owner_id,
                normalized.get("acquisition_cost_minor"),normalized.get("condition"),
                normalized.get("seal_status"),normalized.get("grading_company"),
                normalized.get("grade"),normalized.get("certificate_number"),
                normalized.get("language"),batch_id,candidate["source_row"],
                int(normalized.get("previous_quantity") or 0) + copy_number if adapter == "COLLECTR" else copy_number,
                json.dumps(raw),
            )
            created += 1
        await connection.execute(
            "update tcg.import_candidates set status='COMMITTED' where id=$1 and batch_id=$2 and owner_id=$3 and status='READY'",
            candidate["id"],batch_id,owner_id,
        )
    return created
