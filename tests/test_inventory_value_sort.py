"""Global, exact-group value ordering must agree with the values returned to UI."""
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import inventory_value_sort as sorting
from app.inventory_reference_values import REFERENCE_VALUES_SQL
from app.inventory_catalogue_reference import PRODUCTS_SQL
from app import owner_portal_api


def copy(code, group=None, **extra):
    return dict(id=uuid4(), catalogue_id=uuid4(), inventory_code=code, version=2,
                status="DRAFT", product_type="CARD", game="Pokemon", name=code, set_name="Base",
                card_number="1", variant="Normal", rarity="Rare", condition="Near Mint",
                language="English", catalogue_language="English", seal_status=None,
                grading_company=None, grade=None, display_key=group or code, **extra)


class Candidates:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        assert "where i.owner_id=$1 and p.game=$2" in sql
        assert "limit $3" in sql and "offset" not in sql.lower()
        return deepcopy(self.rows)


@pytest.mark.asyncio
async def test_entire_owner_filtered_population_is_enriched_before_group_page(monkeypatch):
    rows = [copy("B", "pair"), copy("B2", "pair"), copy("A"), copy("Z"), copy("U")]
    conn = Candidates(rows);owner = uuid4();enriched = []
    async def evidence(connection, items):
        assert connection is conn
        enriched.extend(item["id"] for item in items)
        for item in items:
            value = {"B": 500, "B2": 500, "A": 500, "Z": 900, "U": None}[item["inventory_code"]]
            item["reference_value"] = {"status": "AVAILABLE" if value else "UNAVAILABLE", "market_value_minor": value}
            item["market_value_minor"] = value
        return items
    monkeypatch.setattr(sorting, "add_shared_reference_values", evidence)
    page = await sorting.inventory_value_page(conn,"i.owner_id=$1 and p.game=$2",[owner,"Pokemon"],2,1,grouped=True,descending=True)
    assert enriched == [item["id"] for item in rows]
    assert page.total == 4 and page.copy_total == 5
    # Z is above this page; A wins a deterministic tie before the whole B pair.
    assert page.ids == [rows[2]["id"],rows[0]["id"],rows[1]["id"]]
    assert conn.calls[0][1] == (owner,"Pokemon",sorting.MAX_VALUE_SORT_COPIES+1)
    returned = [dict(row,market_value_minor=999999) for row in [rows[2],rows[0],rows[1]]]
    page.apply(returned)
    assert [row["market_value_minor"] for row in returned] == [500,500,500]


@pytest.mark.asyncio
@pytest.mark.parametrize("descending,expected", [(True,["historical","guide","current","unknown"]),(False,["current","guide","historical","unknown"])])
async def test_labels_and_missing_values_keep_their_display_meaning(monkeypatch, descending, expected):
    rows = [copy(code) for code in ["unknown","current","historical","guide"]]
    now = datetime.now(timezone.utc)
    async def evidence(connection, items):
        values = {
            "unknown": {"reference_value": {"status":"UNAVAILABLE"}},
            "current": {"reference_value": {"status":"AVAILABLE","market_value_minor":200}},
            "historical": {"reference_value": {"status":"STALE","last_known_minor":1000,"checked_at":now}},
            "guide": {"reference_value": {"status":"NEEDS_DETAILS"},"catalogue_reference":{"status":"CONDITION_REFERENCE","market_value_minor":500}},
        }
        for item in items:
            item.update(values[item["inventory_code"]])
        return items
    monkeypatch.setattr(sorting,"add_shared_reference_values",evidence)
    page = await sorting.inventory_value_page(Candidates(rows),"i.owner_id=$1 and p.game=$2",[uuid4(),"Pokemon"],10,0,grouped=False,descending=descending)
    assert [page.snapshots[str(identifier)]["inventory_code"] for identifier in page.ids] == expected
    assert page.snapshots[str(rows[2]["id"])]["reference_value"]["status"] == "STALE"


@pytest.mark.asyncio
async def test_actual_shared_evidence_resolver_replaces_old_copy_values_before_sort():
    rows = [copy("cached-high",market_value_minor=999999),copy("evidence-high",market_value_minor=1),copy("no-evidence",market_value_minor=888888)]
    now = datetime.now(timezone.utc)
    snapshots = [dict(snapshot_id=uuid4(), catalogue_id=row["catalogue_id"], basis_condition="Near Mint",
        basis_language="English",grading_company=None,grade=None,seal_status=None,
        market_value_minor=value,recommended_retail_minor=value,confidence=1,
        evidence_checked_at=now-timedelta(hours=1),oldest_sale_at=now-timedelta(days=1),calculated_at=now-timedelta(hours=1),
        algorithm_version="drop-rate-market-v4",method="CATALOGUE_EBAY_V4",limitation=None,
        input_sale_count="5",book_identity_digest=None,reference_current=True)
        for row,value in zip(rows,[100,900])]
    class Connection:
        async def fetch(self, sql, *params):
            if sql == REFERENCE_VALUES_SQL:
                assert set(params[0]) == {item["catalogue_id"] for item in rows}
                return snapshots
            if sql == PRODUCTS_SQL:
                return []
            assert "where i.owner_id=$1" in sql and "i.market_value_minor" not in sql
            return deepcopy(rows)
    page = await sorting.inventory_value_page(Connection(),"i.owner_id=$1",[uuid4()],1,0,grouped=True,descending=True)
    assert page.ids == [rows[1]["id"]]
    returned=[deepcopy(rows[1])];page.apply(returned)
    assert returned[0]["market_value_minor"] == 900
    assert returned[0]["reference_value"]["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_oversize_selection_errors_before_enrichment_instead_of_partial_ranking(monkeypatch):
    monkeypatch.setattr(sorting,"MAX_VALUE_SORT_COPIES",2)
    async def unexpected(*args):
        raise AssertionError("Oversize selections must not start valuation work")
    monkeypatch.setattr(sorting,"add_shared_reference_values",unexpected)
    with pytest.raises(HTTPException) as error:
        await sorting.inventory_value_page(Candidates([copy("a"),copy("b"),copy("c")]),"i.owner_id=$1 and p.game=$2",[uuid4(),"Pokemon"],1,0,grouped=True,descending=True)
    assert error.value.status_code == 422 and "filter" in error.value.detail


@pytest.mark.parametrize("change", [{"version":3},{"condition":"Lightly Played"},{"language":"Japanese"},{"catalogue_id":None}])
def test_concurrent_physical_edits_fail_before_mismatched_value_is_displayed(change):
    row=copy("A");page=sorting.ValueSortedPage(1,1,[row["id"]],{str(row["id"]):row})
    with pytest.raises(HTTPException) as error:
        page.apply([dict(row,**change)])
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        page.apply([])


def test_malformed_history_has_no_numeric_display_and_unknown_is_not_zero():
    assert sorting.displayed_value_minor({"reference_value":{"status":"STALE","last_known_minor":1000,"checked_at":"invalid"}}) is None
    assert sorting.displayed_value_minor({"reference_value":{"status":"NEEDS_DETAILS"},"market_value_minor":999999}) is None


@pytest.mark.asyncio
async def test_bulk_enrichment_queries_unique_catalogues_in_batches_not_each_copy():
    now=datetime.now(timezone.utc);rows=[];snapshots={};calls=[]
    for index in range(250):
        product=uuid4()
        for number in range(2):
            row=copy(f"INV-{index:04}-{number}",str(product));row["catalogue_id"]=product;rows.append(row)
        snapshots[product]=dict(snapshot_id=uuid4(),catalogue_id=product,basis_condition="Near Mint",
            basis_language="English",grading_company=None,grade=None,seal_status=None,
            market_value_minor=100+index,recommended_retail_minor=100+index,
            evidence_checked_at=now-timedelta(hours=1),oldest_sale_at=now-timedelta(days=1),
            calculated_at=now-timedelta(hours=1),algorithm_version="drop-rate-market-v4",
            method="CATALOGUE_EBAY_V4",input_sale_count="5",reference_current=True)
    class Connection:
        async def fetch(self,sql,*params):
            calls.append((sql,params))
            if sql==REFERENCE_VALUES_SQL:
                assert len(params[0])<=100
                return [snapshots[identifier] for identifier in params[0]]
            assert "where i.owner_id=$1" in sql
            return deepcopy(rows)
    page=await sorting.inventory_value_page(Connection(),"i.owner_id=$1",[uuid4()],5,0,grouped=True,descending=True)
    assert page.total==250 and page.copy_total==500 and len(page.ids)==10
    assert len(calls)==4, "One owned candidate read + three shared evidence batches for 250 unique catalogues"
    assert [len(params[0]) for sql,params in calls if sql==REFERENCE_VALUES_SQL]==[100,100,50]
    assert sorted({sorting.displayed_value_minor(row) for row in page.snapshots.values()})==[345,346,347,348,349]


@pytest.mark.asyncio
async def test_inventory_route_uses_readonly_snapshot_and_same_enriched_value(monkeypatch):
    owner,actor=uuid4(),uuid4();row=copy("A")
    snapshot=dict(row,market_value_minor=1200,reference_value={"status":"AVAILABLE","market_value_minor":1200})
    page=sorting.ValueSortedPage(6,8,[row["id"]],{str(row["id"]):snapshot});calls=[]
    class Connection:
        async def fetch(self,sql,*params):
            calls.append((sql,params))
            assert "i.owner_id=$1" in sql and "i.id=any($2::uuid[])" in sql
            assert params==(owner,[row["id"]])
            return [{key:value for key,value in dict(row,market_value_minor=999999).items() if key!="display_key"}]
    connection=Connection()
    @asynccontextmanager
    async def scoped(pool,user_id,request_id,*,readonly_snapshot=False):
        assert user_id==actor and readonly_snapshot is True
        yield connection
    async def sorted_page(conn,where,params,limit,offset,*,grouped,descending):
        assert conn is connection and where=="i.owner_id=$1 and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')" and params==[owner]
        assert (limit,offset,grouped,descending)==(1,2,True,True)
        return page
    async def artwork(conn,items):
        return items
    async def no_recalculation(*args,**kwargs):
        raise AssertionError("The selected page must reuse the exact evidence snapshot used to sort")
    monkeypatch.setattr(owner_portal_api,"user_connection",scoped)
    monkeypatch.setattr(owner_portal_api,"inventory_value_page",sorted_page)
    monkeypatch.setattr(owner_portal_api,"add_reference_artwork",artwork)
    monkeypatch.setattr(owner_portal_api,"add_shared_inventory_media",artwork)
    monkeypatch.setattr(owner_portal_api,"add_shared_reference_values",no_recalculation)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),state=SimpleNamespace(request_id="test"))
    result=await owner_portal_api.owner_inventory(request,SimpleNamespace(user_id=actor),
        {"owner_id":owner,"display_name":"Synthetic owner","owner_type":"CONSIGNOR"},
        search=None,status=None,limit=1,offset=2,group_copies=True,category="",game="",language="",
        grading="",format="",listing_state="",prepare_selling=False,sort="value_desc",include_facets=False)
    assert result["total"]==6 and result["copy_total"]==8
    assert result["items"][0]["market_value_minor"]==1200
    assert "display_key" not in result["items"][0] and len(calls)==1
