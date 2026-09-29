from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .language import clean_language, parse_title_language
from .collectr_snapshot import (
    collectr_adapter_headers,
    collectr_catalogue_identity_key,
    collectr_cost_minor,
    collectr_grade,
    collectr_product_type,
    collectr_snapshot_key,
)

router = APIRouter(prefix="/api/v1/imports")

ImportAdapter = Literal["AUTO", "COLLECTR", "EBAY_PURCHASES", "HOLODEX", "GENERIC_CSV"]


class ImportPreviewRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=8_000_000)
    adapter: ImportAdapter = "AUTO"
    default_game: str | None = Field(default=None, max_length=80)
    default_language: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def normalise(self) -> "ImportPreviewRequest":
        self.filename = self.filename.strip()
        self.default_game = self.default_game.strip() if self.default_game else None
        self.default_language = clean_language(self.default_language)
        if not self.filename.lower().endswith(".csv"):
            raise ValueError("Only CSV imports are supported in this first import release")
        return self


class ImportCommitRequest(BaseModel):
    version: int = Field(ge=1)


ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "card name", "product name", "item title", "title", "product"),
    "game": ("game", "tcg", "category"),
    "set_name": ("set", "set name", "expansion", "series"),
    "card_number": ("card number", "card #", "collector number", "number", "card no"),
    "variant": ("variant", "variance", "printing", "finish", "foil", "version"),
    "rarity": ("rarity",),
    "language": ("language", "lang"),
    "quantity": ("quantity", "qty", "count", "copies"),
    "condition": ("condition", "card condition"),
    "seal_status": ("seal status", "sealed", "sealed status"),
    "grading_company": ("grading company", "grader", "grading service"),
    "grade": ("grade", "grading grade"),
    "certificate_number": ("certificate number", "cert number", "cert #", "certificate"),
    "purchase_price": ("price paid", "purchase price", "average cost paid", "cost", "unit cost", "paid"),
    "currency": ("currency", "currency code"),
    "product_type": ("product type", "type"),
}

CARD_CONDITION_MAP = {
    "nm": "Near Mint",
    "near mint": "Near Mint",
    "lp": "Lightly Played",
    "lightly played": "Lightly Played",
    "mp": "Moderately Played",
    "moderately played": "Moderately Played",
    "hp": "Heavily Played",
    "heavily played": "Heavily Played",
    "damaged": "Damaged",
    "dmg": "Damaged",
}

CANONICAL_SET_NAMES: dict[tuple[str, str], str] = {
    ("one piece", "carrying on his will"): "Carrying On His Will",
}


def _canonical_set_name(game: str | None, set_name: str | None) -> str | None:
    if set_name is None:
        return None
    clean = set_name.strip()
    if not clean:
        return None
    game_key = (game or "").strip().casefold()
    return CANONICAL_SET_NAMES.get((game_key, clean.casefold()), clean)



def _json_value(value: Any, *, expected_type: type, fallback: Any) -> Any:
    """Decode persisted JSON/JSONB whether asyncpg returns text or an object."""

    if value is None:
        return fallback
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Stored import JSON is invalid") from exc
    if not isinstance(decoded, expected_type):
        raise ValueError("Stored import JSON has an unexpected shape")
    return decoded


def _header_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold().replace("_", " ").replace("-", " "))


def _field_map(headers: list[str]) -> dict[str, str]:
    normalized = {_header_key(header): header for header in headers}
    result: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[target] = normalized[alias]
                break
    return result


def _cell(row: dict[str, str], mapping: dict[str, str], key: str) -> str | None:
    source = mapping.get(key)
    if not source:
        return None
    value = (row.get(source) or "").strip()
    return value or None


def _detect_adapter(headers: list[str], requested: ImportAdapter) -> str:
    if requested != "AUTO":
        return requested
    keys = {_header_key(header) for header in headers}
    if collectr_adapter_headers(headers) or "collectr id" in keys:
        return "COLLECTR"
    if {"item number", "seller username", "order number"} & keys:
        return "EBAY_PURCHASES"
    if "holodex" in keys or "scan grade" in keys:
        return "HOLODEX"
    return "GENERIC_CSV"


def _quantity(value: str | None) -> tuple[int, list[str]]:
    if not value:
        return 1, []
    try:
        parsed = int(value)
    except ValueError:
        return 1, ["invalid_quantity"]
    if parsed < 1 or parsed > 1000:
        return 1, ["invalid_quantity"]
    return parsed, []


def _money_minor(value: str | None, currency: str | None) -> tuple[int | None, list[str]]:
    if not value:
        return None, []
    currency_code = (currency or "GBP").strip().upper()
    if currency_code not in ("GBP", "£"):
        return None, ["non_gbp_purchase_cost"]
    cleaned = value.replace("£", "").replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None, ["invalid_purchase_cost"]
    if amount < 0:
        return None, ["invalid_purchase_cost"]
    minor = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return minor, []


def _product_type(value: str | None, seal_status: str | None) -> str:
    if seal_status:
        return "SEALED"
    normalized = (value or "CARD").strip().upper()
    if normalized in {"SEALED", "BOX", "TIN", "ETB", "BOOSTER BOX", "BOOSTER PACK"}:
        return "SEALED"
    if normalized in {"COLLECTION", "SET", "BINDER"}:
        return "COLLECTION"
    return "CARD"


def _seal_status(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    if normalized in {"sealed", "yes", "true", "1", "factory sealed"}:
        return "SEALED"
    if normalized in {"unsealed", "opened", "open", "no", "false", "0"}:
        return "UNSEALED"
    return None


def _normalized_row(
    row: dict[str, str],
    mapping: dict[str, str],
    default_game: str | None,
    default_language: str | None = None,
    *,
    adapter: str = "GENERIC_CSV",
) -> tuple[dict, list[str]]:
    issues: list[str] = []
    seal = _seal_status(_cell(row, mapping, "seal_status"))

    game = _cell(row, mapping, "game") or default_game
    raw_name = _cell(row, mapping, "name")
    parsed_name, title_language = parse_title_language(raw_name)
    raw_set_name = _cell(row, mapping, "set_name")
    _parsed_set_name, set_language = parse_title_language(raw_set_name)
    explicit_language = clean_language(_cell(row, mapping, "language"))
    language_evidence = [
        value for value in (explicit_language, title_language, set_language) if value
    ]
    if len(set(language_evidence)) > 1:
        issues.append("language_conflict")
    language = explicit_language or title_language or set_language or clean_language(default_language)
    name = parsed_name
    set_name = _canonical_set_name(game, raw_set_name)
    card_number = _cell(row, mapping, "card_number")
    rarity = _cell(row, mapping, "rarity") or ""

    if adapter == "COLLECTR":
        product_type = collectr_product_type(name=name, card_number=card_number, rarity=rarity)
    else:
        product_type = _product_type(_cell(row, mapping, "product_type"), seal)

    quantity, quantity_issues = _quantity(_cell(row, mapping, "quantity"))
    issues.extend(quantity_issues)

    if adapter == "COLLECTR":
        cost_minor, cost_issues = collectr_cost_minor(_cell(row, mapping, "purchase_price"))
    else:
        cost_minor, cost_issues = _money_minor(
            _cell(row, mapping, "purchase_price"),
            _cell(row, mapping, "currency"),
        )
    issues.extend(cost_issues)

    raw_condition = _cell(row, mapping, "condition")
    condition = None
    if product_type == "CARD" and raw_condition:
        condition = CARD_CONDITION_MAP.get(raw_condition.casefold())
        if condition is None:
            issues.append("unrecognised_card_condition")

    if not name:
        issues.append("missing_name")
    if not game:
        issues.append("missing_game")
    if not set_name:
        issues.append("missing_set")
    is_collectr_don = (
        adapter == "COLLECTR"
        and (rarity.casefold() == "don!!" or (name or "").strip().casefold().startswith("don!! card"))
    )
    if product_type == "CARD" and not card_number and not is_collectr_don:
        issues.append("missing_card_number")
    if product_type == "CARD" and not language:
        issues.append("missing_language")

    if adapter == "COLLECTR":
        grading_company, grade, grade_issues = collectr_grade(_cell(row, mapping, "grade"))
        issues.extend(grade_issues)
        certificate = None
    else:
        grading_company = _cell(row, mapping, "grading_company")
        grade = _cell(row, mapping, "grade")
        certificate = _cell(row, mapping, "certificate_number")
        if bool(grading_company) != bool(grade):
            issues.append("incomplete_grading_pair")
        if certificate and not grading_company:
            issues.append("certificate_without_grade")

    normalized = {
        "product_type": product_type,
        "game": game,
        "name": name,
        "set_name": set_name,
        "card_number": card_number,
        "variant": _cell(row, mapping, "variant") or "",
        "rarity": rarity,
        "language": language,
        "quantity": quantity,
        "condition": condition,
        "seal_status": seal,
        "grading_company": grading_company,
        "grade": grade,
        "certificate_number": certificate,
        "acquisition_cost_minor": cost_minor,
    }
    return normalized, sorted(set(issues))



async def _catalogue_match(connection: asyncpg.Connection, normalized: dict) -> tuple[UUID | None, list[str]]:
    if any(not normalized.get(key) for key in ("game", "name", "set_name")):
        return None, []

    params: list[object] = [
        normalized["product_type"],
        normalized["game"],
        normalized["name"],
        normalized["set_name"],
    ]
    where = [
        "product_type = $1",
        "lower(btrim(game)) = lower(btrim($2))",
        "lower(btrim(name)) = lower(btrim($3))",
        "lower(btrim(set_name)) = lower(btrim($4))",
    ]
    if normalized["product_type"] == "CARD":
        params.append(normalized.get("card_number") or "")
        where.append(f"lower(btrim(coalesce(card_number, ''))) = lower(btrim(${len(params)}))")
    if normalized.get("variant"):
        params.append(normalized["variant"])
        where.append(f"lower(btrim(variant)) = lower(btrim(${len(params)}))")
    if normalized.get("language"):
        params.append(normalized["language"])
        where.append(f"lower(btrim(coalesce(language, ''))) = lower(btrim(${len(params)}))")

    rows = await connection.fetch(
        f"select id from tcg.catalogue_products where {' and '.join(where)} order by created_at, id limit 3",
        *params,
    )
    if len(rows) == 1:
        return rows[0]["id"], []
    if len(rows) > 1:
        return None, ["ambiguous_catalogue_match"]
    return None, ["catalogue_not_found"]


async def _collectr_previous_snapshot(
    connection: asyncpg.Connection,
    owner_id: UUID,
) -> tuple[UUID | None, dict[tuple[str, ...], dict[str, Any]]]:
    batch = await connection.fetchrow(
        """
        select id
        from tcg.import_batches
        where owner_id = $1
          and adapter = 'COLLECTR'
          and status = 'COMMITTED'
        order by committed_at desc nulls last, created_at desc, id desc
        limit 1
        """,
        owner_id,
    )
    result: dict[tuple[str, ...], dict[str, Any]] = {}

    if batch is not None:
        rows = await connection.fetch(
            """
            select raw_record, normalized_record, catalogue_id
            from tcg.import_candidates
            where batch_id = $1 and owner_id = $2
            order by source_row
            """,
            batch["id"],
            owner_id,
        )
        for row in rows:
            raw = _json_value(row["raw_record"], expected_type=dict, fallback={})
            normalized = _json_value(row["normalized_record"], expected_type=dict, fallback={})
            quantity = int(
                normalized.get("snapshot_quantity")
                or normalized.get("quantity")
                or raw.get("Quantity")
                or 1
            )
            key = collectr_snapshot_key(normalized)
            existing = result.get(key)
            if existing is None:
                result[key] = {
                    "quantity": quantity,
                    "raw_record": raw,
                    "normalized_record": normalized,
                    "catalogue_id": row["catalogue_id"],
                }
            else:
                existing["quantity"] += quantity
        return batch["id"], result

    # Legacy fallback for the first snapshot after the original 2026-09 import.
    rows = await connection.fetch(
        """
        select distinct on (source_row)
            source_record, catalogue_id
        from tcg.inventory_items
        where owner_id = $1
          and import_batch_id is not null
          and source_record is not null
        order by source_row, source_copy
        """,
        owner_id,
    )
    for row in rows:
        raw = _json_value(row["source_record"], expected_type=dict, fallback={})
        mapping = _field_map(list(raw))
        normalized, issues = _normalized_row(raw, mapping, None, None, adapter="COLLECTR")
        if issues:
            continue
        quantity = int(raw.get("Quantity") or 1)
        normalized["snapshot_quantity"] = quantity
        key = collectr_snapshot_key(normalized)
        existing = result.get(key)
        if existing is None:
            result[key] = {
                "quantity": quantity,
                "raw_record": raw,
                "normalized_record": normalized,
                "catalogue_id": row["catalogue_id"],
            }
        else:
            existing["quantity"] += quantity
    return None, result


async def _ensure_collectr_catalogue(
    connection: asyncpg.Connection,
    normalized: dict[str, Any],
) -> UUID:
    rows = await connection.fetch(
        """
        select id
        from tcg.catalogue_products
        where product_type = $1
          and lower(btrim(game)) = lower(btrim($2))
          and lower(btrim(name)) = lower(btrim($3))
          and lower(btrim(set_name)) = lower(btrim($4))
          and lower(btrim(coalesce(card_number, ''))) = lower(btrim(coalesce($5, '')))
          and lower(btrim(variant)) = lower(btrim($6))
          and lower(btrim(rarity)) = lower(btrim($7))
          and lower(btrim(coalesce(language, ''))) = lower(btrim(coalesce($8, '')))
        order by created_at, id
        limit 3
        """,
        normalized["product_type"],
        normalized["game"],
        normalized["name"],
        normalized["set_name"],
        normalized.get("card_number"),
        normalized.get("variant") or "",
        normalized.get("rarity") or "",
        normalized.get("language"),
    )
    if len(rows) == 1:
        return rows[0]["id"]
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail="Collectr identity matches multiple catalogue products; review required",
        )

    catalogue_id = uuid4()
    try:
        await connection.execute(
            """
            insert into tcg.catalogue_products(
                id, identity_key, product_type, game, name, set_name,
                card_number, variant, rarity, language
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            catalogue_id,
            collectr_catalogue_identity_key(normalized),
            normalized["product_type"],
            normalized["game"],
            normalized["name"],
            normalized["set_name"],
            normalized.get("card_number"),
            normalized.get("variant") or "",
            normalized.get("rarity") or "",
            normalized.get("language"),
        )
    except asyncpg.UniqueViolationError:
        rows = await connection.fetch(
            """
            select id
            from tcg.catalogue_products
            where product_type = $1
              and lower(btrim(game)) = lower(btrim($2))
              and lower(btrim(name)) = lower(btrim($3))
              and lower(btrim(set_name)) = lower(btrim($4))
              and lower(btrim(coalesce(card_number, ''))) = lower(btrim(coalesce($5, '')))
              and lower(btrim(variant)) = lower(btrim($6))
              and lower(btrim(rarity)) = lower(btrim($7))
              and lower(btrim(coalesce(language, ''))) = lower(btrim(coalesce($8, '')))
            limit 2
            """,
            normalized["product_type"],
            normalized["game"],
            normalized["name"],
            normalized["set_name"],
            normalized.get("card_number"),
            normalized.get("variant") or "",
            normalized.get("rarity") or "",
            normalized.get("language"),
        )
        if len(rows) != 1:
            raise HTTPException(
                status_code=409,
                detail="Collectr catalogue identity changed concurrently; preview again",
            )
        return rows[0]["id"]
    return catalogue_id


@router.post("/preview", status_code=201)
async def preview_import(
    payload: ImportPreviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    encoded = payload.content.encode("utf-8")
    source_sha256 = hashlib.sha256(encoded).hexdigest()
    try:
        reader = csv.DictReader(io.StringIO(payload.content, newline=""))
        headers = reader.fieldnames or []
        if not headers:
            raise HTTPException(status_code=422, detail="CSV has no header row")
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CSV: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=422, detail="CSV has no data rows")
    if len(rows) > 5000:
        raise HTTPException(status_code=422, detail="Import is limited to 5,000 source rows per batch")

    mapping = _field_map(headers)
    if "name" not in mapping:
        raise HTTPException(status_code=422, detail={"message": "Could not identify a product/card name column", "headers": headers})
    adapter = _detect_adapter(headers, payload.adapter)

    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            "select id, status, created_at from tcg.import_batches where owner_id = $1 and source_sha256 = $2",
            owner["id"], source_sha256,
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail={
                "message": "This exact file has already been imported or previewed",
                "batch_id": str(existing["id"]),
                "status": existing["status"],
            })

        batch_id = uuid4()
        candidates: list[dict] = []
        physical_units = 0
        ready_units = 0
        review_rows = 0
        skipped_rows = 0

        prepared: list[tuple[int, dict[str, str], dict[str, Any], list[str]]] = []
        seen_collectr_keys: set[tuple[str, ...]] = set()
        for source_row, raw in enumerate(rows, start=2):
            normalized, issues = _normalized_row(
                raw,
                mapping,
                payload.default_game,
                payload.default_language,
                adapter=adapter,
            )
            if adapter == "COLLECTR":
                identity = collectr_snapshot_key(normalized)
                if identity in seen_collectr_keys:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message": "Collectr snapshot contains duplicate logical identity rows",
                            "source_row": source_row,
                        },
                    )
                seen_collectr_keys.add(identity)
            prepared.append((source_row, raw, normalized, issues))

        collectr_baseline_id: UUID | None = None
        collectr_baseline: dict[tuple[str, ...], dict[str, Any]] = {}
        if adapter == "COLLECTR":
            collectr_baseline_id, collectr_baseline = await _collectr_previous_snapshot(
                connection,
                owner["id"],
            )

        current_collectr_keys: set[tuple[str, ...]] = set()
        collectr_new_identities = 0
        collectr_increased_identities = 0
        collectr_unchanged_identities = 0
        collectr_delta_units = 0

        for source_row, raw, normalized, issues in prepared:
            catalogue_id = None
            blocking_identity = {"missing_name", "missing_game", "missing_set", "missing_card_number"}
            if not blocking_identity.intersection(issues):
                catalogue_id, match_issues = await _catalogue_match(connection, normalized)
                issues.extend(match_issues)

            snapshot_quantity = int(normalized["quantity"])
            physical_units += snapshot_quantity
            candidate_quantity = snapshot_quantity

            if adapter == "COLLECTR":
                identity = collectr_snapshot_key(normalized)
                current_collectr_keys.add(identity)
                previous = collectr_baseline.get(identity)
                previous_quantity = int(previous["quantity"]) if previous else 0
                delta_quantity = snapshot_quantity - previous_quantity
                normalized["collectr_baseline_batch_id"] = (
                    str(collectr_baseline_id) if collectr_baseline_id else None
                )
                normalized["previous_quantity"] = previous_quantity
                normalized["snapshot_quantity"] = snapshot_quantity
                normalized["delta_quantity"] = delta_quantity
                normalized["reconciliation"] = "SNAPSHOT_DELTA"

                if previous and catalogue_id is None and previous.get("catalogue_id"):
                    catalogue_id = previous["catalogue_id"]
                    issues = [issue for issue in issues if issue != "catalogue_not_found"]

                if delta_quantity < 0:
                    issues.append("collectr_quantity_decrease")
                elif delta_quantity == 0:
                    collectr_unchanged_identities += 1
                else:
                    candidate_quantity = delta_quantity
                    collectr_delta_units += delta_quantity
                    if previous_quantity:
                        collectr_increased_identities += 1
                    else:
                        collectr_new_identities += 1
                    if "catalogue_not_found" in issues:
                        issues = [issue for issue in issues if issue != "catalogue_not_found"]
                        normalized["collectr_create_catalogue"] = True

            issues = sorted(set(issues))
            if adapter == "COLLECTR" and normalized.get("delta_quantity") == 0 and not issues:
                status = "SKIPPED"
                skipped_rows += 1
            else:
                can_create_collectr = (
                    adapter == "COLLECTR"
                    and normalized.get("delta_quantity", 0) > 0
                    and normalized.get("collectr_create_catalogue") is True
                )
                status = "READY" if not issues and (catalogue_id is not None or can_create_collectr) else "REVIEW"
                if status == "READY":
                    ready_units += candidate_quantity
                elif status == "REVIEW":
                    review_rows += 1

            candidates.append({
                "source_row": source_row,
                "quantity": candidate_quantity,
                "raw_record": raw,
                "normalized_record": normalized,
                "catalogue_id": catalogue_id,
                "status": status,
                "issues": issues,
            })

        if adapter == "COLLECTR":
            synthetic_row = len(rows) + 2
            for identity, previous in collectr_baseline.items():
                if identity in current_collectr_keys:
                    continue
                normalized = dict(previous["normalized_record"])
                previous_quantity = int(previous["quantity"])
                normalized["collectr_baseline_batch_id"] = (
                    str(collectr_baseline_id) if collectr_baseline_id else None
                )
                normalized["previous_quantity"] = previous_quantity
                normalized["snapshot_quantity"] = 0
                normalized["delta_quantity"] = -previous_quantity
                normalized["reconciliation"] = "SNAPSHOT_DELTA"
                candidates.append({
                    "source_row": synthetic_row,
                    "quantity": previous_quantity,
                    "raw_record": previous["raw_record"],
                    "normalized_record": normalized,
                    "catalogue_id": previous.get("catalogue_id"),
                    "status": "REVIEW",
                    "issues": ["collectr_identity_missing_from_snapshot"],
                })
                synthetic_row += 1
                review_rows += 1

        warnings: list[str] = []
        if adapter == "COLLECTR":
            baseline_units = sum(int(item["quantity"]) for item in collectr_baseline.values())
            warnings.append(
                "Collectr snapshot reconciliation: "
                f"baseline {len(collectr_baseline)} identities / {baseline_units} units; "
                f"current {len(prepared)} identities / {physical_units} units; "
                f"net new units {collectr_delta_units}."
            )
            warnings.append(
                f"{collectr_unchanged_identities} identities unchanged; "
                f"{collectr_increased_identities} increased; "
                f"{collectr_new_identities} new."
            )
        if adapter == "HOLODEX":
            warnings.append("HoloDex export format is not publicly documented; verify mapped fields carefully before commit.")
        if "game" not in mapping and not payload.default_game:
            warnings.append("No game column was detected; affected rows require review.")

        async with connection.transaction():
            await connection.execute(
                """
                insert into tcg.import_batches(
                    id, owner_id, source, source_sha256, source_rows, physical_units,
                    filename, adapter, status, warnings, version
                ) values ($1, $2, $3, $4, $5, $6, $7, $8, 'PREVIEW', $9::jsonb, 1)
                """,
                batch_id, owner["id"], adapter, source_sha256, len(rows), physical_units,
                payload.filename, adapter, json.dumps(warnings),
            )
            for candidate in candidates:
                await connection.execute(
                    """
                    insert into tcg.import_candidates(
                        batch_id, owner_id, source_row, quantity, raw_record,
                        normalized_record, catalogue_id, status, issues
                    ) values ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9::jsonb)
                    """,
                    batch_id, owner["id"], candidate["source_row"], candidate["quantity"],
                    json.dumps(candidate["raw_record"]), json.dumps(candidate["normalized_record"]),
                    candidate["catalogue_id"], candidate["status"], json.dumps(candidate["issues"]),
                )

        return jsonable_encoder({
            "batch_id": batch_id,
            "version": 1,
            "adapter": adapter,
            "filename": payload.filename,
            "source_rows": len(rows),
            "physical_units": physical_units,
            "ready_units": ready_units,
            "review_rows": review_rows,
            "skipped_rows": skipped_rows,
            "warnings": warnings,
            "detected_columns": mapping,
            "candidates": candidates[:200],
            "preview_truncated": len(candidates) > 200,
        })


@router.get("")
async def list_import_batches(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = 25,
) -> dict:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                b.id,b.filename,b.adapter,b.status,b.source_rows,b.physical_units,
                b.created_at,b.committed_at,b.version,
                coalesce(e.total_items,0)::int as enrichment_total,
                coalesce(e.pending_items,0)::int as enrichment_pending,
                coalesce(e.action_items,0)::int as enrichment_action_required,
                coalesce(e.complete_items,0)::int as enrichment_complete
            from tcg.import_batches b
            left join lateral (
                select
                    count(*)::int as total_items,
                    count(*) filter(where overall_status='PENDING')::int as pending_items,
                    count(*) filter(where overall_status='ACTION_REQUIRED')::int as action_items,
                    count(*) filter(where overall_status='COMPLETE')::int as complete_items
                from tcg.import_enrichment_items ie
                where ie.batch_id=b.id and ie.owner_id=b.owner_id
            ) e on true
            where b.owner_id=$1
            order by b.created_at desc,b.id desc
            limit $2
            """,
            owner["id"],
            limit,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.get("/{batch_id}")
async def get_import_batch(
    batch_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        batch = await connection.fetchrow(
            "select * from tcg.import_batches where id = $1 and owner_id = $2",
            batch_id, owner["id"],
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="Import batch not found")
        candidates = await connection.fetch(
            """
            select id, source_row, quantity, normalized_record, catalogue_id, status, issues
            from tcg.import_candidates where batch_id = $1 and owner_id = $2
            order by source_row limit 5000
            """,
            batch_id, owner["id"],
        )
        candidate_payloads = []
        for row in candidates:
            item = dict(row)
            item["normalized_record"] = _json_value(
                item.get("normalized_record"), expected_type=dict, fallback={}
            )
            item["issues"] = _json_value(item.get("issues"), expected_type=list, fallback=[])
            candidate_payloads.append(item)
        return jsonable_encoder({"batch": dict(batch), "candidates": candidate_payloads})


@router.post("/{batch_id}/commit")
async def commit_import_batch(
    batch_id: UUID,
    payload: ImportCommitRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        async with connection.transaction():
            batch = await connection.fetchrow(
                "select * from tcg.import_batches where id = $1 and owner_id = $2 for update",
                batch_id, owner["id"],
            )
            if batch is None:
                raise HTTPException(status_code=404, detail="Import batch not found")
            if batch["version"] != payload.version:
                raise HTTPException(status_code=409, detail={"message": "Import batch changed", "current_version": batch["version"]})
            if batch["status"] == "COMMITTED":
                return {"batch_id": str(batch_id), "replayed": True, "created_count": 0, "status": "COMMITTED"}
            if batch["status"] != "PREVIEW":
                raise HTTPException(status_code=409, detail="Only PREVIEW batches can be committed")

            if batch["adapter"] == "COLLECTR":
                await connection.fetchval(
                    "select id from tcg.owners where id = $1 for update",
                    owner["id"],
                )
                marker = await connection.fetchrow(
                    """
                    select normalized_record
                    from tcg.import_candidates
                    where batch_id = $1 and owner_id = $2
                    order by source_row
                    limit 1
                    """,
                    batch_id,
                    owner["id"],
                )
                marker_normalized = _json_value(
                    marker["normalized_record"] if marker else None,
                    expected_type=dict,
                    fallback={},
                )
                expected_baseline = marker_normalized.get("collectr_baseline_batch_id")
                latest_baseline = await connection.fetchval(
                    """
                    select id
                    from tcg.import_batches
                    where owner_id = $1
                      and adapter = 'COLLECTR'
                      and status = 'COMMITTED'
                      and id <> $2
                    order by committed_at desc nulls last, created_at desc, id desc
                    limit 1
                    """,
                    owner["id"],
                    batch_id,
                )
                if (str(latest_baseline) if latest_baseline else None) != expected_baseline:
                    raise HTTPException(
                        status_code=409,
                        detail="Collectr baseline changed after preview; preview the latest snapshot again",
                    )

                pending_catalogues = await connection.fetch(
                    """
                    select id, normalized_record
                    from tcg.import_candidates
                    where batch_id = $1 and owner_id = $2
                      and status = 'READY'
                      and catalogue_id is null
                    order by source_row
                    for update
                    """,
                    batch_id,
                    owner["id"],
                )
                for pending in pending_catalogues:
                    normalized = _json_value(
                        pending["normalized_record"],
                        expected_type=dict,
                        fallback={},
                    )
                    if normalized.get("collectr_create_catalogue") is not True:
                        raise HTTPException(
                            status_code=409,
                            detail="Collectr READY row has no verified catalogue action",
                        )
                    catalogue_id = await _ensure_collectr_catalogue(connection, normalized)
                    await connection.execute(
                        "update tcg.import_candidates set catalogue_id = $1 where id = $2",
                        catalogue_id,
                        pending["id"],
                    )

            review_count = await connection.fetchval(
                "select count(*) from tcg.import_candidates where batch_id = $1 and owner_id = $2 and status = 'REVIEW'",
                batch_id, owner["id"],
            )
            if review_count:
                raise HTTPException(status_code=422, detail={
                    "message": "Import still has rows requiring review",
                    "review_rows": review_count,
                })

            candidates = await connection.fetch(
                """
                select * from tcg.import_candidates
                where batch_id = $1 and owner_id = $2 and status = 'READY'
                order by source_row for update
                """,
                batch_id, owner["id"],
            )
            created_count = 0
            for candidate in candidates:
                normalized = _json_value(
                    candidate["normalized_record"], expected_type=dict, fallback={}
                )
                raw_record = _json_value(candidate["raw_record"], expected_type=dict, fallback={})
                for copy_number in range(1, candidate["quantity"] + 1):
                    inventory_id = uuid4()
                    inventory_code = f"INV-{inventory_id.hex.upper()}"
                    unit_cost = normalized.get("acquisition_cost_minor")
                    await connection.execute(
                        """
                        insert into tcg.inventory_items(
                            id, inventory_code, catalogue_id, owner_id,
                            acquisition_cost_minor, currency, condition, seal_status,
                            grading_company, grade, certificate_number, language,
                            identity_confirmed, status, notes,
                            import_batch_id, source_row, source_copy, source_record
                        ) values (
                            $1, $2, $3, $4,
                            $5, 'GBP', $6, $7,
                            $8, $9, $10, $11,
                            false, 'DRAFT', '',
                            $12, $13, $14, $15::jsonb
                        )
                        """,
                        inventory_id, inventory_code, candidate["catalogue_id"], owner["id"],
                        unit_cost, normalized.get("condition"), normalized.get("seal_status"),
                        normalized.get("grading_company"), normalized.get("grade"),
                        normalized.get("certificate_number"), normalized.get("language"),
                        batch_id,
                        candidate["source_row"],
                        (
                            int(normalized.get("previous_quantity") or 0) + copy_number
                            if batch["adapter"] == "COLLECTR"
                            else copy_number
                        ),
                        json.dumps(raw_record),
                    )
                    created_count += 1
                await connection.execute(
                    "update tcg.import_candidates set status = 'COMMITTED' where id = $1",
                    candidate["id"],
                )

            now = datetime.now(timezone.utc)
            updated = await connection.fetchrow(
                """
                update tcg.import_batches
                set status = 'COMMITTED', committed_at = $1,
                    version = version + 1
                where id = $2 and owner_id = $3 and version = $4
                returning *
                """,
                now, batch_id, owner["id"], payload.version,
            )
            return jsonable_encoder({
                "batch": dict(updated),
                "replayed": False,
                "created_count": created_count,
                "status": "COMMITTED",
            })
