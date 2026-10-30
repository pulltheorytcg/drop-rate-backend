"""Recover blank Pokémon reference artwork from exact CardTrader blueprints.

Reuses the existing permitted expansion export and its unique-printing matcher.
Never approves publication media, replaces an image, or modifies physical stock.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .recognition_images import reference_image_bytes

MAX_PROBES = 20
WRITE_SQL = """
update tcg.reference_cards r set image_url=$8,
 evidence=r.evidence || jsonb_build_object('image_reference',$9::jsonb)
where (r.provider,r.system_code,r.language,r.provider_id)=('TCGdex','POKEMON_TCG','English',$1)
 and r.set_id=$2 and r.name=$3 and r.card_number=$4
 and r.source_url=$5 and r.rarity is not distinct from $6
 and r.evidence->>'provider_local_id' is not distinct from $7
 and nullif(btrim(r.image_url),'') is null
returning r.provider_id
"""


def artwork_candidates(refs, blueprints, matches):
    by_id = {}
    for blueprint in blueprints:
        by_id.setdefault(blueprint.get('id'), []).append(blueprint)
    output = []
    for ref in refs:
        if ((ref.get('provider'), ref.get('system_code'), ref.get('language')) !=
                ('TCGdex', 'POKEMON_TCG', 'English') or str(ref.get('image_url') or '').strip()):
            continue
        blueprint_id = matches.get(ref['provider_id'])
        choices = by_id.get(blueprint_id, [])
        if type(blueprint_id) is not int or len(choices) != 1:
            continue
        url = choices[0].get('image_url')
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.hostname not in {'cardtrader.com', 'www.cardtrader.com'}
                    or parsed.username or parsed.password or parsed.fragment or parsed.query
                    or parsed.port not in (None, 443)
                    or not re.fullmatch(r'/uploads/blueprints/image/' + str(blueprint_id) + r'/[^/]+\.(?:jpg|jpeg|png|webp)', parsed.path, re.I)):
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        output.append((ref, blueprint_id, url))
    return output


async def recover_reference_artwork(pool, actor, refs, blueprints, matches, *, limit=MAX_PROBES, dry_run=True, previous_cursor=None):
    if type(limit) is not int or not 0 <= limit <= MAX_PROBES:
        raise ValueError('Invalid artwork probe limit')
    candidates = sorted(artwork_candidates(refs, blueprints, matches), key=lambda row: row[0]['provider_id'])
    if previous_cursor:
        candidates = ([c for c in candidates if c[0]['provider_id'] > previous_cursor]
                      + [c for c in candidates if c[0]['provider_id'] <= previous_cursor])
    report = {'candidates': len(candidates), 'probed': 0, 'verified': 0, 'written': 0, 'cursor': previous_cursor}
    semaphore = asyncio.Semaphore(4)

    async def verify(candidate):
        ref, blueprint_id, url = candidate
        async with semaphore:
            payload = await reference_image_bytes(url, max_bytes=2_000_000, timeout_seconds=8)
        if payload is None:
            return None
        evidence = {
            'verification': 'CARDTRADER_EXACT_REFERENCE_IMAGE_V1',
            'scope': 'REFERENCE_ONLY_NOT_APPROVED_MEDIA', 'provider': 'CardTrader',
            'blueprint_id': blueprint_id, 'image_url': url,
            'reference_source_url': ref['source_url'],
            'reference_identity': {key: ref.get(key) for key in ('provider_id', 'name', 'set_id', 'set_name', 'card_number', 'rarity', 'language')},
            'content_sha256': hashlib.sha256(payload.data).hexdigest(),
            'verified_at': datetime.now(timezone.utc).isoformat(),
        }
        return (ref['provider_id'], ref['set_id'], ref['name'], ref['card_number'],
                ref['source_url'], ref.get('rarity'), (ref.get('evidence') or {}).get('provider_local_id'), url, json.dumps(evidence))

    selected = candidates[:limit]
    if selected:
        report['cursor'] = selected[-1][0]['provider_id']
    report['probed'] = len(selected)
    verified = [row for row in await asyncio.gather(*(verify(c) for c in selected)) if row]
    report['verified'] = len(verified)
    if verified and not dry_run:
        async with user_connection(pool, actor, str(uuid4())) as connection:
            await require_platform_admin(connection)
            for row in verified:
                report['written'] += bool(await connection.fetchval(WRITE_SQL, *row))
    return report
