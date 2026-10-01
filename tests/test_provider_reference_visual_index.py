from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import app.recognition_engine as recognition_engine
from app.recognition_engine import attach_provider_visual_evidence, load_catalogue_candidates
from app.recognition_provider_reference_index import (
    FINGERPRINT_VERSION,
    _hash_hexes,
    discover_provider_reference_visual_hints,
)


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
ENGINE = ROOT / "backend" / "app" / "recognition_engine.py"
INDEX = ROOT / "backend" / "app" / "recognition_provider_reference_index.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001170500_provider_reference_visual_index.sql"
)


class FetchConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return self.rows


def test_provider_reference_hashes_are_fixed_width_hex() -> None:
    assert _hash_hexes((0, 1, (1 << 256) - 1)) == [
        "0" * 64,
        ("0" * 63) + "1",
        "f" * 64,
    ]


@pytest.mark.asyncio
async def test_provider_reference_visual_hint_is_retrieval_only() -> None:
    connection = FetchConnection(
        [
            {
                "provider": "Punk Records",
                "system_code": "ONE_PIECE_CARD_GAME",
                "language": "Japanese",
                "provider_id": "OP05-119_p9",
                "set_id": "OP05",
                "set_name": "Awakening of the New Era",
                "name": "Monkey D. Luffy",
                "card_number": "OP05-119",
                "finish": "Foil",
                "rarity": "SEC",
                "image_url": "https://www.onepiece-cardgame.com/example.png",
                "source_url": "https://example.invalid/reference",
                "evidence": {"art_treatment": "Parallel"},
                "similarity": 0.965,
            }
        ]
    )

    items = await discover_provider_reference_visual_hints(
        connection,
        (1,),
        system_code="ONE_PIECE_CARD_GAME",
        language="Japanese",
    )

    assert len(items) == 1
    assert items[0]["provider_id"] == "OP05-119_p9"
    assert items[0]["base_card_id"] == "OP05-119"
    assert items[0]["visual_similarity"] == 0.965
    assert items[0]["visual_similarity_source"] == "provider_reference_index"
    assert items[0]["exact_printing_verified"] is False
    assert "from .recognition_reference_index import FINGERPRINT_VERSION" in INDEX.read_text()
    assert "recognition_provider_reference_visual_hints" in connection.calls[0][0]


@pytest.mark.asyncio
async def test_indexed_provider_visual_does_not_redownload_image(monkeypatch) -> None:
    item = {
        "provider": "Punk Records",
        "provider_id": "OP05-119_p9",
        "base_card_id": "OP05-119",
        "image_url": "https://www.onepiece-cardgame.com/example.png",
        "identity_score": 0.95,
        "non_number_identity_score": 0.95,
        "visual_similarity": 0.97,
        "visual_similarity_source": "provider_reference_index",
    }

    async def should_not_fetch(_url):
        raise AssertionError("persisted provider fingerprint should avoid remote image fetch")

    monkeypatch.setattr(recognition_engine, "reference_image_hashes", should_not_fetch)

    await attach_provider_visual_evidence((1,), [item])

    assert item["visual_similarity"] == 0.97
    assert item["visual_similarity_source"] == "provider_reference_index"


def test_strong_provider_visual_can_retrieve_without_becoming_identity_proof() -> None:
    source = ENGINE.read_text()

    assert 'item.get("visual_similarity_source") == "provider_reference_index"' in source
    assert 'float(item.get("visual_similarity") or 0.0) >= 0.82' in source
    assert "provider_numbers" in source
    assert "exact_printing_verified" not in source[source.index("async def load_catalogue_candidates"):source.index("async def discover_provider_evidence")]


def test_provider_visual_index_is_private_audited_and_reference_backed() -> None:
    sql = MIGRATION.read_text()

    assert "create table tcg.recognition_provider_reference_fingerprints" in sql
    assert "id uuid primary key default gen_random_uuid()" in sql
    assert "source_hashes bit(256)[]" in sql
    assert "references tcg.reference_cards(provider,system_code,language,provider_id)" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "from public,anon,authenticated" in sql
    assert "recognition_provider_reference_fingerprints_audit" in sql
    assert "revoke delete on tcg.recognition_provider_reference_fingerprints from tcg_api" in sql
    assert "security definer" in sql
    assert "set search_path=pg_catalog" in sql
    assert "from public,anon,authenticated,service_role" in sql
    assert "grant execute on function tcg.recognition_provider_reference_visual_hints" in sql


def test_visual_hint_function_ranks_hashes_in_database_and_respects_release_gate() -> None:
    sql = MIGRATION.read_text()

    assert "bit_count(reference_hash # source_hash.hash)" in sql
    assert "('x' || lower(value))::bit(256)" in sql
    assert "s.release_date is null or s.release_date<=current_date" in sql
    assert "c.image_url=rf.image_url" in sql
    assert "p_min_similarity" in sql
    assert "limit least(greatest(coalesce(p_max_candidates,24),1),50)" in sql


def test_card_pipeline_uses_visual_provider_retrieval_after_object_routing() -> None:
    api = API.read_text()

    assert 'ENGINE_VERSION = "v1.7.0"' in api
    assert '"provider_reference_visual_index_enabled": True' in api
    assert '"provider_reference_visual_index_is_retrieval_only": True' in api
    assert '@router.get("/provider-reference-index/status")' in api
    assert '@router.post("/provider-reference-index/rebuild")' in api
    assert "Depends(require_platform_admin_request)" in api

    sealed_index = api.index('if observation.object_type == "SEALED_PRODUCT"')
    visual_loader_index = api.index("async def _load_provider_reference_hints")
    provider_discovery_index = api.index('_timed("provider_discovery", discover_provider_evidence(observation))')
    visual_timing_index = api.index('_timed("provider_reference_visual", _load_provider_reference_hints())')

    assert sealed_index < visual_loader_index
    assert visual_loader_index < provider_discovery_index
    assert provider_discovery_index < visual_timing_index
    assert "provider_visual_hints" in api
    assert 'current["visual_similarity_source"] = "provider_reference_index"' in api
