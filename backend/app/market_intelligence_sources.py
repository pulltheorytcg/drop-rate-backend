"""Source admission and planning for Drop Rate-owned market intelligence.

This is the cross-source REVIEW boundary, not a new scraper or database.
Existing provider adapters retain their own exact mapping and http/quota code.
All candidate outputs are non-publishable. The actual source acquisition,
ownership, media publication and financial rules stay in their current modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

class EvidenceKind(str, Enum):
    CARD_INFO = "CARD_INFO"
    ARTWORK = "ARTWORK"
    SOLD = "SOLD"
    ACTIVE = "ACTIVE"
    GUIDE = "GUIDE"


# An explicit source inventory, not an assertion that a provider is accessible.
# Mapping/rights/acquisition checks are independently required per provider.
SOURCE_ADAPTERS: dict[str, dict[str, Any]] = {
    "EBAY_BROWSE": {
        "kinds": (EvidenceKind.ACTIVE,),
        "existing_module": "app.ebay_official_adapter",
        "mode": "OFFICIAL_API_EXISTING",
    },
    "EBAY_PRODUCT_RESEARCH": {
        "kinds": (EvidenceKind.SOLD,),
        "existing_module": "app.ebay_signed_in_research",
        "mode": "SIGNED_IN_HUMAN_ASSISTED_PENDING_PR_1076",
    },
    "CARDMARKET_PUBLIC": {
        "kinds": (EvidenceKind.GUIDE, EvidenceKind.CARD_INFO),
        "existing_module": "app.cardmarket_public_pilot",
        "mode": "PUBLIC_EXPORT_EXACT_MAPPING_REQUIRED",
    },
    "TCGDEX": {
        "kinds": (EvidenceKind.CARD_INFO, EvidenceKind.ARTWORK),
        "existing_module": "app.tcgdex_client",
        "mode": "EXISTING_EXACT_MEDIA_RESOLVER",
    },
    "PUNK_RECORDS": {
        "kinds": (EvidenceKind.CARD_INFO, EvidenceKind.ARTWORK),
        "existing_module": "app.free_canonical_media",
        "mode": "EXISTING_EXACT_MEDIA_RESOLVER",
    },
    "YGOPRODECK": {
        "kinds": (EvidenceKind.CARD_INFO, EvidenceKind.ARTWORK),
        "existing_module": "app.expanded_artwork_pilot",
        "mode": "EXACT_PRINT_REVIEW_ONLY",
    },
    "LORCAST": {
        "kinds": (EvidenceKind.CARD_INFO, EvidenceKind.ARTWORK),
        "existing_module": "app.expanded_artwork_pilot",
        "mode": "EXACT_PRINT_REVIEW_ONLY",
    },
    "MTGJSON": {
        "kinds": (EvidenceKind.CARD_INFO,),
        "existing_module": "app.r2_first_mtgjson",
        "mode": "EXISTING_CATALOGUE_SOURCE",
    },
    "SCRYFALL": {
        "kinds": (EvidenceKind.ARTWORK,),
        "existing_module": "app.expanded_artwork_mtg",
        "mode": "EXACT_PRINT_REVIEW_ONLY",
    },
}

_GAMES = {
    "pokemon": "POKEMON",
    "pokémon": "POKEMON",
    "one piece": "ONE_PIECE",
    "dragon ball": "DRAGON_BALL",
    "dragon ball super": "DRAGON_BALL",
    "naruto": "NARUTO",
    "yu gi oh": "YUGIOH",
    "yu-gi-oh!": "YUGIOH",
    "disney lorcana": "LORCANA",
    "lorcana": "LORCANA",
    "magic: the gathering": "MTG",
    "magic the gathering": "MTG",
    "mtg": "MTG",
}
_ART_BY_GAME = {
    "POKEMON": ("TCGDEX",),
    "ONE_PIECE": ("PUNK_RECORDS",),
    "YUGIOH": ("YGOPRODECK",),
    "LORCANA": ("LORCAST",),
    "MTG": ("SCRYFALL",),
}
_INFO_BY_GAME = {
    "POKEMON": ("TCGDEX",),
    "ONE_PIECE": ("PUNK_RECORDS",),
    "YUGIOH": ("YGOPRODECK",),
    "LORCANA": ("LORCAST",),
    "MTG": ("MTGJSON",),
}
_EXACT_FIELDS = ("game", "set_name", "card_number", "variant", "language", "name")

def _clean(value: object) -> str:
    return " ".join(value.strip().casefold().split()) if isinstance(value, str) else ""

@dataclass(frozen=True, slots=True)
class ExactReference:
    reference_id: str
    game: str
    name: str
    set_name: str
    card_number: str
    variant: str
    language: str
    condition: str | None = None
    grading_company: str | None = None
    grade: str | None = None
    # A slab-specific photo is never a canonical reference artwork asset.
    inventory_id: str | None = None
    slab_certificate: str | None = None

    def validate(self) -> "ExactReference":
        if any(not isinstance(getattr(self, k), str) or not getattr(self, k).strip()
               for k in ("reference_id", *_EXACT_FIELDS)):
            raise ValueError("Exact canonical reference identity and ID are required")
        if _clean(self.game) not in _GAMES:
            raise ValueError("Unsupported game requires a separate exact source adapter")
        if bool(self.grading_company) != bool(self.grade):
            raise ValueError("Grading company and grade must be paired")
        return self

    @property
    def game_code(self) -> str:
        return _GAMES[_clean(self.game)]

    def identity(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in _EXACT_FIELDS}

def plan_collection(reference: ExactReference) -> dict[str, Any]:
    """Return only supported existing adapter routes; never start a crawl."""
    reference.validate()
    routes: list[dict[str, Any]] = []
    def add(source: str, kind: EvidenceKind, note: str = "") -> None:
        adapter = SOURCE_ADAPTERS[source]
        if kind not in adapter["kinds"]:
            raise ValueError("Source cannot provide this evidence kind")
        routes.append({
            "source": source,
            "kind": kind.value,
            "existing_module": adapter["existing_module"],
            "acquisition_mode": adapter["mode"],
            "note": note,
            "can_publish_market_value": False,
            "can_publish_artwork": False,
        })
    for source in _INFO_BY_GAME.get(reference.game_code, ()):
        if source == "PUNK_RECORDS" and _clean(reference.language) != "japanese":
            continue  # This first connector cohort is Japanese only.
        add(source, EvidenceKind.CARD_INFO, "Canonical identity review; no automatic remapping")
    for source in _ART_BY_GAME.get(reference.game_code, ()):
        if source == "PUNK_RECORDS" and _clean(reference.language) != "japanese":
            continue  # Existing free media resolver supports Japanese One Piece only.
        add(source, EvidenceKind.ARTWORK, "Candidate only: verify exact printing, bytes and usage rights")
    add("EBAY_BROWSE", EvidenceKind.ACTIVE, "Active asking price, not a completed sale")
    add("EBAY_PRODUCT_RESEARCH", EvidenceKind.SOLD,
        "Human-signed-in review, NOT an unattended account scraper")
    if reference.game_code == "MTG":
        add("CARDMARKET_PUBLIC", EvidenceKind.GUIDE,
            "Exact MTGJSON MCM-ID and source permissions required; never physical Market Value")
    elif reference.game_code in {"YUGIOH", "LORCANA"}:
        add("CARDMARKET_PUBLIC", EvidenceKind.GUIDE,
            "Public guide has no verified exact printing/finish crosswalk for this game")
    return {
        "reference_id": reference.reference_id,
        "game_code": reference.game_code,
        "status": "REVIEW_PLAN_ONLY",
        "routes": routes,
        "no_trusted_artwork_route": not any(r["kind"] == "ARTWORK" for r in routes),
        "writes": {"supabase": False, "shopify": False, "media": False},
        "provider_requests": 0,
    }

def classify_candidate(
    reference: ExactReference, kind: EvidenceKind, source: str,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail-closed, exact-input admission. Never returns a customer-facing value.

    A candidate's untrusted exact fields must match the canonical reference.
    Provenance is mandatory, but provenance alone is not verification.
    """
    reference.validate()
    adapter = SOURCE_ADAPTERS.get(source)
    if adapter is None or kind not in adapter["kinds"]:
        return {"status": "REJECTED_UNSUPPORTED_SOURCE_KIND", "publish": False}
    if not isinstance(candidate, Mapping):
        return {"status": "REJECTED_MALFORMED", "publish": False}
    if (candidate.get("reference_id") != reference.reference_id
            or any(_clean(candidate.get(k)) != _clean(getattr(reference, k)) for k in _EXACT_FIELDS)):
        return {"status": "REJECTED_EXACT_IDENTITY_MISMATCH", "publish": False}
    source_id = candidate.get("source_record_id")
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 160:
        return {"status": "REJECTED_SOURCE_PROVENANCE_MISSING", "publish": False}
    captured_at = candidate.get("captured_at")
    try:
        instant = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return {"status": "REJECTED_OBSERVATION_DATE", "publish": False}
    if instant.utcoffset() is None or instant > datetime.now(timezone.utc):
        return {"status": "REJECTED_OBSERVATION_DATE", "publish": False}
    if kind == EvidenceKind.SOLD:
        # A verified sold claim without a positive actual paid amount or actual
        # sale date is incomplete even before the existing sold normalizer.
        try:
            paid = Decimal(str(candidate.get("price_gbp")))
            paid_valid = paid.is_finite() and Decimal("0") < paid < Decimal("100000000")
            paid_valid = paid_valid and paid.as_tuple().exponent >= -2
        except InvalidOperation:
            paid_valid = False
        try:
            sale_day = date.fromisoformat(str(candidate.get("sold_at")))
        except ValueError:
            sale_day = None
        if not paid_valid or sale_day is None or sale_day > datetime.now(timezone.utc).date():
            return {"status": "REJECTED_INCOMPLETE_SALE_EVIDENCE", "publish": False}
        if (candidate.get("currency") != "GBP"
                or candidate.get("item_country") != "GB"
                or candidate.get("sale_price_basis") != "ACTUAL_PAID_PRICE"
                or candidate.get("sale_verified") is not True):
            return {"status": "REJECTED_UNVERIFIED_SOLD_PRICE", "publish": False}
        if bool(reference.grading_company) != bool(candidate.get("grading_company")):
            return {"status": "REJECTED_GRADE_MISMATCH", "publish": False}
        if reference.grading_company and (
            _clean(candidate.get("grading_company")) != _clean(reference.grading_company)
            or _clean(candidate.get("grade")) != _clean(reference.grade)
        ):
            return {"status": "REJECTED_GRADE_MISMATCH", "publish": False}
        if not reference.grading_company and (
            not reference.condition
            or _clean(candidate.get("condition")) != _clean(reference.condition)
        ):
            return {"status": "REJECTED_UNKNOWN_OR_MISMATCHED_CONDITION", "publish": False}
        # Existing sold normalization/pricing must still verify sale, price and
        # condition; this layer grants no authority to a transcribed claim.
        return {"status": "REVIEW_IN_EXISTING_SOLD_ENGINE", "publish": False}
    if kind == EvidenceKind.ARTWORK:
        if reference.grading_company:
            # Artwork from public catalogues must never stand in for a real slab.
            return {"status": "REJECTED_SLAB_REQUIRES_PHYSICAL_PHOTO", "publish": False}
        if (candidate.get("image_byte_verified") is not True
                or candidate.get("printing_image_verified") is not True
                or candidate.get("rights_status") != "APPROVED"):
            return {"status": "REVIEW_ARTWORK_EVIDENCE_INCOMPLETE", "publish": False}
        return {"status": "REVIEW_EXISTING_MEDIA_APPROVAL_GATE", "publish": False}
    if kind == EvidenceKind.ACTIVE:
        return {"status": "CONTEXT_ONLY_ACTIVE_ASKING", "publish": False}
    if kind == EvidenceKind.GUIDE:
        return {"status": "CONTEXT_ONLY_REGIONAL_GUIDE", "publish": False}
    return {"status": "REVIEW_CANONICAL_CATALOGUE_IDENTITY", "publish": False}
