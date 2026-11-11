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
        assert result["resolutionSource"] == FIRST_PARTY_CAPTURE
        assert result["selectedMedia"][0]["id"] == "photo"
    assert drop_rate["publishReady"] is False
    assert shopify["publishReady"] is True
    assert shopify["shopifyFileIds"] == ["gid://shopify/MediaImage/photo", "gid://shopify/MediaImage/back"]

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
    assert decision["blockers"] == ["approved catalogue image or saved front scan required"]


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


@pytest.mark.parametrize('kind', ['CARD', 'COMIC', 'BOOK', 'FIGURE', 'LEGO', 'SEALED'])
def test_own_product_photo_needs_no_separate_publisher_licence(kind):
    item = owned_item(product_type=kind, seal_status='SEALED')
    photo = physical(context='SEALED_PRODUCT' if kind == 'SEALED' else 'RAW_UNSLEEVED')
    photo.update(permission_evidence_url=None,
                 rights_basis='Photographed by consignor; authorised for sale of this Inventory ID.')
    for channel in ('DROP_RATE', 'SHOPIFY'):
        result = resolve_media(item, [photo], channel=channel)
        assert result['complete']
        assert result['resolutionSource'] == FIRST_PARTY_CAPTURE
        assert result['selectedMedia'][0]['id'] == photo['id']


@pytest.mark.parametrize('change,reason', [
    ({'rights_status': 'PENDING'}, 'photographer/source permission'),
    ({'approval_status': 'PENDING'}, 'internal media approval'),
    ({'revoked_at': '2026-11-07T00:00:00Z'}, 'inactive or revoked'),
    ({'shopify_file_status': 'PROCESSING'}, 'Shopify file processing'),
    ({'rights_tier': INTERNAL_REFERENCE_ONLY}, 'not a first-party product photograph'),
])
def test_photo_blocker_reports_specific_reason(change, reason):
    photo = physical()
    photo.update(change)
    result = resolve_media(owned_item(store_price_minor=8000), [photo], channel='SHOPIFY')
    assert not result['publishReady']
    assert any(reason in blocker for blocker in result['blockers'])
    assert not any('publisher' in blocker or 'copyright' in blocker for blocker in result['blockers'])


def test_first_party_photograph_cannot_become_reusable_catalogue_media():
    photo = physical()
    photo.update(scope='CANONICAL_CARD', inventory_id=None, catalogue_id='catalogue-1')
    assert not resolve_media(owned_item(), [photo], channel='SHOPIFY')['complete']


def test_ebay_uses_exact_approved_tcgdex_art_before_saved_front_scan():
    artwork = _asset()
    artwork.update(
        source_provider="TCGdex",
        public_source_url="https://assets.tcgdex.net/en/swsh/swsh1/001/high.webp",
        shopify_cdn_url=None,
        shopify_file_status="PROCESSING",
    )
    scan = physical()
    result = resolve_media(owned_item(), [artwork, scan], channel="EBAY")
    assert result["complete"] and result["publishReady"]
    assert result["resolutionSource"] == "CANONICAL_STOREFRONT"
    assert result["imageUrls"] == [
        artwork["public_source_url"], scan["shopify_cdn_url"]
    ]
    assert result["requiredSides"] == ["FRONT"]
    assert result["physicalPhotosRequired"] is False


def test_ebay_saved_front_scan_needs_no_back_photo():
    scan = physical()
    result = resolve_media(owned_item(), [scan], channel="EBAY")
    assert result["complete"]
    assert result["imageUrls"] == [scan["shopify_cdn_url"]]


@pytest.mark.parametrize("bad", [
    {"catalogue_id": "someone-elses-card"},
    {"media_variant": "Wrong variant"},
    {"media_language": "Japanese"},
    {"rights_tier": INTERNAL_REFERENCE_ONLY},
    {"approval_status": "PENDING"},
    {"rights_status": "PENDING"},
    {"public_source_url": "https://assets.tcgdex.net.evil.test/stock.webp"},
    {"public_source_url": "https://assets.tcgdex.net@evil.test/stock.webp"},
    {"public_source_url": "http://assets.tcgdex.net/stock.webp"},
])
def test_ebay_never_substitutes_unmatched_unapproved_or_untrusted_catalogue_art(bad):
    artwork = _asset()
    artwork.update(
        public_source_url="https://assets.tcgdex.net/en/cards/card.webp",
        shopify_cdn_url=None, shopify_file_status="PROCESSING",
    )
    artwork.update(bad)
    result = resolve_media(owned_item(), [artwork], channel="EBAY")
    assert not result["complete"]
    assert not result["imageUrls"]


def test_graded_ebay_can_list_exact_catalogue_art_without_claiming_slab_photo():
    artwork = _asset()
    artwork.update(
        public_source_url="https://assets.tcgdex.net/en/cards/card.webp",
        shopify_cdn_url=None, shopify_file_status="PROCESSING",
    )
    result = resolve_media(
        owned_item(grading_company="PSA", grade="10", condition=None),
        [artwork], channel="EBAY"
    )
    assert result["complete"]
    assert result["imageUrls"] == [artwork["public_source_url"]]
    assert result["selectedMedia"][0]["scope"] == "CANONICAL_CARD"
