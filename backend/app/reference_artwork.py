"""Exact provider artwork for existing reference records; no media approval."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

ROOT = "https://raw.githubusercontent.com/Kuroro1990/OPTCG/main"
FOLDERS = {"English": "english", "Japanese": "japanese"}


def punk_pack_url(language: str, set_id: str) -> str:
    if language not in FOLDERS or not re.fullmatch(r"[0-9]{1,12}", set_id):
        raise ValueError("Unsupported One Piece reference pack")
    return f"{ROOT}/{FOLDERS[language]}/data/{set_id}.json"


def punk_pack_artwork(payload, *, language: str, set_id: str):
    source = punk_pack_url(language, set_id)
    if not isinstance(payload, list) or len(payload) > 2000:
        raise ValueError("Invalid One Piece artwork pack")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {}
    hosts = {"en.onepiece-cardgame.com"} if language == "English" else {"www.onepiece-cardgame.com", "onepiece-cardgame.com"}
    for card in payload:
        if not isinstance(card, dict) or str(card.get("pack_id")) != set_id:
            raise ValueError("One Piece artwork pack identity mismatch")
        ident, name = card.get("id"), card.get("name")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident) or not isinstance(name, str) or not name.strip():
            raise ValueError("One Piece artwork printing identity missing")
        image = card.get("img_full_url")
        if not isinstance(image, str):
            continue
        parsed = urlsplit(image)
        if (parsed.scheme != "https" or parsed.netloc not in hosts or parsed.fragment
                or not parsed.path.startswith("/images/cardlist/card/")
                or not re.fullmatch(r"/images/cardlist/card/[A-Za-z0-9_-]+\.(png|webp|jpg|jpeg)", parsed.path)):
            continue
        record = {"provider_id": ident, "name": name, "image_url": image}
        if ident in result and result[ident] != record:
            raise ValueError("Conflicting One Piece artwork printing")
        result[ident] = record
    return result, {"source_url": source, "snapshot_sha256": digest, "language": language, "set_id": set_id}


def match_existing_artwork(rows, artwork):
    """A card number alone never substitutes another parallel or language."""
    return [artwork[row["provider_id"]] for row in rows
            if row["provider_id"] in artwork and artwork[row["provider_id"]]["name"] == row["name"]]


REPAIR_SQL = """
with candidates as (
 select * from jsonb_to_recordset($3::jsonb) as c(provider_id text,name text,image_url text)
)
update tcg.reference_cards r set image_url=c.image_url,
 evidence=r.evidence || jsonb_build_object('image_reference',$4::jsonb)
from candidates c
where r.provider='Punk Records' and r.system_code='ONE_PIECE_CARD_GAME'
 and r.language=$1 and r.set_id=$2 and r.provider_id=c.provider_id and r.name=c.name
 and nullif(btrim(r.image_url),'') is null
returning r.provider_id
"""
