from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ALLOWED_COLLECTION_METHODS = frozenset(
    {
        "OFFICIAL_API",
        "PUBLIC_API",
        "PUBLIC_FEED",
        "PUBLIC_PAGE",
        "SUBSCRIBED_EMAIL",
        "MANUAL_REVIEW",
    }
)
ALLOWED_RIGHTS_STATUSES = frozenset(
    {"REFERENCE_ONLY", "PERMITTED_REUSE", "OWNED", "PUBLIC_DOMAIN"}
)
SIGNAL_ORIGINS = frozenset(
    {"COMPETITOR", "INTERNAL", "MARKET", "SOCIAL", "OFFICIAL"}
)
OBSERVE_ONLY_HANDOFFS = frozenset(
    {
        "CREATE_OPPORTUNITY",
        "PROPOSE_EXPERIMENT",
        "PROPOSE_CONTENT",
        "PROPOSE_ACQUISITION_REVIEW",
        "PROPOSE_MERCHANDISING",
        "PROPOSE_SEO_REVIEW",
    }
)
PROHIBITED_ACTIONS = frozenset(
    {
        "COPY_CREATIVE",
        "COPY_DESCRIPTION",
        "COPY_IMAGE",
        "DIRECT_PRICE_CHANGE",
        "OWNERSHIP_CHANGE",
        "FINANCIAL_ACTION",
        "AUTO_PUBLISH_UNVERIFIED",
        "BYPASS_ACCESS_CONTROL",
    }
)


@dataclass(frozen=True, slots=True)
class SourcePreflight:
    allowed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompetitiveEvidence:
    origin: str
    source_key: str
    confidence: float
    relevance: float
    rights_status: str = "REFERENCE_ONLY"
    competitor_key: str | None = None
    observation_type: str | None = None


@dataclass(frozen=True, slots=True)
class OpportunityDecision:
    state: str
    score: float
    reasons: tuple[str, ...]
    independent_sources: int
    independent_origins: int
    competitor_sources: int
    non_competitor_sources: int


@dataclass(frozen=True, slots=True)
class ActionPreflight:
    allowed: bool
    failures: tuple[str, ...]


def source_preflight(
    *,
    collection_method: str,
    rights_status: str,
    terms_reviewed: bool,
    bypasses_access_control: bool = False,
) -> SourcePreflight:
    """Validate a source before any automated collection adapter is enabled."""
    failures: list[str] = []
    method = str(collection_method or "").strip().upper()
    rights = str(rights_status or "").strip().upper()

    if method not in ALLOWED_COLLECTION_METHODS:
        failures.append("collection_method_not_approved")
    if rights not in ALLOWED_RIGHTS_STATUSES:
        failures.append("rights_status_not_approved")
    if bypasses_access_control:
        failures.append("access_control_bypass_prohibited")
    if method != "MANUAL_REVIEW" and not terms_reviewed:
        failures.append("provider_terms_review_required")

    return SourcePreflight(not failures, tuple(failures))


def _bounded_score(value: float, *, field: str) -> float:
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return score


def _normalized_evidence(signal: CompetitiveEvidence) -> CompetitiveEvidence:
    origin = str(signal.origin or "").strip().upper()
    source_key = str(signal.source_key or "").strip()
    rights = str(signal.rights_status or "").strip().upper()
    competitor_key = (
        str(signal.competitor_key).strip()
        if signal.competitor_key is not None
        else None
    )
    observation_type = (
        str(signal.observation_type).strip().upper()
        if signal.observation_type is not None
        else None
    )

    if origin not in SIGNAL_ORIGINS:
        raise ValueError("Competitive evidence origin is not supported")
    if not source_key:
        raise ValueError("Competitive evidence requires a stable source key")
    if rights not in ALLOWED_RIGHTS_STATUSES:
        raise ValueError("Competitive evidence rights status is not supported")
    if origin == "COMPETITOR" and not competitor_key:
        raise ValueError("Competitor evidence requires a competitor key")

    return CompetitiveEvidence(
        origin=origin,
        source_key=source_key,
        confidence=_bounded_score(signal.confidence, field="confidence"),
        relevance=_bounded_score(signal.relevance, field="relevance"),
        rights_status=rights,
        competitor_key=competitor_key,
        observation_type=observation_type,
    )


def _dedupe_evidence(
    signals: Iterable[CompetitiveEvidence],
) -> list[CompetitiveEvidence]:
    """Keep the strongest evidence item per stable source key."""
    best: dict[str, CompetitiveEvidence] = {}
    for raw in signals:
        signal = _normalized_evidence(raw)
        previous = best.get(signal.source_key)
        if previous is None:
            best[signal.source_key] = signal
            continue
        previous_strength = (previous.confidence * 0.6) + (previous.relevance * 0.4)
        signal_strength = (signal.confidence * 0.6) + (signal.relevance * 0.4)
        if signal_strength > previous_strength:
            best[signal.source_key] = signal
    return list(best.values())


def evaluate_competitive_opportunity(
    signals: Iterable[CompetitiveEvidence],
    *,
    qualification_threshold: float = 0.72,
) -> OpportunityDecision:
    """Turn corroborated evidence into a shadow-mode opportunity, never an action.

    Competitor behavior alone is insufficient. A QUALIFIED opportunity requires at
    least one competitor signal plus corroboration from a different origin such as
    Drop Rate behavior, market data, social trend data or an official source.
    """
    threshold = _bounded_score(
        qualification_threshold,
        field="qualification_threshold",
    )
    evidence = _dedupe_evidence(signals)
    origins = {signal.origin for signal in evidence}
    competitor_signals = [
        signal for signal in evidence if signal.origin == "COMPETITOR"
    ]
    non_competitor_signals = [
        signal for signal in evidence if signal.origin != "COMPETITOR"
    ]

    reasons: list[str] = []
    if not competitor_signals:
        reasons.append("competitor_evidence_required")
    if len(evidence) < 2:
        reasons.append("independent_source_corroboration_required")
    if len(origins) < 2 or not non_competitor_signals:
        reasons.append("non_competitor_corroboration_required")

    if not evidence:
        return OpportunityDecision(
            state="WATCH",
            score=0.0,
            reasons=tuple(reasons or ["insufficient_evidence"]),
            independent_sources=0,
            independent_origins=0,
            competitor_sources=0,
            non_competitor_sources=0,
        )

    strengths = [
        (signal.confidence * 0.6) + (signal.relevance * 0.4)
        for signal in evidence
    ]
    base_score = sum(strengths) / len(strengths)
    corroboration_bonus = min(
        0.10,
        max(0, len(origins) - 1) * 0.04
        + max(0, len(evidence) - 2) * 0.01,
    )
    score = round(min(1.0, base_score + corroboration_bonus), 5)

    if reasons:
        state = "WATCH"
    elif score >= threshold:
        state = "QUALIFIED"
    else:
        state = "WATCH"
        reasons.append("evidence_score_below_threshold")

    return OpportunityDecision(
        state=state,
        score=score,
        reasons=tuple(reasons),
        independent_sources=len(evidence),
        independent_origins=len(origins),
        competitor_sources=len(competitor_signals),
        non_competitor_sources=len(non_competitor_signals),
    )


def action_preflight(
    *,
    requested_action: str,
    opportunity_state: str,
) -> ActionPreflight:
    """Keep competitive intelligence OBSERVE-only.

    This layer may create evidence-backed proposals. It cannot publish, change a
    price, alter ownership/finance or copy competitor expression. Downstream
    governed systems own any experiment/content/commerce action.
    """
    action = str(requested_action or "").strip().upper()
    state = str(opportunity_state or "").strip().upper()
    failures: list[str] = []

    if action in PROHIBITED_ACTIONS:
        failures.append("prohibited_competitive_action")
    elif action not in OBSERVE_ONLY_HANDOFFS:
        failures.append("outside_observe_authority")

    if action != "CREATE_OPPORTUNITY" and state != "QUALIFIED":
        failures.append("qualified_opportunity_required")

    return ActionPreflight(not failures, tuple(failures))
