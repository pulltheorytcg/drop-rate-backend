"""Drop Rate batch discovery plan ported from Lovable Market Scout.

Lovable src/lib/ebay.server.ts -> buildSearchPlan (2026-11-13). The actual eBay
requests run only through Railway's already quota-reserved EbayOfficialClient,
not a second Lovable API client. Retrieval broadens; existing exact identity,
condition, language, independent-seller and outlier checks remain untouched.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from .reference_asking_estimator import _reference_spec

GAME_NAMES = {
    "POKEMON_TCG": "Pokemon",
    "ONE_PIECE_CARD_GAME": "One Piece",
    "DRAGON_BALL_SUPER_FUSION_WORLD": "Fusion World",
    "DRAGON_BALL_SUPER_MASTERS": "Dragon Ball Super",
    "NARUTO_BANDAI_LEGACY": "Naruto",
    "NARUTO_KAYOU": "Naruto",
}

# Query diversity does not prove listing identity. Every returned item needs
# eBay getItem followed by the existing deterministic exact-match validator.
MAX_QUERIES_PER_REFERENCE = 4
MAX_CANDIDATE_SUMMARIES = 160
MAX_DETAILS_PER_REFERENCE = 12
EARLY_STOP_PLAUSIBLE = 5  # exact-identity, distinct-seller summaries; not loosely plausible rows


def build_reference_search_plan(reference: Mapping[str, object]) -> tuple[str, ...]:
    """Use independent canonical anchors, never free-form AI-generated text."""
    if not isinstance(reference, Mapping):
        return ()
    game = GAME_NAMES.get(reference.get("system_code"))
    name = reference.get("name")
    number = reference.get("card_number")
    set_name = reference.get("set_name")
    if not all(isinstance(v, str) and v.strip() for v in (game, name, number)):
        return ()
    evidence = reference.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    terms = evidence.get("set_title_terms")
    if isinstance(terms, (list, tuple)):
        terms = next((v for v in terms if isinstance(v, str) and v.strip()), None)
    if not isinstance(terms, str) or not terms.strip():
        terms = set_name if isinstance(set_name, str) and set_name.strip() else None
    # Prefer the same already-verified canonical short release alias used by
    # FastAPI's deterministic matcher. Do not independently guess an eBay
    # abbreviation or trust a provider-internal numeric database set ID.
    spec, reason = _reference_spec(reference)
    if reason is None and spec.get("set_alias_source"):
        alternatives = spec.get("set_alternatives", ())
        if len(alternatives) > 1 and len(alternatives[-1]) == 1:
            terms = alternatives[-1][0]
    # The catalogue's internal set_id (for example sv03.5) is not necessarily
    # an eBay-printed set code. Use the code already printed on numbered cards.
    prefix = number.split("-", 1)[0] if "-" in number else ""
    code = prefix if re.fullmatch(r"[A-Za-z]{1,7}[0-9]{1,4}", prefix) else None
    rarity = reference.get("rarity")
    finish = reference.get("finish")
    variant = (finish if isinstance(finish, str) and re.search(
        r"alt|manga|parallel|reverse|secret|illustration", finish, flags=re.I) else None)
    if variant is None and isinstance(rarity, str) and re.search(
            r"secret|special|alt|illustration", rarity, flags=re.I):
        variant = rarity
    language = reference.get("language")
    short_language = {"English": "EN", "Japanese": "JPN"}.get(language)
    plan: list[str] = []
    seen: set[str] = set()

    def add(*parts: str | None) -> None:
        clean = [re.sub(r'[\(\)"<>]', " ", p).strip() for p in parts if isinstance(p, str) and p.strip()]
        clean = [re.sub(r"\s+", " ", p) for p in clean if p]
        if len(clean) < 2:
            return
        query = " ".join(clean)
        if not 1 <= len(query) <= 100:
            return
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            plan.append(query)

    # Keep the legacy query first for comparable pilot measurements.
    add(game, name, number)
    # Second query deliberately omits canonical product name, as in Lovable.
    # The unchanged _matches() still insists on exact title/structured identity.
    add(number, terms, game)
    add(name, terms, variant or code)
    add(name, number, variant or short_language)
    add(name, number)
    return tuple(plan[:MAX_QUERIES_PER_REFERENCE])
