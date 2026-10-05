from datetime import datetime, timezone
from decimal import Decimal

from app.ebay_sold_pricing import SoldComparable
from app.social_market_evidence import (
    TARGETS,
    matches_target,
    select_newest_exact_comps,
    summarise_exact_market,
)


def target(key):
    return next(item for item in TARGETS if item.key == key)


def row(item_id, title, price="100.00", date="2026-10-01T12:00:00Z"):
    return {
        "item_id": item_id,
        "title": title,
        "date_sold": date,
        "sale_price": price,
        "shipping_price": "5.00",
        "item_link": "https://www.ebay.co.uk/itm/" + item_id,
    }


def test_umbreon_raw_rejects_graded_and_non_english():
    raw = target("umbreon_vmax_215_raw")
    assert matches_target(
        row("1", "Umbreon VMAX 215/203 Evolving Skies Alt Art English NM"),
        raw,
    )
    assert not matches_target(
        row("2", "Umbreon VMAX 215/203 Evolving Skies PSA 10"),
        raw,
    )
    assert not matches_target(
        row("3", "Umbreon VMAX 215/203 Evolving Skies Korean"),
        raw,
    )


def test_umbreon_psa10_requires_psa_and_10():
    psa = target("umbreon_vmax_215_psa10")
    assert matches_target(
        row("1", "Umbreon VMAX 215/203 Evolving Skies PSA 10 GEM MINT"),
        psa,
    )
    assert not matches_target(
        row("2", "Umbreon VMAX 215/203 Evolving Skies PSA 9"),
        psa,
    )


def test_goku_p2_requires_strong_super_alt_marker():
    raw = target("goku_fb01_139_p2_raw")
    accepted = (
        "Son Goku FB01-139 Super Alt Art SCR English",
        "Son Goku FB01-139 Super Alternate Art English",
        "Son Goku FB01-139 GDR God Rare English",
        "Son Goku FB01-139 2 Star Ghost English",
    )
    for index, title in enumerate(accepted):
        assert matches_target(row(str(index), title), raw)

    # Ordinary SCR-star alternate art must never leak into the p2 bucket.
    assert not matches_target(
        row("x", "Son Goku FB01-139 SCR* Alternate Art English NM"),
        raw,
    )


def test_goku_psa10_rejects_japanese_and_raw():
    psa = target("goku_fb01_139_p2_psa10")
    assert matches_target(
        row("1", "PSA 10 Son Goku FB01-139 SCR Super Alternate Art ENG 2 Star"),
        psa,
    )
    assert not matches_target(
        row("2", "Son Goku FB01-139 Super Alternate Art English"),
        psa,
    )
    assert not matches_target(
        row("3", "PSA 10 Son Goku FB01-139 Super Alt Art Japanese"),
        psa,
    )


def test_newest_exact_comps_dedupes_and_caps_at_five():
    raw = target("umbreon_vmax_215_raw")
    rows = [
        row(
            str(i),
            "Umbreon VMAX 215/203 Evolving Skies Alternate Art English",
            price=str(100 + i),
            date=f"2026-09-{20+i:02d}T12:00:00Z",
        )
        for i in range(1, 7)
    ]
    rows.append(dict(rows[-1]))
    payload = {"currency": "GBP", "results": rows}
    comps = select_newest_exact_comps(payload, target=raw)
    assert len(comps) == 5
    assert comps[0].item_id == "6"
    assert len({comp.item_id for comp in comps}) == 5


def test_summary_abstains_below_five():
    raw = target("umbreon_vmax_215_raw")
    comps = [
        SoldComparable(
            item_id=str(i),
            title="fixture",
            sold_at=datetime(2026, 10, i + 1, tzinfo=timezone.utc),
            price_minor=10000 + i * 100,
            shipping_minor=500,
            condition_raw=None,
            url=None,
        )
        for i in range(4)
    ]
    result = summarise_exact_market(
        raw,
        comps,
        usd_to_gbp_rate=Decimal("0.75"),
        fx_effective_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
        fx_retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["market_value_gbp_minor"] is None
    assert result["market_value_usd_minor"] is None


def test_summary_uses_median_and_auditable_fx():
    raw = target("umbreon_vmax_215_raw")
    prices = [10000, 20000, 30000, 40000, 1000000]
    comps = [
        SoldComparable(
            item_id=str(i),
            title="fixture",
            sold_at=datetime(2026, 10, i + 1, tzinfo=timezone.utc),
            price_minor=price,
            shipping_minor=None,
            condition_raw=None,
            url=None,
        )
        for i, price in enumerate(prices)
    ]
    result = summarise_exact_market(
        raw,
        comps,
        usd_to_gbp_rate=Decimal("0.75"),
        fx_effective_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
        fx_retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    assert result["status"] == "READY"
    assert result["market_value_gbp_minor"] == 30000
    assert result["market_value_usd_minor"] == 40000
