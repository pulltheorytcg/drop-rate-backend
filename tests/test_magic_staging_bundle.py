"""A hard fail-closed boundary between CI source previews and private R2."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.collectible_source_adapters import ReferenceSourceError, magic_printings
from app.object_storage import ObjectStorageError
from scripts.archive_magic_staging_bundle import (
    INDEX_NAME, PRINTING_REFS, SOURCE_ROWS, WINDOW_OFFSETS,
    archive_bundle, validate_bundle,
)
from scripts.pilot_expanded_catalogues import save_magic_staging_snapshot


def _make_bundle(tmp_path: Path, monkeypatch) -> Path:
    """Construct 771 distinct test source cards / exactly 1179 test finishes."""
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    set_data = {"code": "FDN", "name": "Foundations", "releaseDate": "2024-11-15",
                "totalSetSize": 771}
    windows = []
    total = 0
    for offset in WINDOW_OFFSETS:
        records = []
        count = min(100, SOURCE_ROWS - offset)
        for i in range(offset, offset + count):
            source_card = {
                "uuid": str(UUID(int=i + 1)), "setCode": "FDN",
                "name": f"Sample card {i}", "number": str(i + 1),
                "rarity": "common", "availability": ["paper"],
                "finishes": ["foil", "nonfoil"] if i < 408 else ["nonfoil"],
            }
            records.extend({"set": source_set, "card": card}
                           for source_set, card in magic_printings(set_data, source_card))
        snapshot = json.dumps({"version": 1, "source": "magic", "records": records},
                              sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode()
        artifact = save_magic_staging_snapshot(snapshot, set_code="FDN",
                                               offset=offset, limit=100)
        windows.append({"offset": offset, "source_rows_examined": count,
                        "validated_printings": len(records),
                        "quarantined_source_rows": 0, "artifact": artifact})
        total += len(records)
    assert total == PRINTING_REFS
    index = {
        "kind": "PRIVATE_MTGJSON_R2_INPUT_BUNDLE_NOT_UPLOADED",
        "schema_version": 1, "set_code": "FDN", "provider": "MTGJSON",
        "license_url": "https://www.mtgjson.com/license/",
        "source_rows_examined": SOURCE_ROWS,
        "validated_printing_refs": PRINTING_REFS,
        "quarantined_source_rows": 0, "private": True,
        "r2_objects_uploaded": 0, "supabase_rows_written": 0,
        "shopify_products_created": 0, "windows": windows,
    }
    (reports / INDEX_NAME).write_text(json.dumps(index, indent=2, sort_keys=True))
    return reports


def _modify_snapshot(reports: Path, window_number: int, change) -> None:
    index_path = reports / INDEX_NAME
    index = json.loads(index_path.read_text())
    artifact = index["windows"][window_number]["artifact"]
    old_path = reports / artifact["file_name"]
    payload = json.loads(old_path.read_bytes())
    change(payload)
    new_raw = json.dumps(payload, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(new_raw).hexdigest()
    old_path.unlink()
    artifact["sha256"] = digest
    artifact["bytes"] = len(new_raw)
    artifact["file_name"] = (
        f"mtgjson-FDN-{index['windows'][window_number]['offset']}-100-{digest[:16]}.json")
    (reports / artifact["file_name"]).write_bytes(new_raw)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True))


class MemoryR2:
    def __init__(self):
        self.parts = {}
        self.calls = 0
        self.fail_readback = False

    def put_verified_reference_snapshot(self, payload):
        self.calls += 1
        digest = hashlib.sha256(payload).hexdigest()
        self.parts[digest] = payload
        return {"key": f"private/catalogue-reference-inputs/{digest}.json.gz",
                "sha256": digest, "size_bytes": len(payload), "verified": True}

    def read_verified_reference_snapshot(self, digest):
        return b"corrupted readback" if self.fail_readback else self.parts[digest]


@pytest.mark.asyncio
async def test_magic_bundle_dry_run_preflights_all_eight_without_remote_access(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    data = validate_bundle(reports)
    assert len(data.parts) == 8
    assert len({part.sha256 for part in data.parts}) == 8
    monkeypatch.delenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", raising=False)
    result = await archive_bundle(reports)
    assert result["status"] == "DRY_RUN_VERIFIED"
    assert result["validated_printing_refs"] == 1179
    assert result["r2_objects_uploaded"] == result["supabase_rows_written"] == 0
    assert result["shopify_products_created"] == result["images_mirrored"] == 0


@pytest.mark.asyncio
async def test_magic_bundle_apply_requires_explicit_flag_and_readback(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    storage = MemoryR2()
    monkeypatch.delenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        await archive_bundle(reports, apply=True, storage=storage)
    assert storage.calls == 0
    monkeypatch.setenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", "true")
    result = await archive_bundle(reports, apply=True, storage=storage)
    assert result["status"] == "PRIVATE_R2_ARCHIVED"
    assert result["r2_objects_uploaded"] == storage.calls == 9
    verified_index = json.loads(storage.parts[result["private_r2_index_sha256"]])
    assert verified_index["public_feed_published"] is False
    assert len(verified_index["parts"]) == 8
    assert all(part["key"].startswith("private/") for part in verified_index["parts"])
    assert result["supabase_rows_written"] == result["shopify_products_created"] == 0


@pytest.mark.asyncio
async def test_magic_bundle_no_complete_index_if_r2_readback_fails(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    storage = MemoryR2()
    storage.fail_readback = True
    monkeypatch.setenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", "true")
    with pytest.raises(ObjectStorageError, match="readback"):
        await archive_bundle(reports, apply=True, storage=storage)
    assert storage.calls == 1  # A private orphan is safe; no final bundle index.


def test_magic_bundle_rejects_modified_or_missing_artifact(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    index = json.loads((reports / INDEX_NAME).read_text())
    part = reports / index["windows"][0]["artifact"]["file_name"]
    part.write_bytes(part.read_bytes() + b" ")
    with pytest.raises(ReferenceSourceError, match="SHA-256"):
        validate_bundle(reports)
    part.unlink()
    with pytest.raises(ReferenceSourceError, match="missing"):
        validate_bundle(reports)


def test_magic_bundle_rejects_price_field_even_if_digest_is_rewritten(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    _modify_snapshot(reports, 0, lambda snapshot: snapshot["records"][0]["card"].update(
        market_value_gbp_minor=9999))
    with pytest.raises(ReferenceSourceError, match="unreviewed"):
        validate_bundle(reports)


def test_magic_bundle_rejects_cross_window_duplicate_even_if_rehashed(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    index = json.loads((reports / INDEX_NAME).read_text())
    first = json.loads((reports / index["windows"][0]["artifact"]["file_name"]).read_bytes())
    row = copy.deepcopy(first["records"][0])
    _modify_snapshot(reports, 1, lambda snapshot: snapshot["records"].__setitem__(0, row))
    with pytest.raises(ReferenceSourceError, match="Duplicate Magic printing"):
        validate_bundle(reports)


def test_magic_bundle_rejects_quarantine_and_changed_source_set(tmp_path, monkeypatch):
    reports = _make_bundle(tmp_path, monkeypatch)
    index_file = reports / INDEX_NAME
    index = json.loads(index_file.read_text())
    index["windows"][0]["quarantined_source_rows"] = 1
    index["quarantined_source_rows"] = 1
    index_file.write_text(json.dumps(index))
    with pytest.raises(ReferenceSourceError, match="zero-write gate"):
        validate_bundle(reports)
    index["windows"][0]["quarantined_source_rows"] = 0
    index["quarantined_source_rows"] = 0
    index_file.write_text(json.dumps(index))
    _modify_snapshot(reports, 0, lambda snapshot: snapshot["records"][0]["set"].update(
        set_id="OTHER"))
    with pytest.raises(ReferenceSourceError, match="source, set or finish"):
        validate_bundle(reports)
