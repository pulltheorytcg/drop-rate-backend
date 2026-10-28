"""Pure, conservative estimates from explicitly comparable current UK listings.

No network/database calls. Inputs are canonical catalogue references and eBay
Browse item summaries. Results are asking-price estimates, never sold values.
The caller supplies the actual acquisition timestamp; timestamps are not renewed
when an existing report is evaluated again.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
from typing import Any


SOURCE = "EBAY_OFFICIAL_BROWSE"
METHOD_VERSION = "EBAY_UK_RAW_ASK_V1"
TTL = timedelta(days=3)
FINISH_LABELS = ("Normal", "Holo", "Reverse Holo", "Foil", "Parallel", "Alt Art", "Manga")
_FINISH_LABEL = dict(zip(("normal", "holo", "reverse", "foil", "parallel", "alt art", "manga"), FINISH_LABELS))
_GAMES = {
    "POKEMON_TCG": ("pokemon",),
    "ONE_PIECE_CARD_GAME": ("one piece",),
    "DRAGON_BALL_SUPER_FUSION_WORLD": ("fusion world",),
    "DRAGON_BALL_SUPER_MASTERS": ("dragon ball super masters", "dbs masters"),
    "NARUTO_BANDAI_LEGACY": ("naruto bandai",),
    "NARUTO_KAYOU": ("naruto kayou",),
}
_LANGUAGES = {
    "english": ("english", "eng", "en"),
    "japanese": ("japanese", "jpn", "jp"),
    "chinese": ("chinese", "simplified chinese", "traditional chinese", "cn"),
    "korean": ("korean", "kr"),
    "french": ("french", "francais", "fr"),
    "german": ("german", "deutsch", "de"),
    "italian": ("italian", "italiano", "it"),
    "spanish": ("spanish", "espanol", "es"),
    "portuguese": ("portuguese", "pt"),
}
_FINISHES = {
    "normal": "normal", "regular": "normal", "non holo": "normal",
    "non holofoil": "normal", "non foil": "normal", "nonholo": "normal",
    "holo": "holo", "holofoil": "holo", "holographic": "holo",
    "reverse": "reverse", "reverse holo": "reverse", "reverse holofoil": "reverse",
    "reverse foil": "reverse", "foil": "foil", "parallel": "parallel",
    "alt art": "alt art", "alternate art": "alt art", "manga": "manga",
}
_SPECIAL_MARKERS = {
    "alt art": ("alt art", "alternate art", "alternative art", "aa"),
    "parallel": ("parallel",), "manga": ("manga",),
    "first edition": ("first edition", "1st edition"),
    "shadowless": ("shadowless",), "stamped": ("stamped", "stamp"),
    "reprint": ("reprint",), "promo": ("promo", "promotion"),
    "full art": ("full art",), "special art": ("special art",),
    "master ball": ("master ball", "masterball"),
    "poke ball": ("poke ball", "pokeball"),
    "ex": ("ex",), "gx": ("gx",), "v": ("v",), "vmax": ("vmax",),
    "vstar": ("vstar",), "radiant": ("radiant",), "shining": ("shining",),
    "mega": ("mega",), "shiny": ("shiny",), "tera": ("tera",),
}
_GRADE_RE = re.compile(r"\b(?:psa|bgs|cgc|sgc|beckett|ars|ksa|mnt|ags|hga|gma|pgx|pca)(?:\s*\d+(?:\.\d+)?)?\b|\b(?:graded|slab(?:bed)?|grading)\b|\b(?:tag|ace|grade|gem\s+mint|pristine)\s*(?:\d+(?:\.\d+)?|grading)\b", re.I)
_MULTI_RE = re.compile(r"\b(?:bundle|bundles|lot|lots|playset|pair|replica|proxy|proxies|custom|fake|reproduction|digital|oversized|jumbo|pick|choose|mystery)\b|\b(?:x\s*(?:[2-9]|[1-9]\d+)|(?:[2-9]|[1-9]\d+)\s*x|(?:[2-9]|[1-9]\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:cards?|copies)|set\s+of\s+(?:[2-9]|[1-9]\d+|two|three|four))\b", re.I)
_CARD_CODES = re.compile(r"(?<![A-Z0-9])(?:OP|ST|EB|PRB|FB|FS|BT|EX|TB|SD|DB|P|E|SB)\d{0,3}\s*-\s*\d{1,4}(?![A-Z0-9])", re.I)
_SET_CODES = re.compile(r"\b(?:OP|ST|EB|PRB|FB|FS|BT|EX|TB|SD|DB|SB)\d{1,3}\b", re.I)
_FRACTIONS = re.compile(r"(?<![A-Z0-9])(?:[A-Z]{0,3}\d{1,4})\s*/\s*(?:[A-Z]{0,3}\d{1,4})(?![A-Z0-9])", re.I)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def _phrase(text: str, term: object) -> bool:
    needle = _text(term)
    return bool(needle and f" {needle} " in f" {text} ")


def _game_words(text: str, alias: str) -> bool:
    return set(_text(alias).split()).issubset(text.split())


def _terms(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and _text(v) for v in value):
        return ()
    return tuple(value)


def _aspects(row: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("localizedAspects", "localizedItemAspects"):
        values = row.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, Mapping) and isinstance(value.get("value"), str):
                    name = _text(value.get("name"))
                    result[name] = " ".join(filter(None, (result.get(name), _text(value["value"]))))
    return result


def _variant_markers(text: str) -> set[str]:
    return {marker for marker, aliases in _SPECIAL_MARKERS.items() if any(_phrase(text, alias) for alias in aliases)}


def _reference_spec(reference: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    required = ("provider", "system_code", "language", "provider_id", "set_id", "name", "card_number")
    if any(not isinstance(reference.get(k), str) or not reference[k].strip() for k in required):
        return None, "MISSING_CANONICAL_IDENTITY"
    game = reference["system_code"]
    language = _text(reference["language"])
    if game not in _GAMES or language not in _LANGUAGES:
        return None, "UNSUPPORTED_GAME_OR_LANGUAGE"
    evidence = reference.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    finish_text = _text(reference.get("finish"))
    finish = _FINISHES.get(finish_text)
    if finish_text and finish is None:
        return None, "UNSUPPORTED_FINISH"
    proof = _terms(evidence.get("variant_title_terms"))
    group_count = reference.get("reference_group_count", 1)
    if isinstance(group_count, bool) or not isinstance(group_count, int) or group_count < 1:
        return None, "INVALID_VARIANT_GROUP"
    ambiguous = reference.get("ambiguous_variant") is True or group_count > 1
    provider_variant = _text(str(evidence.get("provider_variant") or "") + " " + reference["provider_id"])
    if (ambiguous or re.search(r"(?:^|\s)p\d+(?:$|\s)", provider_variant)) and not proof:
        return None, "UNRESOLVED_PARALLEL_IDENTITY"
    set_name = reference.get("set_name") or evidence.get("set_name")
    set_terms = _terms(evidence.get("set_title_terms"))
    if not set_terms and isinstance(set_name, str) and _text(set_name):
        set_terms = (set_name,)
    # Printed set codes can prove set membership; provider-internal numeric IDs cannot.
    if not set_terms and "-" in reference["card_number"]:
        prefix = reference["card_number"].split("-", 1)[0]
        if _text(prefix) == _text(reference["set_id"]):
            set_terms = (prefix,)
    if not set_terms:
        return None, "MISSING_SET_IDENTITY"
    canonical_text = _text(" ".join(str(reference.get(k) or "") for k in ("name", "finish", "rarity")))
    markers = _variant_markers(canonical_text + " " + _text(set_name))
    markers |= _variant_markers(_text(" ".join(proof)))
    return {"game": game, "language": language, "finish": finish, "set_terms": set_terms,
            "variant_terms": proof, "markers": markers}, None


def reference_asking_eligibility(reference: Mapping[str, Any]) -> str | None:
    """Return a stable rejection reason, or None if acquisition may be useful.

    ``evidence.variant_title_terms`` must be an independently verified exact
    print discriminator. The caller must provide ``reference_group_count`` or
    ``ambiguous_variant`` from the complete catalogue, not a filtered page.
    """
    return _reference_spec(reference)[1]


def _money(value: object, *, zero_allowed: bool = False) -> int | None:
    if not isinstance(value, Mapping) or value.get("currency") != "GBP":
        return None
    raw = value.get("value")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        amount = Decimal(str(raw))
        if not amount.is_finite() or amount < 0 or (amount == 0 and not zero_allowed):
            return None
        # GBP costs finer than a penny are ambiguous; never silently round inputs.
        pennies = amount * 100
        if pennies != pennies.to_integral_value() or pennies > 100_000_000:
            return None
        return int(pennies)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def _shipping(row: Mapping[str, Any]) -> int | None:
    options = row.get("shippingOptions")
    if not isinstance(options, list) or not options:
        return None
    amounts = []
    for option in options:
        if not isinstance(option, Mapping):
            return None
        amount = _money(option.get("shippingCost"), zero_allowed=True)
        if amount is None:
            return None
        amounts.append(amount)
    return min(amounts)


def _number_matches(title: str, aspect: str, expected: str) -> bool:
    compact = lambda v: re.sub(r"\s+", "", v).casefold()
    canonical = compact(expected)
    seen = {compact(m.group()) for pattern in (_CARD_CODES, _FRACTIONS) for m in pattern.finditer(title)}
    if any(number != canonical and not ("/" not in canonical and number.split("/", 1)[0] == canonical) for number in seen):
        return False
    if aspect and _text(aspect) != _text(expected):
        return False
    pattern = re.escape(expected).replace(r"\ ", r"\s*")
    return bool(aspect or re.search(r"(?<![\w])" + pattern + r"(?![\w])", title, re.I))


def _condition_matches(text: str) -> bool:
    # Ordinary raw terminology is allowed, including 'ungraded'. Restrict the
    # price cohort to NM/Mint; mixing played/damaged cards corrupts the median.
    if any(_phrase(text, term) for term in ("played", "lightly played", "moderately played", "heavily played", "damaged", "poor", "good", "excellent", "fair", "lp", "mp", "hp", "dmg")):
        return False
    return any(_phrase(text, term) for term in ("near mint", "nm", "mint"))


def _listing_finish(row: Mapping[str, Any], spec: Mapping[str, Any]) -> str | None:
    aspects = _aspects(row)
    finish_text = " ".join((_text(row.get("title")), aspects.get("finish", "")))
    normal = any(_phrase(finish_text, term) for term in ("normal", "regular", "non holo", "nonholo", "non foil", "nonfoil"))
    reverse = _phrase(finish_text, "reverse")
    positive = re.sub(r"\bnon\s*(?:holofoil|holo|foil)\b", "", finish_text)
    holo = any(_phrase(positive, term) for term in ("holo", "holofoil", "holographic"))
    foil = _phrase(positive, "foil")
    if normal and (reverse or holo or foil):
        return None
    # A special canonical print still requires its explicit markers above.
    expected = spec["finish"]
    if expected in {"parallel", "alt art", "manga"}:
        return expected if expected in spec["markers"] else None
    if reverse:
        found = "reverse" if (holo or foil) else None
    elif normal:
        found = "normal"
    elif holo:
        found = "holo"
    elif foil:
        found = "foil"
    else:
        found = None
    return found if expected is None or found == expected else None


def _matches(row: Mapping[str, Any], reference: Mapping[str, Any], spec: Mapping[str, Any]) -> str | None:
    raw_title = row.get("title")
    title = _text(raw_title)
    if not title:
        return "MISSING_TITLE"
    aspects = _aspects(row)
    all_text = " ".join((title, _text(row.get("condition")), " ".join(aspects.values())))
    grade_text = re.sub(r"\bnot(?:\s+professionally)?\s+graded\b", "", all_text)
    if _GRADE_RE.search(grade_text) or str(row.get("conditionId")) == "2750":
        return "GRADED_OR_SLAB"
    if any(aspects.get(k) not in (None, "", "no", "ungraded", "not graded") for k in ("professional grader", "grade", "certification number")):
        return "GRADED_OR_SLAB"
    if _MULTI_RE.search(all_text):
        return "MULTI_ITEM_OR_NON_PHYSICAL"
    game_text = " ".join((title, aspects.get("game", "")))
    if not any(_game_words(game_text, alias) for alias in _GAMES[spec["game"]]):
        return "GAME_MISMATCH"
    if any(any(_game_words(game_text, alias) for alias in aliases) for game, aliases in _GAMES.items() if game != spec["game"]):
        return "GAME_MISMATCH"
    if spec["game"] == "DRAGON_BALL_SUPER_MASTERS" and _phrase(game_text, "fusion world"):
        return "GAME_MISMATCH"
    if spec["game"] == "DRAGON_BALL_SUPER_FUSION_WORLD" and _phrase(game_text, "masters"):
        return "GAME_MISMATCH"
    # Do not infer English from a UK seller or from the absence of Japanese.
    language_text = " ".join((title, aspects.get("language", "")))
    found_languages = {lang for lang, aliases in _LANGUAGES.items() if any(_phrase(language_text, alias) for alias in aliases)}
    if found_languages != {spec["language"]}:
        return "LANGUAGE_MISMATCH_OR_UNKNOWN"
    if not all(token in title.split() for token in _text(reference["name"]).split()):
        return "NAME_MISMATCH"
    if not _number_matches(str(raw_title), aspects.get("card number", ""), reference["card_number"]):
        return "CARD_NUMBER_MISMATCH"
    set_text = " ".join((title, aspects.get("set", "")))
    if not all(_phrase(set_text, term) for term in spec["set_terms"]):
        return "SET_MISMATCH"
    # Known prefix collisions cannot be established by substring containment.
    for base, expanded in (("base set", "base set 2"), ("team rocket", "team rocket returns")):
        if any(_text(term) == base for term in spec["set_terms"]) and _phrase(set_text, expanded):
            return "SET_MISMATCH"
    if aspects.get("set") and not all(_text(term) == aspects["set"] for term in spec["set_terms"]):
        return "SET_MISMATCH"
    allowed_codes = {m.group().casefold() for m in _SET_CODES.finditer(" ".join((*spec["set_terms"], reference["card_number"])))}
    if any(m.group().casefold() not in allowed_codes for m in _SET_CODES.finditer(str(raw_title))):
        return "SET_MISMATCH"
    if _variant_markers(all_text) != spec["markers"]:
        return "VARIANT_MISMATCH"
    if not all(_phrase(title, term) for term in spec["variant_terms"]):
        return "VARIANT_PROOF_MISSING"
    if _listing_finish(row, spec) is None:
        return "FINISH_MISMATCH_OR_UNKNOWN"
    if not _condition_matches(all_text):
        return "CONDITION_OUTSIDE_NM_MINT"
    return None


def _comparable(row: Mapping[str, Any], reference: Mapping[str, Any], spec: Mapping[str, Any], observed_at: datetime) -> tuple[dict[str, Any] | None, str | None]:
    reason = _matches(row, reference, spec)
    if reason:
        return None, reason
    options = row.get("buyingOptions")
    if not isinstance(options, list) or "FIXED_PRICE" not in options or any(option not in ("FIXED_PRICE", "BEST_OFFER") for option in options) or row.get("currentBidPrice") is not None or row.get("bidCount") not in (None, 0, "0"):
        return None, "NOT_FIXED_PRICE"
    if row.get("itemEndDate") is not None:
        raw_end = row["itemEndDate"]
        try:
            end = datetime.fromisoformat(raw_end.replace("Z", "+00:00")) if isinstance(raw_end, str) else None
        except ValueError:
            end = None
        if end is None or end.tzinfo is None or end.utcoffset() is None or end <= observed_at:
            return None, "ENDED_OR_INVALID_LISTING_TIME"
    location = row.get("itemLocation")
    if not isinstance(location, Mapping) or location.get("country") != "GB":
        return None, "NON_GB_OR_UNKNOWN_LOCATION"
    price = _money(row.get("price"))
    if price is None:
        return None, "INVALID_GBP_PRICE"
    shipping = _shipping(row)
    if shipping is None:
        return None, "UNKNOWN_OR_INVALID_SHIPPING"
    item_id = row.get("itemId")
    if not isinstance(item_id, str) or not item_id.strip():
        return None, "MISSING_ITEM_ID"
    item_id = item_id.strip()
    match = re.fullmatch(r"v1\|(\d+)\|\d+", item_id)
    if match:
        item_id = match[1]
    seller = row.get("seller")
    username = seller.get("username") if isinstance(seller, Mapping) else None
    if not isinstance(username, str) or not username.strip():
        return None, "MISSING_SELLER_ID"
    seller_hash = hashlib.sha256((SOURCE + ":" + username.strip().casefold()).encode()).hexdigest()
    return {"item_id": item_id, "seller_hash": seller_hash, "title": row["title"],
            "price_gbp_minor": price, "shipping_gbp_minor": shipping,
            "delivered_gbp_minor": price + shipping,
            "finish": _FINISH_LABEL[_listing_finish(row, spec)], "condition": "Near Mint",
            "match_proof": {"game": spec["game"], "language": spec["language"],
                            "card_number": reference["card_number"], "set_terms": list(spec["set_terms"]),
                            "variant_terms": list(spec["variant_terms"])}}, None


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _quantile(values: list[int], fraction: Decimal) -> int:
    index = Decimal(len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return _round(Decimal(values[lower]) + (Decimal(values[upper] - values[lower]) * (index - lower)))


def estimate_reference_asking_price(
    reference: Mapping[str, Any], browse_rows: Sequence[Mapping[str, Any]], *,
    observed_at: datetime, now: datetime | None = None,
) -> dict[str, Any]:
    """Estimate the delivered GBP asking price for raw NM/Mint single cards.

    Three independent sellers must remain after deduplication and robust outlier
    removal. One seller contributes its lowest delivered comparable only. A
    report is valid for exactly three days after acquisition. No caller should
    interpret this result as a completed sale or a calibrated sold market value.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "source": SOURCE, "method_version": METHOD_VERSION, "basis": "ASKING_PRICE_ESTIMATE",
        "status": "INVALID_EVIDENCE_TIME", "price_gbp_minor": None, "estimate_minor": None,
        "estimate_low_minor": None, "estimate_high_minor": None, "currency": "GBP",
        "condition_basis": "RAW_NEAR_MINT_OR_MINT", "includes_shipping": True,
        "observed_at": None, "expires_at": None, "sample_count": 0, "seller_count": 0,
        "confidence": "NONE", "evidence": {}, "comparables": [], "rejection_counts": {},
        "selected_finish": None, "physical_valuation_eligible": False,
        "identity": {key: reference.get(key) for key in ("name", "set_id", "card_number", "set_name", "finish", "rarity")},
    }
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None or not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        return result
    observed_at = observed_at.astimezone(timezone.utc)
    current = current.astimezone(timezone.utc)
    result.update(observed_at=observed_at.isoformat(), expires_at=(observed_at + TTL).isoformat())
    if observed_at > current:
        return result
    if current >= observed_at + TTL:
        result["status"] = "STALE_EVIDENCE"
        return result
    spec, reason = _reference_spec(reference)
    if reason or spec is None:
        result.update(status="IDENTITY_UNSUPPORTED", rejection_counts={reason: 1})
        return result
    rejected: Counter[str] = Counter()
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in browse_rows:
        if not isinstance(row, Mapping):
            rejected["INVALID_ROW"] += 1
            continue
        comparable, reason = _comparable(row, reference, spec, observed_at)
        if comparable is None:
            rejected[reason or "INVALID_ROW"] += 1
        else:
            by_id[comparable["item_id"]].append(comparable)
    by_seller: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rows in by_id.values():
        signatures = {(r["seller_hash"], r["price_gbp_minor"], r["shipping_gbp_minor"], r["finish"], _text(r["title"])) for r in rows}
        if len(signatures) != 1:
            rejected["CONFLICTING_DUPLICATE_ITEM"] += len(rows)
            continue
        rejected["DUPLICATE_ITEM"] += len(rows) - 1
        by_seller[(rows[0]["seller_hash"], rows[0]["finish"])].append(rows[0])
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rows in by_seller.values():
        rows.sort(key=lambda r: (r["delivered_gbp_minor"], r["item_id"]))
        buckets[rows[0]["finish"]].append(rows[0])
        rejected["DUPLICATE_SELLER"] += len(rows) - 1
    before_outliers = {finish: len(rows) for finish, rows in buckets.items()}
    for finish, rows in list(buckets.items()):
        rows.sort(key=lambda r: (r["delivered_gbp_minor"], r["item_id"]))
        if len(rows) >= 3:
            prices = [r["delivered_gbp_minor"] for r in rows]
            centre = Decimal(str(median(prices)))
            mad = Decimal(str(median([abs(Decimal(v) - centre) for v in prices])))
            # The relative floor handles repeated identical prices (MAD == 0).
            threshold = max(centre * Decimal("0.20"), mad * 3)
            kept = [r for r in rows if abs(Decimal(r["delivered_gbp_minor"]) - centre) <= threshold]
            rejected["PRICE_OUTLIER"] += len(rows) - len(kept)
            buckets[finish] = kept
    selected = min(buckets, key=lambda finish: (-len(buckets[finish]), FINISH_LABELS.index(finish))) if buckets else None
    candidates = buckets[selected] if selected else []
    for comparable in candidates:
        comparable["observed_at"] = observed_at.isoformat()
    result["matched_seller_count_before_outliers"] = before_outliers.get(selected, 0)
    result["finish_bucket_counts"] = {finish: len(rows) for finish, rows in sorted(buckets.items())}
    rejected["OTHER_FINISH_BUCKET"] += sum(len(rows) for finish, rows in buckets.items() if finish != selected)
    result.update(comparables=candidates, selected_finish=selected, sample_count=len(candidates), seller_count=len(candidates),
                  evidence={"finish": selected, "condition": "Near Mint", "condition_basis": "RAW_NEAR_MINT_OR_MINT",
                            "physical_valuation_eligible": False, "comparables": candidates},
                  rejection_counts={key: value for key, value in sorted(rejected.items()) if value})
    if len(candidates) < 3:
        result["status"] = "INSUFFICIENT_COMPARABLES"
        return result
    prices = [r["delivered_gbp_minor"] for r in candidates]
    centre = Decimal(str(median(prices)))
    low = _quantile(prices, Decimal("0.25"))
    high = _quantile(prices, Decimal("0.75"))
    dispersion = Decimal(max(prices) - min(prices)) / centre
    if dispersion > Decimal("0.50") or Decimal(high - low) / centre > Decimal("0.35"):
        result["status"] = "EXCESSIVE_DISPERSION"
        return result
    result.update(status="READY", price_gbp_minor=_round(centre), estimate_minor=_round(centre),
                  estimate_low_minor=low, estimate_high_minor=high,
                  confidence="MEDIUM" if len(candidates) >= 5 else "LOW",
                  dispersion_ratio=float(dispersion))
    return result
