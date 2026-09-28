from __future__ import annotations

from typing import Any, Mapping

from .language import clean_language


DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR = 5_000

STOREFRONT_ALLOWED = "STOREFRONT_ALLOWED"
MARKETPLACE_NATIVE_ONLY = "MARKETPLACE_NATIVE_ONLY"
INTERNAL_REFERENCE_ONLY = "INTERNAL_REFERENCE_ONLY"
FIRST_PARTY_CAPTURE = "FIRST_PARTY_CAPTURE"

RIGHTS_TIERS = {
    STOREFRONT_ALLOWED,
    MARKETPLACE_NATIVE_ONLY,
    INTERNAL_REFERENCE_ONLY,
    FIRST_PARTY_CAPTURE,
}


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: object) -> str:
    return _text(value).casefold()


def _language(value: object) -> str:
    return clean_language(value) or ""


def _int_value(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def physical_photo_policy(
    item: Mapping[str, Any],
    *,
    threshold_minor: int = DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
) -> dict[str, Any]:
    """Return the deterministic physical-photo rule for one inventory item.

    AI is deliberately absent from this decision. The rule is based only on
    stored inventory facts and a configured GBP-minor-unit threshold.
    """

    if threshold_minor < 100:
        raise ValueError("Physical-photo threshold must be at least £1.00")

    product_type = _text(item.get("product_type"))
    if product_type in {"SEALED", "COLLECTION"}:
        return {
            "mediaPolicy": "PHYSICAL_ITEM_REQUIRED",
            "physicalPhotosRequired": True,
            "requiredSides": ["FRONT"],
            "captureContext": "SEALED_PRODUCT",
            "reasons": ["sealed product requires exact packaging photo"],
            "thresholdMinor": threshold_minor,
        }
    if product_type != "CARD":
        return {
            "mediaPolicy": "CANONICAL_STOREFRONT_ALLOWED",
            "physicalPhotosRequired": False,
            "requiredSides": ["FRONT"],
            "reasons": [],
            "thresholdMinor": threshold_minor,
        }

    reasons: list[str] = []
    graded = bool(
        _text(item.get("grading_company"))
        and _text(item.get("grade"))
    )
    if graded:
        reasons.append("graded card")

    values = [
        _int_value(item.get("store_price_minor")),
        _int_value(item.get("market_value_minor")),
        _int_value(item.get("recommended_retail_minor")),
    ]
    known_values = [value for value in values if value is not None]
    if known_values and max(known_values) >= threshold_minor:
        reasons.append(f"value at or above £{threshold_minor / 100:.2f}")

    condition = _text(item.get("condition"))
    if condition and condition != "Near Mint" and not graded:
        reasons.append("condition-specific raw card")

    review_status = _text(item.get("condition_review_status"))
    if review_status in {
        "NEEDS_REVIEW",
        "NEEDS_RESHOOT",
        "REJECTED_BELOW_NEAR_MINT",
    }:
        reasons.append(f"condition exception: {review_status}")

    if item.get("identity_confirmed") is False:
        reasons.append("identity not confirmed")

    reasons = list(dict.fromkeys(reasons))
    required = bool(reasons)
    return {
        "mediaPolicy": (
            "PHYSICAL_ITEM_REQUIRED"
            if required
            else "CANONICAL_STOREFRONT_ALLOWED"
        ),
        "physicalPhotosRequired": required,
        "reasons": reasons,
        "requiredSides": ["FRONT", "BACK"] if required else ["FRONT"],
        "thresholdMinor": threshold_minor,
    }


def _base_ready(asset: Mapping[str, Any]) -> bool:
    return (
        _text(asset.get("approval_status")) == "APPROVED"
        and _text(asset.get("rights_status")) == "VERIFIED"
        and _text(asset.get("source_status") or "ACTIVE") == "ACTIVE"
        and not asset.get("revoked_at")
        and _text(asset.get("media_kind") or "IMAGE") == "IMAGE"
        and _text(asset.get("shopify_file_status")) == "READY"
        and bool(_text(asset.get("shopify_file_gid")))
    )


def _sort_key(asset: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(asset.get("approved_at")),
        _text(asset.get("created_at")),
        _text(asset.get("id")),
    )


def _latest_by_side(
    assets: list[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for side in ("FRONT", "BACK", "OTHER"):
        choices = [asset for asset in assets if _text(asset.get("side")) == side]
        if choices:
            result[side] = max(choices, key=_sort_key)
    return result


def _inventory_capture_candidates(
    item: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    inventory_id = _text(item.get("id"))
    product_type = _text(item.get("product_type"))
    candidates = [
        asset
        for asset in assets
        if _base_ready(asset)
        and _text(asset.get("scope")) == "INVENTORY_ITEM"
        and _text(asset.get("inventory_id")) == inventory_id
        and _text(asset.get("rights_tier")) == FIRST_PARTY_CAPTURE
    ]
    if product_type in {"SEALED", "COLLECTION"}:
        return [
            asset
            for asset in candidates
            if _text(asset.get("capture_context")) == "SEALED_PRODUCT"
        ]
    return candidates


def _canonical_scope(item: Mapping[str, Any]) -> str:
    return (
        "CANONICAL_CARD"
        if _text(item.get("product_type")) == "CARD"
        else "CANONICAL_PRODUCT"
    )


def _canonical_match_reason(
    item: Mapping[str, Any],
    asset: Mapping[str, Any],
) -> str | None:
    expected_scope = _canonical_scope(item)
    if _text(asset.get("scope")) != expected_scope:
        return "not canonical media"
    if _text(asset.get("catalogue_id")) != _text(item.get("catalogue_id")):
        return "canonical product identity mismatch"
    if _text(asset.get("rights_tier")) != STOREFRONT_ALLOWED:
        return "canonical media rights tier is not storefront allowed"
    if _text(asset.get("source_status") or "ACTIVE") != "ACTIVE" or asset.get("revoked_at"):
        return "canonical media source is inactive or revoked"
    if (
        _text(asset.get("approval_status")) != "APPROVED"
        or _text(asset.get("rights_status")) != "VERIFIED"
    ):
        return "canonical media is not rights-approved"
    if _text(asset.get("media_kind") or "IMAGE") != "IMAGE":
        return "canonical media is not an image"
    if (
        _text(asset.get("shopify_file_status")) != "READY"
        or not _text(asset.get("shopify_file_gid"))
    ):
        return "canonical media is not ready in Shopify"

    expected_language = _language(
        item.get("language") or item.get("catalogue_language")
    )
    asset_language = _language(asset.get("media_language"))
    if not expected_language:
        return "canonical media blocked until product language/region is verified"
    if asset_language != expected_language:
        return "canonical media language mismatch"

    expected_variant = _norm(item.get("variant"))
    asset_variant = _norm(asset.get("media_variant"))
    if asset_variant != expected_variant:
        return "canonical media variant mismatch"

    if not (
        _text(asset.get("rights_basis"))
        or _text(asset.get("permission_evidence_url"))
    ):
        return "canonical media permission evidence is missing"
    return None


def _canonical_candidates(
    item: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    matches: list[Mapping[str, Any]] = []
    diagnostics: list[str] = []
    catalogue_id = _text(item.get("catalogue_id"))
    expected_scope = _canonical_scope(item)
    for asset in assets:
        if _text(asset.get("scope")) != expected_scope:
            continue
        if _text(asset.get("catalogue_id")) != catalogue_id:
            continue
        reason = _canonical_match_reason(item, asset)
        if reason is None:
            matches.append(asset)
        else:
            diagnostics.append(reason)
    return matches, list(dict.fromkeys(diagnostics))


def _selected_summary(asset: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": asset.get("id"),
        "scope": asset.get("scope"),
        "side": asset.get("side"),
        "rightsTier": asset.get("rights_tier"),
        "sourceProvider": asset.get("source_provider"),
        "sourceReference": asset.get("source_reference"),
        "sourceUrl": asset.get("public_source_url"),
        "shopifyCdnUrl": asset.get("shopify_cdn_url"),
        "mediaLanguage": asset.get("media_language"),
        "mediaVariant": asset.get("media_variant"),
        "captureContext": asset.get("capture_context"),
        "shopifyFileId": asset.get("shopify_file_gid"),
    }


def resolve_storefront_media(
    item: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
    *,
    threshold_minor: int = DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
) -> dict[str, Any]:
    """Resolve the exact storefront media for an inventory item, fail closed.

    Priority:
      1. ready FIRST_PARTY_CAPTURE media for the exact inventory item;
      2. for low-risk items only, exact STOREFRONT_ALLOWED canonical media;
      3. otherwise Action Required / first-party capture.
    """

    policy = physical_photo_policy(item, threshold_minor=threshold_minor)
    physical = _latest_by_side(_inventory_capture_candidates(item, assets))
    physical_front = physical.get("FRONT")
    physical_back = physical.get("BACK")

    selected: list[Mapping[str, Any]] = []
    blockers: list[str] = []
    source = "NONE"
    rights_tier: str | None = None
    selection_reason = ""

    if policy["physicalPhotosRequired"]:
        required_sides = list(policy.get("requiredSides") or ["FRONT", "BACK"])
        by_side = {"FRONT": physical_front, "BACK": physical_back}
        for required_side in required_sides:
            if by_side.get(required_side) is None:
                blockers.append(
                    f"approved first-party physical {required_side.casefold()} image"
                )

        for required_side in required_sides:
            asset = by_side.get(required_side)
            if asset is not None and not _text(asset.get("capture_context")):
                blockers.append(
                    f"capture context for physical-item {required_side.casefold()} image"
                )

        if not blockers:
            selected = [
                by_side[side]
                for side in required_sides
                if by_side.get(side) is not None
            ]
            source = FIRST_PARTY_CAPTURE
            rights_tier = FIRST_PARTY_CAPTURE
            selection_reason = (
                "Exact first-party media selected because physical photos are "
                "mandatory for this inventory item."
            )
    elif physical_front is not None:
        selected = [physical_front]
        if physical_back is not None:
            selected.append(physical_back)
        source = FIRST_PARTY_CAPTURE
        rights_tier = FIRST_PARTY_CAPTURE
        selection_reason = (
            "Exact first-party inventory media was available and takes "
            "priority over reusable canonical media."
        )
    else:
        canonical_matches, diagnostics = _canonical_candidates(item, assets)
        canonical = _latest_by_side(canonical_matches)
        canonical_front = canonical.get("FRONT")
        if canonical_front is None:
            blockers.append("exact storefront-allowed canonical front image")
            blockers.extend(diagnostics)
        else:
            selected = [canonical_front]
            canonical_back = canonical.get("BACK")
            if canonical_back is not None:
                selected.append(canonical_back)
            source = "CANONICAL_STOREFRONT"
            rights_tier = STOREFRONT_ALLOWED
            selection_reason = (
                "No physical photos are required by policy; exact canonical "
                "media with verified storefront rights was selected."
            )

    blockers = list(dict.fromkeys(blockers))
    file_ids = [
        _text(asset.get("shopify_file_gid"))
        for asset in selected
        if _text(asset.get("shopify_file_gid"))
    ]
    return {
        **policy,
        "complete": not blockers,
        "blockers": blockers,
        "approvedMediaCount": len(selected),
        "shopifyFileIds": list(dict.fromkeys(file_ids)),
        "resolutionSource": source,
        "rightsTier": rights_tier,
        "selectionReason": selection_reason,
        "selectedMedia": [_selected_summary(asset) for asset in selected],
        "actionRequiredReason": blockers[0] if blockers else None,
    }
