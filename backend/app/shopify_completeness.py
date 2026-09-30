from __future__ import annotations

from html import escape
from typing import Any, Mapping

from .brands import brand_for_game
from .language import clean_language, display_title, language_code
from .media_resolver import (
    DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
    FIRST_PARTY_CAPTURE,
    STOREFRONT_ALLOWED,
    physical_photo_policy,
)


CARD_CATEGORY_GID = "gid://shopify/TaxonomyCategory/ae-2-2-3-3"
CARD_CATEGORY_NAME = "Non-Sports Trading Cards"
DEFAULT_THEME_TEMPLATE = "default"
BASE_COLLECTION = "Trading Cards"
SEALED_COLLECTION = "Sealed"
SEALED_PRODUCT_TYPE = "Sealed TCG Product"
SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MAX = 320
PRODUCT_TITLE_MAX = 255


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _trim(value: str, limit: int) -> str:
    text = " ".join(value.strip().split())
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rstrip(" ,.;:-")
    return shortened + "…"


def _language(item: Mapping[str, Any]) -> str:
    return clean_language(item.get("language") or item.get("catalogue_language")) or ""


def _storefront_brand(game: object) -> str:
    brand = brand_for_game(_text(game))
    if brand == "Pokemon":
        return "Pokémon"
    return brand


def _condition_label(item: Mapping[str, Any]) -> str:
    grading_company = _text(item.get("grading_company"))
    grade = _text(item.get("grade"))
    if grading_company and grade:
        return f"{grading_company} {grade}"
    return _text(item.get("condition"))


def _is_sealed_product(item: Mapping[str, Any]) -> bool:
    return _text(item.get("product_type")) in {"SEALED", "COLLECTION"}


def product_title(item: Mapping[str, Any]) -> str:
    language = _language(item)
    if _is_sealed_product(item):
        return _trim(display_title(item.get("name"), language), PRODUCT_TITLE_MAX)
    parts = [
        display_title(item.get("name"), language),
        _text(item.get("card_number")),
        _text(item.get("set_name")),
        _text(item.get("variant")),
        _condition_label(item),
    ]
    return _trim(" · ".join(part for part in parts if part), PRODUCT_TITLE_MAX)


def product_description_html(item: Mapping[str, Any]) -> str:
    fields = [
        ("Game", _text(item.get("game"))),
        ("Set", _text(item.get("set_name"))),
        ("Card number", _text(item.get("card_number"))),
        ("Language", _language(item)),
        ("Condition", _condition_label(item)),
        ("Rarity", _text(item.get("rarity"))),
        ("Variant", _text(item.get("variant"))),
        ("Inventory ID", _text(item.get("inventory_code"))),
    ]
    rows = "".join(
        f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>"
        for label, value in fields
        if value
    )
    name = escape(_text(item.get("name")))
    if _is_sealed_product(item):
        return (
            f"<p><strong>{name}</strong> is an individually tracked sealed TCG product "
            "from Drop Rate inventory.</p>"
            f"<ul>{rows}</ul>"
            "<p>Product identity, language/region, seal status and price are controlled by "
            "the Drop Rate inventory system. Storefront media is governed by Drop Rate's "
            "item-specific media policy and must clear its publication checks.</p>"
        )
    reference_image_note = ""
    set_name = _text(item.get("set_name")).casefold()
    name_text = _text(item.get("name")).casefold()
    if "pre-release" in set_name:
        reference_image_note = (
            "<p><strong>Image note:</strong> The official reference image may show "
            "the base artwork. The physical item is the Pre-Release printing; "
            "event/pre-release markings may differ from the reference image.</p>"
        )
    elif (
        _text(item.get("game")).casefold() == "one piece"
        and (
            "release event" in set_name
            or "promotion cards" in set_name
            or "round 1 promo" in name_text
            or "treasure campaign pack" in name_text
            or "regional" in name_text
        )
    ):
        reference_image_note = (
            "<p><strong>Image note:</strong> An official card reference image may be "
            "shown for this promotional/event printing. The physical promotional "
            "printing or event markings may differ from the reference image.</p>"
        )
    return (
        f"<p><strong>{name}</strong> is an individually tracked physical trading card "
        "from Drop Rate inventory.</p>"
        f"<ul>{rows}</ul>"
        f"{reference_image_note}"
        "<p>Card identity, language, condition and price are controlled by the "
        "Drop Rate inventory system. Storefront media is governed by Drop Rate's "
        "item-specific media policy and must clear its publication checks.</p>"
    )


def seo_title(item: Mapping[str, Any]) -> str:
    language = _language(item)
    lang = language_code(language) or language
    parts = [
        _text(item.get("name")),
        _text(item.get("card_number")),
        _text(item.get("set_name")),
        lang,
        "Drop Rate",
    ]
    return _trim(" | ".join(part for part in parts if part), SEO_TITLE_MAX)


def seo_description(item: Mapping[str, Any]) -> str:
    condition = _condition_label(item)
    language = _language(item)
    bits = [
        _text(item.get("name")),
        _text(item.get("card_number")),
        f"from {_text(item.get('set_name'))}" if _text(item.get("set_name")) else "",
        condition,
        language,
    ]
    sentence = ", ".join(bit for bit in bits if bit)
    item_label = (
        "sealed TCG product"
        if _is_sealed_product(item)
        else "physical trading card"
    )
    return _trim(
        f"{sentence}. Individually tracked {item_label} from Drop Rate.",
        SEO_DESCRIPTION_MAX,
    )


def product_tags(item: Mapping[str, Any]) -> list[str]:
    brand = brand_for_game(_text(item.get("game")))
    language = _language(item)
    condition = _condition_label(item)
    grading_company = _text(item.get("grading_company"))
    grade = _text(item.get("grade"))
    sealed = _is_sealed_product(item)
    card_kind = (
        "Sealed Product"
        if sealed
        else "Graded Card"
        if grading_company and grade
        else "Raw Card"
    )
    values = [
        "Drop Rate",
        "TCG",
        "Trading Card" if not sealed else "",
        "Sealed Product" if sealed else "",
        brand,
        _text(item.get("game")),
        _text(item.get("set_name")),
        f"Language:{language}" if language else "",
        f"Condition:{condition}" if condition and not sealed else "",
        (
            f"Rarity:{_text(item.get('rarity'))}"
            if _text(item.get("rarity")) and not sealed
            else ""
        ),
        (
            f"Variant:{_text(item.get('variant'))}"
            if _text(item.get("variant")) and not sealed
            else ""
        ),
        f"Grader:{grading_company}" if grading_company else "",
        f"Grade:{grade}" if grade else "",
        card_kind,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _text(value)
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def product_metafields(item: Mapping[str, Any]) -> list[dict[str, str]]:
    sealed = _is_sealed_product(item)
    values = {
        "inventory_id": _text(item.get("inventory_code")),
        "catalogue_id": _text(item.get("catalogue_id")),
        "game": _text(item.get("game")),
        "set_name": _text(item.get("set_name")),
        "card_number": "" if sealed else _text(item.get("card_number")),
        "language": _language(item),
        "condition": "" if sealed else _text(item.get("condition")),
        "rarity": "" if sealed else _text(item.get("rarity")),
        "variant": "" if sealed else _text(item.get("variant")),
        "grading_company": "" if sealed else _text(item.get("grading_company")),
        "grade": "" if sealed else _text(item.get("grade")),
        "product_type": _text(item.get("product_type")),
        "seal_status": _text(item.get("seal_status")) if sealed else "",
    }
    return [
        {
            "namespace": "drop_rate",
            "key": key,
            "type": "single_line_text_field",
            "value": value,
        }
        for key, value in values.items()
        if value
    ]


def required_collection_titles(item: Mapping[str, Any]) -> list[str]:
    brand = _storefront_brand(item.get("game"))
    result = [SEALED_COLLECTION] if _is_sealed_product(item) else [BASE_COLLECTION]
    if brand:
        result.append(brand)
    return result


def shipping_profile_key(item: Mapping[str, Any]) -> str:
    product_type = _text(item.get("product_type"))
    if product_type == "CARD":
        if _text(item.get("grading_company")) and _text(item.get("grade")):
            return "GRADED_CARD"
        return "RAW_CARD"
    if product_type in {"SEALED", "COLLECTION"}:
        catalogue_key = _text(item.get("catalogue_id")).replace("-", "").upper()
        if (
            len(catalogue_key) == 32
            and all(char in "0123456789ABCDEF" for char in catalogue_key)
        ):
            # Sealed formats vary too widely for one generic weight. Keep the
            # shipping profile owner-scoped, but key it to the canonical product
            # so copies of the same exact sealed SKU share verified dimensions
            # and weight without leaking those values across unrelated products.
            return f"SEALED_{catalogue_key}"
        return "UNSUPPORTED_SEALED_PRODUCT_ID"
    return f"UNSUPPORTED_{product_type or 'PRODUCT'}"


def normalise_shipping_profile(
    profile: Mapping[str, Any] | None,
    *,
    expected_key: str,
) -> dict[str, Any] | None:
    if not isinstance(profile, Mapping):
        return None
    if not bool(profile.get("active")):
        return None
    key = _text(profile.get("profile_key"))
    if key != expected_key:
        return None
    try:
        weight_value = float(profile.get("weight_value"))
    except (TypeError, ValueError):
        return None
    weight_unit = _text(profile.get("weight_unit"))
    if weight_value <= 0 or weight_unit not in {
        "GRAMS", "KILOGRAMS", "OUNCES", "POUNDS"
    }:
        return None
    return {
        "profileKey": key,
        "label": _text(profile.get("label")),
        "weight": {
            "value": weight_value,
            "unit": weight_unit,
        },
        "shippingPackageId": _text(profile.get("shipping_package_gid")) or None,
    }


def media_policy(
    item: Mapping[str, Any],
    *,
    threshold_minor: int = DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
) -> str:
    return str(
        physical_photo_policy(item, threshold_minor=threshold_minor)["mediaPolicy"]
    )


def media_completeness(
    media_policy_name: str,
    assets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compatibility completeness helper with fail-closed rights-tier rules.

    Production Shopify resolution uses media_resolver.resolve_storefront_media
    because exact language/variant validation requires the inventory item.
    """

    ready_assets = [
        asset
        for asset in assets
        if _text(asset.get("approval_status")) == "APPROVED"
        and _text(asset.get("rights_status")) == "VERIFIED"
        and _text(asset.get("source_status") or "ACTIVE") == "ACTIVE"
        and not asset.get("revoked_at")
        and _text(asset.get("shopify_file_status")) == "READY"
        and _text(asset.get("media_kind") or "IMAGE") == "IMAGE"
        and _text(asset.get("shopify_file_gid"))
    ]

    blockers: list[str] = []
    if media_policy_name == "PHYSICAL_ITEM_REQUIRED":
        selected = [
            asset
            for asset in ready_assets
            if _text(asset.get("scope")) == "INVENTORY_ITEM"
            and _text(asset.get("rights_tier")) == FIRST_PARTY_CAPTURE
        ]
        sides = {_text(asset.get("side")) for asset in selected}
        if "FRONT" not in sides:
            blockers.append("approved first-party physical front image")
        if "BACK" not in sides:
            blockers.append("approved first-party physical back image")
        contexts = {
            _text(asset.get("capture_context"))
            for asset in selected
            if _text(asset.get("side")) in {"FRONT", "BACK"}
        }
        if "" in contexts or not contexts:
            blockers.append("capture context for physical-item media")
    else:
        first_party = [
            asset
            for asset in ready_assets
            if _text(asset.get("scope")) == "INVENTORY_ITEM"
            and _text(asset.get("rights_tier")) == FIRST_PARTY_CAPTURE
        ]
        canonical = [
            asset
            for asset in ready_assets
            if _text(asset.get("scope")) == "CANONICAL_CARD"
            and _text(asset.get("rights_tier")) == STOREFRONT_ALLOWED
        ]
        first_party_sides = {_text(asset.get("side")) for asset in first_party}
        if "FRONT" in first_party_sides:
            selected = first_party
        else:
            selected = canonical
            canonical_sides = {_text(asset.get("side")) for asset in canonical}
            if "FRONT" not in canonical_sides:
                blockers.append("exact storefront-allowed canonical front image")

    file_ids = [
        _text(asset.get("shopify_file_gid"))
        for asset in selected
        if _text(asset.get("shopify_file_gid"))
    ]
    return {
        "complete": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "approvedMediaCount": len(selected),
        "shopifyFileIds": list(dict.fromkeys(file_ids)),
        "mediaPolicy": media_policy_name,
    }


def verify_remote_product(
    plan: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    expected_price: str,
    expected_sku: str,
    expected_collection_titles: set[str],
    expected_media_file_ids: set[str],
    expected_quantity: int,
    expected_status: str,
    expected_shipping_spec: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []

    expected_template = _text(plan.get("template"))
    actual_template = _text(snapshot.get("templateSuffix")) or DEFAULT_THEME_TEMPLATE

    checks = {
        "title": (_text(snapshot.get("title")), _text(plan.get("title"))),
        "description": (
            _text(snapshot.get("descriptionHtml")),
            _text(plan.get("descriptionHtml")),
        ),
        "vendor": (_text(snapshot.get("vendor")), _text(plan.get("vendor"))),
        "product type": (
            _text(snapshot.get("productType")),
            _text(plan.get("productType")),
        ),
        "theme template": (actual_template, expected_template),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            blockers.append(f"remote {label}")

    category = snapshot.get("category")
    actual_category = (
        _text(category.get("id")) if isinstance(category, Mapping) else ""
    )
    if actual_category != _text(plan.get("category")):
        blockers.append("remote category")

    actual_tags = {_text(tag) for tag in snapshot.get("tags", []) if _text(tag)}
    expected_tags = {_text(tag) for tag in plan.get("tags", []) if _text(tag)}
    if actual_tags != expected_tags:
        blockers.append("remote tags")

    actual_seo = snapshot.get("seo")
    expected_seo = plan.get("seo")
    if not isinstance(actual_seo, Mapping) or not isinstance(expected_seo, Mapping):
        blockers.append("remote SEO")
    else:
        if _text(actual_seo.get("title")) != _text(expected_seo.get("title")):
            blockers.append("remote SEO title")
        if _text(actual_seo.get("description")) != _text(
            expected_seo.get("description")
        ):
            blockers.append("remote SEO description")

    metafields = snapshot.get("metafields")
    nodes = metafields.get("nodes") if isinstance(metafields, Mapping) else None
    actual_metafields = {
        _text(node.get("key")): _text(node.get("value"))
        for node in nodes or []
        if isinstance(node, Mapping)
    }
    expected_metafields = {
        _text(row.get("key")): _text(row.get("value"))
        for row in plan.get("metafields", [])
        if isinstance(row, Mapping)
    }
    for key, value in expected_metafields.items():
        if actual_metafields.get(key) != value:
            blockers.append(f"remote metafield: {key}")

    collections = snapshot.get("collections")
    collection_nodes = (
        collections.get("nodes") if isinstance(collections, Mapping) else None
    )
    actual_collections = {
        _text(node.get("title"))
        for node in collection_nodes or []
        if isinstance(node, Mapping) and _text(node.get("title"))
    }
    if not expected_collection_titles.issubset(actual_collections):
        blockers.append("remote collections")

    variants = snapshot.get("variants")
    variant_nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if (
        not isinstance(variant_nodes, list)
        or len(variant_nodes) != 1
        or not isinstance(variant_nodes[0], Mapping)
    ):
        blockers.append("remote single variant")
    else:
        variant = variant_nodes[0]
        if _text(variant.get("price")) != expected_price:
            blockers.append("remote price")
        if _text(variant.get("inventoryPolicy")) != "DENY":
            blockers.append("remote oversell protection")
        try:
            inventory_quantity = int(variant.get("inventoryQuantity"))
        except (TypeError, ValueError):
            inventory_quantity = -1
        if inventory_quantity != expected_quantity:
            blockers.append("remote inventory quantity")
        inventory_item = variant.get("inventoryItem")
        if not isinstance(inventory_item, Mapping):
            blockers.append("remote inventory item")
        else:
            if _text(inventory_item.get("sku")) != expected_sku:
                blockers.append("remote SKU")
            if inventory_item.get("tracked") is not True:
                blockers.append("remote inventory tracking")
            if inventory_item.get("requiresShipping") is not True:
                blockers.append("remote shipping requirement")

            measurement = inventory_item.get("measurement")
            weight = (
                measurement.get("weight")
                if isinstance(measurement, Mapping)
                else None
            )
            expected_weight = expected_shipping_spec.get("weight")
            if not isinstance(weight, Mapping) or not isinstance(
                expected_weight, Mapping
            ):
                blockers.append("remote shipping weight")
            else:
                try:
                    actual_weight_value = float(weight.get("value"))
                    expected_weight_value = float(expected_weight.get("value"))
                except (TypeError, ValueError):
                    blockers.append("remote shipping weight")
                else:
                    if abs(actual_weight_value - expected_weight_value) > 0.000001:
                        blockers.append("remote shipping weight")
                if _text(weight.get("unit")) != _text(expected_weight.get("unit")):
                    blockers.append("remote shipping weight unit")

    media = snapshot.get("media")
    media_nodes = media.get("nodes") if isinstance(media, Mapping) else None
    actual_media_ids = {
        _text(node.get("id"))
        for node in media_nodes or []
        if isinstance(node, Mapping) and _text(node.get("id"))
    }
    if not expected_media_file_ids.issubset(actual_media_ids):
        blockers.append("remote media")

    if _text(snapshot.get("status")) != expected_status:
        blockers.append(f"remote status: {expected_status}")

    unique = list(dict.fromkeys(blockers))
    return {"complete": not unique, "blockers": unique}


def build_shopify_product_plan(
    item: Mapping[str, Any],
    *,
    physical_photo_threshold_minor: int = DEFAULT_PHYSICAL_PHOTO_THRESHOLD_MINOR,
) -> dict[str, Any]:
    product_type = _text(item.get("product_type"))
    sealed = _is_sealed_product(item)
    category_id = CARD_CATEGORY_GID if product_type == "CARD" or sealed else None
    vendor = _storefront_brand(item.get("game"))
    return {
        "title": product_title(item),
        "descriptionHtml": product_description_html(item),
        "category": category_id,
        "categoryName": CARD_CATEGORY_NAME if category_id else None,
        "vendor": vendor,
        "productType": (
            "Trading Card"
            if product_type == "CARD"
            else SEALED_PRODUCT_TYPE
            if sealed
            else product_type
        ),
        "tags": product_tags(item),
        "seo": {
            "title": seo_title(item),
            "description": seo_description(item),
        },
        "template": DEFAULT_THEME_TEMPLATE,
        "requiredCollections": required_collection_titles(item),
        "metafields": product_metafields(item),
        "mediaPolicy": media_policy(
            item,
            threshold_minor=physical_photo_threshold_minor,
        ),
        "shippingProfileKey": shipping_profile_key(item),
        "requiresShipping": True,
        "inventoryTracked": True,
        "inventoryPolicy": "DENY",
        "statusBeforePublish": "DRAFT",
        "statusAfterPublish": "ACTIVE",
    }


def product_create_input(plan: Mapping[str, Any], *, handle: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": plan["title"],
        "descriptionHtml": plan["descriptionHtml"],
        "handle": handle,
        "status": plan["statusBeforePublish"],
        "vendor": plan["vendor"],
        "productType": plan["productType"],
        "tags": plan["tags"],
        "seo": plan["seo"],
        "metafields": plan["metafields"],
    }
    if plan.get("category"):
        payload["category"] = plan["category"]
    # Shopify's default product template is represented by no templateSuffix.
    # The plan still records "default" so completeness is explicit/auditable.
    return payload


def product_completeness(
    plan: Mapping[str, Any],
    *,
    store_price_minor: int | None,
    inventory_code: str | None,
    approved_media_count: int,
    existing_collection_titles: set[str],
    publication_configured: bool,
    location_configured: bool,
    shipping_profile: Mapping[str, Any] | None,
    media_blockers: list[str] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []

    required_text = {
        "title": plan.get("title"),
        "description": plan.get("descriptionHtml"),
        "category": plan.get("category"),
        "vendor": plan.get("vendor"),
        "product type": plan.get("productType"),
        "SEO title": (plan.get("seo") or {}).get("title"),
        "SEO description": (plan.get("seo") or {}).get("description"),
        "theme template": plan.get("template"),
    }
    for label, value in required_text.items():
        if not _text(value):
            blockers.append(label)

    if store_price_minor is None or store_price_minor < 0:
        blockers.append("price")
    if not _text(inventory_code):
        blockers.append("SKU / Inventory ID")
    if not plan.get("inventoryTracked"):
        blockers.append("inventory tracking")
    if not plan.get("requiresShipping"):
        blockers.append("shipping requirement")

    shipping_key = _text(plan.get("shippingProfileKey"))
    shipping_spec = normalise_shipping_profile(
        shipping_profile,
        expected_key=shipping_key,
    )
    if shipping_key.startswith("UNSUPPORTED_"):
        blockers.append(f"supported shipping profile mapping: {shipping_key}")
    elif shipping_spec is None:
        blockers.append(f"shipping profile: {shipping_key}")
    if plan.get("inventoryPolicy") != "DENY":
        blockers.append("oversell protection")
    if not plan.get("metafields"):
        blockers.append("product metafields")
    if not plan.get("tags"):
        blockers.append("tags")

    required_collections = {
        _text(value) for value in plan.get("requiredCollections", []) if _text(value)
    }
    missing_collections = sorted(required_collections - existing_collection_titles)
    if missing_collections:
        blockers.extend(f"collection: {name}" for name in missing_collections)

    if media_blockers:
        blockers.extend(media_blockers)
    elif approved_media_count <= 0:
        blockers.append("approved media")
    if not publication_configured:
        blockers.append("Shopify publication")
    if not location_configured:
        blockers.append("Shopify inventory location")

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "complete": not unique_blockers,
        "blockers": unique_blockers,
        "requiredCollections": sorted(required_collections),
        "missingCollections": missing_collections,
        "approvedMediaCount": approved_media_count,
        "mediaPolicy": plan.get("mediaPolicy"),
        "shippingProfileKey": shipping_key,
        "shippingSpec": shipping_spec,
    }
