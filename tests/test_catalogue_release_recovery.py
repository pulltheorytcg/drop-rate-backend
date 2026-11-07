"""Release aliases recover source guides without relaxing printing identity."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import pokemon_catalogue_market as pk, dragon_ball_market as db, one_piece_market as op
from app.catalogue_coverage import coverage_summary, COVERAGE_SQL
from app.reference_applicability import POCKET_RELEASES


@pytest.mark.parametrize('set_id,title', pk.EX_RELEASE_TITLES.items())
def test_ex_prefix_matches_exact_provider_release_and_preserves_original_identity(set_id,title):
    ref=dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',
             provider_id=set_id+'-12',set_id=set_id,set_name=title,name='Pikachu',
             card_number='12/100',declared_card_count=1)
    single=dict(idProduct=1,idCategory=51,categoryName='Pokémon Single',idExpansion=2,name='Pikachu')
    box=dict(idProduct=3,idCategory=52,categoryName='Pokémon Booster',idExpansion=2,name='EX '+title+' Booster')
    assert pk.matched_products([ref],{'1':single},{'3':box})=={ref['provider_id']:single}
    assert ref['set_name']==title
    now=datetime.now(timezone.utc)
    fx=SimpleNamespace(rate=Decimal('.86'),source='ECB_EURO_REFERENCE_RATES',effective_at=now,retrieved_at=now)
    quotes=pk.quotes_for(ref,single,dict(idProduct=1,idCategory=51,trend=10),now,fx)
    assert quotes[0]['reference_identity']['set_name']==title
    assert quotes[0]['physical_valuation_eligible'] is False
    for change in ({'set_id':'another'}, {'set_name':'Other'}, {'language':'Japanese'},
                   {'provider':'Other'}, {'system_code':'ONE_PIECE_CARD_GAME'}):
        assert not pk.matched_products([{**ref,**change}],{'1':single},{'3':box})
    # Original and prefixed titles must not point at different expansions.
    assert not pk.matched_products([ref],{'1':single},
        {'3':box,'4':{**box,'idProduct':4,'idExpansion':99,'name':title+' Booster'}})
    assert not pk.matched_products([ref],{'1':single,'2':{**single,'idProduct':4}},{'3':box})
    assert not pk.matched_products([ref,{**ref,'provider_id':'parallel'}],{'1':single},{'3':box})


@pytest.mark.parametrize('identity,title', db.REFERENCE_RELEASE_ALIASES.items())
def test_dragon_ball_aliases_require_exact_set_identity_and_unique_print(identity,title):
    system,set_id,original=identity
    fusion=system==db.FUSION
    ref=dict(provider='Bandai Official',system_code=system,language='English',set_id=set_id,
             set_name=original,provider_id=set_id+':FB11-002.png' if fusion else set_id+':BT24-002.png',
             card_number='FB11-002' if fusion else 'BT24-002',name='Vegeta',rarity='Common[C]')
    single=dict(idProduct=1,idCategory=1049,categoryName='Dragon Ball Super Singles',idExpansion=2,
                name='Vegeta (FB11-002) [Fusion World]' if fusion else 'Vegeta')
    starter='Starter' in original
    box=dict(idProduct=3,idCategory=1053 if starter else 1050,
             categoryName='Dragon Ball Super Starter Decks' if starter else 'Dragon Ball Super Boosters',
             idExpansion=2,name='Starter Deck: '+title if starter else title+' Booster'+(' [Fusion World]' if fusion else ''))
    assert db.matched_products([ref],{'1':single},{'3':box})=={(system,ref['provider_id']):single}
    for change in ({'set_id':'another'}, {'set_name':'Other'}, {'language':'Japanese'}, {'provider':'Other'}):
        assert not db.matched_products([{**ref,**change}],{'1':single},{'3':box})
    assert not db.matched_products([ref],{'1':single,'2':{**single,'idProduct':9}},{'3':box})
    assert not db.matched_products([ref,{**ref,'provider_id':'parallel'}],{'1':single},{'3':box})
    assert not db.matched_products([ref],{'1':single},{'3':box,'4':{**box,'idExpansion':9}})
    now=datetime.now(timezone.utc)
    fx=SimpleNamespace(rate=Decimal('.86'),source='ECB_EURO_REFERENCE_RATES',effective_at=now,retrieved_at=now)
    quotes=db.guide_quotes(ref,single,dict(idProduct=1,idCategory=1049,trend=10),now,fx)
    assert quotes[0]['match_basis']=='EXACT_RELEASE_ALIAS_AND_UNIQUE_PRINTING'
    assert quotes[0]['physical_valuation_eligible'] is False
    assert quotes[0]['reference_identity']['set_name']==original


@pytest.mark.parametrize('code,official,market', [
    ('PRB01','PREMIUM BOOSTER -ONE PIECE CARD THE BEST- [PRB-01]','The Best'),
    ('PRB02','PREMIUM BOOSTER -ONE PIECE CARD THE BEST vol.2- [PRB-02]','The Best Vol.2'),
])
def test_premium_reprints_keep_set_and_variant_uniqueness(code,official,market):
    ref=dict(provider='Punk Records',system_code='ONE_PIECE_CARD_GAME',language='English',
             provider_id='OP01-001_r1',set_id='premium',set_name=official,
             name='Roronoa Zoro',card_number='OP01-001')
    single=dict(idProduct=1,idCategory=1621,categoryName='One Piece Single',idExpansion=2,name='Roronoa Zoro (OP01-001)')
    box=dict(idProduct=3,idCategory=1624,categoryName='One Piece Booster Boxes',idExpansion=2,name=market+' Booster Box')
    assert op.matched_products([ref],{'1':single},{'3':box})=={ref['provider_id']:single}
    for suffix in (' (Non-English)',' Case (10x Booster Box)',' (Asia Region Legal)'):
        assert not op.matched_products([ref],{'1':single},{'3':{**box,'name':box['name']+suffix}})
    assert not op.matched_products([{**ref,'language':'Japanese'}],{'1':single},{'3':box})
    assert not op.matched_products([ref,{**ref,'provider_id':'OP01-001_r2'}],{'1':single},{'3':box})
    assert not op.matched_products([ref],{'1':single,'4':{**single,'idProduct':4}},{'3':box})
    assert not op.matched_products([ref],{'1':single},{'3':box,'4':{**box,'idExpansion':9}})


def test_digital_references_are_explicitly_separate_without_inflating_priced_coverage():
    def row(status,n):
        return dict(kind='CARD',system_code='POKEMON_TCG',language='English',status=status,products=n)
    result=coverage_summary([row('REFERENCE_AVAILABLE',10),row('EXACT_QUOTE_UNAVAILABLE',4),
                             row('NOT_APPLICABLE_DIGITAL',3)])
    assert result['by_kind']['CARD']==dict(total=17,priced=10,missing=7)
    assert result['physical_cards']==dict(total=14,priced=10,missing=4)
    assert result['non_physical_cards']==3
    assert len(POCKET_RELEASES)==15
    assert '(r.set_id,s.name) in' in COVERAGE_SQL
    assert "r.provider='TCGdex'" in COVERAGE_SQL


def test_alias_does_not_rescue_conflicting_original_release_ids():
    ref=dict(system_code=db.MASTERS,set_id='428024',set_name='Z07 Booster -BEYOND GENERATIONS-')
    expansions={(db.MASTERS,'beyondgenerations'):None,(db.MASTERS,'beyondgeneration'):555}
    assert db.reference_expansion(ref,expansions) is None
