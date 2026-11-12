"""FastAPI integration boundaries for eBay signed-in research, without a DB/provider."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import ebay_signed_in_research_api as api


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
OWNER = UUID("22222222-2222-4222-8222-222222222222")
INVENTORY = UUID("33333333-3333-4333-8333-333333333333")
CODE = "INV-3B801C9CE17B48DEA1EE0DD8AB38EA25"
ROOT = Path(__file__).resolve().parents[1]


def canonical(**kwargs):
    target = {
        "game": "Pokemon",
        "name": "Charmander",
        "set_name": "Phantasmal Flames",
        "card_number": "011/094",
        "variant": "Normal",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "language": "English",
    }
    target.update(kwargs)
    return target


def request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="research-test-request"),
    )


def actor():
    return SimpleNamespace(user_id=ACTOR)


def reviewed_rows(target=None, *, now=None):
    target = target or canonical()
    now = now or datetime.now(timezone.utc)
    return [{
        "source": "EBAY_PRODUCT_RESEARCH",
        "sale_price_basis": "ACTUAL_PAID_PRICE",
        "item_id": str(123456789000 + i),
        "title": f"Pokemon Charmander 011/094 Phantasmal Flames Near Mint",
        "sold_at": (now - timedelta(days=i + 1)).date().isoformat(),
        "price_gbp": str(i + 2) + ".00",
        "shipping_gbp": None,
        "currency": "GBP",
        "item_country": "GB",
        "condition_raw": "Near Mint",
        "set_name": target["set_name"],
        "card_number": target["card_number"],
        "variant": target["variant"],
        "language": target["language"],
    } for i in range(5)]


def install_fake_owner_read(monkeypatch, *, exists=True, target=None):
    calls = {"read_only": [], "read_queries": [], "pricing": 0}
    target = target or canonical()

    class Connection:
        async def fetchval(self, sql, owner_id, inventory_code):
            calls["read_queries"].append((sql, owner_id, inventory_code))
            assert "owner_id=$1" in sql
            assert owner_id == OWNER
            return INVENTORY if exists and inventory_code == CODE else None

    @asynccontextmanager
    async def fake_user_connection(pool, user_id, request_id, *, readonly_snapshot=False):
        assert user_id == ACTOR
        calls["read_only"].append(readonly_snapshot)
        assert readonly_snapshot is True
        yield Connection()

    async def fake_owner(conn):
        return {"id": OWNER}

    async def fake_target(conn, owner_id, inventory_id):
        calls["pricing"] += 1
        assert owner_id == OWNER and inventory_id == INVENTORY
        return target

    monkeypatch.setattr(api, "user_connection", fake_user_connection)
    monkeypatch.setattr(api, "_owner", fake_owner)
    monkeypatch.setattr(api, "_target_snapshot", fake_target)
    return calls


@pytest.mark.asyncio
async def test_search_uses_read_only_owner_scope_and_returns_only_research_link(monkeypatch):
    calls = install_fake_owner_read(monkeypatch)
    result = await api.prepare_ebay_research(CODE, request(), actor())
    assert result["target"]["card_number"] == "011/094"
    assert result["sold_search_url"].startswith("https://www.ebay.co.uk/sch/i.html?")
    assert "LH_Sold=1" in result["sold_search_url"]
    assert result["automated_evidence_available"] is False
    assert result["can_change_market_value"] is False
    assert result["can_change_store_price"] is False
    assert result["can_change_shopify"] is False
    assert calls["read_only"] == [True]
    assert calls["pricing"] == 1


@pytest.mark.asyncio
async def test_wrong_or_other_owner_inventory_is_not_disclosed(monkeypatch):
    calls = install_fake_owner_read(monkeypatch, exists=False)
    with pytest.raises(HTTPException) as exc:
        await api.prepare_ebay_research(CODE, request(), actor())
    assert exc.value.status_code == 404
    assert calls["pricing"] == 0
    with pytest.raises(HTTPException) as invalid:
        await api.prepare_ebay_research("INV-invalid space", request(), actor())
    assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_five_reviewed_sales_can_preview_without_publishing(monkeypatch):
    calls = install_fake_owner_read(monkeypatch)
    body = api.ResearchPreviewBody(sales=reviewed_rows())
    result = await api.preview_ebay_research(CODE, body, request(), actor())
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["eligible_exact_count"] == 5
    assert result["candidate_median_item_price_minor"] == 400
    assert result["candidate_is_market_value"] is False
    assert result["evidence_is_verified_for_market_value"] is False
    assert result["database_writes"] is False
    assert result["shopify_writes"] is False
    assert result["existing_pricing_engine_not_invoked_for_publication"] is True
    assert calls["read_only"] == [True]
    assert "123456789000" not in str(result)


@pytest.mark.asyncio
async def test_wrong_language_sale_is_rejected(monkeypatch):
    install_fake_owner_read(monkeypatch)
    rows = reviewed_rows()
    rows[0]["title"] = "Pokemon Charmander 011/094 Japanese Near Mint"
    result = await api.preview_ebay_research(CODE, api.ResearchPreviewBody(sales=rows), request(), actor())
    assert result["eligible_exact_count"] == 4
    assert result["candidate_median_item_price_minor"] is None


@pytest.mark.parametrize("bad", [
    [{"title": "<div>"}],
    [{"buyer_name": "Do not store personal information"}],
    [{"title": "x" * 301}],
    [{"title": {"nested": "object"}}],
])
def test_input_allows_minimal_sale_evidence_only(bad):
    if bad == [{"title": "<div>"}]:
        # HTML-like text is permitted as plain text, never rendered via innerHTML.
        api._validate_review_rows(bad)
        return
    with pytest.raises(HTTPException) as err:
        api._validate_review_rows(bad)
    assert err.value.status_code == 422


def test_large_review_batch_is_rejected():
    rows = [{"title": "x" * 300} for _ in range(300)]
    with pytest.raises(HTTPException) as err:
        api._validate_review_rows(rows)
    assert err.value.status_code == 413


def test_seller_hub_includes_review_only_entry_point_not_apply_button():
    html = (ROOT / "backend/app/static/index.html").read_text()
    js = (ROOT / "backend/app/static/ebay-research-panel.js").read_text()
    main = (ROOT / "backend/app/main.py").read_text()
    assert 'id="ebay-research-lookup"' in html
    assert 'id="ebay-research-preview"' in html
    assert 'id="ebay-research-rows"' in html
    assert "ebay-research-panel.js" in main
    assert "ebay_research_router, dependencies=[Depends(require_platform_admin_request)]" in main
    assert "ebay-research/inventory/" in js
    assert "actual paid price" in js
    assert "innerHTML" not in js
    assert "market_value_minor=" not in js
    assert "store_price_minor=" not in js
