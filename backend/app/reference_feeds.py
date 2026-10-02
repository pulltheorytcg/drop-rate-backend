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
                    cards.append({"provider_id":card['id'],"name":card['name'],
                        "card_number":f"{local}/{total}" if total else local,
                        "image_url":f"{card['image']}/high.webp" if card.get('image') else None,
                        "source_url":f"{base}/cards/{quote(str(card['id']),safe='')}",
                        "evidence":{"shared_finish_artwork":True,"provider_local_id":local,
                            "detail_level":"SET_CHECKLIST","physical_finish_unresolved":True}})
                yield record,cards

    async def punk(self):
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
                yield {"provider":"Punk Records","system_code":"ONE_PIECE_CARD_GAME","language":language,
                    "set_id":sid,"name":names.get(sid) or f"Provider pack {sid}",
                    "source_url":f"{root}/{folder}/packs.json"},cards

    async def one_piece_official(self):
        from .reference_one_piece import official_feed
        async for record, cards in official_feed(self):
            yield record, cards
