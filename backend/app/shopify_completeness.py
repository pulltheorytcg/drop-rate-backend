from __future__ import annotations

from html import escape
from typing import Any, Mapping

from .brands import brand_for_game
from .language import clean_language, display_title, language_code


CARD_CATEGORY_GID = "gid://shopify/TaxonomyCategory/ae-2-2-3-3"
CARD_CATEGORY_NAME = "Non-Sports Trading Cards"
DEFAULT_THEME_TEMPLATE = "default"
BASE_COLLECTION = "Trading Cards"
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


def product_title(item: Mapping[str, Any]) -> str:
    language = _language(item)
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
    return (
        f"<p><strong>{name}</strong> is an individually tracked physical trading card "
        "from Drop Rate inventory.</p>"
        f"<ul>{rows}</ul>"
        "<p>Card identity, language, condition and price are controlled by the "
        "Drop Rate inventory system. Images may be representative unless the listing "
        "explicitly states that item-specific photographs are shown.</p>"
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
    return _trim(
        f"{sentence}. Individually tracked physical trading card from Drop Rate.",
        SEO_DESCRIPTION_MAX,
    )


def product_tags(item: Mapping[str, Any]) -> list[str]:
    brand = brand_for_game(_text(item.get("game")))
    language = _language(item)
    condition = _condition_label(item)
    grading_company = _text(item.get("grading_company"))
    grade = _text(item.get("grade"))
    values = [
        "Drop Rate",
        "TCG",
        "Trading Card",
        brand,
        _text(item.get("game")),
        _text(item.get("set_name")),
        f"Language:{language}" if language else "",
        f"Condition:{condition}" if condition else "",
        f"Rarity:{_text(item.get('rarity'))}" if _text(item.get("rarity")) else "",
        f"Variant:{_text(item.get('variant'))}" if _text(item.get("variant")) else "",
        f"Grader:{grading_company}" if grading_company else "",
        f"Grade:{grade}" if grade else "",
        "Graded Card" if grading_company and grade else "Raw Card",
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
    values = {
        "inventory_id": _text(item.get("inventory_code")),
        "game": _text(item.get("game")),
        "set_name": _text(item.get("set_name")),
        "card_number": _text(item.get("card_number")),
        "language": _language(item),
        "condition": _text(item.get("condition")),
        "rarity": _text(item.get("rarity")),
        "variant": _text(item.get("variant")),
        "grading_company": _text(item.get("grading_company")),
        "grade": _text(item.get("grade")),
        "product_type": _text(item.get("product_type")),
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
    result = [BASE_COLLECTION]
    if brand:
        result.append(brand)
    return result


def media_policy(item: Mapping[str, Any]) -> str:
    if _text(item.get("grading_company")) and _text(item.get("grade")):
        return "PHYSICAL_ITEM_REQUIRED"
    return "CANONICAL_CARD_ALLOWED"


def build_shopify_product_plan(item: Mapping[str, Any]) -> dict[str, Any]:
    product_type = _text(item.get("product_type"))
    category_id = CARD_CATEGORY_GID if product_type == "CARD" else None
    vendor = _storefront_brand(item.get("game"))
    return {
        "title": product_title(item),
        "descriptionHtml": product_description_html(item),
        "category": category_id,
        "categoryName": CARD_CATEGORY_NAME if category_id else None,
        "vendor": vendor,
        "productType": "Trading Card" if product_type == "CARD" else product_type,
        "tags": product_tags(item),
        "seo": {
            "title": seo_title(item),
            "description": seo_description(item),
        },
        "template": DEFAULT_THEME_TEMPLATE,
        "requiredCollections": required_collection_titles(item),
        "metafields": product_metafields(item),
        "mediaPolicy": media_policy(item),
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
    media_readiness: Mapping[str, Any],
    existing_collection_titles: set[str],
    publication_configured: bool,
    location_configured: bool,
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

    if not media_readiness.get("complete"):
        blockers.extend(
            str(blocker)
            for blocker in media_readiness.get("blockers", ["approved media"])
        )
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
        "approvedMediaCount": int(media_readiness.get("approvedMediaCount") or 0),
        "mediaPolicy": plan.get("mediaPolicy"),
        "mediaReadiness": dict(media_readiness),
    }
