"""Documented public data feeds. Imported facts remain unverified references."""
from __future__ import annotations

import asyncio
import html
from collections import defaultdict
from urllib.parse import quote

import httpx

LANGUAGES = {"en":"English", "ja":"Japanese", "fr":"French", "de":"German", "it":"Italian"}
MAX_BYTES = 40_000_000


class ReferenceFeedError(RuntimeError):
    pass



SV11B_NUMBER_PROOF = {
    "verification": "TCGDEX_REVIEWED_PRINTED_DENOMINATOR_V1",
    "upstream_commit": "d09f7844f36b6cd69444650260372af490e9dbb7",
    "upstream_file": "https://github.com/tcgdex/cards-database/blob/d09f7844f36b6cd69444650260372af490e9dbb7/data-asia/SV/SV11B.ts",
    "printed_denominator": 86, "total_cards": 174,
}


# Four exact TCGdex printings whose /high.webp endpoint returned HTTP 404 on
# 2026-11-01 while the same-card /low.webp was downloaded and visually checked
# against its printed name/number. Never apply to a nearby printing, translated
# card, a changed upstream image base, or an altered provider checklist entry.
# These are reference-only images, not media rights or inventory approval.
TCGDEX_REVIEWED_LOW_WEBP = {
    "sv03.5-163": ("sv03.5", "Leftovers", "163", "163/165", "en/sv/sv03.5/163",
                   "c6353512656a25d7c0ec6e30a9fc82c2759ecc03f37a9e17a03a134fefcae70b"),
    "A2a-021": ("A2a", "Abomasnow", "021", "021/75", "en/tcgp/A2a/021",
                 "afc837a0a18d0d44a28e49e82795a81f53e5e326262848177f1d9c76973a250d"),
    "ex14-97": ("ex14", "Shiftry ex", "97", "97/100", "en/ex/ex14/97",
                "c6e2d64dfaa08b95cd5ca192389d840e67589c58ef654b94e72173aee5dce34f"),
    "A3a-072": ("A3a", "Blacephalon", "072", "072/69", "en/tcgp/A3a/072",
                 "432a1a2ac577fde631be8bdb58525f84b3719daac3d2fd22c61d18bebfdcd804"),
}


def tcgdex_reviewed_image(lang, set_id, card, printed_number):
    """Return a reviewed same-print low image, or the untouched provider high URL."""
    base = card.get("image")
    if not isinstance(base, str) or not base:
        return None, None
    high = f"{base}/high.webp"
    reviewed = TCGDEX_REVIEWED_LOW_WEBP.get(card.get("id")) if lang == "en" else None
    if not reviewed:
        return high, None
    expected_set, expected_name, expected_local, expected_print, path, digest = reviewed
    if (set_id, card.get("name"), str(card.get("localId")), printed_number, base) != (
            expected_set, expected_name, expected_local, expected_print,
            f"https://assets.tcgdex.net/{path}"):
        return high, None
    low = f"{base}/low.webp"
    return low, {"verification": "TCGDEX_REVIEWED_LOW_WEBP_V1",
                 "reviewed_at": "2026-11-01", "review_method": "EXACT_PRINTED_NAME_NUMBER_AND_RASTER",
                 "source_url": f"https://api.tcgdex.net/v2/en/cards/{card['id']}",
                 "image_url": low, "original_high_url": high,
                 "content_sha256": digest, "width": 245, "height": 337,
                 "scope": "REFERENCE_ONLY_NOT_APPROVED_MEDIA"}


def tcgdex_card_number(language, set_id, provider_id, local, official):
    """Retain the reviewed printed fraction while upstream API metadata lags."""
    if language == "ja" and set_id == "SV11B":
        if (type(official) is not int or official not in {86, 174}
                or not isinstance(local, str) or len(local) != 3
                or not local.isascii() or not local.isdecimal()
                or not 1 <= int(local) <= 174
                or provider_id != f"SV11B-{local}"):
            raise ReferenceFeedError("Reviewed SV11B collector identity changed")
        return f"{local}/086"
    return f"{local}/{official}" if official else local


class ReferenceFeeds:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.failures = []

    async def close(self):
        await self.client.aclose()

    async def get_text(self, url, **params):
        # All URLs originate in the fixed provider adapters below, never uploads.
        await asyncio.sleep(0.12)
        async with self.client.stream("GET", url, params=params or None) as response:
            if response.status_code != 200:
                raise ReferenceFeedError(f"Reference source returned HTTP {response.status_code}")
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>MAX_BYTES:
                    raise ReferenceFeedError("Reference response exceeds maximum size")
        return body.decode('utf-8')

    async def get(self, url, **params):
        import json
        try:
            return json.loads(await self.get_text(url, **params))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReferenceFeedError("Reference source returned invalid JSON") from exc

    async def dragon_ball_masters(self):
        from .reference_public import bandai_feed
        async for record, cards in bandai_feed(self, fusion=False):
            yield record, cards

    async def dragon_ball_fusion(self):
        from .reference_public import bandai_feed
        async for record, cards in bandai_feed(self, fusion=True):
            yield record, cards

    async def naruto_kayou(self):
        from .reference_public import naruto_feed
        async for record, cards in naruto_feed(self, kayou=True):
            yield record, cards

    async def naruto_bandai(self):
        from .reference_public import naruto_feed
        async for record, cards in naruto_feed(self, kayou=False):
            yield record, cards

    async def tcgdex(self):
        for lang in ("en","ja"):
            base=f"https://api.tcgdex.net/v2/{lang}"
            sets=await self.get(f"{base}/sets")
            if not isinstance(sets,list) or len(sets)>1000:
                raise ReferenceFeedError("Invalid TCGdex set list")
            for brief in sets:
                sid=str(brief['id'])
                url=f"{base}/sets/{quote(sid,safe='')}"
                payload=await self.get(url)
                record={"provider":"TCGdex","system_code":"POKEMON_TCG","language":LANGUAGES[lang],
                    "set_id":sid,"name":payload['name'],"release_date":payload.get('releaseDate'),
                    "declared_card_count":payload.get('cardCount',{}).get('total'),"source_url":url}
                total=payload.get('cardCount',{}).get('official')
                cards=[]
                for card in payload['cards']:
                    local=str(card['localId'])
                    number=tcgdex_card_number(lang,sid,str(card["id"]),local,total)
                    image,review=tcgdex_reviewed_image(lang,sid,card,number)
                    evidence={"shared_finish_artwork":True,"provider_local_id":local,
                        "detail_level":"SET_CHECKLIST","physical_finish_unresolved":True}
                    if review:
                        evidence["image_reference"]=review
                    cards.append({"provider_id":card['id'],"name":card['name'],
                        "card_number":number,"image_url":image,
                        "source_url":f"{base}/cards/{quote(str(card['id']),safe='')}",
                        "evidence":evidence})
                if lang == "ja" and sid == "SV11B":
                    for card in cards:
                        card["evidence"]["collector_number_reference"] = dict(SV11B_NUMBER_PROOF)
                yield record,cards

    async def punk(self):
        from .reference_artwork import match_existing_artwork, punk_pack_artwork, punk_pack_url
        root="https://raw.githubusercontent.com/Kuroro1990/OPTCG/main"
        for folder,language in (("english","English"),("japanese","Japanese")):
            index=await self.get(f"{root}/{folder}/index/cards_by_id.json")
            packs=await self.get(f"{root}/{folder}/packs.json")
            # Packs have varied in representation; retain exact source pack IDs
            # rather than inventing a release name when metadata is absent.
            if isinstance(packs,list):
                names={str(p.get('id') or p.get('pack_id')):p.get('name') for p in packs if isinstance(p,dict)}
            elif isinstance(packs,dict):
                names={str(k):html.unescape(v.get('raw_title') or v.get('name') or '') if isinstance(v,dict) else str(v) for k,v in packs.items()}
            else:
                raise ReferenceFeedError("Invalid One Piece set index")
            groups=defaultdict(list)
            import re
            for pid,card in index.items():
                sid=str(card.get('pack_id') or '')
                if not sid or not card.get('name'): continue
                groups[sid].append({"provider_id":pid,"name":card['name'],
                    "card_number":re.sub(r'_(?:p|r)\d+$','',pid,flags=re.I),
                    "source_url":f"{root}/{folder}/cards/{quote(sid,safe='')}/{quote(pid,safe='')}.json",
                    "evidence":{"cost":card.get('cost'),"power":card.get('power'),
                        "colors":card.get('colors') or [],"card_type":card.get('category'),
                        "detail_level":"PROVIDER_INDEX","printing_id":pid}})
            for sid,cards in groups.items():
                # The lightweight index has no images; full pack data binds art
                # to an exact language and printing, including parallel suffixes.
                artwork, evidence = punk_pack_artwork(await self.get(punk_pack_url(language,sid)),language=language,set_id=sid)
                matched = {c['provider_id']:c for c in match_existing_artwork(cards,artwork)}
                for card in cards:
                    if card['provider_id'] in matched:
                        card['image_url'] = matched[card['provider_id']]['image_url']
                        card['rarity'] = matched[card['provider_id']].get('rarity')
                        card['evidence']['image_reference'] = evidence
                yield {"provider":"Punk Records","system_code":"ONE_PIECE_CARD_GAME","language":language,
                    "set_id":sid,"name":names.get(sid) or f"Provider pack {sid}",
                    "source_url":f"{root}/{folder}/packs.json"},cards

    async def one_piece_official(self):
        from .reference_one_piece import official_feed
        async for record, cards in official_feed(self):
            yield record, cards
