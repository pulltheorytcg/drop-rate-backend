from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import access_control,database_capacity,pokemon_cardtrader_market as bridge
from app import pokemon_catalogue_market as pricing,pokemon_subset_price_refresh as runner
from app.cardtrader_client import CardTraderApiError


def references():
    suffixes=[str(n) for n in range(1,84)]+["28a","73a"]+[f"RC{n}" for n in range(1,33)]
    rows=[dict(provider="TCGdex",system_code="POKEMON_TCG",language="English",
        provider_id="g1-"+suffix,set_id="g1",set_name="Generations",declared_card_count=117,
        card_number=suffix+"/83",name="Fixture "+suffix) for suffix in suffixes]
    for row in rows:
        suffix=row["provider_id"][3:]
        row["name"]={"RC6":"Flareon EX","RC28":"Flareon EX","RC21":"Sylveon EX",
                     "RC32":"Sylveon EX","RC29":"Pikachu"}.get(suffix,row["name"])
    return rows


@pytest.mark.parametrize("change",["missing","duplicate","title","language","number","count"])
def test_full117_identity_is_required_before_partitioning(change):
    rows=references()
    assert len(pricing.bounded_references(rows,"g1"))==32
    if change=="missing":rows.pop()
    elif change=="duplicate":rows[-1]=rows[0]
    elif change=="title":rows[0]["set_name"]="Generations other"
    elif change=="language":rows[0]["language"]="Japanese"
    elif change=="number":rows[-1]["card_number"]="RC32/32"
    else:rows[0]["declared_card_count"]=116
    with pytest.raises(ValueError):
        pricing.validate_generations_scope(rows)


def blueprint(number):
    rarity="Holo Rare" if number in {6,21} else "Ultra Rare" if number>=28 else "Common"
    suffix=f"RC{number}/RC32"
    name={"RC6":"Flareon EX","RC28":"Flareon EX","RC21":"Sylveon EX",
          "RC32":"Sylveon EX","RC29":"Pikachu"}.get(f"RC{number}",f"Fixture RC{number}")
    return dict(id=126234+number,game_id=5,expansion_id=1907,category_id=73,name=name,
        version=(rarity+" | " if rarity in {"Holo Rare","Ultra Rare"} else "")+suffix,
        fixed_properties={"collector_number":("0" if number<10 else "")+suffix,
                          "pokemon_rarity":rarity},card_market_ids=[288509+number])


@pytest.mark.parametrize("change",["wrong_version","wrong_rarity","arbitrary_prefix","double_zero","zero_ten","wrong_expansion"])
def test_leading_zero_correction_requires_exact_independent_metadata(change):
    row=blueprint(6);expansion=dict(id=1907,game_id=5,name="Radiant Collection Generation")
    assert bridge.blueprint_number_key(row,expansion)==("RC",6,"")
    if change=="wrong_version":row["version"]="Holo Rare | RC7/RC32"
    elif change=="wrong_rarity":row["fixed_properties"]["pokemon_rarity"]="Common"
    elif change=="arbitrary_prefix":row["version"]="Unreviewed | RC6/RC32"
    elif change=="double_zero":row["fixed_properties"]["collector_number"]="00RC6/RC32"
    elif change=="zero_ten":row["fixed_properties"]["collector_number"]="0RC10/RC32";row["version"]="Holo Rare | RC10/RC32"
    else:expansion["id"]=1908
    assert bridge.blueprint_number_key(row,expansion) is None


@pytest.fixture
def environment(monkeypatch):
    state=SimpleNamespace(rows=references(),writes=[],receipts=[],claims=[],claim_reads=0,
        fail_base=False,truncate_base=False,provider_reads=0,omit_price=None,unlocks=0,base_extra=[],rc=[blueprint(n) for n in range(1,33)])
    now=datetime.now(timezone.utc)
    products={str(288509+n):dict(idProduct=288509+n,idCategory=51,categoryName="Pokémon Single",
        idExpansion=1907,name=blueprint(n)["name"]) for n in range(1,33)}
    base=[dict(id=999000+n,game_id=5,expansion_id=1906,category_id=73,name=f"Fixture {n}",
        fixed_properties={"collector_number":f"{n}/83"},card_market_ids=[811000+n]) for n in range(1,84)]
    products["811001"]=dict(idProduct=811001,idCategory=51,categoryName="Pokémon Single",idExpansion=1906,name="Fixture 1")

    class Client:
        async def list_games(self): return [dict(id=5,name="Pokémon")]
        async def list_expansions(self):return [dict(id=1906,game_id=5,name="Generations"),dict(id=1907,game_id=5,name="Radiant Collection Generation")]
        async def list_categories(self,**kwargs):return [dict(id=73,game_id=5,name="Pokemon Single Cards")]
        async def list_blueprints(self,*,expansion_id):
            if expansion_id==1906:
                if state.fail_base:raise CardTraderApiError("private provider detail")
                return (base[:1] if state.truncate_base else base)+state.base_extra
            return state.rc

    class Connection:
        async def fetch(self,sql,*args):
            if sql.startswith(pricing.READ_SQL):
                assert args in (("g1",),())
                return deepcopy(state.rows)
            if sql==pricing.OUTSIDE_SCOPE_CLAIMS_SQL:
                state.claim_reads+=1
                assert len(args[0])==32 and all(x.startswith("g1-RC") for x in args[0])
                claims=state.claims(state.claim_reads) if callable(state.claims) else state.claims
                return [dict(product_id=value) for value in claims]
            assert "checked_at=$2" in sql
            return [dict(provider_id=value[3]) for value in state.writes]
        async def executemany(self,sql,values):
            assert sql==pricing.WRITE_SQL
            assert all(value[3].startswith("g1-RC") and value[5]>0 for value in values)
            state.writes.extend(values)
        async def fetchval(self,sql,*args):
            if "pg_try_advisory_lock" in sql:return True
            if "pg_advisory_unlock" in sql:state.unlocks+=1;return True
            assert "reference_sync_runs" in sql and args==("generations_radiant_catalogue_prices",)
            state.receipts.append(("start",args));return uuid4()
        async def execute(self,sql,*args):
            assert "update tcg.reference_sync_runs" in sql
            state.receipts.append(("finish",args))
    connection=Connection()
    @asynccontextmanager
    async def user_connection(*args):yield connection
    class Pool:
        def acquire(self):return user_connection()
    async def admin(connection):pass
    async def capacity(connection):return SimpleNamespace(refresh_allowed=True,report=lambda:{"refresh_allowed":True})
    async def download(client,path,**kwargs):
        state.provider_reads+=1
        if "nonsingles" in path:return {},now
        if "singles" in path:return products,now
        return {key:dict(idProduct=int(key),idCategory=51,trend=10) for key in products if key!=state.omit_price},now
    class FX:
        async def quote(self,**kwargs):return SimpleNamespace(rate=Decimal("0.85"),source="TEST_ECB",effective_at=now,retrieved_at=now)
    monkeypatch.setattr(pricing,"user_connection",user_connection)
    monkeypatch.setattr(pricing,"download",download)
    monkeypatch.setattr(pricing,"matched_products",lambda *args:{})
    monkeypatch.setattr(runner,"user_connection",user_connection)
    monkeypatch.setattr(runner,"require_platform_admin",admin)
    monkeypatch.setattr(runner,"check_database_capacity",capacity)
    monkeypatch.setattr(access_control,"require_platform_admin",admin)
    monkeypatch.setattr(database_capacity,"check_database_capacity",capacity)
    state.client,state.fx,state.pool,state.actor=Client(),FX(),Pool(),uuid4()
    return state


@pytest.mark.asyncio
async def test_preview_requires_both_partitions_and_only_outputs_rc(environment):
    e=environment
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx)
    assert result["status"]=="VERIFIED" and result["source_checked"]==117 and result["checked"]==32
    assert result["priced"]==32 and not e.writes and not e.receipts
    assert result["cardtrader_bridge"]["sets_checked"]==2
    quote=next(r for r in result["preview"] if r["provider_id"]=="g1-RC6")["quotes"][0]
    assert quote["cardtrader_collector_number"]=="0RC6/RC32"
    assert quote["normalized_collector_number"]=="RC6"
    assert quote["physical_valuation_eligible"] is False and quote["price_gbp_minor"]==850


@pytest.mark.asyncio
async def test_apply_never_writes_base_or_clears_unpriced_rc(environment):
    e=environment;e.omit_price="288515"
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx,apply=True)
    assert result["status"]=="COMPLETE" and result["written"]==31
    assert len(e.writes)==31 and all(r[3].startswith("g1-RC") for r in e.writes)
    assert "g1-RC6" not in {r[3] for r in e.writes}
    assert e.receipts[-1][1][1]=="COMPLETE" and e.unlocks==1


@pytest.mark.asyncio
@pytest.mark.parametrize("multi",[False,True])
async def test_unpriced_base_claim_blocks_radiant_candidate(environment,multi):
    e=environment
    e.base_extra=[dict(id=999002,game_id=5,expansion_id=1906,category_id=73,name="Unpriced",
        fixed_properties={"collector_number":"82/83"},card_market_ids=[288515,999999] if multi else [288515])]
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx)
    assert result["priced"]==31
    assert "g1-RC6" not in {r["provider_id"] for r in result["preview"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure",["base","truncated_base","duplicate_rc","missing_rc","malformed_claim"])
async def test_incomplete_source_preserves_all_prices(environment,failure):
    e=environment
    if failure=="base":e.fail_base=True
    elif failure=="truncated_base":e.truncate_base=True
    elif failure=="duplicate_rc":e.rc.append(deepcopy(e.rc[0]))
    elif failure=="missing_rc":e.rc.pop()
    else:e.base_extra=[dict(id=999002,game_id=5,expansion_id=1906,category_id=73,card_market_ids="invalid")]
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx,apply=True)
    assert result["status"]=="INCOMPLETE" and not e.writes


@pytest.mark.asyncio
async def test_outside_claim_rechecked_with_base_outside_scope(environment):
    e=environment;e.claims=lambda n:[] if n==1 else ["288515"]
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx,apply=True)
    assert result["status"]=="INCOMPLETE" and not e.writes


@pytest.mark.asyncio
async def test_partial_canonical_checklist_stops_before_provider_reads(environment):
    e=environment;e.rows.pop()
    result=await runner.refresh_generations_radiant(e.pool,e.actor,e.client,e.fx,apply=True)
    assert result["status"]=="INCOMPLETE" and not e.writes and e.provider_reads==0


@pytest.mark.asyncio
async def test_daily_failed_partition_cannot_overwrite_with_name_only_prices(environment,monkeypatch):
    e=environment;e.fail_base=True
    old=deepcopy(e.rows)
    monkeypatch.setattr(pricing,"matched_products",lambda *args:{"g1-RC6":dict(idProduct=288515)})
    result=await pricing.refresh_pokemon_catalogue_prices(e.pool,e.actor,e.fx,cardtrader_client=e.client)
    assert result["provider_failures"] and not e.writes
    assert e.rows==old
