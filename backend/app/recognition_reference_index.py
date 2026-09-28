from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from .recognition_images import hash_similarity, reference_image_hashes
from .recognition_learning import decode_fingerprints, encode_fingerprints


FINGERPRINT_VERSION = "dhash16-multicrop-rotate-v1"
MAX_REFERENCE_ROWS = 10_000
DEFAULT_MIN_SIMILARITY = 0.40
DEFAULT_MAX_CANDIDATES = 24
REBUILD_MAX_CONCURRENCY = 6


def _trust_level(row: Mapping[str, Any]) -> str:
    return "VERIFIED" if str(row.get("approval_status") or "") == "APPROVED" else "PROVISIONAL"


async def _eligible_reference_rows(
    connection,
    *,
    limit: int,
    catalogue_ids: Sequence[UUID] | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    catalogue_filter = ""
    if catalogue_ids:
        params.append(list(dict.fromkeys(catalogue_ids)))
        catalogue_filter = f"and ma.catalogue_id = any(${len(params)}::uuid[])"
    params.append(limit)
    limit_index = len(params)

    rows = await connection.fetch(
        f"""
        select
            ma.id as media_asset_id,
            ma.catalogue_id,
            pr.system_code,
            ma.public_source_url,
            ma.version as media_asset_version,
            ma.approval_status,
            ma.source_provider,
            ma.provider_asset_id,
            pcm.match_status,
            pcm.verification_basis,
            pcm.confidence
        from tcg.media_assets ma
        join tcg.catalogue_product_profiles pr
          on pr.catalogue_id=ma.catalogue_id
        left join lateral (
            select
                x.match_status,
                x.verification_basis,
                x.confidence
            from tcg.provider_catalogue_mappings x
            where x.catalogue_id=ma.catalogue_id
              and lower(x.source_provider)=lower(coalesce(ma.source_provider,''))
              and x.provider_id=ma.provider_asset_id
              and x.match_status <> 'REJECTED'
            order by
                case x.match_status when 'VERIFIED' then 0 when 'REVIEW' then 1 else 2 end,
                x.confidence desc,
                x.created_at desc
            limit 1
        ) pcm on true
        where ma.catalogue_id is not null
          and ma.scope='CANONICAL_CARD'
          and ma.side='FRONT'
          and ma.media_kind='IMAGE'
          and ma.source_type='LICENSED_PROVIDER'
          and ma.source_status='ACTIVE'
          and ma.rights_status='VERIFIED'
          and ma.public_source_url is not null
          and (
              ma.approval_status='APPROVED'
              or (
                  pcm.match_status in ('VERIFIED','REVIEW')
                  and pcm.verification_basis='DETERMINISTIC_EXACT'
                  and coalesce(pcm.confidence,0) >= 0.99
              )
          )
          {catalogue_filter}
        order by
            case ma.approval_status when 'APPROVED' then 0 else 1 end,
            ma.updated_at desc,
            ma.id
        limit ${limit_index}
        """,
        *params,
    )
    return [dict(row) for row in rows]


async def rebuild_reference_index(
    connection,
    *,
    actor_user_id: UUID,
    limit: int = 200,
    catalogue_ids: Sequence[UUID] | None = None,
) -> dict[str, Any]:
    """Hash trusted canonical provider images and persist reusable exact-printing hints.

    Pending-but-deterministically-matched media is indexed as PROVISIONAL and may
    retrieve candidates only. APPROVED media is VERIFIED and can later contribute
    to exact-printing visual evidence.
    """
    rows = await _eligible_reference_rows(
        connection,
        limit=limit,
        catalogue_ids=catalogue_ids,
    )
    semaphore = asyncio.Semaphore(REBUILD_MAX_CONCURRENCY)

    async def fingerprint(row: dict[str, Any]) -> tuple[dict[str, Any], tuple[int, ...] | None]:
        url = str(row.get("public_source_url") or "").strip()
        if not url:
            return row, None
        async with semaphore:
            hashes = await reference_image_hashes(url)
        return row, hashes

    resolved = await asyncio.gather(*[fingerprint(row) for row in rows])

    indexed = 0
    skipped_unavailable = 0
    verified = 0
    provisional = 0
    for row, hashes in resolved:
        if not hashes:
            skipped_unavailable += 1
            continue

        trust_level = _trust_level(row)
        await connection.execute(
            """
            insert into tcg.recognition_reference_fingerprints(
                catalogue_id,media_asset_id,system_code,fingerprint_version,
                source_fingerprints,trust_level,media_asset_version,source_url,
                created_by_user_id
            ) values(
                $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9
            )
            on conflict (media_asset_id,fingerprint_version)
            do update set
                catalogue_id=excluded.catalogue_id,
                system_code=excluded.system_code,
                source_fingerprints=excluded.source_fingerprints,
                trust_level=excluded.trust_level,
                media_asset_version=excluded.media_asset_version,
                source_url=excluded.source_url,
                updated_at=clock_timestamp(),
                version=tcg.recognition_reference_fingerprints.version+1
            where
                tcg.recognition_reference_fingerprints.catalogue_id
                    is distinct from excluded.catalogue_id
                or tcg.recognition_reference_fingerprints.system_code
                    is distinct from excluded.system_code
                or tcg.recognition_reference_fingerprints.source_fingerprints
                    is distinct from excluded.source_fingerprints
                or tcg.recognition_reference_fingerprints.trust_level
                    is distinct from excluded.trust_level
                or tcg.recognition_reference_fingerprints.media_asset_version
                    is distinct from excluded.media_asset_version
                or tcg.recognition_reference_fingerprints.source_url
                    is distinct from excluded.source_url
            """,
            row["catalogue_id"],
            row["media_asset_id"],
            row["system_code"],
            FINGERPRINT_VERSION,
            json.dumps(encode_fingerprints(hashes)),
            trust_level,
            row["media_asset_version"],
            row["public_source_url"],
            actor_user_id,
        )
        indexed += 1
        if trust_level == "VERIFIED":
            verified += 1
        else:
            provisional += 1

    return {
        "eligible": len(rows),
        "indexed": indexed,
        "verified": verified,
        "provisional": provisional,
        "skipped_unavailable": skipped_unavailable,
        "fingerprint_version": FINGERPRINT_VERSION,
    }


async def discover_reference_candidate_hints(
    connection,
    source_hashes: tuple[int, ...],
    *,
    system_code: str | None = None,
    max_rows: int = MAX_REFERENCE_ROWS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Retrieve visually similar catalogue printings from persistent fingerprints."""
    if not source_hashes:
        return []

    rows = await connection.fetch(
        """
        select catalogue_id,media_asset_id,system_code,source_fingerprints,trust_level
        from tcg.recognition_reference_hint_rows($1,$2)
        """,
        system_code,
        max_rows,
    )

    best: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        fingerprints = decode_fingerprints(row["source_fingerprints"])
        if not fingerprints:
            continue
        similarity = hash_similarity(source_hashes, fingerprints)
        if similarity is None or float(similarity) < min_similarity:
            continue

        catalogue_id = row["catalogue_id"]
        current = best.get(catalogue_id)
        candidate = {
            "catalogue_id": catalogue_id,
            "media_asset_id": row["media_asset_id"],
            "system_code": row["system_code"],
            "similarity": round(float(similarity), 5),
            "trust_level": row["trust_level"],
            "fingerprint_version": FINGERPRINT_VERSION,
        }
        if current is None:
            best[catalogue_id] = candidate
            continue

        current_key = (
            float(current["similarity"]),
            1 if current["trust_level"] == "VERIFIED" else 0,
        )
        candidate_key = (
            float(candidate["similarity"]),
            1 if candidate["trust_level"] == "VERIFIED" else 0,
        )
        if candidate_key > current_key:
            best[catalogue_id] = candidate

    ranked = sorted(
        best.values(),
        key=lambda item: (
            -float(item["similarity"]),
            0 if item["trust_level"] == "VERIFIED" else 1,
            str(item["catalogue_id"]),
        ),
    )
    return ranked[:max_candidates]


def attach_reference_candidate_hints(
    candidates: list[dict[str, Any]],
    hints: Sequence[Mapping[str, Any]],
) -> None:
    """Attach persistent retrieval provenance to local catalogue candidates."""
    by_catalogue = {
        str(item.get("catalogue_id")): item
        for item in hints
        if item.get("catalogue_id") is not None
    }
    for candidate in candidates:
        hint = by_catalogue.get(str(candidate.get("catalogue_id")))
        if hint is None:
            candidate["reference_index_similarity"] = None
            candidate["reference_index_trust"] = None
            candidate["reference_index_media_asset_id"] = None
            candidate["reference_index_fingerprint_version"] = None
            continue
        candidate["reference_index_similarity"] = float(hint.get("similarity") or 0.0)
        candidate["reference_index_trust"] = str(hint.get("trust_level") or "")
        candidate["reference_index_media_asset_id"] = hint.get("media_asset_id")
        candidate["reference_index_fingerprint_version"] = hint.get("fingerprint_version")


async def reference_index_status(connection) -> dict[str, Any]:
    eligible = await connection.fetchrow(
        """
        select
            count(*) filter (
                where ma.approval_status='APPROVED'
            )::integer as verified_eligible,
            count(*) filter (
                where ma.approval_status<>'APPROVED'
            )::integer as provisional_eligible
        from tcg.media_assets ma
        left join lateral (
            select x.match_status,x.verification_basis,x.confidence
            from tcg.provider_catalogue_mappings x
            where x.catalogue_id=ma.catalogue_id
              and lower(x.source_provider)=lower(coalesce(ma.source_provider,''))
              and x.provider_id=ma.provider_asset_id
              and x.match_status <> 'REJECTED'
            order by
                case x.match_status when 'VERIFIED' then 0 when 'REVIEW' then 1 else 2 end,
                x.confidence desc,
                x.created_at desc
            limit 1
        ) pcm on true
        where ma.catalogue_id is not null
          and ma.scope='CANONICAL_CARD'
          and ma.side='FRONT'
          and ma.media_kind='IMAGE'
          and ma.source_type='LICENSED_PROVIDER'
          and ma.source_status='ACTIVE'
          and ma.rights_status='VERIFIED'
          and ma.public_source_url is not null
          and (
              ma.approval_status='APPROVED'
              or (
                  pcm.match_status in ('VERIFIED','REVIEW')
                  and pcm.verification_basis='DETERMINISTIC_EXACT'
                  and coalesce(pcm.confidence,0) >= 0.99
              )
          )
        """
    )
    indexed = await connection.fetchrow(
        """
        select
            count(*)::integer as indexed,
            count(*) filter (where trust_level='VERIFIED')::integer as verified,
            count(*) filter (where trust_level='PROVISIONAL')::integer as provisional,
            count(*) filter (
                where ma.version<>rf.media_asset_version
                   or ma.public_source_url<>rf.source_url
                   or ma.source_status<>'ACTIVE'
                   or ma.rights_status<>'VERIFIED'
            )::integer as stale
        from tcg.recognition_reference_fingerprints rf
        join tcg.media_assets ma on ma.id=rf.media_asset_id
        where rf.fingerprint_version=$1
        """,
        FINGERPRINT_VERSION,
    )
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "verified_eligible": int(eligible["verified_eligible"] or 0),
        "provisional_eligible": int(eligible["provisional_eligible"] or 0),
        "indexed": int(indexed["indexed"] or 0),
        "verified": int(indexed["verified"] or 0),
        "provisional": int(indexed["provisional"] or 0),
        "stale": int(indexed["stale"] or 0),
    }
