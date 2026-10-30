"""Explicit seller-held sealed stock; purchase cost is not a consignment payout input."""
from collections.abc import Mapping


def sealed_seller_candidate(item):
    return (item.get('owner_type') == 'CONSIGNOR'
            and item.get('product_type') == 'SEALED'
            and item.get('seal_status') == 'SEALED'
            and item.get('catalogue_identity_status') == 'VERIFIED'
            and bool(item.get('language'))
            and item.get('language') == item.get('catalogue_language')
            and not any(item.get(k) for k in ('condition','grading_company','grade','certificate_number')))


def seller_held_consignment(item):
    record = item.get('source_record') or {}
    approval = record.get('seller_held_approval') if isinstance(record, Mapping) else None
    if not isinstance(approval, Mapping):
        return False
    return (item.get('owner_type') == 'CONSIGNOR' and item.get('product_type') == 'SEALED'
            and item.get('identity_confirmed') is True and item.get('seal_status') == 'SEALED'
            and str(approval.get('owner_id')) == str(item.get('owner_id'))
            and str(approval.get('catalogue_id')) == str(item.get('catalogue_id'))
            and approval.get('language') == (item.get('language') or item.get('catalogue_language'))
            and item.get('language') == item.get('catalogue_language')
            and approval.get('name') == item.get('name')
            and approval.get('set_name') == item.get('set_name')
            and approval.get('variant') == item.get('variant')
            and bool(approval.get('actor_user_id')))


def ebay_listing_scope_blocker(owner_type: str, product_type: str) -> str | None:
    """The existing v1 publisher scope, shared by readiness display and execution."""
    if owner_type == "CONSIGNOR":
        return "Consignor eBay publishing is not enabled yet"
    if product_type != "CARD":
        return "eBay v1 only supports individual physical cards"
    return None


def ebay_preparation(item: Mapping) -> dict:
    """Owner-safe, read-only checklist; publication still runs every eBay gate."""
    graded = bool(item.get("grading_company") or item.get("grade"))
    condition_ready = bool(item.get("grading_company") and item.get("grade")) if graded else item.get("condition") == "Near Mint"
    checks = [
        ("identity", "Exact printing confirmed", bool(item.get("identity_ready")), "Drop Rate review"),
        ("language", "Language recorded", bool(item.get("language")), "Item details"),
        ("condition", "Condition or grade recorded", condition_ready,
         "Record the grade, or Near Mint for the current raw-card eBay service"),
        ("price", "Selling price saved", (item.get("store_price_minor") or 0) >= 100, "Save a selling price below"),
        ("approval", "Approved for sale", item.get("status") == "APPROVED" and item.get("sale_intent") == "FOR_SALE", "Request listing review below"),
        ("photos", "Front and back photos approved", bool(item.get("ebay_photos_ready")), "Drop Rate needs photos of this physical copy"),
        ("condition_review", "Photo-backed condition verified",
         item.get("condition_review_status") == ("VERIFIED_GRADED" if graded else "VERIFIED_NEAR_MINT"), "Drop Rate condition review"),
        ("intake", "Cost and dispatch location recorded", bool(item.get("intake_ready")), "Drop Rate intake review"),
        ("shipping", "Shipping profile configured", bool(item.get("ebay_shipping_ready")), "Drop Rate shipping setup"),
    ]
    return {
        "scope_blocker": ebay_listing_scope_blocker(item.get("owner_type"), item.get("product_type")),
        "completed": sum(bool(ready) for _, _, ready, _ in checks),
        "checks": [{"code": code, "label": label, "complete": bool(ready), "next_step": step}
                   for code, label, ready, step in checks],
    }
