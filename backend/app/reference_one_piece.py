"""Bounded official checklist repair for releases absent from the community feed."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from .reference_feeds import ReferenceFeedError
from .reference_public import Document


# Reviewed release metadata: https://en.onepiece-cardgame.com/products/op16.html
OFFICIAL_SETS = ({
    "provider": "Bandai Official", "system_code": "ONE_PIECE_CARD_GAME",
    "language": "English", "set_id": "569116", "name": "The Time of Battle [OP-16]",
    "release_date": "2026-06-12", "declared_card_count": 155,
    "source_url": "https://en.onepiece-cardgame.com/cardlist/?series=569116",
},)


def official_cards(content: str, record: dict) -> list[dict]:
    cards = []
    for card in Document(content).root.all("dl", "modalCol"):
        def field(cls):
            item = next(card.all("div", cls), None)
            if item is None:
                return ""
            heading = next(item.all("h3"), None)
            value = item.text()
            return value.removeprefix(heading.text()).strip() if heading else value

        info = field("infoCol").split(" | ")
        if len(info) != 3 or not re.fullmatch(r"[A-Z]+\d{2}-\d{3}", info[0]):
            raise ReferenceFeedError("Official One Piece checklist identity is incomplete")
        number, rarity, card_type = info
        front = next(card.all("div", "frontCol"), None)
        img = next(front.all("img"), None) if front else None
        image = urljoin(record["source_url"], (img.attrs.get("data-src") or img.attrs.get("src", "")) if img else "")
        parsed = urlparse(image)
        printing = parsed.path.rsplit("/", 1)[-1].removesuffix(".png")
        if parsed.hostname != "en.onepiece-cardgame.com" or not re.fullmatch(re.escape(number) + r"(?:_[a-z]\d+)?", printing):
            raise ReferenceFeedError("Official One Piece printing image does not match its number")
        name = field("cardName")
        if not name:
            raise ReferenceFeedError("Official One Piece card name is missing")

        def numeric(cls):
            value = field(cls)
            return int(value) if value.isdecimal() else None

        attribute = next(card.all("div", "attribute"), None)
        attributes = [node.text() for node in attribute.all("i")] if attribute else []
        cards.append({
            "provider_id": printing, "card_number": number, "name": name,
            "rarity": rarity, "image_url": image, "source_url": record["source_url"] + "#" + printing,
            "evidence": {"card_type": card_type.title(),
                "cost": numeric("cost") if card_type != "LEADER" else None,
                "life": numeric("cost") if card_type == "LEADER" else None,
                "power": numeric("power"), "counter": numeric("counter"),
                "colors": field("color").split("/"), "attributes": attributes,
                "types": field("feature").split("/"), "effect": field("text"),
                "art_treatment": "Parallel" if "_p" in printing else "Base",
                "detail_level": "OFFICIAL_CHECKLIST", "printing_id": printing,
                "physical_finish_unresolved": True},
        })
    if len(cards) != record["declared_card_count"] or len({row["provider_id"] for row in cards}) != len(cards):
        raise ReferenceFeedError("Official One Piece checklist count is incomplete or contains duplicate printings")
    return cards


async def official_feed(feeds):
    for record in OFFICIAL_SETS:
        yield dict(record), official_cards(await feeds.get_text(record["source_url"]), record)
