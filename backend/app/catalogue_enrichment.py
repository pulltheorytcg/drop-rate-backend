"""Cloudflare R2-first, append-only per-print enrichment worklists.

Only verified *already published* source generations are eligible. Every
candidate records the missing exact-image rights/printing and market sold-
evidence requirements. This does NOT download unlicensed images, calculate
price from asking/RRP, publish art, or touch physical inventory/Shopify.

R2 holds immutable SHA-256 verified private candidate objects; PostgreSQL is
queried only for the authoritative published source fingerprint and identity.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .r2_first_catalogue import _parse_part, _json, load_manifest
from .r2_first_import import APPROVED_METADATA_SOURCES, _permission
from .r2_first_sources import source_descriptor
from . import r2_first_service as service

log = logging.getLogger(__name__)

SCHEMA = "drop-rate-verified-enrichment-worklist-v1"
PARTS_PER_PASS = 6
SLOT_SECONDS = 900  # 15 minutes; one full MTG sweep in ~13h at 6 parts/pass.
MAX_BATCH_BYTES = 3_000_000
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class EnrichmentError(ValueError):
    """Untrusted source, capacity, publication drift or invalid R2 snapshot."""


def candidate(row: dict) -> dict:
    """Metadata-only requirements, NEVER authority to use artwork or a price."""
    if row["product_type"] == "CARD":
        exact = bool(row["set_id"] and row["card_number"])
    else:
        # A curated figure SKU is insufficient evidence of physical variation.
        exact = False
    return {
        "reference_key": row["key"],
        "provider_id": row["provider_id"],
        "product_type": row["product_type"],
        "set_id": row["set_id"],
        "card_number": row["card_number"],
        "language": row["language"],
        "finish": row["finish"] or "",
        "rarity": row["rarity"] or "",
        "release_date": row["release_date"],
        "identity_state": "PRINTING_REVIEW_REQUIRED" if exact else "IDENTITY_REVIEW_REQUIRED",
        "artwork_state": "NEEDS_EXACT_PRINT_AND_COMMERCIAL_RIGHTS_PROOF",
        "market_state": "NEEDS_EXACT_UK_SOLD_EVIDENCE",
        "slab_photo_state": "NOT_APPLICABLE_TO_CANONICAL_REFERENCE",
    }


def plan_bytes(manifest: dict, part: dict, rows: list[dict]) -> bytes:
    """Closed, bounded canonical object for one exact R2 source part."""
    if not rows or len(rows) != part["rows"] or part["rows"] > 500:
        raise EnrichmentError("Invalid verified source part")
    digest = hashlib.sha256(_json(manifest)).hexdigest()
    # canonical source manifest hash is independently checked in run_batch.
    payload = {
        "schema": SCHEMA,
        "source_manifest_sha256": digest,
        "provider": manifest["provider"],
        "system_code": manifest["system_code"],
        "language": manifest["language"],
        "source_revision": manifest["source_revision"],
        "source_permission_ref": manifest["permission_ref"],
        "part_sha256": part["sha256"],
        "part_ordinal": part["ordinal"],
        "records": [candidate(row) for row in rows],
        "no_artwork_rights_inferred": True,
        "no_market_value_inferred": True,
        "no_physical_inventory_or_shopify_writes": True,
    }
    raw = _json(payload)
    if not 0 < len(raw) <= MAX_BATCH_BYTES:
        raise EnrichmentError("Enrichment worklist exceeds private R2 bound")
    return raw


async def _authorised_publication(pool, actor: UUID, descriptor):
    async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as conn:
        await require_platform_admin(conn)
        row = await conn.fetchrow(
            """select * from tcg_private.r2_first_catalogue_publications
               where provider=$1 and system_code=$2 and language=$3 and active""",
            descriptor.provider, descriptor.system_code, descriptor.catalogue_language,
        )
    return dict(row) if row else None


async def run_batch(pool, actor: str, source: str, *, storage=None, slot=None) -> dict:
    """Scan bounded parts; R2 verified queues survive independently of SQL volume.

    The selection algorithm is deterministic for the 15-minute UTC slot, so
    missed runs are retried on future cycles and duplicate events are harmless.
    Public source references are never transformed into permissions or prices.
    """
    if source not in APPROVED_METADATA_SOURCES:
        raise EnrichmentError("Unapproved source")
    descriptor = source_descriptor(source)
    actor_id = UUID(str(actor))
    current = await _authorised_publication(pool, actor_id, descriptor)
    if current is None:
        return {
            "status": "NO_ACTIVE_CATALOGUE_GENERATION",
            "source": source, "processed_parts": 0, "candidate_count": 0,
            "source_manifest_sha256": None, "worklist_sha256": [],
        }
    digest = current["manifest_sha256"]
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise EnrichmentError("Invalid active manifest digest")
    storage = storage or service.storage()
    manifest = await load_manifest(digest, storage)
    service._manifest_binding(manifest, current)
    _permission(manifest)
    scope = (manifest["provider"], manifest["system_code"], manifest["language"])
    parts = manifest["parts"]
    if not parts or len(parts) > 1024:
        raise EnrichmentError("Invalid active source partition")
    if slot is None:
        slot = int(datetime.now(timezone.utc).timestamp() // SLOT_SECONDS)
    if type(slot) is not int or slot < 0:
        raise EnrichmentError("Invalid clock slot")
    start = slot * PARTS_PER_PASS % len(parts)
    indexes = [(start + i) % len(parts) for i in range(min(PARTS_PER_PASS, len(parts)))]
    receipts = []
    examined = reviewed = 0
    for index in indexes:
        part = parts[index]
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot, part["sha256"])
        rows = await asyncio.to_thread(_parse_part, raw, part, scope)
        plan = plan_bytes(manifest, part, rows)
        expected = hashlib.sha256(plan).hexdigest()
        uploaded = await asyncio.to_thread(storage.put_verified_reference_snapshot, plan)
        if (uploaded.get("verified") is not True or uploaded.get("sha256") != expected):
            raise EnrichmentError("R2 worklist failed write verification")
        readback = await asyncio.to_thread(storage.read_verified_reference_snapshot, expected)
        if readback != plan:
            raise EnrichmentError("R2 worklist failed byte readback")
        receipts.append({"part_ordinal": part["ordinal"], "worklist_sha256": expected,
                         "candidate_count": len(rows)})
        examined += len(rows)
        reviewed += sum(not row["set_id"] or (row["product_type"] == "CARD" and not row["card_number"])
                        or row["product_type"] != "CARD" for row in rows)
    # A new catalogue generation may have won while the R2 worklists staged;
    # existing immutable blobs remain private, never adopted as a live pointer.
    latest = await _authorised_publication(pool, actor_id, descriptor)
    if (latest is None or latest["manifest_sha256"] != digest
            or latest["generation"] != current["generation"]):
        return {"status": "STALE_GENERATION_PRIVATE_ONLY", "source": source,
                "processed_parts": 0, "candidate_count": 0,
                "source_manifest_sha256": digest, "worklist_sha256": []}
    output = {
        "status": "PRIVATE_ENRICHMENT_WORKLIST_VERIFIED",
        "source": source, "system_code": manifest["system_code"],
        "generation": current["generation"],
        "source_manifest_sha256": digest,
        "total_source_parts": len(parts),
        "processed_parts": len(receipts), "candidate_count": examined,
        "identity_review_count": reviewed,
        "requires_exact_rights_and_printing": examined,
        "requires_verified_sold_evidence": examined,
        "worklist_parts": receipts,
        "worklist_sha256": [r["worklist_sha256"] for r in receipts],
        "artwork_published": False, "market_values_written": 0,
        "shopify_updated": False, "ownership_or_price_changed": False,
    }
    log.warning("ENRICHMENT_PRIVATE_WORKLIST source=%s generation=%s part_count=%s reviewed=%s",
                source, current["generation"], len(receipts), reviewed)
    return output
