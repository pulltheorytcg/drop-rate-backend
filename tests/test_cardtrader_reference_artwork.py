import asyncio
import json
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import cardtrader_reference_artwork as art
from test_book_connector_import import run_sql


def reference(n=1, **changes):
    return dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
                provider_id=f'svp-{n:03}', set_id='svp', name=f'Card {n}', card_number=f'{n:03}/225',
                rarity='Promo', source_url=f'https://api.tcgdex.net/v2/en/cards/svp-{n:03}',
                evidence={'provider_local_id': f'{n:03}'}, image_url=None, **changes)


def blueprint(n=1):
    return {'id': n, 'image_url': f'https://cardtrader.com/uploads/blueprints/image/{n}/preview_card.jpg'}


@pytest.mark.parametrize('url', [
    'http://cardtrader.com/uploads/blueprints/image/1/preview_card.jpg',
    'https://evil.test/uploads/blueprints/image/1/preview_card.jpg',
    'https://cardtrader.com/uploads/blueprints/image/2/preview_card.jpg',
    'https://user:secret@cardtrader.com/uploads/blueprints/image/1/preview_card.jpg',
    'https://cardtrader.com/uploads/blueprints/image/1/preview_card.jpg?url=other',
    'https://cardtrader.com/uploads/blueprints/image/1/preview_card.svg', None,
])
def test_wrong_asset_or_untrusted_image_never_reaches_downloader(url):
    assert art.artwork_candidates([reference()], [{**blueprint(), 'image_url': url}], {'svp-001': 1}) == []


def test_existing_images_wrong_language_and_ambiguous_blueprints_are_kept_out():
    r = reference(); r['image_url'] = 'https://assets.tcgdex.net/existing.webp'
    assert not art.artwork_candidates([r], [blueprint()], {'svp-001': 1})
    r = reference(); r['language'] = 'Japanese'
    assert not art.artwork_candidates([r], [blueprint()], {'svp-001': 1})
    assert not art.artwork_candidates([reference()], [blueprint(), blueprint()], {'svp-001': 1})
    assert not art.artwork_candidates([reference()], [blueprint()], {})


@pytest.mark.asyncio
async def test_recovery_is_bounded_resumes_failures_and_only_writes_verified_exact_references(monkeypatch):
    refs = [reference(n) for n in range(1, 26)]
    blueprints = [blueprint(n) for n in range(1, 26)]
    matches = {r['provider_id']: n for n, r in enumerate(refs, 1)}
    downloads, writes, running, peak = [], [], 0, 0
    async def download(url, **limits):
        nonlocal running, peak
        assert limits == {'max_bytes': 2_000_000, 'timeout_seconds': 8}
        downloads.append(url); running += 1; peak = max(peak, running)
        await asyncio.sleep(0); running -= 1
        return None if '/image/1/' in url else SimpleNamespace(data=b'verified decoded image')
    async def save(sql, *args):
        assert sql == art.WRITE_SQL; writes.append(args); return args[0]
    @asynccontextmanager
    async def connection(*args):
        yield SimpleNamespace(fetchval=save)
    monkeypatch.setattr(art, 'reference_image_bytes', download)
    monkeypatch.setattr(art, 'user_connection', connection)
    monkeypatch.setattr(art, 'require_platform_admin', AsyncMock())
    result = await art.recover_reference_artwork(None, None, refs, blueprints, matches, dry_run=False)
    assert (result['probed'], result['verified'], result['written'], result['cursor']) == (20, 19, 19, 'svp-020')
    assert peak <= 4 and len(downloads) == 20 and len(writes) == 19
    evidence = json.loads(writes[0][-1])
    assert evidence['scope'] == 'REFERENCE_ONLY_NOT_APPROVED_MEDIA'
    assert evidence['blueprint_id'] == 2 and len(evidence['content_sha256']) == 64
    downloads.clear(); writes.clear()
    result = await art.recover_reference_artwork(None, None, refs, blueprints, matches,
        limit=2, dry_run=True, previous_cursor=result['cursor'])
    assert result['cursor'] == 'svp-022' and result['verified'] == 2 and not writes
    assert '/image/21/' in downloads[0]


def test_database_rechecks_identity_and_does_not_overwrite_existing_art(tmp_path):
    setup = """create schema art_test; create table art_test.reference_cards(
      provider text,system_code text,language text,provider_id text,set_id text,name text,
      card_number text,source_url text,rarity text,evidence jsonb,image_url text);
      insert into art_test.reference_cards values('TCGdex','POKEMON_TCG','English','svp-001',
        'svp','Card 1','001/225','https://api.tcgdex.net/v2/en/cards/svp-001','Promo',
        '{"provider_local_id":"001"}',null);"""
    r = reference()
    args = [r['provider_id'], r['set_id'], r['name'], r['card_number'], r['source_url'],
            r['rarity'], '001', blueprint()['image_url'], json.dumps({'scope': 'REFERENCE_ONLY_NOT_APPROVED_MEDIA'})]
    def statement(values):
        return re.sub(r'\$(\d+)', lambda match: "'"+values[int(match[1])-1].replace("'", "''")+"'",
                      art.WRITE_SQL.replace('tcg.', 'art_test.'))
    changed = args.copy(); changed[2] = 'Different printing'
    result = run_sql(tmp_path, [statement(changed), statement(args), statement(args)],
                     setup=setup, inspect='select image_url,evidence from art_test.reference_cards')
    assert all(row['ok'] for row in result['results']), result
    assert [len(row['rows']) for row in result['results']] == [0, 1, 0]
    assert result['inspected'][0]['image_url'] == args[7]
    assert result['inspected'][0]['evidence']['provider_local_id'] == '001'
