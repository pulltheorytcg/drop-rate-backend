from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .recognition_images import reference_image_hashes
from .recognition_reference_index import FINGERPRINT_VERSION


REBUILD_MAX_CONCURRENCY = 10
DEFAULT_MIN_SIMILARITY = 0.40
DEFAULT_MAX_CANDIDATES = 24


def _hash_hexes(hashes: tuple[int, ...]) -> list[str]:
    return [f"{value:064x}" for value in hashes]


async def _eligible_provider_reference_rows(
    connection,
    *,
    limit: int,
    system_code: str | None = None,
    language: str | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        select
            c.provider,c.system_code,c.language,c.provider_id,c.set_id,
            c.name,c.card_number,c.image_url,c.source_url,c.refreshed_at,
            s.name as set_name,s.release_date
        from tcg.reference_cards c
        join tcg.reference_sets s
          on s.provider=c.provider
         and s.system_code=c.system_code
         and s.language=c.language
         and s.set_id=c.set_id
        left join tcg.recognition_provider_reference_fingerprints rf
          on rf.provider=c.provider
         and rf.system_code=c.system_code
         and rf.language=c.language
         and rf.provider_id=c.provider_id
         and rf.fingerprint_version=$1
        where c.image_url is not null
          and btrim(c.image_url)<>''
          and (s.release_date is null or s.release_date<=current_date)
          and ($2::text is null or c.system_code=$2)
          and (
              $3::text is null
              or btrim($3)=''
              or $3='Unknown'
              or c.language in ($3,'Unknown')
          )
          and (
              rf.provider_id is null
              or rf.image_url is distinct from c.image_url
          )
        order by
            c.system_code,c.provider,c.language,
            c.refreshed_at desc,c.provider_id
        limit $4
        offset $5
        """,
        FINGERPRINT_VERSION,
        system_code,
        language,
        limit,
        max(0, offset),
    )
    return [dict(row) for row in rows]


async def fingerprint_provider_reference_rows(rows: list[Mapping[str, Any]]):
    """Fetch provider reference images outside a database transaction."""
    semaphore = asyncio.Semaphore(REBUILD_MAX_CONCURRENCY)

    async def one(row: Mapping[str, Any]):
        async with semaphore:
            hashes = await reference_image_hashes(str(row.get("image_url") or ""))
        return dict(row), hashes

    return await asyncio.gather(*(one(row) for row in rows))


async def rebuild_provider_reference_index(
    connection,
    *,
    actor_user_id: UUID,
    prepared: list | None = None,
    limit: int = 500,
    system_code: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    if prepared is None:
        rows = await _eligible_provider_reference_rows(
            connection,
            limit=limit,
            system_code=system_code,
            language=language,
        )
        resolved = await fingerprint_provider_reference_rows(rows)
    else:
        resolved = prepared

    indexed = 0
    skipped_unavailable = 0
    for row, hashes in resolved:
        if not hashes:
            skipped_unavailable += 1
            continue

        write_result = await connection.execute(
            """
            insert into tcg.recognition_provider_reference_fingerprints(
                provider,system_code,language,provider_id,fingerprint_version,
                source_hashes,image_url,created_by_user_id
            )
            select
                c.provider,c.system_code,c.language,c.provider_id,$1,
                array(
                    select ('x' || lower(value))::bit(256)
                    from unnest($2::text[]) value
                ),
                c.image_url,$3
            from tcg.reference_cards c
            join tcg.reference_sets s
              on s.provider=c.provider
             and s.system_code=c.system_code
             and s.language=c.language
             and s.set_id=c.set_id
            where c.provider=$4
              and c.system_code=$5
              and c.language=$6
              and c.provider_id=$7
              and c.image_url=$8
              and c.image_url is not null
              and (s.release_date is null or s.release_date<=current_date)
            on conflict (
                provider,system_code,language,provider_id,fingerprint_version
            )
            do update set
                source_hashes=excluded.source_hashes,
                image_url=excluded.image_url,
                updated_at=clock_timestamp(),
                version=tcg.recognition_provider_reference_fingerprints.version+1
            where
                tcg.recognition_provider_reference_fingerprints.source_hashes
                    is distinct from excluded.source_hashes
                or tcg.recognition_provider_reference_fingerprints.image_url
                    is distinct from excluded.image_url
            """,
            FINGERPRINT_VERSION,
            _hash_hexes(tuple(hashes)),
            actor_user_id,
            row["provider"],
            row["system_code"],
            row["language"],
            row["provider_id"],
            row["image_url"],
        )
        if write_result != "INSERT 0 0":
            indexed += 1

    return {
        "eligible": len(resolved),
        "indexed": indexed,
        "skipped_unavailable": skipped_unavailable,
        "fingerprint_version": FINGERPRINT_VERSION,
    }


async def provider_reference_index_status(connection) -> dict[str, Any]:
    total = await connection.fetchrow(
        """
        select
            count(*)::integer as eligible,
            count(*) filter (
                where rf.provider_id is not null
                  and rf.image_url=c.image_url
            )::integer as indexed_current,
            count(*) filter (
                where rf.provider_id is not null
                  and rf.image_url is distinct from c.image_url
            )::integer as stale
        from tcg.reference_cards c
        join tcg.reference_sets s
          on s.provider=c.provider
         and s.system_code=c.system_code
         and s.language=c.language
         and s.set_id=c.set_id
        left join tcg.recognition_provider_reference_fingerprints rf
          on rf.provider=c.provider
         and rf.system_code=c.system_code
         and rf.language=c.language
         and rf.provider_id=c.provider_id
         and rf.fingerprint_version=$1
        where c.image_url is not null
          and btrim(c.image_url)<>''
          and (s.release_date is null or s.release_date<=current_date)
        """,
        FINGERPRINT_VERSION,
    )
    systems = await connection.fetch(
        """
        select
            c.system_code,
            count(*)::integer as eligible,
            count(*) filter (
                where rf.provider_id is not null
                  and rf.image_url=c.image_url
            )::integer as indexed_current
        from tcg.reference_cards c
        join tcg.reference_sets s
          on s.provider=c.provider
         and s.system_code=c.system_code
         and s.language=c.language
         and s.set_id=c.set_id
        left join tcg.recognition_provider_reference_fingerprints rf
          on rf.provider=c.provider
         and rf.system_code=c.system_code
         and rf.language=c.language
         and rf.provider_id=c.provider_id
         and rf.fingerprint_version=$1
        where c.image_url is not null
          and btrim(c.image_url)<>''
          and (s.release_date is null or s.release_date<=current_date)
        group by c.system_code
        order by c.system_code
        """,
        FINGERPRINT_VERSION,
    )
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "eligible": int(total["eligible"] or 0),
        "indexed_current": int(total["indexed_current"] or 0),
        "stale": int(total["stale"] or 0),
        "systems": [dict(row) for row in systems],
    }


async def discover_provider_reference_visual_hints(
    connection,
    source_hashes: tuple[int, ...],
    *,
    system_code: str,
    language: str,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    if not source_hashes or not system_code:
        return []

    rows = await connection.fetch(
        """
        select *
        from tcg.recognition_provider_reference_visual_hints(
            $1,$2,$3::text[],$4,$5
        )
        """,
        system_code,
        language,
        _hash_hexes(source_hashes),
        max_candidates,
        min_similarity,
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        evidence = item.get("evidence")
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        if not isinstance(evidence, Mapping):
            evidence = {}
        visual_similarity = float(item.get("similarity") or 0.0)
        output.append(
            {
                **dict(evidence),
                "provider": item["provider"],
                "provider_id": item["provider_id"],
                "system_code": item["system_code"],
                "language": item["language"],
                "name": item["name"],
                "base_card_id": item["card_number"],
                "set_id": item["set_id"],
                "set_name": item["set_name"],
                "finish": item.get("finish"),
                "rarity": item.get("rarity"),
                "image_url": item.get("image_url"),
                "source_reference": item.get("source_url"),
                "library_reference": True,
                "exact_printing_verified": False,
                "visual_similarity": visual_similarity,
                "visual_similarity_source": "provider_reference_index",
                "retrieval_score": visual_similarity,
            }
        )
    return output
