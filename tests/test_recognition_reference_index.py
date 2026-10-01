from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import app.recognition_engine as recognition_engine
from app.recognition_engine import (
    _provider_identity_fingerprint,
    attach_visual_evidence,
    score_candidate,
)
from app.recognition_learning import encode_fingerprints
from app.recognition_reference_index import (
    FINGERPRINT_VERSION,
    attach_reference_candidate_hints,
    discover_reference_candidate_hints,
)

from test_recognition_engine import candidate, observation


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260927231525_recognition_reference_fingerprint_index.sql"
)
POLICY_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260927231615_fix_reference_fingerprint_admin_update_policy.sql"
)
API = ROOT / "backend" / "app" / "recognition.py"
ENGINE = ROOT / "backend" / "app" / "recognition_engine.py"
INDEX = ROOT / "backend" / "app" / "recognition_reference_index.py"


class FetchConnection:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, _query, *_args):
        return self.rows


def test_reference_hint_is_attached_only_to_matching_catalogue() -> None:
    first = candidate()
    second = candidate()
    media_id = uuid4()
    hints = [
        {
            "catalogue_id": first["catalogue_id"],
            "media_asset_id": media_id,
            "system_code": "ONE_PIECE_CARD_GAME",
            "similarity": 0.97,
            "trust_level": "PROVISIONAL",
            "fingerprint_version": FINGERPRINT_VERSION,
        }
    ]

    attach_reference_candidate_hints([first, second], hints)

    assert first["reference_index_similarity"] == 0.97
    assert first["reference_index_trust"] == "PROVISIONAL"
    assert first["reference_index_media_asset_id"] == media_id
    assert second["reference_index_similarity"] is None
    assert second["reference_index_trust"] is None


@pytest.mark.asyncio
async def test_reference_retrieval_ranks_matching_exact_printing() -> None:
    expected_catalogue = uuid4()
    unrelated_catalogue = uuid4()
    rows = [
        {
            "catalogue_id": expected_catalogue,
            "media_asset_id": uuid4(),
            "system_code": "ONE_PIECE_CARD_GAME",
            "source_fingerprints": encode_fingerprints((1,)),
            "trust_level": "VERIFIED",
        },
        {
            "catalogue_id": unrelated_catalogue,
            "media_asset_id": uuid4(),
            "system_code": "ONE_PIECE_CARD_GAME",
            "source_fingerprints": encode_fingerprints(((1 << 256) - 1,)),
            "trust_level": "PROVISIONAL",
        },
    ]

    hints = await discover_reference_candidate_hints(
        FetchConnection(rows),
        (1,),
        system_code="ONE_PIECE_CARD_GAME",
        min_similarity=0.40,
    )

    assert [item["catalogue_id"] for item in hints] == [expected_catalogue]
    assert hints[0]["similarity"] == 1.0
    assert hints[0]["trust_level"] == "VERIFIED"


def test_provisional_reference_retrieval_cannot_inflate_printing_confidence() -> None:
    item = candidate(visual=0.99)
    item["reference_image_approval_status"] = "PENDING"
    item["reference_index_similarity"] = 0.99
    item["reference_index_trust"] = "PROVISIONAL"
    item["reference_index_media_asset_id"] = uuid4()
    item["reference_index_fingerprint_version"] = FINGERPRINT_VERSION

    scored = score_candidate(observation(), item, visual_similarity=0.99)

    assert scored["signals"]["visual_retrieval"]["match"] == 0.99
    assert scored["signals"]["visual_retrieval"]["trust"] == "PROVISIONAL"
    assert scored["signals"]["visual"]["available"] is False
    assert scored["signals"]["visual"]["provisional_match"] == 0.99
    assert scored["signals"]["visual"]["match"] == 0.0


def test_verified_reference_index_can_support_exact_printing_visual() -> None:
    item = candidate()
    item["reference_image_approval_status"] = "APPROVED"
    item["reference_index_similarity"] = 0.99
    item["reference_index_trust"] = "VERIFIED"
    item["reference_index_media_asset_id"] = uuid4()
    item["reference_index_fingerprint_version"] = FINGERPRINT_VERSION

    scored = score_candidate(observation(), item)

    assert scored["signals"]["visual_retrieval"]["trust"] == "VERIFIED"
    assert scored["signals"]["visual"]["available"] is True
    assert scored["signals"]["visual"]["source"] == "verified_reference_index"
    assert scored["signals"]["visual"]["match"] == 0.99


def test_unmapped_provider_image_is_not_exact_printing_visual_proof() -> None:
    obs = observation()
    item = candidate()
    provider_item = {
        "provider": "Punk Records",
        "provider_id": "OP05-119_p9",
        "base_card_id": "OP05-119",
        "language": "Japanese",
        "name": "Monkey D. Luffy",
        "rarity": "SEC",
        "card_type": "Character",
        "cost": 10,
        "power": 12000,
        "colors": ["Purple"],
        "attributes": ["Strike"],
        "types": ["Straw Hat Crew"],
        "effect": "Example visible effect text.",
        "art_treatment": "Base",
        "visual_similarity": 0.99,
        "retrieval_score": 1.0,
    }
    provider_item.update(_provider_identity_fingerprint(obs, provider_item))

    scored = score_candidate(
        obs,
        item,
        provider_evidence=[provider_item],
    )

    assert scored["signals"]["provider"]["provider_id"] == "OP05-119_p9"
    assert scored["signals"]["provider_print"]["match"] == 0.0
    assert scored["signals"]["visual"]["available"] is False
    assert scored["signals"]["visual"]["provisional_match"] == 0.99


def test_review_state_provider_mapping_cannot_prove_exact_printing_visual() -> None:
    obs = observation()
    item = candidate()
    item["provider_mappings"] = [
        {
            "source_provider": "Punk Records",
            "provider_id": "OP05-119",
            "match_status": "REVIEW",
        }
    ]
    provider_item = {
        "provider": "Punk Records",
        "provider_id": "OP05-119",
        "base_card_id": "OP05-119",
        "language": "Japanese",
        "name": "Monkey D. Luffy",
        "rarity": "SEC",
        "card_type": "Character",
        "cost": 10,
        "power": 12000,
        "colors": ["Purple"],
        "attributes": ["Strike"],
        "types": ["Straw Hat Crew"],
        "effect": "Example visible effect text.",
        "art_treatment": "Base",
        "visual_similarity": 0.99,
        "retrieval_score": 1.0,
    }
    provider_item.update(_provider_identity_fingerprint(obs, provider_item))

    scored = score_candidate(obs, item, provider_evidence=[provider_item])

    assert scored["signals"]["provider"]["match"] == 1.0
    assert scored["signals"]["provider_print"]["match"] == 0.0
    assert scored["signals"]["visual"]["available"] is False
    assert scored["signals"]["visual"]["provisional_match"] == 0.99


def test_verified_provider_mapping_can_contribute_exact_printing_visual() -> None:
    obs = observation()
    item = candidate()
    item["provider_mappings"] = [
        {
            "source_provider": "Punk Records",
            "provider_id": "OP05-119",
            "match_status": "VERIFIED",
        }
    ]
    provider_item = {
        "provider": "Punk Records",
        "provider_id": "OP05-119",
        "base_card_id": "OP05-119",
        "language": "Japanese",
        "name": "Monkey D. Luffy",
        "rarity": "SEC",
        "card_type": "Character",
        "cost": 10,
        "power": 12000,
        "colors": ["Purple"],
        "attributes": ["Strike"],
        "types": ["Straw Hat Crew"],
        "effect": "Example visible effect text.",
        "art_treatment": "Base",
        "visual_similarity": 0.99,
        "retrieval_score": 1.0,
    }
    provider_item.update(_provider_identity_fingerprint(obs, provider_item))

    scored = score_candidate(obs, item, provider_evidence=[provider_item])

    assert scored["signals"]["provider_print"]["match"] == 1.0
    assert scored["signals"]["visual"]["available"] is True
    assert scored["signals"]["visual"]["source"] == "exact_provider_image"
    assert scored["signals"]["visual"]["match"] == 0.99


@pytest.mark.asyncio
async def test_catalogue_visual_reuses_persistent_reference_without_network(monkeypatch) -> None:
    media_id = uuid4()
    item = candidate()
    item["reference_image_url"] = "https://www.onepiece-cardgame.com/images/cardlist/card/OP05-119.png"
    item["reference_media_asset_id"] = media_id
    item["reference_image_approval_status"] = "APPROVED"
    item["reference_index_similarity"] = 0.965
    item["reference_index_trust"] = "VERIFIED"
    item["reference_index_media_asset_id"] = media_id

    async def should_not_fetch(_url):
        raise AssertionError("persistent fingerprint should avoid a remote image fetch")

    monkeypatch.setattr(recognition_engine, "reference_image_hashes", should_not_fetch)

    await attach_visual_evidence((1,), [item])

    assert item["visual_similarity"] == 0.965
    assert item["visual_similarity_source"] == "persistent_reference_index"


def test_reference_index_schema_is_private_audited_and_trust_split() -> None:
    sql = MIGRATION.read_text()
    policy_sql = POLICY_MIGRATION.read_text()

    assert "create table tcg.recognition_reference_fingerprints" in sql
    assert "trust_level in ('PROVISIONAL','VERIFIED')" in sql
    assert "unique (media_asset_id, fingerprint_version)" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "from public,anon,authenticated" in sql
    assert "recognition_reference_fingerprints_audit" in sql
    assert "revoke delete on tcg.recognition_reference_fingerprints from tcg_api" in sql
    creator_index = (
        ROOT
        / "database"
        / "migrations"
        / "20260927232335_index_reference_fingerprint_creator.sql"
    ).read_text()
    assert "recognition_reference_fingerprints_created_by_idx" in creator_index
    assert "using (tcg.is_platform_admin())" in policy_sql
    assert "created_by_user_id=tcg.current_user_id()" not in policy_sql


def test_phase_one_runs_visual_retrieval_beside_vision_and_keeps_it_auditable() -> None:
    api = API.read_text()
    engine = ENGINE.read_text()
    index = INDEX.read_text()

    assert 'ENGINE_VERSION = "v1.6.1"' in api
    assert '@router.get("/reference-index/status")' in api
    assert '@router.post("/reference-index/rebuild")' in api
    assert '"persistent_reference_index_enabled": True' in api
    assert '"reference_index_provisional_is_retrieval_only": True' in api
    assert '_timed("reference_retrieval", _load_reference_hints())' in api
    assert "reference_catalogue_ids=" in api
    assert "attach_reference_candidate_hints(candidates, reference_hints)" in api
    assert '"reference_index_hints": reference_hints' in api
    assert "reference_index_trust == \"VERIFIED\"" in engine
    assert "provider_visual = provider_visual_raw if exact_provider_print else None" in engine
    assert "DETERMINISTIC_EXACT" in index
    assert 'return "VERIFIED" if str(row.get("approval_status") or "") == "APPROVED"' in index
