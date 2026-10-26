"""Offline free Dragon Ball pricing tests: no live key, no paid endpoints."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import pokewallet_dragon_ball_market as dbs
from app.fx import FxQuote

NOW=datetime(2026,10,25,12,tzinfo=timezone.utc)
ID="dbs_"+"a"*64


def fusion(**fields):
    row=dict(provider="Bandai Official",system_code=dbs.FUSION,
        language="English",set_id="583001",
        set_name="BOOSTER PACK -AWAKENED PULSE- [FB01]",
        card_number="FB01-001",provider_id="583001:FB01-001",name="Son Goku",
        rarity=None,has_detail_value=False,existing_catalogue_value=0,
        existing_source=None,existing_pricing_updated_at=None)
    row.update(fields)
    return row


def masters(**fields):
    row=dict(provider="Bandai Official",system_code=dbs.MASTERS,
        language="English",set_id="428001",
        set_name="Series 1 Booster -GALACTIC BATTLE-",
        card_number="BT1-053",provider_id="428001:BT1-053.png",
        name="Senzu Bean",rarity="Common[C]",
        has_detail_value=False,existing_catalogue_value=0,
        existing_source=None,existing_pricing_updated_at=None)
    row.update(fields)
    return row


def product(**fields):
    row=dict(id=ID,card_info=dict(name="Son Goku",set_name="Awakened Pulse",
        set_code="FB01",set_id="9001",card_number="FB01-001",
        product_type="card",rarity=None,variants=["Normal"]),
        cardmarket=dict(product_url="https://www.cardmarket.com/en/DragonBallSuper/Products/Singles/Awakened-Pulse/Son-Goku",
            prices=[dict(variant_type="normal",trend=12.34)]),
        tcgplayer=None)
    row.update(fields)
    return row


def body(*results, query="FB01-00", page=1, total=None, truncated=False):
    count=len(results) if total is None else total
    return dict(query=query,results=list(results),
        pagination=dict(page=page,limit=100,total=count,
            total_pages=(count+99)//100),
        metadata=dict(truncated=truncated))


def test_bandaibase_identity_excludes_variants_and_unknown_releases():
    assert dbs.reference_release(fusion())=="awakenedpulse"
    assert dbs.reference_release(masters())=="galacticbattle"
    assert dbs.reference_release(fusion(provider_id="583001:FB01-001_p1")) is None
    assert dbs.reference_release(masters(provider_id="428001:BT1-053_PR.png")) is None
    assert dbs.reference_release(fusion(set_name="Promotion Card")) is None
    assert dbs.reference_release(fusion(language="Japanese")) is None
    assert dbs.reference_release(masters(card_number="BT1-053_PR")) is None
    groups=dbs.wanted_groups([fusion(),fusion(provider_id="583001:FB01-001_p1")],NOW)
    assert len(groups["FB01-00"])==1
    assert dbs.wanted_groups([fusion(has_detail_value=True)],NOW)=={}


def test_search_shards_are_bounded_by_printed_number_not_just_set():
    refs=[fusion(card_number="FB01-001",provider_id="583001:FB01-001"),
          fusion(card_number="FB01-002",provider_id="583001:FB01-002"),
          fusion(card_number="FB01-011",provider_id="583001:FB01-011"),
          masters()]
    groups=dbs.wanted_groups(refs,NOW)
    assert len(groups["FB01-00"])==2
    assert len(groups["FB01-01"])==1
    assert len(groups["BT1-05"])==1
    assert "FB01" not in groups
    assert "BT1" not in groups


def test_unique_release_number_name_and_variant_or_fail_closed():
    ref=fusion()
    src=product()
    matches,stats=dbs.verified_matches([ref],[src])
    assert matches==[(ref,src)] and stats["matching_rarity"]==1
    assert dbs.verified_matches([ref],[src,product(id="dbs_"+"b"*64)])[0]==[]
    # A product from a different release can reuse the same printed ID.
    promo=product(id="dbs_"+"b"*64,card_info=src["card_info"]|{
        "set_name":"Promotion Cards","set_id":"9002"})
    assert dbs.verified_matches([ref],[src,promo])[0]==[(ref,src)]
    assert dbs.verified_matches([ref],[product(card_info=src["card_info"]|{
        "name":"Son Goku (Alternate Art)"})])[0]==[]
    assert dbs.verified_matches([ref],[product(card_info=src["card_info"]|{
        "card_number":"FB01-002"})])[0]==[]
    assert dbs.verified_matches([fusion(rarity="Common")],[
        product(card_info=src["card_info"]|{"rarity":"Secret Rare"})])[0]==[]
    assert dbs.verified_matches([masters()],[product(card_info={
        **src["card_info"],"name":"Senzu Bean","set_name":"Galactic Battle",
        "card_number":"BT1-053","rarity":"Super Rare"})])[0]==[]
    assert dbs.verified_matches([masters()],[product(card_info={
        **src["card_info"],"name":"Senzu Bean","set_name":"Galactic Battle",
        "card_number":"053"})])[0]==[]  # No inference from ordinal.
    # Unlike Cardmarket-only 64-character IDs, TCGplayer-linked dbs_ IDs
    # do not have one fixed documented digest size.
    extended=product(id="dbs_"+"a"*94)
    assert dbs.verified_matches([ref],[extended])[0]==[(ref,extended)]
    assert dbs.verified_matches([ref],[product(id="dbs_not_hex")])[0]==[]


def test_complete_pages_bounded_and_invalid_search_rejected():
    assert len(dbs.complete_search_page(body(product()),"FB01-00",1)[0])==1
    for bad in [body(product(),query="FB02-00"),
                body(product(),truncated=True),
                body(product(),total=201),
                body(product(),page=2)]:
        with pytest.raises(dbs.FreeSourceError):
            dbs.complete_search_page(bad,"FB01-00",1)


def test_indicative_guide_eur_and_usd_are_never_physical_values():
    eur=FxQuote("EUR","GBP",Decimal(".86"),NOW,NOW,"ECB")
    usd=FxQuote("USD","GBP",Decimal(".75"),NOW,NOW,"ECB")
    guide=dbs.source_guide(fusion(),product(),{"EUR":eur},NOW)
    assert guide["source"]==dbs.SOURCE_CM
    assert guide["price_gbp_minor"]==1061
    assert guide["physical_valuation_eligible"] is False
    assert guide["sold_comparable"] is False
    no_cm=product(cardmarket=None,tcgplayer={"url":"https://www.tcgplayer.com/product/1/example",
        "prices":[{"sub_type_name":"Foil","market_price":10}]})
    assert dbs.source_guide(fusion(),no_cm,{"USD":usd},NOW)["finish"]=="Holofoil"
    assert dbs.source_guide(fusion(),no_cm,{"USD":usd},NOW)["price_gbp_minor"]==750
    malicious=product(cardmarket={"product_url":"https://evil.example/cards/1",
        "prices":[{"variant_type":"normal","trend":12.34}]})
    assert dbs.source_guide(fusion(),malicious,{"EUR":eur},NOW) is None
    duplicate=product(cardmarket={"prices":[
        {"variant_type":"normal","trend":1},{"variant_type":"normal","trend":2}]})
    assert dbs.source_guide(fusion(),duplicate,{"EUR":eur},NOW) is None


def test_writer_is_catalogue_only_and_guards_original_source_and_printing():
    # The legacy reference detail writer accepts only 14 arguments; this
    # adapter builds 16 to carry rarity and source-conflict protection.
    assert "insert into tcg.reference_catalogue_prices" in dbs.WRITE_SQL
    assert "insert into tcg.reference_market_prices" not in dbs.WRITE_SQL
    assert "r.rarity is not distinct from $15" in dbs.WRITE_SQL
    assert "quotes->0->>'source'=$16" in dbs.WRITE_SQL


class HttpResponse:
    def __init__(self,payload,status=200):
        self.payload,self.status_code=payload,status
        self.headers={}
        self.content=json.dumps(payload).encode()
    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self,status=200):
        self.calls=[]
        self.status=status
    async def get(self,url,params,headers):
        assert url==dbs.BASE_URL+"/dbs/search"  # never paywalled endpoint
        assert params["q"]=="FB01-00"
        assert params["limit"]==100
        assert headers["X-API-Key"]=="pk_live_fixture"
        self.calls.append((url,params))
        return HttpResponse(body(product()),self.status)


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,expected_writes",[(True,0),(False,1)])
async def test_free_api_job_persists_only_catalogue_guide(monkeypatch,dry_run,expected_writes):
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,sql):
                assert sql==dbs.READ_SQL
                return [fusion()]
            async def executemany(self,sql,rows):
                assert sql==dbs.WRITE_SQL
                writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(dbs,"user_connection",connection)
    class FX:
        async def quote(self,**kwargs):
            return FxQuote(kwargs["base_currency"],"GBP",Decimal(".86"),NOW,NOW,"ECB")
    client=FakeHttp()
    result=await dbs.refresh_pokewallet_dragon_ball(
        object(),uuid4(),FX(),"pk_live_fixture",
        dry_run=dry_run,request_limit=8,http_client=client)
    assert result["requests"]==1 and result["matches"]==1
    assert result["eligible_quotes"]==1 and result["writes_attempted"]==expected_writes
    assert len(writes)==expected_writes
    if writes:
        row=writes[0]
        assert row[0:4]==("Bandai Official",dbs.FUSION,"English","583001:FB01-001")
        assert row[4][0]["source"]==dbs.SOURCE_CM
        assert row[4][0]["physical_valuation_eligible"] is False


@pytest.mark.asyncio
async def test_rate_limit_stops_run_without_any_writes(monkeypatch):
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [fusion()]
            async def executemany(self,*args):raise AssertionError("No writes on 429")
        yield Conn()
    monkeypatch.setattr(dbs,"user_connection",connection)
    result=await dbs.refresh_pokewallet_dragon_ball(
        object(),uuid4(),object(),"pk_live_fixture",
        dry_run=False,http_client=FakeHttp(status=429))
    assert result["reason"]=="RATE_LIMITED"
    assert result["requests"]==1 and result["writes_attempted"]==0


@pytest.mark.asyncio
async def test_bad_free_search_diagnostics_are_bounded_and_never_log_cards(monkeypatch):
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [fusion()]
            async def executemany(self,*args):
                raise AssertionError("Invalid provider page must never be stored")
        yield Conn()
    monkeypatch.setattr(dbs,"user_connection",connection)
    class MalformedSearch(FakeHttp):
        async def get(self,url,params,headers):
            return HttpResponse(body(product(),total=201))
    report=await dbs.refresh_pokewallet_dragon_ball(
        object(),uuid4(),object(),"pk_live_fixture",
        dry_run=False,request_limit=4,http_client=MalformedSearch())
    assert report["requests"]==1 and report["writes_attempted"]==0
    assert report["invalid_queries"]==1
    sample=report["invalid_samples"][0]
    assert sample["reason"]=="INCOMPLETE_SEARCH"
    assert sample["pagination"]["total"]==201
    assert sample["result_count"]==1
    assert "card_info" not in str(sample) and "prices" not in str(sample)


@pytest.mark.asyncio
async def test_daily_scheduler_dragon_ball_is_flagged_quota_bounded_and_idempotent(monkeypatch):
    from app import catalogue_maintenance as jobs
    from types import SimpleNamespace
    now=datetime.now(timezone.utc)
    calls=[]
    receipts=[]
    state={"previous":None,"dbs_started_at":now}
    class Conn:
        async def fetchval(self,*args):return True
        async def execute(self,*args):return None
        async def fetch(self,sql,*args):
            if "reference_sync_runs" in sql:
                return [dict(source=s,started_at=now,status="COMPLETE",
                             report={"importer_revision":jobs.SOURCE_REVISIONS.get(s,1)})
                        for s in jobs.SOURCES]
            base=[dict(job=name,started_at=now,status="COMPLETE",
                       report={"importer_revision":rev})
                  for name,rev in {
                    "REFERENCE_PRICES":jobs.REFERENCE_JOB_REVISION,
                    "SEALED_REFERENCE_PRICES":jobs.SEALED_MARKET_REVISION,
                    "CATALOGUE_VALUES":jobs.CATALOGUE_VALUE_REVISION,
                    "CARDMARKET_VALUES":jobs.CARDMARKET_VALUE_REVISION,
                    "POKEWALLET_PRICES":jobs.POKEWALLET_JOB_REVISION*10+1,
                    "CATALOGUE_COVERAGE":1}.items()]
            if state["previous"] is not None:
                base.append(dict(job="POKEWALLET_DBS_PRICES",started_at=state["dbs_started_at"],
                                 status="COMPLETE",report=state["previous"]))
            return base
    @asynccontextmanager
    async def connection(*args):yield Conn()
    async def authorized(*args):return None
    async def capacity(*args):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419,"off")
    async def refresh(*args,**kwargs):
        calls.append(kwargs)
        return {"requests":3,"eligible_quotes":2,"writes_attempted":0,"cursor":"BT2"}
    async def receipt(*args):receipts.append(args)
    monkeypatch.setattr(jobs,"user_connection",connection)
    monkeypatch.setattr(jobs,"require_platform_admin",authorized)
    monkeypatch.setattr(jobs,"check_database_capacity",capacity)
    monkeypatch.setattr(jobs,"refresh_pokewallet_dragon_ball",refresh)
    monkeypatch.setattr(jobs,"receipt",receipt)
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield Conn()
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        pokewallet_api_key="pk_live_fixture",pokewallet_pricing_apply_enabled=True,
        pokewallet_dragon_ball_enabled=True,
        pokewallet_dragon_ball_apply_enabled=False,pokewallet_dragon_ball_request_limit=8)
    await jobs.daily_pass(Pool(),settings)
    assert len(calls)==1 and calls[0]["dry_run"] is True
    assert calls[0]["request_limit"]==8
    assert any(r[2]=="POKEWALLET_DBS_PRICES" for r in receipts)
    state["previous"]={"importer_revision":jobs.POKEWALLET_DBS_JOB_REVISION*10,
                       "cursor":"BT2","writes_attempted":0}
    await jobs.daily_pass(Pool(),settings)
    assert len(calls)==1
    # Only the stale DBS job rotates; the One Piece job remains current.
    state["dbs_started_at"]=now-timedelta(hours=2)
    await jobs.daily_pass(Pool(),settings)
    assert len(calls)==2 and calls[-1]["request_limit"]==8
    state["dbs_started_at"]=now
    # Applying a verified trial is a separate revision, not another
    # unbounded request in the five-minute loop.
    settings.pokewallet_dragon_ball_apply_enabled=True
    await jobs.daily_pass(Pool(),settings)
    assert len(calls)==3 and calls[-1]["dry_run"] is False


def test_hourly_budget_is_bounded_and_utc_unambiguous_through_dst():
    from app import catalogue_maintenance as jobs
    assert jobs.DBS_HOURLY_REQUEST_BUDGET==18
    assert jobs.hourly_slot(datetime(2026,10,25,0,45,tzinfo=timezone.utc)) == datetime(2026,10,25,0,tzinfo=timezone.utc)
    assert jobs.hourly_slot(datetime(2026,10,25,1,45,tzinfo=timezone.utc)) == datetime(2026,10,25,1,tzinfo=timezone.utc)


def special_ref(set_id="583301",number="ST01-002",name="Krillin",**fields):
    row=fusion(set_id=set_id,set_name={"583301":"STORY BOOSTER 01 [ST01]",
        "583201":"MANGA BOOSTER 01 [SB01]"}[set_id],card_number=number,
        provider_id=set_id+":"+number,name=name)
    row.update(fields)
    return row


def special_products(key="st01"):
    from pathlib import Path
    return json.loads((Path(__file__).parent/"fixtures"/"fusion_special_identity.json").read_text())[key]


@pytest.mark.parametrize("set_id,number,name,key",[
    ("583201","SB01-001","Cell","sb01"),("583201","SB01-002","Android 16","sb01"),
    ("583201","SB01-003","Android 17","sb01"),("583201","SB01-009","Cell","sb01"),
    ("583301","ST01-001","Son Goten","st01"),("583301","ST01-002","Krillin","st01"),
    ("583301","ST01-003","Son Goku","st01"),("583301","ST01-004","Son Goku","st01"),
    ("583301","ST01-005","Son Goten","st01"),("583301","ST01-006","Son Goten","st01"),
    ("583301","ST01-007","Son Goten","st01"),
    ("583301","ST01-008","Son Goten/Son Gohan : Adolescence","st01"),
    ("583301","ST01-009","Son Gohan : Adolescence","st01")])
def test_observed_special_release_variants_require_one_explicit_v1_base(set_id,number,name,key):
    ref=special_ref(set_id,number,name)
    matches,_=dbs.verified_matches([ref],special_products(key))
    assert len(matches)==1
    assert "-V1-" in matches[0][1]["cardmarket"]["product_url"]
    assert not any(label in matches[0][1]["card_info"]["name"]
                   for label in ("(Alternate Art)","(Gold)","(Dragon Ball Pattern)"))


@pytest.mark.parametrize("change",["unknown_competitor","two_bases","wrong_set_id",
                                  "wrong_release_path","unlabelled_v2","no_v1",
                                  "wrong_number","wrong_base_name","no_source_rarity"])
def test_special_release_identity_rejects_ambiguous_or_changed_sources(change):
    from copy import deepcopy
    products=[deepcopy(p) for p in special_products() if p["card_info"]["card_number"]=="ST01-002"]
    if change=="unknown_competitor":
        products.append(product(id="dbs_"+"b"*64,card_info=products[0]["card_info"]))
    elif change=="two_bases":
        extra=deepcopy(products[0]);extra["id"]="dbs_"+"b"*64;products.append(extra)
    elif change=="wrong_set_id":products[0]["card_info"]["set_id"]="other"
    elif change=="wrong_release_path":
        products[0]["cardmarket"]["product_url"]=products[0]["cardmarket"]["product_url"].replace("Story-Booster-01","Other")
    elif change=="unlabelled_v2":products[1]["card_info"]["name"]="Krillin"
    elif change=="no_v1":products=products[1:]
    elif change=="wrong_number":products[0]["card_info"]["card_number"]="ST01-003"
    elif change=="wrong_base_name":products[0]["card_info"]["name"]="Vegeta"
    elif change=="no_source_rarity":products[0]["card_info"]["rarity"]=None
    assert not dbs.verified_matches([special_ref()],products)[0]


def test_special_release_scope_does_not_admit_promos_reprints_or_sb02_misfiles():
    for ref in (special_ref(set_id="583301",provider_id="583301:ST01-002_p1"),
                special_ref(set_id="583301",set_name="Other [ST01]"),
                special_ref(set_id="583301",number="FB01-002"),
                special_ref(set_id="583301",language="Japanese"),
                special_ref(set_id="583301",provider="Other")):
        assert dbs.reference_release(ref) is None
    sb02=fusion(set_id="583202",set_name="MANGA BOOSTER 02 [SB02]",
        card_number="SB02-002",provider_id="583202:SB02-002",name="North Kai")
    assert dbs.reference_release(sb02) is None
    assert not dbs.verified_matches([sb02],special_products("sb02"))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,expected_writes",[(True,0),(False,1)])
async def test_scoped_special_release_returns_preview_and_tags_only_requested_set(monkeypatch,dry_run,expected_writes):
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,sql):return [fusion(),special_ref()]
            async def executemany(self,sql,rows):writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(dbs,"user_connection",connection)
    class Client:
        async def get(self,url,params,headers):
            assert params["q"]=="ST01-00"
            return HttpResponse(body(*special_products(),query="ST01-00"))
    class FX:
        async def quote(self,**kwargs):
            return FxQuote(kwargs["base_currency"],"GBP",Decimal(".86"),NOW,NOW,"ECB")
    run_id=str(uuid4())
    report=await dbs.refresh_pokewallet_dragon_ball(
        object(),uuid4(),FX(),"pk_live_fixture",dry_run=dry_run,request_limit=35,
        http_client=Client(),reference_set_id="583301",operator_run_id=run_id)
    assert report["requests"]==1 and report["target_prefixes"]==1
    assert report["preview"][0]["provider_id"]=="583301:ST01-002"
    assert report["writes_attempted"]==expected_writes and len(writes)==expected_writes
    assert all(row[4][0]["operator_run_id"]==run_id for row in writes)
    assert all(row[4][0]["physical_valuation_eligible"] is False for row in writes)


@pytest.mark.asyncio
async def test_unknown_special_release_scope_rejected_before_io():
    with pytest.raises(ValueError,match="UNREVIEWED_REFERENCE_SET"):
        await dbs.refresh_pokewallet_dragon_ball(None,uuid4(),None,"fixture",
            reference_set_id="583202")


@pytest.mark.parametrize("field,value",[("product_type",None),("set_id",None),("id","invalid")])
def test_malformed_same_number_release_competitor_cannot_manufacture_unique_base(field,value):
    from copy import deepcopy
    products=[deepcopy(p) for p in special_products() if p["card_info"]["card_number"]=="ST01-002"]
    competitor=deepcopy(products[1])
    competitor["id"]="dbs_"+"b"*64
    if field=="id":competitor["id"]=value
    else:competitor["card_info"][field]=value
    products.append(competitor)
    assert not dbs.verified_matches([special_ref()],products)[0]


def test_reviewed_v1_proof_cannot_fall_back_to_unproved_tcgplayer_variant():
    from copy import deepcopy
    ref=special_ref()
    product=deepcopy(dbs.verified_matches([ref],special_products())[0][0][1])
    product["cardmarket"]["prices"]=[]
    product["tcgplayer"]={"url":"https://www.tcgplayer.com/product/707947/dragon-ball-super-fusion-world-story-booster-01-krillin-dragon-ball-pattern",
        "prices":[{"sub_type_name":"Normal","market_price":99}]}
    rates={currency:FxQuote(currency,"GBP",Decimal(".86"),NOW,NOW,"ECB")
           for currency in ("EUR","USD")}
    assert dbs.source_guide(ref,product,rates,NOW) is None


@pytest.mark.asyncio
async def test_scoped_budget_reports_unattempted_prefixes_without_extra_requests(monkeypatch):
    refs=[special_ref(number=f"ST01-{n:03}",name="Krillin") for n in range(1,82,10)]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,sql):return refs
        yield Conn()
    monkeypatch.setattr(dbs,"user_connection",connection)
    class Client:
        async def get(self,url,params,headers):
            return HttpResponse(body(query=params["q"]))
    report=await dbs.refresh_pokewallet_dragon_ball(
        object(),uuid4(),object(),"pk_live_fixture",dry_run=True,request_limit=35,
        http_client=Client(),reference_set_id="583301")
    assert report["target_prefixes"]==9
    assert report["requests"]==8 and report["unattempted_queries"]==1


@pytest.mark.parametrize("title",[None,"Other Release"])
def test_known_source_set_competitor_with_contradictory_title_cannot_disappear(title):
    from copy import deepcopy
    products=[deepcopy(p) for p in special_products() if p["card_info"]["card_number"]=="ST01-002"]
    products[1]["card_info"]["set_name"]=title
    assert not dbs.verified_matches([special_ref()],products)[0]
