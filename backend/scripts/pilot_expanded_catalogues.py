"""Read-only, bounded source batches for Magic, LEGO, Funko, Topps, Panini.

Examples:
  PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source magic --set-code FDN --limit 25
  PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source lego --year 2026 --limit 25
  PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source tops --input-jsonl approved_topps_rows.jsonl

The Funko/Topps/Panini batch requires an authorised, source-attributed input
file; the pilot does NOT scrape product pages or claim upstream licensing.
No source images, asking prices, raw provider dumps, physical inventory or
Shopify objects are imported. Optional private R2 source archiving is separately
flagged and available only for normalized MIT-licensed MTGJSON metadata. It is
not a customer-facing R2 catalogue feed.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import io
import json
import os
import re
from pathlib import Path

import httpx

from app.collectible_source_adapters import (
    ReferenceSourceError, figure_product, lego_set_product,
    magic_printings, sports_checklist_printing,
)
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage


MAX_BATCH = 100
MAX_FILE_BYTES = 1_000_000
ROOT = "https://cdn.rebrickable.com/media/downloads"


def _csv_gzip(payload: bytes, *, columns: set[str], max_size: int, max_rows: int) -> list[dict]:
    if len(payload) > max_size:
        raise ReferenceSourceError("LEGO compressed CSV exceeds bounded source size")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            expanded = stream.read(max_size * 20 + 1)
        if len(expanded) > max_size * 20:
            raise ReferenceSourceError("LEGO expanded CSV exceeds source size limit")
        reader = csv.DictReader(io.StringIO(expanded.decode("utf-8-sig")))
        if not columns.issubset(set(reader.fieldnames or [])):
            raise ReferenceSourceError("LEGO source CSV schema has changed")
        rows = list(reader)
        if len(rows) > max_rows:
            raise ReferenceSourceError("LEGO CSV row count exceeds expected bound")
        return rows
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReferenceSourceError("Invalid LEGO gzip/CSV source") from exc


async def _magic(client: httpx.AsyncClient, *, set_code: str, offset: int, limit: int):
    if not re.fullmatch(r"[A-Z0-9]{2,10}", set_code):
        raise ReferenceSourceError("Magic source needs an exact uppercase set code")
    response = await client.get(f"https://mtgjson.com/api/v5/{set_code}.json")
    response.raise_for_status()
    if len(response.content) > 15_000_000:
        raise ReferenceSourceError("Magic set response exceeds permitted size")
    document = response.json()
    if not isinstance(document, dict) or not isinstance(document.get("data"), dict):
        raise ReferenceSourceError("Invalid MTGJSON set document")
    details = document["data"]
    if details.get("code") != set_code or not isinstance(details.get("cards"), list):
        raise ReferenceSourceError("MTGJSON set identity mismatch")
    rows = details["cards"]
    if len(rows) > 30_000:
        raise ReferenceSourceError("MTGJSON set row count exceeds expected bound")
    # An unusual printing must not abort other independent, exact-identity rows.
    return [_preview_magic_printings(details, row) for row in rows[offset:offset + limit]], len(rows)


async def _lego(client: httpx.AsyncClient, *, year: int | None, offset: int, limit: int):
    if year is not None and not 1940 <= year <= 2100:
        raise ReferenceSourceError("Unsupported LEGO year")
    set_reply, theme_reply = await asyncio.gather(
        client.get(f"{ROOT}/sets.csv.gz"), client.get(f"{ROOT}/themes.csv.gz"))
    set_reply.raise_for_status()
    theme_reply.raise_for_status()
    sets = _csv_gzip(set_reply.content,
                     columns={"set_num", "name", "year", "theme_id", "num_parts"},
                     max_size=2_000_000, max_rows=50_000)
    theme_rows = _csv_gzip(theme_reply.content,
                           columns={"id", "name", "parent_id"},
                           max_size=200_000, max_rows=2_000)
    themes = {r["id"]: r["name"] for r in theme_rows}
    parents = {r["id"]: r.get("parent_id") for r in theme_rows}
    def is_non_building_theme(theme_id: str) -> bool:
        visited = set()
        while theme_id:
            if theme_id in visited or theme_id not in themes:
                return True  # Unknown/cyclic ancestry is not a verified set.
            visited.add(theme_id)
            if themes[theme_id].casefold() in {"gear", "books", "non-lego"}:
                return True
            theme_id = parents.get(theme_id) or ""
        return False

    if year is not None:
        sets = [row for row in sets if row.get("year") == str(year)]
    # Rebrickable's 'sets' table includes non-set merchandise such as Jibbitz;
    # these are not LEGO builds and must never be promoted as construction sets.
    sets = [row for row in sets if row.get("num_parts", "").isdecimal()
            and int(row["num_parts"]) >= 2
            and not is_non_building_theme(row.get("theme_id", ""))]
    # Keep a rejected set in the receipt with its source position; never relax
    # exact edition validation to make a preview pass.
    return [_preview_lego_set(row, themes=themes) for row in sets[offset:offset + limit]], len(sets)


def _preview_magic_printings(details: dict, row: dict):
    try:
        return magic_printings(details, row)
    except ReferenceSourceError as exc:
        return exc


def _preview_lego_set(row: dict, *, themes: dict[str, str]):
    try:
        return [lego_set_product(row, themes=themes)]
    except ReferenceSourceError as exc:
        return exc


def _approved_input(source: str, path: Path, *, offset: int, limit: int):
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ReferenceSourceError("Approved input JSONL missing or oversized")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ReferenceSourceError("Input JSONL contains a non-object")
            rows.append(row)
    if len(rows) > 2000:
        raise ReferenceSourceError("Input JSONL exceeds staging row limit")
    batch = []
    for row in rows[offset:offset + limit]:
        if source == "funko":
            if row.get("system_code") != "FUNKO_POP":
                batch.append(ReferenceSourceError("Funko input must declare FUNKO_POP"))
                continue
            try:
                batch.append([{"figure": figure_product({**row, "reference_image_url": None})}])
            except ReferenceSourceError as exc:
                batch.append(exc)
        else:
            if row.get("manufacturer") != ("Topps" if source == "topps" else "Panini"):
                batch.append(ReferenceSourceError("Input manufacturer does not match batch provider"))
                continue
            try:
                set_record, card, details = sports_checklist_printing(row)
                batch.append([{"set": set_record, "card": card, "details": details}])
            except ReferenceSourceError as exc:
                batch.append(exc)
    return batch, len(rows)


def _closed_report(source: str, batches: list, *, available: int, offset: int, limit: int,
                   year: int | None, with_snapshot: bool = False):
    output = []
    identities = {}
    problems = []
    for i, batch in enumerate(batches):
        try:
            if isinstance(batch, ReferenceSourceError):
                raise batch
            for entry in batch:
                if isinstance(entry, tuple):
                    record, product = entry
                    kind = "sealed" if source == "lego" else "card"
                    row = {"set": record, kind: product}
                else:
                    row = entry
                payload = row.get("card") or row.get("sealed") or row.get("figure")
                if payload is None or payload.get("image_url") is not None or payload.get("image_r2_key") is not None:
                    raise ReferenceSourceError("Unreviewed media in batch")
                identity = (payload["provider"], payload["system_code"],
                            payload["language"], payload["provider_id"]) if source == "funko" else (
                            row["set"]["provider"], row["set"]["system_code"],
                            row["set"]["language"], payload["provider_id"])
                encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                if identity in identities:
                    if identities[identity] != encoded:
                        raise ReferenceSourceError("Conflicting source identity in batch")
                    continue
                identities[identity] = encoded
                output.append(row)
        except (ReferenceSourceError, KeyError) as exc:
            problems.append({"source_position": offset + i, "reason": str(exc)})
    if len(output) > MAX_BATCH * 8:
        raise ReferenceSourceError("Expanded finish rows exceed bounded batch limit")
    snapshot = json.dumps({"version": 1, "source": source, "records": output},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(snapshot) > 2_000_000:
        raise ReferenceSourceError("Normalized reference snapshot exceeds safe bound")
    report = {
        "source": source, "mode": "DRY_RUN_ONLY", "source_rows_available": available,
        "source_rows_examined": len(batches), "offset": offset, "limit": limit,
        "year_filter": year, "validated_reference_candidates": len(output),
        "quarantined_source_rows": len(problems), "quarantine_sample": problems[:8],
        "distinct_reference_groups": len({r["set"]["set_id"] for r in output if "set" in r}),
        "normalised_metadata_sha256": hashlib.sha256(snapshot).hexdigest(),
        "normalised_metadata_bytes": len(snapshot),
        "uploaded_r2_objects": 0, "supabase_rows_written": 0,
        "images_mirrored": 0, "verified_market_prices": 0, "shopify_products_created": 0,
        "source_rights_gate": "REBRICKABLE_COMMERCIAL_REUSE_PENDING" if source == "lego"
                              else "OFFICIAL_CURATED_INPUT_PERMISSION_REQUIRED" if source in {"funko", "topps", "panini"}
                              else "MTGJSON_METADATA_LICENSE_REVIEWED_IMAGES_EXCLUDED",
    }
    return (report, snapshot) if with_snapshot else report


async def archive_magic_private_snapshot(storage: S3ObjectStorage, payload: bytes) -> dict:
    """Verified private R2 receipt; never a public feed, image or price import."""
    if os.getenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", "false").lower() != "true":
        raise RuntimeError("Private Magic metadata R2 archiving is disabled")
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ReferenceSourceError("Invalid Magic source snapshot") from exc
    if (not isinstance(document, dict) or set(document) != {"version", "source", "records"}
            or document["version"] != 1 or document["source"] != "magic"
            or not isinstance(document["records"], list)
            or len(document["records"]) > MAX_BATCH * 8):
        raise ReferenceSourceError("Only a closed Magic metadata snapshot may be archived")
    source_fields = {"provider", "system_code", "language", "set_id", "name",
                     "release_date", "declared_card_count", "source_url"}
    card_fields = {"provider_id", "name", "card_number", "number_key", "finish",
                   "rarity", "image_url", "source_url", "evidence"}
    evidence_fields = {"provider_local_id", "set_code", "finish", "scryfall_id",
                       "artwork_status", "market_value_status"}
    for row in document["records"]:
        if (not isinstance(row, dict) or set(row) != {"set", "card"}
                or not isinstance(row["set"], dict) or not isinstance(row["card"], dict)
                or set(row["set"]) != source_fields or set(row["card"]) != card_fields
                or not isinstance(row["card"].get("evidence"), dict)
                or set(row["card"]["evidence"]) != evidence_fields
                or row["set"].get("provider") != "MTGJSON"
                or row["set"].get("system_code") != "MAGIC_THE_GATHERING"
                or row["card"].get("image_url") is not None):
            raise ReferenceSourceError("Magic snapshot includes unreviewed provider fields")
    receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, payload)
    if (not receipt.get("verified") or not isinstance(receipt.get("sha256"), str)
            or await asyncio.to_thread(
                storage.read_verified_reference_snapshot, receipt["sha256"]) != payload):
        raise ObjectStorageError("Magic source archive failed full R2 readback")
    return {"key": receipt["key"], "sha256": receipt["sha256"],
            "compressed_bytes": receipt["size_bytes"], "verified": True,
            "public": False}


async def main(args):
    if not 0 <= args.offset <= 200000 or not 1 <= args.limit <= MAX_BATCH:
        raise ReferenceSourceError("Offsets and batches must be bounded")
    if args.archive_private_r2 and args.source != "magic":
        raise ReferenceSourceError("Only reviewed Magic metadata may be privately archived")
    if (args.archive_private_r2 and
            os.getenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", "false").lower() != "true"):
        raise RuntimeError("Private Magic metadata R2 archiving is disabled")
    if args.source in {"funko", "topps", "panini"}:
        if not args.input_jsonl:
            raise ReferenceSourceError("Curated Funko/Topps/Panini batch requires --input-jsonl")
        batches, available = _approved_input(args.source, Path(args.input_jsonl),
                                             offset=args.offset, limit=args.limit)
    else:
        if args.input_jsonl:
            raise ReferenceSourceError("Live Magic/LEGO preview does not accept local source overrides")
        async with httpx.AsyncClient(timeout=30, headers={
                "User-Agent": "DropRateMetadataPilot/1.0 (read-only)", "Accept": "application/json"}) as client:
            if args.source == "magic":
                if not args.set_code or args.year is not None:
                    raise ReferenceSourceError("Magic requires --set-code; --year applies only to LEGO")
                batches, available = await _magic(client, set_code=args.set_code,
                                                  offset=args.offset, limit=args.limit)
            else:
                if args.set_code:
                    raise ReferenceSourceError("LEGO does not use a Magic set code")
                batches, available = await _lego(client, year=args.year,
                                                 offset=args.offset, limit=args.limit)
    report, snapshot = _closed_report(args.source, batches, available=available,
                                      offset=args.offset, limit=args.limit,
                                      year=args.year, with_snapshot=True)
    if args.archive_private_r2:
        config = ObjectStorageConfig.from_env()
        if config is None:
            raise RuntimeError("Private R2 archive requested without configured object storage")
        report["private_r2_archive"] = await archive_magic_private_snapshot(
            S3ObjectStorage(config), snapshot)
        report["mode"] = "PRIVATE_R2_ARCHIVE"
        report["uploaded_r2_objects"] = 1
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        choices=("magic", "lego", "funko", "topps", "panini"))
    parser.add_argument("--set-code", help="Exact MTGJSON set code, e.g. FDN")
    parser.add_argument("--year", type=int, help="LEGO filter; does not imply popularity")
    parser.add_argument("--input-jsonl", help="Authorised official-source JSONL for Funko/Topps/Panini")
    parser.add_argument("--archive-private-r2", action="store_true",
                        help="Flagged private metadata receipt for Magic only; no DB, media or Shopify writes")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    asyncio.run(main(parser.parse_args()))
