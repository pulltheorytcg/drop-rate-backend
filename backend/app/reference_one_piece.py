"""Discover released English boosters missing from the older community index."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, urljoin, urlparse

from .reference_feeds import ReferenceFeedError
from .reference_public import Document


# Reviewed release metadata: https://en.onepiece-cardgame.com/products/op16.html
OFFICIAL_SETS = ({
    "provider": "Bandai Official", "system_code": "ONE_PIECE_CARD_GAME",
    "language": "English", "set_id": "569116", "name": "The Time of Battle [OP-16]",
    "release_date": "2026-06-12", "declared_card_count": 155,
    "source_url": "https://en.onepiece-cardgame.com/cardlist/?series=569116",
},)
INDEX = 'https://en.onepiece-cardgame.com/cardlist/'
PRODUCTS = 'https://en.onepiece-cardgame.com/products/'


def release_code(label):
    codes = re.findall(r'\[([A-Z0-9 -]+)\]', label.upper())
    return re.sub(r'[ -]', '', codes[-1]) if codes else ''


def released_products(content):
    releases = {}
    root = Document(content).root
    for item in root.all('li', 'linkListColBox'):
        title = next(item.all('h4', 'linkListColTitle'), None)
        stamp = next(item.all('time'), None)
        if title is None or stamp is None:
            continue
        code = release_code(title.text())
        if not re.fullmatch(r'OP\d{2}(?:EB\d{2})?', code):
            continue
        try:
            released = date.fromisoformat(stamp.attrs.get('datetime', ''))
        except ValueError as exc:
            raise ReferenceFeedError('Official booster release date is invalid') from exc
        if code in releases and releases[code] != released:
            raise ReferenceFeedError('Official booster release dates conflict')
        releases[code] = released
    pages = {1}
    for link in root.all('a'):
        url = urlparse(urljoin(PRODUCTS, link.attrs.get('href', '')))
        if url.hostname == 'en.onepiece-cardgame.com' and url.path == '/products/':
            page = (parse_qs(url.query).get('page') or [''])[0]
            if page.isdecimal():
                pages.add(int(page))
    if not 1 <= max(pages) <= 30:
        raise ReferenceFeedError('Official product pagination exceeds limit')
    return releases, max(pages)


def booster_sets(content, releases, *, today):
    records = {}
    for option in Document(content).root.all('option'):
        sid = option.attrs.get('value') or ''
        # Punk Records supplies earlier releases. This open-ended boundary
        # complements it without duplicating its entire English catalogue.
        if not sid.isdecimal() or not 569115 <= int(sid) < 569200:
            continue
        name = Document(option.text()).root.text()
        code = release_code(name)
        released = releases.get(code)
        if released is None:
            raise ReferenceFeedError('Official booster is missing release metadata: ' + code)
        if released > today:
            continue
        reviewed = next((r for r in OFFICIAL_SETS if r['set_id'] == sid), {})
        records[sid] = {'provider':'Bandai Official', 'system_code':'ONE_PIECE_CARD_GAME',
            'language':'English', 'set_id':sid, 'name':reviewed.get('name', name),
            'release_date':released.isoformat(), 'source_url':INDEX+'?series='+sid}
    if not records:
        raise ReferenceFeedError('Official index has no released booster checklists')
    return list(records.values())


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
        if len(info) != 3 or not re.fullmatch(r"(?:[A-Z]+\d{2}|P)-\d{3}", info[0]):
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
    releases, pages = released_products(await feeds.get_text(PRODUCTS))
    for page in range(2, pages + 1):
        extra, _ = released_products(await feeds.get_text(PRODUCTS+'?page='+str(page)))
        for code, stamp in extra.items():
            if code in releases and releases[code] != stamp:
                raise ReferenceFeedError('Official booster release dates conflict')
            releases[code] = stamp
    # The bare index redirects to the newest series. A known checklist has
    # the same complete series selector without following an unchecked URL.
    records = booster_sets(await feeds.get_text(OFFICIAL_SETS[0]['source_url']), releases, today=date.today())
    prepared = []
    seen = set()
    for record in records:
        content = await feeds.get_text(record['source_url'])
        counts = [node.text() for node in Document(content).root.all('div', 'countCol')]
        if len(counts) != 1 or not re.fullmatch(r'\d{1,4} results', counts[0]):
            raise ReferenceFeedError('Official checklist result count is missing')
        record['declared_card_count'] = int(counts[0].split()[0])
        if not 1 <= record['declared_card_count'] <= 2000:
            raise ReferenceFeedError('Official checklist exceeds card limit')
        cards = official_cards(content, record)
        identities = {row['provider_id'] for row in cards}
        if seen & identities:
            raise ReferenceFeedError('Official printing is shared by multiple release checklists')
        seen.update(identities)
        prepared.append((record, cards))
    # Validate the entire bounded discovery before publishing any new set.
    for record, cards in prepared:
        yield record, cards
