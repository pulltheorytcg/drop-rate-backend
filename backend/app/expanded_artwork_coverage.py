"""DR107: authoritative read-only artwork coverage for the three R2-first TCGs.

Report counts only images that are BOTH linked to a current published R2
reference and verified/approved/ready in the canonical Postgres media ledger.
Raw third-party URL candidates, import metadata, scans of other owners' cards,
and old/stale publication generations are never counted as published art.

No image retrieval, R2 writes, source approval, pricing or Shopify mutations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection

router = APIRouter(prefix="/api/v1/artwork", tags=["artwork-coverage"])

GAMES = {
    "YUGIOH": "Yu-Gi-Oh!",
    "DISNEY_LORCANA": "Disney Lorcana",
    "MAGIC_THE_GATHERING": "Magic: The Gathering",
}

COVERAGE_SQL = """
select p.provider, p.system_code, p.language, p.record_count,
       p.released_record_count, p.manifest_sha256, p.published_at,
       count(distinct l.reference_key)::int as materialized_links,
       count(distinct l.reference_key) filter (
         where m.id is not null
       )::int as approved_canonical_images
from tcg_private.r2_first_catalogue_publications p
left join tcg_private.r2_first_catalogue_links l
  on l.provider=p.provider and l.system_code=p.system_code
 and l.language=p.language
 and l.source_manifest_sha256=p.manifest_sha256
left join tcg.media_assets m on m.catalogue_id=l.catalogue_id
 and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
 and m.media_kind='IMAGE' and m.side='FRONT'
 and m.rights_tier='STOREFRONT_ALLOWED'
 and m.rights_status='VERIFIED'
 and m.approval_status='APPROVED'
 and m.source_status='ACTIVE' and m.revoked_at is null
 and m.shopify_file_status='READY'
where p.active and p.system_code in ('YUGIOH','DISNEY_LORCANA','MAGIC_THE_GATHERING')
group by p.provider,p.system_code,p.language,p.record_count,
         p.released_record_count,p.manifest_sha256,p.published_at
order by p.system_code
"""


def summarize(rows) -> dict:
    """Conservative, publication-pinned coverage; missing source fails closed."""
    by_game = {}
    for src in rows:
        row = dict(src)
        system = row.get("system_code")
        if system not in GAMES or system in by_game:
            raise ValueError("Duplicate or unexpected artwork source publication")
        released = int(row["released_record_count"])
        stored = int(row["record_count"])
        linked = int(row["materialized_links"])
        approved = int(row["approved_canonical_images"])
        if not (0 <= approved <= linked <= released <= stored):
            raise ValueError("Inconsistent artwork coverage counters")
        by_game[system] = {
            "game": GAMES[system],
            "source": row["provider"],
            "language": row["language"],
            "stored_records": stored,
            "released_records": released,
            "linked_reference_records": linked,
            "approved_listing_artwork_records": approved,
            "unlinked_records": released - linked,
            "linked_without_approved_artwork": linked - approved,
            "artwork_missing_records": released - approved,
            "artwork_coverage_percent": round(approved * 100 / released, 2) if released else 0.0,
            "publication_manifest_sha256": row["manifest_sha256"],
            "publication_at": row["published_at"],
            "status": "AVAILABLE" if approved == released and released else "ARTWORK_INCOMPLETE",
        }
    for code in GAMES:
        if code not in by_game:
            by_game[code] = {
                "game": GAMES[code], "status": "MISSING_PUBLISHED_CATALOGUE",
                "released_records": 0, "approved_listing_artwork_records": 0,
                "artwork_missing_records": None, "artwork_coverage_percent": 0.0,
            }
    released_total = sum(item["released_records"] for item in by_game.values())
    approved_total = sum(item["approved_listing_artwork_records"] for item in by_game.values())
    return {
        "schema": "drop-rate-artwork-coverage-v1",
        "games": {key: by_game[key] for key in GAMES},
        "totals": {
            "released_records": released_total,
            "approved_listing_artwork_records": approved_total,
            "artwork_missing_records": released_total - approved_total,
            "artwork_coverage_percent": round(approved_total * 100 / released_total, 2)
            if released_total else 0.0,
        },
        "image_candidates_are_not_approved": True,
        "reads_only": True,
    }


@router.get("/coverage")
async def artwork_coverage(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Platform-admin-only via main.py router dependency; no image bytes."""
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        rows = await connection.fetch(COVERAGE_SQL)
    return jsonable_encoder({
        **summarize(rows),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })
