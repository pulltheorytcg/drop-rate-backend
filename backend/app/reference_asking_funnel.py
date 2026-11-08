"""Counts only: no source content, pricing permissions or display activation.

Candidate rejections are first-failure reasons, not independent attributes.
Reference outcomes use a different denominator and must never be added to them.
Old receipts remain incomplete evidence; missing instrumentation is not zero.
"""
from copy import deepcopy


COUNTERS = (
    "references_searched", "searches_returning_listings", "candidates_discovered",
    "selected_detail_candidates", "full_details_retrieved", "details_evaluated",
    "exact_identity_and_condition_accepted", "comparable_rows_accepted",
    "estimates_generated", "estimates_persisted",
    "missing_language_evidence", "conflicting_language_evidence",
)


def begin_funnel(report):
    if "funnel" not in report:
        report["funnel"] = dict.fromkeys(COUNTERS, 0) | {
            "version": 1, "prior_requests_not_instrumented": report.get("requests", 0),
            "reference_outcomes": {}, "detail_first_rejections": {},
            "dedup_and_sample_rejections": {},
            "valuation_permission": "NOT_VERIFIED",
            "market_value_display_eligible": 0,
            "display_blocker": "CURRENT_POLICY_EXCLUDES_BROWSE_ESTIMATES",
        }


def record_estimate(report, estimate):
    funnel = report["funnel"]
    stage = estimate.get("funnel", {})
    if stage.get("evaluated") is True:
        funnel["details_evaluated"] += stage["rows_seen"]
        funnel["exact_identity_and_condition_accepted"] += stage["identity_and_condition_accepted"]
        funnel["comparable_rows_accepted"] += stage["comparable_rows_accepted"]
        for key in ("missing_language_evidence", "conflicting_language_evidence"):
            funnel[key] += stage.get(key, 0)
    status = estimate["status"]
    outcomes = funnel["reference_outcomes"]
    outcomes[status] = outcomes.get(status, 0) + 1
    funnel["estimates_generated"] += status == "READY"
    for reason, count in estimate.get("rejection_counts", {}).items():
        if stage.get("evaluated") is not True:
            continue
        post_match = reason in {"CONFLICTING_DUPLICATE_ITEM", "DUPLICATE_ITEM",
                                "DUPLICATE_SELLER", "PRICE_OUTLIER", "OTHER_FINISH_BUCKET"}
        reasons = funnel["dedup_and_sample_rejections" if post_match else "detail_first_rejections"]
        reasons[reason] = reasons.get(reason, 0) + count


def receipt_funnel(report):
    """Read-only explanation of a receipt; never recompute a historical price."""
    if isinstance(report.get("funnel"), dict):
        return deepcopy(report["funnel"])
    stats = report.get("stats", {})
    return {
        "version": 0, "instrumentation": "LEGACY_INCOMPLETE",
        "references_searched": stats.get("search_requests", stats.get("collected")),
        "searches_returning_listings": None,
        "candidates_discovered": stats.get("summaries_seen"),
        "full_details_retrieved": stats.get("details_observed"),
        "exact_identity_and_condition_accepted": None,
        "estimates_generated": stats.get("matched"),
        "estimates_persisted": stats.get("written"),
        "market_value_display_eligible": None,
        "legacy_mixed_rejection_counts": deepcopy(report.get("rejections", {})),
        "limitation": "Missing counters cannot be reconstructed as zero; display needs current readback.",
    }
