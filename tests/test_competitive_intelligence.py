from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.competitive_intelligence import (
    CompetitiveEvidence,
    action_preflight,
    evaluate_competitive_opportunity,
    source_preflight,
)


ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "automation" / "n8n" / "workflow-registry.json"
ENGINE = ROOT / "backend" / "app" / "competitive_intelligence.py"


def evidence(
    origin: str,
    source_key: str,
    *,
    confidence: float = 0.9,
    relevance: float = 0.9,
    competitor_key: str | None = None,
) -> CompetitiveEvidence:
    return CompetitiveEvidence(
        origin=origin,
        source_key=source_key,
        confidence=confidence,
        relevance=relevance,
        competitor_key=competitor_key,
    )


def test_source_preflight_requires_terms_review_for_automation() -> None:
    result = source_preflight(
        collection_method="PUBLIC_PAGE",
        rights_status="REFERENCE_ONLY",
        terms_reviewed=False,
    )
    assert result.allowed is False
    assert result.failures == ("provider_terms_review_required",)


def test_source_preflight_blocks_access_control_bypass() -> None:
    result = source_preflight(
        collection_method="PUBLIC_API",
        rights_status="REFERENCE_ONLY",
        terms_reviewed=True,
        bypasses_access_control=True,
    )
    assert result.allowed is False
    assert "access_control_bypass_prohibited" in result.failures


def test_single_competitor_observation_cannot_qualify() -> None:
    result = evaluate_competitive_opportunity(
        [evidence("COMPETITOR", "competitor-a:homepage:v1", competitor_key="competitor-a")]
    )
    assert result.state == "WATCH"
    assert "independent_source_corroboration_required" in result.reasons
    assert "non_competitor_corroboration_required" in result.reasons


def test_multiple_competitors_alone_still_do_not_drive_strategy() -> None:
    result = evaluate_competitive_opportunity(
        [
            evidence("COMPETITOR", "competitor-a:promo:1", competitor_key="competitor-a"),
            evidence("COMPETITOR", "competitor-b:promo:9", competitor_key="competitor-b"),
        ]
    )
    assert result.state == "WATCH"
    assert "non_competitor_corroboration_required" in result.reasons


def test_competitor_plus_internal_and_market_signals_can_qualify() -> None:
    result = evaluate_competitive_opportunity(
        [
            evidence(
                "COMPETITOR",
                "competitor-a:manga-merchandising:1",
                competitor_key="competitor-a",
                confidence=0.92,
                relevance=0.95,
            ),
            evidence(
                "INTERNAL",
                "drop-rate:search:manga:2026-w40",
                confidence=0.94,
                relevance=0.96,
            ),
            evidence(
                "MARKET",
                "market:manga-velocity:2026-w40",
                confidence=0.90,
                relevance=0.93,
            ),
        ]
    )
    assert result.state == "QUALIFIED"
    assert result.independent_origins == 3
    assert result.competitor_sources == 1
    assert result.non_competitor_sources == 2
    assert result.score >= 0.72


def test_duplicate_source_keys_do_not_fake_corroboration() -> None:
    result = evaluate_competitive_opportunity(
        [
            evidence("COMPETITOR", "same-source", competitor_key="competitor-a"),
            evidence(
                "COMPETITOR",
                "same-source",
                competitor_key="competitor-a",
                confidence=0.95,
            ),
        ]
    )
    assert result.independent_sources == 1
    assert result.state == "WATCH"


def test_out_of_range_scores_fail_closed() -> None:
    with pytest.raises(ValueError, match="confidence"):
        evaluate_competitive_opportunity(
            [
                evidence(
                    "COMPETITOR",
                    "competitor-a:1",
                    competitor_key="competitor-a",
                    confidence=1.2,
                )
            ]
        )


def test_observe_layer_can_only_hand_off_proposals() -> None:
    allowed = action_preflight(
        requested_action="PROPOSE_EXPERIMENT",
        opportunity_state="QUALIFIED",
    )
    blocked_publish = action_preflight(
        requested_action="PUBLISH_SOCIAL",
        opportunity_state="QUALIFIED",
    )
    blocked_copy = action_preflight(
        requested_action="COPY_DESCRIPTION",
        opportunity_state="QUALIFIED",
    )

    assert allowed.allowed is True
    assert blocked_publish.allowed is False
    assert "outside_observe_authority" in blocked_publish.failures
    assert blocked_copy.allowed is False
    assert "prohibited_competitive_action" in blocked_copy.failures


def test_unqualified_opportunity_cannot_be_handed_to_growth_engines() -> None:
    result = action_preflight(
        requested_action="PROPOSE_CONTENT",
        opportunity_state="WATCH",
    )
    assert result.allowed is False
    assert "qualified_opportunity_required" in result.failures


def test_registry_adds_competitive_intelligence_as_planned_observe_only() -> None:
    registry = json.loads(REGISTRY.read_text())
    row = next(item for item in registry["workflows"] if item["key"] == "competitive-intelligence")

    assert row["sequence"] == 43
    assert row["domain"] == "Intelligence"
    assert row["authority"] == "OBSERVE"
    assert row["status"] == "PLANNED"
    assert row["ai_may_assist"] is True
    assert "founder-approved competitor watchlist" in row["activation_requires"]
    assert "source-specific terms/rights review" in row["activation_requires"]
    assert "shadow-mode opportunity scoring proof" in row["activation_requires"]
    assert row.get("implementation_path") is None


def test_foundation_contains_no_external_fetch_or_mutation_code() -> None:
    source = ENGINE.read_text().casefold()
    assert "requests." not in source
    assert "httpx." not in source
    assert "shopify" not in source
    assert "update tcg." not in source
    assert "insert into" not in source
