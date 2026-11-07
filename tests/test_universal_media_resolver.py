"""DR106 universal media decisions never widen image permissions by channel."""
from copy import deepcopy

import pytest

from app.media_resolver import (
    FIRST_PARTY_CAPTURE,
    INTERNAL_REFERENCE_ONLY,
    MEDIA_CHANNELS,
    STOREFRONT_ALLOWED,
    resolve_media,
)
from test_media_resolver import _asset, _item


def physical(*, side="FRONT", owner="owner-a", inventory="inventory-1",
             asset_id="photo", context="RAW_UNSLEEVED"):
    value = _asset(
        asset_id=asset_id, scope="INVENTORY_ITEM", side=side,
        inventory_id=inventory, catalogue_id=None,
        rights_tier=FIRST_PARTY_CAPTURE, capture_context=context,
    )
    value.update(
        owner_id=owner, source_type="FOUNDER_UPLOAD",
        shopify_cdn_url=f"https://cdn.shopify.com/s/files/1/{asset_id}.jpg",
    )
    return value


def owned_item(**changes):
    return _item(owner_id="owner-a", **changes)


def test_all_channels_resolve_from_one_inventory_without_mutating_source():
    card = owned_item()
    official = _asset()
    front = physical()
    back = physical(side="BACK", asset_id="back")
    sources = [official, front, back]
    frozen = deepcopy((card, sources))

    drop_rate = resolve_media(card, sources, channel="DROP_RATE", purpose="DISPLAY")
    shopify = resolve_media(card, sources, channel="SHOPIFY")
    ebay = resolve_media(card, sources, channel="EBAY")
    whatnot = resolve_media(card, sources, channel="WHATNOT")

    assert MEDIA_CHANNELS == {"DROP_RATE", "SHOPIFY", "EBAY", "WHATNOT"}
    for result in (drop_rate, shopify):
        assert result["complete"]
        assert result["resolutionSource"] == "CANONICAL_STOREFRONT"
        assert result["selectedMedia"][0]["id"] == "asset-1"
    assert drop_rate["publishReady"] is False
    assert shopify["publishReady"] is True
    assert shopify["shopifyFileIds"] == ["gid://shopify/MediaImage/asset-1"]

    assert ebay["complete"] and ebay["publishReady"]
    assert ebay["resolutionSource"] == FIRST_PARTY_CAPTURE
    assert ebay["imageUrls"] == [
        "https://cdn.shopify.com/s/files/1/photo.jpg",
        "https://cdn.shopify.com/s/files/1/back.jpg",
    ]
    assert all(asset["scope"] == "INVENTORY_ITEM" for asset in ebay["selectedMedia"])
    assert whatnot["complete"] is False and whatnot["publishReady"] is False
    assert whatnot["channelConnected"] is False
    assert whatnot["imageUrls"] == [] and whatnot["shopifyFileIds"] == []
    assert "WHATNOT_CHANNEL_NOT_CONNECTED" in whatnot["blockers"]
    assert (card, sources) == frozen


@pytest.mark.parametrize("bad", [
    {"owner_id": "owner-b"},
    {"inventory_id": "copy-other"},
    {"scope": "CANONICAL_CARD"},
    {"source_type": "OFFICIAL_PROVIDER"},
    {"rights_tier": INTERNAL_REFERENCE_ONLY},
    {"rights_status": "PENDING"},
    {"approval_status": "PENDING"},
    {"source_status": "INACTIVE"},
    {"revoked_at": "2026-11-07T10:00:00Z"},
    {"shopify_file_status": "PROCESSING"},
    {"shopify_cdn_url": "http://cdn.shopify.com/front.jpg"},
    {"shopify_cdn_url": "https://cdn.shopify.com.evil.example/photo.jpg"},
    {"shopify_cdn_url": "https://cdn.shopify.com@evil.example/photo.jpg"},
    {"shopify_cdn_url": "https://cdn.shopify.com/ok#frag"},
])
def test_ebay_never_promotes_wrong_owner_unapproved_or_untrusted_photo(bad):
    front = physical()
    front.update(bad)
    decision = resolve_media(
        owned_item(), [_asset(), front, physical(side="BACK", asset_id="back")],
        channel="EBAY",
    )
    assert not decision["complete"]
    assert not decision["publishReady"]
    assert decision["imageUrls"] == []
    assert decision["blockers"] == ["approved FRONT + BACK physical photos are required"]


def test_ebay_requires_approved_photograph_of_the_exact_slab_not_raw_art():
    slab = owned_item(grading_company="PSA", grade="10",
                      certificate_number="123456789", condition=None)
    front = physical(context="RAW_UNSLEEVED")
    back = physical(side="BACK", asset_id="back", context="GRADED_SLAB")
    wrong = resolve_media(slab, [_asset(), front, back], channel="EBAY")
    assert not wrong["complete"]
    front["capture_context"] = "GRADED_SLAB"
    exact = resolve_media(slab, [front, back], channel="EBAY")
    assert exact["complete"] and len(exact["imageUrls"]) == 2
    assert exact["selectedMedia"][0]["captureContext"] == "GRADED_SLAB"


def test_ebay_never_uses_stock_images_as_fallback():
    blocked = resolve_media(owned_item(), [_asset()], channel="EBAY")
    assert not blocked["complete"]
    assert blocked["imageUrls"] == []
    assert blocked["resolutionSource"] == "NONE"


def test_official_image_wrong_printing_remains_blocked_across_drop_rate_and_shopify():
    wrong = _asset(variant="Wrong Artwork", language="Japanese")
    for channel in ("SHOPIFY", "DROP_RATE", "WHATNOT"):
        result = resolve_media(
            owned_item(), [wrong], channel=channel,
            purpose="DISPLAY" if channel == "DROP_RATE" else "LISTING",
        )
        assert not result["complete"]
        assert result["imageUrls"] == []
        assert all(asset["id"] != wrong["id"] for asset in result["selectedMedia"])


def test_graded_shopify_and_drop_rate_do_not_use_raw_official_card_art():
    item = owned_item(grading_company="PSA", grade="10",
                      certificate_number="123456789", condition=None)
    for channel in ("DROP_RATE", "SHOPIFY"):
        result = resolve_media(item, [_asset()], channel=channel)
        assert not result["complete"]
        assert result["selectedMedia"] == []


def test_unknown_channels_purposes_and_missing_ownership_fail_closed():
    for kwargs in (
        {"channel": "UNREGISTERED"},
        {"channel": "EBAY", "purpose": "AUTO_APPROVE"},
    ):
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_media(owned_item(), [], **kwargs)
    no_owner = resolve_media(_item(), [physical(), physical(side="BACK")],
                             channel="EBAY")
    assert not no_owner["complete"]


def test_unconnected_whatnot_does_not_reuse_a_valid_shopify_publish_decision():
    result = resolve_media(owned_item(), [_asset()], channel="WHATNOT")
    assert not result["complete"]
    assert not result["publishReady"]
    assert not result["channelConnected"]
    assert result["selectedMedia"][0]["rightsTier"] == STOREFRONT_ALLOWED
    assert result["imageUrls"] == []
