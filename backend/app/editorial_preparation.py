"""Stateless static-content preparation. Never authorises or publishes a post.

Input evidence is a caller-supplied observation, not an authoritative database
record. No URLs are fetched and no source text is executed or sent to an AI.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    source_id: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    kind: Literal["PUBLISHER", "SOLD_RECORD", "ASKING_PRICE", "INDEX", "SOCIAL_LEAD"]


class Fact(StrictModel):
    text: str = Field(min_length=1, max_length=180)
    source_ids: list[str] = Field(min_length=1, max_length=10)


class Sale(StrictModel):
    # origin_transaction_id is the original marketplace transaction identity,
    # shared across syndicated sources. Feed-row IDs are not sufficient.
    origin_transaction_id: str = Field(min_length=1, max_length=150)
    source_id: str = Field(min_length=1, max_length=120)
    printing_id: str = Field(min_length=1, max_length=150)
    language: str = Field(min_length=1, max_length=40)
    state: Literal["RAW_NM", "PSA_9", "PSA_10"]
    amount_minor: int = Field(strict=True, gt=0, le=100_000_000)
    currency: Literal["GBP"]
    sold_at: AwareDatetime
    # Aggregation must use the same declared price basis for every comparison.
    price_basis: Literal["ITEM_PRICE_EXCLUDES_SHIPPING_TAX_AND_PREMIUM"]


class GradingComparison(StrictModel):
    printing_id: str = Field(min_length=1, max_length=150)
    language: str = Field(min_length=1, max_length=40)
    sales: list[Sale] = Field(min_length=1, max_length=90)


class Destination(StrictModel):
    url: HttpUrl
    subject_ids: list[str] = Field(min_length=1, max_length=20)
    checked_at: AwareDatetime


class EditorialBrief(StrictModel):
    schema_version: Literal[1] = 1
    story_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    medium: Literal["TRADING_CARDS", "COMICS", "MANGA", "ANIME", "LIVE_ACTION_FILM"] = "TRADING_CARDS"
    franchise: str = Field(default="UNASSIGNED", min_length=1, max_length=80)
    series: Literal[
        "ARTIST_CONNECTIONS", "BUDGET_BINDER", "RANKED_GUIDE",
        "RAW_TO_GRADED", "MARKET_MOVERS", "RELEASE_RADAR",
        "STORY_SPOTLIGHT", "SCREEN_RADAR", "COMMUNITY_PICKS",
    ]
    headline: str = Field(min_length=1, max_length=85)
    subject_ids: list[str] = Field(min_length=1, max_length=20)
    evidence: list[Evidence] = Field(min_length=1, max_length=30)
    facts: list[Fact] = Field(min_length=3, max_length=5)
    takeaway: str = Field(min_length=1, max_length=160)
    destination: Destination | None = None
    grading: GradingComparison | None = None


TEMPLATES = {
    "ARTIST_CONNECTIONS": "BEHIND_THE_ART",
    "BUDGET_BINDER": "BUILD_A_BINDER",
    "RANKED_GUIDE": "THE_SHORTLIST",
    "RAW_TO_GRADED": "WORTH_THE_GRADE",
    "MARKET_MOVERS": "THE_PRICE_CHECK",
    "RELEASE_RADAR": "NEXT_DROP",
    "STORY_SPOTLIGHT": "THE_STORY_BEHIND",
    "SCREEN_RADAR": "NEXT_ON_SCREEN",
    "COMMUNITY_PICKS": "YOUR_SHORTLIST",
}
# Initial editorial screening policy, not a market standard or profit model.
GRADING_POLICY = {
    "max_raw_minor": 3000,
    "minimum_psa10_to_raw_multiple": 4,
    "minimum_distinct_sales_per_state": 5,
    "sale_window_days": 30,
    "maximum_spread_multiple": 3,
}


def _grading_screen(
    comparison: GradingComparison, sources: dict[str, Evidence], now: datetime
) -> tuple[dict | None, list[str]]:
    reasons: list[str] = []
    groups: dict[str, list[int]] = {"RAW_NM": [], "PSA_9": [], "PSA_10": []}
    seen: set[str] = set()
    for sale in comparison.sales:
        if sale.origin_transaction_id in seen:
            reasons.append("duplicate_original_sale")
            continue
        seen.add(sale.origin_transaction_id)
        if (sale.printing_id, sale.language) != (comparison.printing_id, comparison.language):
            reasons.append("printing_or_language_mismatch")
            continue
        source = sources.get(sale.source_id)
        if source is None or source.kind != "SOLD_RECORD":
            reasons.append("sale_requires_completed_sale_source")
            continue
        if not now - timedelta(days=30) <= sale.sold_at <= now:
            reasons.append("sale_outside_comparison_window")
            continue
        if sale.sold_at > source.observed_at:
            reasons.append("sale_after_observation")
            continue
        groups[sale.state].append(sale.amount_minor)
    if any(len(values) < 5 for values in groups.values()):
        reasons.append("insufficient_distinct_raw_psa9_or_psa10_sales")
    if any(values and max(values) > min(values) * 3 for values in groups.values()):
        reasons.append("sale_dispersion_requires_review")
    if reasons:
        return None, sorted(set(reasons))
    medians = {key: Decimal(str(median(values))) for key, values in groups.items()}
    raw, psa10 = medians["RAW_NM"], medians["PSA_10"]
    if raw > GRADING_POLICY["max_raw_minor"]:
        reasons.append("raw_price_above_affordable_screen")
    if psa10 < raw * GRADING_POLICY["minimum_psa10_to_raw_multiple"]:
        reasons.append("psa10_premium_below_screen")
    if reasons:
        return None, reasons
    return {
        "basis": "OBSERVED_GBP_ITEM_PRICE_MEDIANS_NOT_PROFIT",
        "window_days": 30,
        "counts": {key: len(values) for key, values in groups.items()},
        "median_minor": {key: str(value) for key, value in medians.items()},
        "hero": [f"Raw card: £{raw / 100:.2f}", f"PSA 10: £{psa10 / 100:.2f}"],
        "psa9": f"PSA 9: £{medians['PSA_9'] / 100:.2f}",
        "psa10_to_raw_multiple": str((psa10 / raw).quantize(Decimal("0.01"))),
        "net_profit": None,
        "expected_value": None,
        "note": "Condition and grade are uncertain. Grading, shipping, fees and taxes are excluded.",
    }, []


def _tracked_url(brief: EditorialBrief, origin: str | None, now: datetime) -> str | None:
    destination = brief.destination
    if destination is None or not origin:
        return None
    try:
        allowed, target = urlsplit(origin), urlsplit(str(destination.url))
        if (
            allowed.scheme != "https" or target.scheme != "https"
            or allowed.username or allowed.password or target.username or target.password
            or allowed.port not in (None, 443) or target.port not in (None, 443)
            or not allowed.hostname or target.hostname != allowed.hostname
            or allowed.path not in ("", "/") or allowed.query or allowed.fragment
            or target.query or target.fragment or target.path in ("", "/")
            or not target.path.startswith(("/products/", "/collections/", "/pages/"))
            or "%" in target.path or "\\" in target.path or ".." in target.path
            or not set(brief.subject_ids).intersection(destination.subject_ids)
            or not now - timedelta(hours=1) <= destination.checked_at <= now
        ):
            return None
        # Platform is bound later by its adapter, never guessed here.
        query = urlencode({
            "utm_medium": "organic_social", "utm_campaign": brief.series.lower(),
            "utm_content": brief.story_id,
        })
        return urlunsplit(("https", allowed.netloc, target.path, query, ""))
    except ValueError:
        return None


def prepare_editorial(
    brief: EditorialBrief, *, now: datetime | None = None, storefront_origin: str | None = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    blockers: list[str] = []
    sources = {source.source_id: source for source in brief.evidence}
    if len(sources) != len(brief.evidence):
        blockers.append("duplicate_source_identity")
    for source in brief.evidence:
        if not source.observed_at <= now <= source.valid_until:
            blockers.append("stale_or_future_evidence")
        if source.valid_until < source.observed_at:
            blockers.append("invalid_evidence_window")
    for fact in brief.facts:
        if any(key not in sources for key in fact.source_ids):
            blockers.append("missing_fact_source")
        elif all(sources[key].kind == "SOCIAL_LEAD" for key in fact.source_ids):
            blockers.append("social_lead_is_not_fact_verification")
    comparison = None
    if brief.series == "RAW_TO_GRADED":
        if brief.medium != "TRADING_CARDS":
            blockers.append("card_grading_model_not_valid_for_this_medium")
        elif brief.grading is None:
            blockers.append("grading_comparison_required")
        elif brief.grading.printing_id not in brief.subject_ids:
            blockers.append("grading_subject_mismatch")
        else:
            comparison, reasons = _grading_screen(brief.grading, sources, now)
            blockers.extend(reasons)
    elif brief.grading is not None:
        blockers.append("grading_data_on_wrong_series")
    tracked_url = _tracked_url(brief, storefront_origin, now)
    if brief.destination is not None and tracked_url is None:
        blockers.append("destination_unconfigured_stale_or_invalid")
    canonical = json.dumps(brief.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(("editorial-prepare-v1:" + canonical).encode()).hexdigest()
    slides = [{"role": "HOOK", "text": brief.headline}]
    slides.extend({"role": "EVIDENCE", "text": fact.text, "source_ids": fact.source_ids} for fact in brief.facts)
    slides.append({"role": "TAKEAWAY", "text": brief.takeaway})
    slides.append({
        "role": "NEXT_STEP",
        "text": "Explore the matching collection" if tracked_url else "Save this guide for your next collection check.",
        "url": tracked_url,
    })
    return {
        "schema_version": 1,
        "status": "NEEDS_EVIDENCE" if blockers else "PREPARED_FOR_REVIEW",
        "publishable": False,
        "stored": False,
        "fingerprint": fingerprint,
        "template": TEMPLATES[brief.series],
        "slides": slides,
        "grading_screen": comparison,
        "grading_policy": GRADING_POLICY,
        "preparation_blockers": sorted(set(blockers)),
        "publication_blockers": [
            "authoritative_source_and_claim_verification_pending",
            "licensed_media_and_render_validation_pending",
            "durable_job_revision_and_publication_claim_pending",
            "account_connection_and_publisher_readback_pending",
            "live_destination_and_inventory_recheck_pending",
        ],
        "platforms": {
            "INSTAGRAM": "CAROUSEL_ADAPTER_AND_ACCOUNT_UNVERIFIED",
            "FACEBOOK": "MULTI_IMAGE_ADAPTER_AND_PAGE_UNVERIFIED",
            "TIKTOK": "PHOTO_DIRECT_POST_ADAPTER_AND_ACCOUNT_UNVERIFIED",
            "X": "IMAGE_POST_OR_THREAD_ADAPTER_ACCOUNT_AND_COST_UNVERIFIED",
            "YOUTUBE": "STATIC_COMMUNITY_PUBLISH_API_UNAVAILABLE",
        },
        "design": {"master": [1080, 1350], "tiktok": [1080, 1920], "music": False},
    }
