from pathlib import Path

import app.shopify_readiness as readiness


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "backend" / "app" / "shopify_readiness.py"
DASHBOARD = ROOT / "backend" / "app" / "static" / "dashboard-shell.js"


def item(code: str, *, missing: list[str] | None = None, media_ready: bool = False) -> dict:
    return {
        "id": code,
        "inventory_code": code,
        "name": f"Card {code}",
        "card_number": "001/100",
        "status": "APPROVED",
        "missing": list(missing or []),
        "media_ready": media_ready,
    }


def test_local_readiness_summary_separates_core_and_media_blockers(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness,
        "_test_sync_missing",
        lambda row: list(row["missing"]),
    )
    monkeypatch.setattr(
        readiness,
        "build_shopify_product_plan",
        lambda row: {"mediaPolicy": "RAW_CARD"},
    )
    monkeypatch.setattr(
        readiness,
        "_media_assets_for_item",
        lambda row, assets: [{"ready": row["media_ready"]}],
    )
    monkeypatch.setattr(
        readiness,
        "media_completeness",
        lambda policy, assets: {
            "blockers": [] if assets[0]["ready"] else ["canonical FRONT media"]
        },
    )

    result = readiness.summarize_local_readiness(
        [
            item("READY", media_ready=True),
            item("MEDIA", media_ready=False),
            item("VERIFY", missing=["identity confirmation", "card language"]),
        ],
        [],
    )

    assert result["considered"] == 3
    assert result["operational_ready"] == 2
    assert result["operational_blocked"] == 1
    assert result["operational_blockers"] == {
        "identity confirmation": 1,
        "card language": 1,
    }
    assert result["media_ready"] == 1
    assert result["media_blocked"] == 1
    assert result["media_blockers"] == {"canonical FRONT media": 1}
    assert result["next_operational_items"][0]["inventory_code"] == "VERIFY"
    assert result["next_media_items"][0]["inventory_code"] == "MEDIA"


def test_local_readiness_endpoint_is_owner_scoped_and_has_no_publish_path() -> None:
    source = SOURCE.read_text()

    assert '@router.get("/readiness")' in source
    assert "where i.owner_id=$1" in source
    assert "sil.id is null" in source
    assert "lim.id is null" in source
    assert "_test_sync_missing" in source
    assert "media_completeness" in source
    assert '"network_calls"] = 0' in source
    assert '"publication_actions"] = 0' in source
    assert "ShopifyAdminClient" not in source
    assert "_client()" not in source
    assert "publish_product" not in source


def test_dashboard_exposes_shopify_readiness_without_publish_controls() -> None:
    js = DASHBOARD.read_text()

    assert "/api/v1/shopify/readiness" in js
    assert "Shopify readiness" in js
    assert "Core ready" in js
    assert "Media ready" in js
    assert "Open Verify" in js
    assert "Open Media" in js

    start = js.index("async function loadShopifyReadiness()")
    end = js.index("function portfolioIdentityMeta", start)
    block = js[start:end]
    assert "test-sync" not in block
    assert "publish" not in block.casefold()
    assert "POST" not in block
