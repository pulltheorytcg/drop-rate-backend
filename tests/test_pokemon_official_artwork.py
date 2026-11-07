import json

import pytest

from app import pokemon_official_artwork as art
from app.catalogue_browser import provider_reference_artwork_url
from app.recognition_images import _trusted_reference_url
from test_book_connector_import import run_sql


def reference(**changes):
    row = dict(provider_id='SV11W-001', set_id='SV11W', name='クルミル',
               card_number='001/86', local_id='001',
               source_url='https://api.tcgdex.net/v2/ja/cards/SV11W-001')
    return dict(row, **changes)


def source(**changes):
    row = dict(set_name='SV11W', name='クルミル', number='001', set_total='086',
               jp_id=47623, url='https://www.pokemon-card.com/card-search/details.php/card/47623',
               img='https://www.pokemon-card.com/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg')
    return dict(row, **changes)


def test_exact_set_number_total_name_and_official_asset_are_required():
    candidates, rejected = art.artwork_candidates([reference()], [source()])
    assert not rejected and len(candidates) == 1
    assert candidates[0]['official_card_id'] == 47623
    assert candidates[0]['card_number'] == '001/86'


@pytest.mark.parametrize('changes', [
    {'name': 'ハハコモリ'}, {'card_number': '001/87'}, {'card_number': '002/86'},
    {'card_number': '001'}, {'set_id': 'SV11B'}, {'local_id': '2'},
    {'provider_id': 'SV11W-002'}, {'language': 'English'}, {'image_url': 'already-present'},
    {'source_url': 'https://api.tcgdex.net/v2/en/cards/SV11W-001'},
])
def test_wrong_reference_identity_is_not_repaired(changes):
    assert not art.artwork_candidates([reference(**changes)], [source()])[0]


@pytest.mark.parametrize('changes', [
    {'jp_id': 47624}, {'number': '002'}, {'set_name': 'SV11B'}, {'set_total': '87'},
    {'name': 'クルミル ex'}, {'url': 'https://evil.test/card/47623'},
    {'img': 'https://www.pokemon-card.com/assets/images/card_images/large/SV11B/047623_P_KURUMIRU.jpg'},
])
def test_wrong_source_identity_is_not_repaired(changes):
    assert not art.artwork_candidates([reference()], [source(**changes)])[0]


def test_multiple_official_finishes_and_duplicate_references_are_unresolved():
    alternate = source(jp_id=48167, url='https://www.pokemon-card.com/card-search/details.php/card/48167',
        img='https://www.pokemon-card.com/assets/images/card_images/large/SV11W/048167_P_KURUMIRU.jpg')
    assert not art.artwork_candidates([reference()], [source(), alternate])[0]
    assert not art.artwork_candidates([reference(), reference()], [source()])[0]


def test_promos_require_the_same_explicit_official_series_code():
    ref = reference(set_id='SV-P', provider_id='SV-P-001', name='ピカチュウ', card_number='001',
                    source_url='https://api.tcgdex.net/v2/ja/cards/SV-P-001')
    card = source(set_name='SV-P', name='ピカチュウ', set_total='SV-P',
        img='https://www.pokemon-card.com/assets/images/card_images/large/SV-P/047623_P_PIKACHU.jpg')
    assert len(art.artwork_candidates([ref], [card])[0]) == 1
    for total in ('', 'S-P', 'PROMO', '86'):
        assert not art.artwork_candidates([ref], [dict(card, set_total=total)])[0]


@pytest.mark.parametrize('url', [
    'http://www.pokemon-card.com/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg',
    'https://www.pokemon-card.com.evil.test/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg',
    'https://user:secret@www.pokemon-card.com/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg',
    'https://www.pokemon-card.com:8443/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg',
    'https://www.pokemon-card.com/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg?url=other',
    'https://www.pokemon-card.com/assets/images/card_images/large/SV11W/047623_P_KURUMIRU.jpg#fragment',
    'https://www.pokemon-card.com/assets/images/card_images/large/SV11W/../047623_P_KURUMIRU.jpg',
    'https://www.pokemon-card.com/private/047623_P_KURUMIRU.jpg', None,
])
def test_image_proxy_rejects_arbitrary_official_host_urls(url):
    assert not art.official_image_url(url)
    assert not provider_reference_artwork_url(url, 'TCGdex', 'POKEMON_TCG')
    if url is not None:
        assert not _trusted_reference_url(url)


def test_verified_art_uses_existing_private_proxy_and_cache_provider_scope():
    url = source()['img']
    assert _trusted_reference_url(url)
    assert provider_reference_artwork_url(url, 'TCGdex', 'POKEMON_TCG')
    assert not provider_reference_artwork_url(url, 'Bandai Official', 'DRAGON_BALL_SUPER_MASTERS')


def test_database_rechecks_identity_preserves_evidence_and_replays_safely(tmp_path):
    ref = reference()
    setup = """create schema art_test; create table art_test.reference_cards(
      provider text,system_code text,language text,provider_id text,set_id text,name text,
      card_number text,source_url text,evidence jsonb,image_url text);
      insert into art_test.reference_cards values('TCGdex','POKEMON_TCG','Japanese','SV11W-001',
        'SV11W','クルミル','001/86','https://api.tcgdex.net/v2/ja/cards/SV11W-001',
        '{"provider_local_id":"001","physical_finish_unresolved":true}',null);"""
    entry = dict(ref, image_url=source()['img'], evidence={
        'verification': art.VERIFICATION, 'scope': 'REFERENCE_ONLY_NOT_APPROVED_MEDIA'})
    def statement(row):
        payload = json.dumps([row], ensure_ascii=False).replace("'", "''")
        return art.WRITE_SQL.replace('tcg.', 'art_test.').replace('$1', "'"+payload+"'")
    bad = [dict(entry, **{key: 'changed'}) for key in ('name','set_id','card_number','local_id','source_url')]
    result = run_sql(tmp_path, [*(statement(row) for row in bad), statement(entry), statement(entry)],
        setup=setup, inspect='select image_url,evidence from art_test.reference_cards')
    assert all(row['ok'] for row in result['results']), result
    assert [row['rows'][0]['written'] for row in result['results']] == [0]*5 + [1,0]
    assert result['inspected'][0]['image_url'] == entry['image_url']
    assert result['inspected'][0]['evidence']['physical_finish_unresolved'] is True
