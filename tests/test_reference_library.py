import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from app.recognition_games import collector_key
from app.reference_feeds import ReferenceFeedError
from app.reference_public import archive_page, bandai_cards, bandai_sets
from app.reference_library import reference_candidates
from app.recognition_engine import _provider_identity_fingerprint, resolve_candidates, score_candidate
from test_recognition_engine import observation, candidate


def test_application_registers_library_with_valid_configuration(monkeypatch):
    from app.settings import get_settings
    from app.main import create_app
    for key,value in {'TCG_AUTH_ISSUER':'https://example.supabase.co/auth/v1',
        'TCG_DATABASE_URL':'postgresql://test:test@localhost/test','TCG_AUTH_AUDIENCE':'authenticated',
        'TCG_SUPABASE_PUBLISHABLE_KEY':'test-only'}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    try:
        app=create_app()
        assert '/api/v1/reference-library/coverage' in {r.path for r in app.routes}
        assert '/api/v1/recognition/resolve' in {r.path for r in app.routes}
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize('a,b',[('OP05-001','OP5-1'),('001/102','1/102'),('BT01-009','BT1-9')])
def test_padding_normalizes(a,b):
    assert collector_key(a)==collector_key(b)


@pytest.mark.parametrize('a,b',[('1/11','11/1'),('SLR+001','SLR-001'),('◇CC-MR-001','CC-MR-001'),('NRZ07-UR-001','NRB07-UR-001')])
def test_distinct_identities_survive_normalization(a,b):
    assert collector_key(a)!=collector_key(b)


def test_fusion_keeps_alternate_images_and_requires_full_count():
    body='Result<span>2</span>' + ''.join(
      f'<a class="cardStr" data-src="detail.php?card_no=FB01-001&amp;p={p}"><img data-src="../../images/{p or "base"}.webp" alt="FB01-001 Son Goku"></a>'
      for p in ['', '_p1'])
    cards=bandai_cards(body,fusion=True,url='https://www.dbs-cardgame.com/fw/en/cardlist/',set_id='583001')
    assert len({c['provider_id'] for c in cards})==2
    assert cards[0]['card_number']==cards[1]['card_number']=='FB01-001'
    assert cards[0]['image_url']!=cards[1]['image_url']
    with pytest.raises(ReferenceFeedError):
        bandai_cards(body.replace('<span>2','<span>3'),fusion=True,url='https://www.dbs-cardgame.com/fw/en/cardlist/',set_id='583001')


def test_missing_card_lists_fail_instead_of_reporting_complete():
    with pytest.raises(ReferenceFeedError): bandai_sets('<html></html>',fusion=True)
    with pytest.raises(ReferenceFeedError): bandai_cards('',fusion=False,url='https://www.dbs-cardgame.com/',set_id='1')
    with pytest.raises(ReferenceFeedError): archive_page('<html></html>','kayou')


def test_archive_decodes_data_without_executing_scripts():
    rows=[{'slug':'n001','name':'Naruto','cardNumber':'N001','setSlug':'set-one'}]
    body='1:["$",{"cards":'+json.dumps(rows)+'}]'
    page='<script>self.__next_f.push('+json.dumps([1,body])+')</script><a href="/archive/classic-ccg/cards/page/30">Last</a>'
    assert archive_page(page,'classic-ccg')==(rows,30)


@pytest.mark.parametrize('game,number,name,language',[
    ('Pokemon','1/102','Alakazam','English'),
    ('One Piece','OP01-001','Roronoa Zoro','English'),
    ('Dragon Ball Super Masters','BT1-001','Champa','English'),
    ('Dragon Ball Super Fusion World','FB01-001','Son Goku','Japanese'),
    ('Naruto Kayou','NRZ07-UR-001','Orochimaru','Chinese'),
    ('Naruto Bandai Legacy','N001','Naruto Uzumaki','English'),
])
def test_never_scanned_reference_produces_review_candidate(game,number,name,language):
    obs=observation(game=game,card_number=number,name_guess=name,language=language,
        cost=None,power=None,colors=[],attributes=[],traits=[],effect_text='',rarity_text='',card_type_text='')
    item={'provider':'Checklist','provider_id':'unseen','name':name,'base_card_id':number,
        'language':language,'library_reference':True,'exact_printing_verified':False}
    item.update(_provider_identity_fingerprint(obs,item))
    result=resolve_candidates(obs,[],provider_evidence=[item],exact_threshold=.94,min_margin=.08,high_value_review_minor=20000)
    assert result['decision']=='NEEDS_REVIEW'
    assert result['candidates'][0]['provider_id']=='unseen'
    assert result['candidates'][0]['catalogue_id'] is None


def test_unverified_checklist_cannot_inflate_local_printing_score():
    obs=observation()
    local=candidate()
    before=score_candidate(obs,local)
    item={'provider':'Checklist','provider_id':'unverified','name':obs.name_guess,
        'base_card_id':obs.card_number,'language':obs.language,'library_reference':True,
        'visual_similarity':1.0,'art_treatment':'Base'}
    item.update(_provider_identity_fingerprint(obs,item))
    assert score_candidate(obs,local,provider_evidence=[item])==before


def test_retrieval_is_system_scoped_and_preserves_unknown_language():
    class Connection:
        async def fetch(self,sql,*args):
            assert 'c.system_code=$1' in sql
            assert "c.language in ($2,'Unknown')" in sql
            assert args[0]=='NARUTO_KAYOU'
            return [{'provider':'Archive','provider_id':'r001','name':'Naruto','card_number':'R001',
                'set_name':'T1 W1','set_id':'t1w1','language':'Unknown','rarity':'R','finish':None,
                'image_url':None,'source_url':'https://example.org/card','release_date':None,
                'refreshed_at':datetime.now(timezone.utc),'evidence':{'language_unverified':True}}]
    items=asyncio.run(reference_candidates(Connection(),observation(game='Naruto Kayou',language='Chinese',card_number='R001')))
    assert items[0]['language']=='Unknown'
    assert items[0]['exact_printing_verified'] is False
    assert items[0]['language_unverified'] is True
