"""Publisher-artwork evidence for same-name One Piece printing collisions.

The official checklist identifies printings with ``_pN`` IDs. Marketplace
catalogues identify them with different product IDs and occasionally V.N
labels. Neither numeric order nor price is evidence that the artworks agree.
This module accepts a printing crosswalk only when *both* sides provide a
complete release-specific set of images with a reciprocal, unique match.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from .one_piece_market import normalized, release_identity
from .recognition_images import hash_similarity


MIN_ARTWORK_SIMILARITY = 0.93
MIN_ARTWORK_MARGIN = 0.09
MAX_PRINTINGS_PER_GROUP = 5
ALTERNATE_SUBTYPES = {
    "alternateart", "altart", "parallel", "special", "sp", "manga",
    "superparallel", "foil", "holofoil", "textured",
}
RARITY_ALIASES = {
    "l": "leader", "c": "common", "uc": "uncommon", "r": "rare",
    "sr": "superrare", "sec": "secretrare", "sp": "special",
}


def is_exact_release_slug(slug: str, release: tuple[str, str]) -> bool:
    """Accept Cardmarket's official release title or Bandai's exact set code.

    No prefix/fuzzy matching: OP16, OP17 and language-specific releases must
    remain distinct even if the printed card number or name is similar.
    """
    return normalized(slug) in {release[0], normalized(release[1])}


def normalized_rarity(value) -> str:
    name = normalized(value)
    return RARITY_ALIASES.get(name, name)
PRINTED_TITLE = re.compile(
    r"^(.+) \(((?:OP|EB|PRB)\d{2}-\d{3})\)(?: \(V\.([1-9]\d*)\))?$", re.I
)


@dataclass(frozen=True)
class ArtworkLink:
    reference_id: str
    source_id: str
    similarity: float
    margin: float


def official_groups(references: list[dict], code_for_reference) -> dict[tuple[str, str], list[dict]]:
    """Accept only complete, independently publisher-identified English art.

    The caller provides its existing strict release-code resolver, because a
    printed number or an arbitrary set title alone is insufficient identity.
    """
    candidates = defaultdict(list)
    raw_group_ids = defaultdict(set)
    for ref in references:
        if (ref.get("provider") != "Bandai Official" or ref.get("language") != "English"
                or ref.get("system_code") != "ONE_PIECE_CARD_GAME"):
            continue
        number = str(ref.get("card_number") or "")
        printing = str(ref.get("provider_id") or "")
        if not re.fullmatch(r"(?:OP|EB|PRB)\d{2}-\d{3}", number):
            continue
        code = code_for_reference({**ref, "provider_id": number})
        if not code:
            continue
        group = (code, number)
        raw_group_ids[group].add((str(ref.get("set_id")), printing))
        if not (printing == number or re.fullmatch(re.escape(number) + r"_p[1-9]\d*", printing)):
            continue
        evidence = ref.get("evidence") or {}
        if (not isinstance(evidence, dict)
                or evidence.get("detail_level") != "OFFICIAL_CHECKLIST"
                or evidence.get("printing_id") != printing):
            continue
        image_url = str(ref.get("image_url") or "")
        try:
            uri = urlsplit(image_url)
        except ValueError:
            continue
        if (uri.scheme != "https" or uri.hostname != "en.onepiece-cardgame.com"
                or not uri.path.endswith("/" + printing + ".png")):
            continue
        candidates[group].append(ref)

    result = {}
    for key, refs in candidates.items():
        if not (2 <= len(refs) <= MAX_PRINTINGS_PER_GROUP):
            continue
        number = key[1]
        if not any(r["provider_id"] == number for r in refs):
            continue
        if (len(raw_group_ids[key]) != len(refs)
                or len({r["provider_id"] for r in refs}) != len(refs)
                or len({r["image_url"] for r in refs}) != len(refs)
                or len({r["set_id"] for r in refs}) != 1
                or len({normalized(r["set_name"]) for r in refs}) != 1
                or len({normalized(html.unescape(r["name"])) for r in refs}) != 1
                or len({normalized(r.get("rarity")) for r in refs}) != 1
                or len({normalized(r.get("finish")) for r in refs}) != 1):
            continue
        result[key] = sorted(refs, key=lambda row: row["provider_id"])
    return result


def source_products_for_group(products: list[dict], refs: list[dict]) -> list[dict]:
    """Keep only unambiguously labelled products in the *same* release.

    Reject the entire group when a source item is unlabelled, duplicated,
    regionally different, or does not name the printed Bandai card number.
    Do not use a product's price as a match signal.
    """
    number = refs[0]["card_number"]
    expected_name = normalized(html.unescape(refs[0]["name"]))
    expected_release = release_identity(refs[0]["set_name"])
    if expected_release is None:
        return []
    expected_rarity = normalized_rarity(refs[0].get("rarity"))
    rows = [p for p in products if isinstance(p, dict) and p.get("card_number") == number
            and p.get("product_type", "card") == "card"]
    if len(rows) != len(refs) or len({p.get("id") for p in rows}) != len(rows):
        return []
    editions, versions, slugs = [], set(), set()
    for product in rows:
        if normalized_rarity(product.get("rarity")) != expected_rarity:
            return []
        ident = str(product.get("id") or "")
        if not re.fullmatch(r"op_[a-zA-Z0-9]{6,128}", ident):
            return []
        market = product.get("cardmarket")
        if not isinstance(market, dict):
            return []
        title = PRINTED_TITLE.fullmatch(html.unescape(str(market.get("product_name") or "")))
        if not title or title[2].upper() != number or normalized(title[1]) != expected_name:
            return []
        try:
            uri = urlsplit(str(market.get("product_url") or ""))
        except ValueError:
            return []
        path = uri.path.split("/")
        if (uri.scheme != "https" or uri.hostname not in {"www.cardmarket.com", "cardmarket.com"}
                or uri.query or uri.fragment or len(path) != 7
                or path[1] not in {"en", "de", "it", "fr", "es", "pt"}
                or path[2:5] != ["OnePiece", "Products", "Singles"]
                or path[5].casefold().endswith(("-japanese", "-non-english"))
                or not is_exact_release_slug(path[5], expected_release)):
            return []
        card_slug = re.fullmatch(r".+-" + re.escape(number) + r"(?:-V([1-9]\d*))?", path[6], re.I)
        if not card_slug or card_slug[1] != title[3]:
            return []
        version = int(card_slug[1]) if card_slug[1] else 1
        subtype = normalized(product.get("sub_type_name"))
        if (version in versions or (version == 1 and subtype != "normal")
                or (version != 1 and subtype not in ALTERNATE_SUBTYPES)):
            return []
        versions.add(version)
        slugs.add(path[5].casefold())
        editions.append(product)
    if len(slugs) != 1 or versions != set(range(1, len(refs) + 1)):
        return []
    return editions


def image_proven_source_candidates(
    products: list[dict], refs: list[dict], diagnostic: dict | None=None,
) -> list[dict]:
    """Allow *unlabelled* editions into image verification, never into pricing.

    A strict V1/V2 crosswalk is preferable, but not necessary when every
    competing source image will be compared to the publisher's exact printing.
    The whole source number group, including extra printings, must fit the
    bounded image budget. We never choose a product by price or ID order.
    """
    def reject(reason):
        if diagnostic is not None:
            diagnostic[reason] = diagnostic.get(reason, 0) + 1
        return []

    if not refs:
        return reject("artwork_candidates_no_publisher_reference")
    number = refs[0]["card_number"]
    expected_name = normalized(html.unescape(refs[0]["name"]))
    release = release_identity(refs[0]["set_name"])
    if release is None:
        return reject("artwork_candidates_unknown_release")
    expected_rarity = normalized_rarity(refs[0].get("rarity"))
    rows = [p for p in products if isinstance(p, dict) and p.get("card_number") == number]
    if not (len(refs) <= len(rows) <= MAX_PRINTINGS_PER_GROUP):
        return reject("artwork_candidates_incomplete_or_oversized")
    ids = [str(p.get("id") or "") for p in rows]
    if len(set(ids)) != len(ids) or not all(re.fullmatch(r"op_[A-Za-z0-9]{6,128}", value) for value in ids):
        return reject("artwork_candidates_invalid_ids")
    for product in rows:
        if (product.get("product_type", "card") != "card" or
                normalized_rarity(product.get("rarity")) != expected_rarity):
            return reject("artwork_candidates_incompatible_kind_or_rarity")
        market = product.get("cardmarket")
        if not isinstance(market, dict):
            return reject("artwork_candidates_no_market_product")
        title = PRINTED_TITLE.fullmatch(html.unescape(str(market.get("product_name") or "")))
        if not title or title[2].upper() != number or normalized(title[1]) != expected_name:
            return reject("artwork_candidates_title_mismatch")
        try:
            uri = urlsplit(str(market.get("product_url") or ""))
        except ValueError:
            return reject("artwork_candidates_url_invalid")
        path = uri.path.split("/")
        if (uri.scheme != "https" or uri.hostname not in {"www.cardmarket.com", "cardmarket.com"}
                or uri.query or uri.fragment or len(path) != 7
                or path[1] not in {"en", "de", "it", "fr", "es", "pt"}
                or path[2:5] != ["OnePiece", "Products", "Singles"]
                or path[5].casefold().endswith(("-japanese", "-non-english"))
                or not is_exact_release_slug(path[5], release)):
            return reject("artwork_candidates_release_mismatch")
        slug = re.fullmatch(r".+-" + re.escape(number) + r"(?:-V([1-9]\d*))?", path[6], re.I)
        if not slug or (title[3] and slug[1] and title[3] != slug[1]):
            return reject("artwork_candidates_printed_number_mismatch")
    return rows


def match_image_fingerprints(
    references: list[dict], products: list[dict],
    official_hashes: dict[str, tuple[int, ...]],
    source_hashes: dict[str, tuple[int, ...]],
) -> list[ArtworkLink]:
    """Require a reciprocal one-to-one match with an independent margin.

    The strongest cross-print image score, not visual similarity in isolation,
    decides. A publisher pair or source pair with near-identical images is
    ambiguous and must remain unpriced.
    """
    if not (2 <= len(references) <= len(products) <= MAX_PRINTINGS_PER_GROUP):
        return []
    ref_ids = [r["provider_id"] for r in references]
    source_ids = [p["id"] for p in products]
    if any(not official_hashes.get(key) for key in ref_ids):
        return []
    if any(not source_hashes.get(key) for key in source_ids):
        return []
    if any(hash_similarity(official_hashes[a], official_hashes[b]) >= MIN_ARTWORK_SIMILARITY
           for i, a in enumerate(ref_ids) for b in ref_ids[i + 1:]):
        return []
    if any(hash_similarity(source_hashes[a], source_hashes[b]) >= MIN_ARTWORK_SIMILARITY
           for i, a in enumerate(source_ids) for b in source_ids[i + 1:]):
        return []
    scores = {
        (ref_id, source_id): hash_similarity(official_hashes[ref_id], source_hashes[source_id]) or 0.0
        for ref_id in ref_ids for source_id in source_ids
    }
    result = []
    for ref_id in ref_ids:
        ranked = sorted(((scores[ref_id, source_id], source_id) for source_id in source_ids), reverse=True)
        score, source_id = ranked[0]
        margin = round(score - ranked[1][0], 5)
        reverse = sorted((scores[other_id, source_id] for other_id in ref_ids), reverse=True)
        if (score < MIN_ARTWORK_SIMILARITY or margin < MIN_ARTWORK_MARGIN
                or reverse[0] != score or reverse[0] - reverse[1] < MIN_ARTWORK_MARGIN):
            return []
        result.append(ArtworkLink(ref_id, source_id, score, margin))
    if len({match.source_id for match in result}) != len(result):
        return []
    return result
