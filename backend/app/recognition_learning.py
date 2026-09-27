from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from .recognition_images import hash_similarity


TRAIN_PERCENT = 80
VALIDATION_PERCENT = 10
HOLDOUT_PERCENT = 10
MAX_FINGERPRINTS = 16


def encode_fingerprints(values: Sequence[int]) -> list[str]:
    """Serialize 256-bit dHash fingerprints without storing source image pixels."""
    output: list[str] = []
    for value in values[:MAX_FINGERPRINTS]:
        if not isinstance(value, int) or value < 0 or value >= (1 << 256):
            raise ValueError("Recognition fingerprint is outside the 256-bit range")
        output.append(f"{value:064x}")
    return output


def decode_fingerprints(values: object) -> tuple[int, ...]:
    if not isinstance(values, list):
        return ()
    output: list[int] = []
    for raw in values[:MAX_FINGERPRINTS]:
        if not isinstance(raw, str) or len(raw) != 64:
            continue
        try:
            value = int(raw, 16)
        except ValueError:
            continue
        if value < 0 or value >= (1 << 256):
            continue
        output.append(value)
    return tuple(dict.fromkeys(output))


def dataset_split(source_image_sha256: str) -> str:
    """Keep every copy of one image in one partition to prevent train/test leakage."""
    digest = str(source_image_sha256 or "").strip().casefold()
    if len(digest) != 64:
        raise ValueError("Recognition learning split requires a SHA-256 image digest")
    try:
        bucket = int(digest[:8], 16) % 100
    except ValueError as exc:
        raise ValueError("Recognition learning split requires a SHA-256 image digest") from exc
    if bucket < TRAIN_PERCENT:
        return "TRAIN"
    if bucket < TRAIN_PERCENT + VALIDATION_PERCENT:
        return "VALIDATION"
    return "HOLDOUT"


async def register_runtime_model(
    connection,
    *,
    engine_version: str,
    vision_model: str,
    actor_user_id: UUID,
) -> None:
    """Register the running pair; promotion of future candidates remains deliberate."""
    await connection.execute(
        """
        insert into tcg.recognition_model_versions(
            engine_version,vision_model,status,metrics,
            created_by_user_id,promoted_at
        ) values($1,$2,'PRODUCTION','{}'::jsonb,$3,clock_timestamp())
        on conflict (engine_version,vision_model) do nothing
        """,
        engine_version,
        vision_model,
        actor_user_id,
    )


async def materialize_learning_example(
    connection,
    *,
    run_id: UUID,
    feedback_id: UUID,
    engine_version: str,
) -> dict[str, Any]:
    """Turn one explicit human label into immutable positive/negative learning truth."""
    row = await connection.fetchrow(
        """
        select
            f.id as feedback_id,f.owner_id,f.outcome,f.selected_catalogue_id,
            f.supersedes_feedback_id,f.actor_user_id,
            r.system_code,r.ai_model,r.source_image_sha256,
            r.source_width,r.source_height,r.source_fingerprints,
            r.ai_observation,r.provider_evidence,r.top_score,
            r.runner_up_score,r.score_margin
        from tcg.recognition_feedback f
        join tcg.recognition_runs r on r.id=f.run_id
        where f.id=$1 and f.run_id=$2
        """,
        feedback_id,
        run_id,
    )
    if row is None:
        raise ValueError("Recognition feedback/run pair was not found")
    if not row["source_image_sha256"] or not row["system_code"] or not row["ai_model"]:
        raise ValueError("Recognition run is missing learning provenance")

    supersedes_example_id = None
    if row["supersedes_feedback_id"] is not None:
        supersedes_example_id = await connection.fetchval(
            """
            select id
            from tcg.recognition_learning_examples
            where feedback_id=$1
            """,
            row["supersedes_feedback_id"],
        )

    split = dataset_split(str(row["source_image_sha256"]))
    example = await connection.fetchrow(
        """
        insert into tcg.recognition_learning_examples(
            run_id,feedback_id,owner_id,system_code,selected_catalogue_id,
            label_outcome,engine_version,vision_model,source_image_sha256,
            source_width,source_height,source_fingerprints,observation,
            provider_evidence,top_score,runner_up_score,score_margin,
            dataset_split,supersedes_example_id,created_by_user_id
        ) values(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb,
            $14::jsonb,$15,$16,$17,$18,$19,$20
        )
        returning *
        """,
        run_id,
        row["feedback_id"],
        row["owner_id"],
        row["system_code"],
        row["selected_catalogue_id"],
        row["outcome"],
        engine_version,
        row["ai_model"],
        row["source_image_sha256"],
        row["source_width"],
        row["source_height"],
        row["source_fingerprints"],
        row["ai_observation"],
        row["provider_evidence"],
        row["top_score"],
        row["runner_up_score"],
        row["score_margin"],
        split,
        supersedes_example_id,
        row["actor_user_id"],
    )

    candidates = await connection.fetch(
        """
        select
            candidate_key,source_kind,catalogue_id,provider,provider_id,
            rank,score,signals,candidate_snapshot
        from tcg.recognition_candidates
        where run_id=$1
          and not hard_rejected
        order by rank
        """,
        run_id,
    )
    for candidate in candidates:
        if (
            row["selected_catalogue_id"] is not None
            and candidate["catalogue_id"] == row["selected_catalogue_id"]
        ):
            continue
        reason = (
            "REJECTED_ALL"
            if row["outcome"] == "REJECTED_ALL"
            else "WRONG_VIABLE_CANDIDATE"
        )
        await connection.execute(
            """
            insert into tcg.recognition_hard_negatives(
                learning_example_id,candidate_key,source_kind,
                negative_catalogue_id,provider,provider_id,original_rank,
                original_score,negative_reason,signals,candidate_snapshot
            ) values(
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb
            )
            on conflict (learning_example_id,candidate_key) do nothing
            """,
            example["id"],
            candidate["candidate_key"],
            candidate["source_kind"],
            candidate["catalogue_id"],
            candidate["provider"],
            candidate["provider_id"],
            candidate["rank"],
            candidate["score"],
            reason,
            candidate["signals"],
            candidate["candidate_snapshot"],
        )

    return dict(example)


async def attach_learning_visual_evidence(
    connection,
    source_hashes: tuple[int, ...],
    candidates: list[dict[str, Any]],
    *,
    max_examples_per_candidate: int = 8,
) -> None:
    """Attach a bounded signal from prior active TRAIN labels for the same printing."""
    catalogue_ids = [
        candidate.get("catalogue_id")
        for candidate in candidates
        if candidate.get("catalogue_id") is not None
    ]
    catalogue_ids = list(dict.fromkeys(catalogue_ids))
    if not source_hashes or not catalogue_ids:
        for candidate in candidates:
            candidate["learning_visual_similarity"] = None
            candidate["learning_example_count"] = 0
        return

    rows = await connection.fetch(
        """
        with active as (
            select
                e.id,e.selected_catalogue_id,e.source_fingerprints,e.created_at,
                row_number() over (
                    partition by e.selected_catalogue_id
                    order by e.created_at desc,e.id desc
                ) as recency_rank
            from tcg.recognition_learning_examples e
            where e.selected_catalogue_id = any($1::uuid[])
              and e.dataset_split='TRAIN'
              and e.label_outcome in ('CONFIRMED_TOP','CORRECTED_TO_CANDIDATE')
              and not exists (
                  select 1
                  from tcg.recognition_learning_examples newer
                  where newer.supersedes_example_id=e.id
              )
        )
        select selected_catalogue_id,source_fingerprints
        from active
        where recency_rank <= $2
        """,
        catalogue_ids,
        max_examples_per_candidate,
    )

    by_catalogue: dict[UUID, list[tuple[int, ...]]] = {}
    for row in rows:
        fingerprints = decode_fingerprints(row["source_fingerprints"])
        if fingerprints:
            by_catalogue.setdefault(row["selected_catalogue_id"], []).append(fingerprints)

    for candidate in candidates:
        catalogue_id = candidate.get("catalogue_id")
        examples = by_catalogue.get(catalogue_id, [])
        similarities = [
            hash_similarity(source_hashes, fingerprints)
            for fingerprints in examples
        ]
        usable = [float(value) for value in similarities if value is not None]
        candidate["learning_visual_similarity"] = max(usable) if usable else None
        candidate["learning_example_count"] = len(usable)


async def learning_status(connection, *, owner_id: UUID) -> dict[str, Any]:
    row = await connection.fetchrow(
        """
        select
            count(*)::integer as total_examples,
            count(*) filter (where dataset_split='TRAIN')::integer as train_examples,
            count(*) filter (where dataset_split='VALIDATION')::integer as validation_examples,
            count(*) filter (where dataset_split='HOLDOUT')::integer as holdout_examples,
            count(*) filter (
                where label_outcome='CORRECTED_TO_CANDIDATE'
            )::integer as corrected_examples,
            count(*) filter (
                where label_outcome='REJECTED_ALL'
            )::integer as rejected_all_examples
        from tcg.recognition_learning_examples
        where owner_id=$1
        """,
        owner_id,
    )
    negatives = await connection.fetchval(
        """
        select count(*)::integer
        from tcg.recognition_hard_negatives n
        join tcg.recognition_learning_examples e
          on e.id=n.learning_example_id
        where e.owner_id=$1
        """,
        owner_id,
    )
    result = dict(row) if row is not None else {}
    result["hard_negatives"] = int(negatives or 0)
    result["raw_source_images_stored"] = False
    result["online_learning_source"] = "HUMAN_VERIFIED_TRAIN_SPLIT"
    return result
