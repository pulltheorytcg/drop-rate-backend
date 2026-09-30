"""Deterministic policy and decision primitives for governed storefront experiments."""

from dataclasses import dataclass
from math import erf, sqrt
from typing import Mapping, Sequence

APPROVED_AUTONOMOUS_SURFACES = frozenset({
    "product_card_copy", "cta_wording", "pdp_information_order",
    "image_order", "trust_block_position", "collection_sort",
    "recommendation_placement", "homepage_section_order",
    "mobile_navigation", "consign_cta",
})
PROHIBITED_CHANGE_CLASSES = frozenset({
    "price", "acquisition_cost", "ownership", "commission", "settlement",
    "payout", "legal", "privacy", "consent", "checkout", "payment",
    "scarcity_claim", "discount_claim", "authenticity_claim", "grade_claim",
})

@dataclass(frozen=True)
class PreflightResult:
    allowed: bool
    failures: tuple[str, ...]

@dataclass(frozen=True)
class VariantMetric:
    variant_id: str
    sessions: int
    conversions: int
    is_control: bool = False

@dataclass(frozen=True)
class Decision:
    state: str
    winner_variant_id: str | None
    evidence: Mapping[str, float | int | str]

def preflight(*, surface: str, change_classes: Sequence[str], authority_level: int,
              approved: bool, analytics_ready: bool, rollback_ready: bool,
              conflicting_experiment: bool = False) -> PreflightResult:
    failures: list[str] = []
    prohibited = sorted(set(change_classes) & PROHIBITED_CHANGE_CLASSES)
    if prohibited:
        failures.append("prohibited_change:" + ",".join(prohibited))
    if authority_level >= 2 and surface not in APPROVED_AUTONOMOUS_SURFACES:
        failures.append("surface_not_autonomous")
    if authority_level <= 1 and not approved:
        failures.append("human_approval_required")
    if not analytics_ready:
        failures.append("analytics_not_ready")
    if not rollback_ready:
        failures.append("rollback_not_ready")
    if conflicting_experiment:
        failures.append("surface_conflict")
    return PreflightResult(not failures, tuple(failures))

def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))

def decide_two_variant(*, variants: Sequence[VariantMetric], minimum_sample_size: int,
                       minimum_practical_effect: float, confidence_threshold: float,
                       observation_hours: float, minimum_observation_hours: int) -> Decision:
    if len(variants) != 2 or sum(v.is_control for v in variants) != 1:
        return Decision("INCONCLUSIVE", None, {"reason": "requires_one_control_one_treatment"})
    control = next(v for v in variants if v.is_control)
    treatment = next(v for v in variants if not v.is_control)
    if observation_hours < minimum_observation_hours:
        return Decision("CONTINUE", None, {"reason": "minimum_observation_window"})
    if min(control.sessions, treatment.sessions) < minimum_sample_size:
        return Decision("CONTINUE", None, {"reason": "minimum_sample_size"})
    if min(control.sessions, treatment.sessions) <= 0:
        return Decision("INCONCLUSIVE", None, {"reason": "zero_sessions"})

    pc = control.conversions / control.sessions
    pt = treatment.conversions / treatment.sessions
    pooled = (control.conversions + treatment.conversions) / (control.sessions + treatment.sessions)
    se = sqrt(max(pooled * (1 - pooled) * (1/control.sessions + 1/treatment.sessions), 0.0))
    if se == 0:
        return Decision("INCONCLUSIVE", None, {"reason": "zero_variance", "control_rate": pc, "treatment_rate": pt})
    z = (pt - pc) / se
    confidence = _normal_cdf(abs(z))
    absolute_effect = pt - pc
    evidence = {"control_rate": pc, "treatment_rate": pt, "absolute_effect": absolute_effect,
                "z_score": z, "confidence": confidence}
    if confidence < confidence_threshold or abs(absolute_effect) < minimum_practical_effect:
        return Decision("INCONCLUSIVE", None, evidence)
    winner = treatment.variant_id if absolute_effect > 0 else control.variant_id
    return Decision("WINNER", winner, evidence)
