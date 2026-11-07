"""Conservative, index-only auction video recognition for authorised pilot footage.

No AI/provider calls, screenshot persistence, price selection, ownership writes,
auction automation, or market-price mutation. A visual hash alone NEVER proves
the exact print. An exact result needs the independently read text/identity
fields plus one approved live media match with a large visual margin.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence

from .recognition_games import collector_key


MIN_EXACT_VISUAL_SIMILARITY = 0.94
MIN_VISUAL_MARGIN = 0.07
MAX_CANDIDATES = 12


@dataclass(frozen=True, slots=True)
class ObservedCard:
    game: str
    language: str
    name: str
    set_name: str
    card_number: str
    finish: str
    object_type: str = "RAW_CARD"


def _clean(text: object) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "").strip().casefold())
    deaccented = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"\s+", " ", deaccented).split())


def _exact_identity_matches(record: Mapping, observed: ObservedCard) -> bool:
    """No identity borrowing across sets, languages, finishes or grades."""
    if observed.object_type != "RAW_CARD":
        return False
    if _clean(observed.game) not in {"pokemon", "pokemon tcg"}:
        return False
    if _clean(record.get("game")) not in {"pokemon", "pokemon tcg"}:
        return False
    if _clean(observed.language) != "english" or _clean(record.get("language")) != "english":
        return False
    if _clean(observed.finish) not in {"normal", "holofoil", "reverse holofoil"}:
        return False
    return all((
        bool(_clean(observed.name)),
        bool(_clean(observed.set_name)),
        bool(collector_key(observed.card_number)),
        _clean(record.get("name")) == _clean(observed.name),
        _clean(record.get("set_name")) == _clean(observed.set_name),
        collector_key(record.get("card_number")) == collector_key(observed.card_number),
        _clean(record.get("variant")) == _clean(observed.finish),
    ))


def confirm_exact_printing(
    hints: Sequence[Mapping],
    media_catalogue_rows: Sequence[Mapping],
    observed: ObservedCard,
) -> dict | None:
    """Abstain if any competing lookalike, untrusted media or input ambiguity.

    The full visual shortlist is considered for margin checks, even if a
    competing image lacks metadata, otherwise missing data could falsely
    make one variant appear unique.
    """
    by_pair = {
        (str(row.get("catalogue_id")), str(row.get("media_asset_id"))): row
        for row in media_catalogue_rows
        if str(row.get("approval_status")) == "APPROVED"
        and str(row.get("source_status")) == "ACTIVE"
        and str(row.get("rights_status")) == "VERIFIED"
        and str(row.get("product_type")) == "CARD"
    }
    ranked = sorted(
        (hint for hint in hints if hint.get("similarity") is not None),
        key=lambda item: -float(item["similarity"]),
    )
    if not ranked:
        return None
    top = ranked[0]
    if (
        str(top.get("trust_level")) != "VERIFIED"
        or float(top["similarity"]) < MIN_EXACT_VISUAL_SIMILARITY
        or (len(ranked) > 1 and
            float(top["similarity"]) - float(ranked[1]["similarity"]) < MIN_VISUAL_MARGIN)
    ):
        return None
    row = by_pair.get((str(top.get("catalogue_id")), str(top.get("media_asset_id"))))
    if row is None or not _exact_identity_matches(row, observed):
        return None
    return {
        "catalogue_id": str(row["catalogue_id"]),
        "identityKey": "card:" + str(row["catalogue_id"]) + ":English:" + str(row["variant"]) + ":RAW",
        "title": str(row["name"]) + " · " + str(row["set_name"]) + " · " + str(row["card_number"]),
        "language": "English",
        "finish": str(row["variant"]),
    }
