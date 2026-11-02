import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.object_storage import ObjectStorageError
from app.reference_source_backup import FIELDS, validate_row


def fixture_row() -> dict:
    fields = {
        "provider": "provider", "system_code": "POKEMON", "language": "Japanese",
        "provider_id": "fixture-001", "set_id": "s1", "name": "Pokémon test",
        "card_number": "1", "number_key": "0001", "finish": None,
        "rarity": "Common", "image_url": "https://example.test/1.png",
        "source_url": None,
        "evidence": {"characters": ["猫", {"exact": True}]},
        "refreshed_at": datetime(2026, 11, 2, tzinfo=timezone.utc).isoformat(),
    }
    assert tuple(fields) == FIELDS
    return fields


def encode(row) -> bytes:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()


def test_full_source_row_including_omitted_display_columns_is_valid():
    assert validate_row(encode(fixture_row())) == (
        "provider", "POKEMON", "Japanese", "fixture-001",
    )


@pytest.mark.parametrize("change", [
    lambda row: row.pop("evidence"),
    lambda row: row.update(unknown_source_field="not in the approved schema"),
    lambda row: row.update(provider_id=""),
    lambda row: row.update(set_id=3),
    lambda row: row.update(refreshed_at="2026-11-02T00:00:00"),
    lambda row: row.update(refreshed_at="not-a-date"),
])
def test_schema_drift_and_invalid_identity_fail_closed(change):
    row = fixture_row()
    change(row)
    with pytest.raises(ObjectStorageError):
        validate_row(encode(row))


def test_duplicate_json_fields_and_nonfinite_json_are_rejected():
    row = fixture_row()
    raw = encode(row).decode()
    with pytest.raises(ObjectStorageError):
        validate_row(raw.replace('"provider":"provider"',
                                 '"provider":"provider","provider":"other"').encode())
    with pytest.raises(ObjectStorageError):
        validate_row(raw.replace('"card_number":"1"', '"card_number":NaN').encode())


def test_incorrect_field_order_is_rejected():
    row = fixture_row()
    reversed_row = {name: row[name] for name in reversed(FIELDS)}
    with pytest.raises(ObjectStorageError):
        validate_row(encode(reversed_row))
