from __future__ import annotations

from app.media_resolver import (
    FIRST_PARTY_CAPTURE,
    INTERNAL_REFERENCE_ONLY,
    MARKETPLACE_NATIVE_ONLY,
    STOREFRONT_ALLOWED,
    physical_photo_policy,
    resolve_storefront_media,
)


def _item(**overrides):
    row = {
        "id": "inventory-1",
        "catalogue_id": "catalogue-1",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "language": "English",
        "catalogue_language": "English",
        "identity_confirmed": True,
        "condition": "Near Mint",
        "condition_review_status": "NOT_REVIEWED",
        "grading_company": None,
        "grade": None,
        "store_price_minor": 499,
        "market_value_minor": 450,
        "recommended_retail_minor": 499,
    }
    row.update(overrides)
    return row


def _asset(
    *,
    asset_id="asset-1",
    scope="CANONICAL_CARD",
    side="FRONT",
    rights_tier=STOREFRONT_ALLOWED,
    language="English",
    variant="Normal",
    inventory_id=None,
    catalogue_id="catalogue-1",
    source_status="ACTIVE",
    capture_context=None,
):
    return {
        "id": asset_id,
        "scope": scope,
        "side": side,
        "inventory_id": inventory_id,
        "catalogue_id": catalogue_id,
        "rights_tier": rights_tier,
        "rights_status": "VERIFIED",
        "approval_status": "APPROVED",
        "media_kind": "IMAGE",
        "source_status": source_status,
        "revoked_at": None,
        "rights_basis": "Provider licence permits product-page use",
        "permission_evidence_url": "https://example.com/licence",
        "source_provider": "Example Provider",
        "source_reference": f"provider:{asset_id}",
        "media_language": language,
        "media_variant": variant,
        "capture_context": capture_context,
        "shopify_file_status": "READY",
        "shopify_file_gid": f"gid://shopify/MediaImage/{asset_id}",
        "shopify_cdn_url": f"https://cdn.example.com/{asset_id}.jpg",
        "created_at": "2026-09-27T10:00:00Z",
        "approved_at": "2026-09-27T10:01:00Z",
    }


def test_low_value_raw_card_uses_exact_storefront_allowed_canonical_media() -> None:
    result = resolve_storefront_media(_item(), [_asset()])

    assert result["complete"] is True
    assert result["physicalPhotosRequired"] is False
    assert result["mediaPolicy"] == "CANONICAL_STOREFRONT_ALLOWED"
    assert result["resolutionSource"] == "CANONICAL_STOREFRONT"
    assert result["rightsTier"] == STOREFRONT_ALLOWED
    assert result["selectedMedia"][0]["mediaLanguage"] == "English"


def test_marketplace_native_and_internal_reference_media_never_satisfy_storefront() -> None:
    for tier in (MARKETPLACE_NATIVE_ONLY, INTERNAL_REFERENCE_ONLY):
        result = resolve_storefront_media(
            _item(),
            [_asset(rights_tier=tier)],
        )
        assert result["complete"] is False
        assert result["shopifyFileIds"] == []
        assert "rights tier" in " ".join(result["blockers"])


def test_language_mismatch_fails_closed() -> None:
    result = resolve_storefront_media(
        _item(language="English"),
        [_asset(language="Japanese")],
    )
    assert result["complete"] is False
    assert "canonical media language mismatch" in result["blockers"]


def test_variant_mismatch_fails_closed() -> None:
    result = resolve_storefront_media(
        _item(variant="Illustration Rare"),
        [_asset(variant="Normal")],
    )
    assert result["complete"] is False
    assert "canonical media variant mismatch" in result["blockers"]


def test_revoked_or_dead_source_never_satisfies_storefront() -> None:
    revoked = _asset(source_status="REVOKED")
    revoked["revoked_at"] = "2026-09-27T12:00:00Z"
    dead = _asset(asset_id="asset-dead", source_status="DEAD")

    for asset in (revoked, dead):
        result = resolve_storefront_media(_item(), [asset])
        assert result["complete"] is False
        assert "inactive or revoked" in " ".join(result["blockers"])


def test_high_value_raw_card_requires_exact_first_party_front_and_back() -> None:
    item = _item(store_price_minor=5_000)
    canonical = _asset()
    result = resolve_storefront_media(item, [canonical], threshold_minor=5_000)

    assert result["physicalPhotosRequired"] is True
    assert result["complete"] is False
    assert result["resolutionSource"] == "NONE"
    assert "approved first-party physical front image" in result["blockers"]
    assert "approved first-party physical back image" in result["blockers"]

    front = _asset(
        asset_id="front",
        scope="INVENTORY_ITEM",
        side="FRONT",
        rights_tier=FIRST_PARTY_CAPTURE,
        inventory_id="inventory-1",
        catalogue_id=None,
        capture_context="PENNY_SLEEVE",
    )
    back = _asset(
        asset_id="back",
        scope="INVENTORY_ITEM",
        side="BACK",
        rights_tier=FIRST_PARTY_CAPTURE,
        inventory_id="inventory-1",
        catalogue_id=None,
        capture_context="PENNY_SLEEVE",
    )
    complete = resolve_storefront_media(
        item,
        [canonical, front, back],
        threshold_minor=5_000,
    )
    assert complete["complete"] is True
    assert complete["resolutionSource"] == FIRST_PARTY_CAPTURE
    assert complete["shopifyFileIds"] == [
        "gid://shopify/MediaImage/front",
        "gid://shopify/MediaImage/back",
    ]


def test_graded_card_always_requires_physical_capture() -> None:
    policy = physical_photo_policy(
        _item(
            condition=None,
            grading_company="PSA",
            grade="10",
            store_price_minor=499,
        )
    )
    assert policy["physicalPhotosRequired"] is True
    assert "graded card" in policy["reasons"]


def test_exact_first_party_front_has_priority_for_low_risk_card() -> None:
    physical = _asset(
        asset_id="physical-front",
        scope="INVENTORY_ITEM",
        side="FRONT",
        rights_tier=FIRST_PARTY_CAPTURE,
        inventory_id="inventory-1",
        catalogue_id=None,
        capture_context="RAW_UNSLEEVED",
    )
    result = resolve_storefront_media(_item(), [_asset(), physical])
    assert result["complete"] is True
    assert result["resolutionSource"] == FIRST_PARTY_CAPTURE
    assert result["selectedMedia"][0]["id"] == "physical-front"
