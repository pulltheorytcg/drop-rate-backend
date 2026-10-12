"""Temporary feature-branch source preparation; removed before PR review.

These are exact text edits to existing modules, not a new runtime or migration.
Each complete source file is checksum-checked before any file is written.
"""
import hashlib
from pathlib import Path

EXPECTED = {
 'backend/app/inventory_reference_values.py':'e47961808f320c400084fa12441190724dd1bd46105454d5e12e6bc7a0f1d8de',
 'backend/app/owner_portal_api.py':'242cdc3d3ee2c67a41e905471291b62818bd29f7f2ae1697a967e9199beca0bb',
 'backend/app/static/reference-value-display.js':'7ee161b0bca0e003b571a51841323c9da54735415b6836f9529cec05edbb620f',
 'backend/app/static/owner.html':'4cfb4d996be4beacf2a12e571683835849b31052fd6a74ca65788745504bf457',
 'backend/app/static/owner-portal.js':'986d2c3b08e2a755d0ccc82e99911c8cf1574257943ed23c1633b9bdf0d4535b',
 'backend/app/static/owner-inventory.js':'aa05fb50ac2813ac0ebbfd5e2c0827d119b20a336b5fb7824752f2fdaa0868b2',
 'backend/app/main.py':'a1ab66b5166e1d583800b5f5751e7596c9fc84f6796757b866d84344de0288f3',
}
texts = {}
for path, expected in EXPECTED.items():
    raw=Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected, path
    texts[path]=raw.decode()
def edit(path, old, new):
    assert texts[path].count(old)==1,(path,old[:70])
    texts[path]=texts[path].replace(old,new)

p='backend/app/inventory_reference_values.py'
edit(p,' s.grading_company,s.grade,s.seal_status,s.market_value_minor,s.confidence,',' s.grading_company,s.grade,s.seal_status,s.market_value_minor,s.recommended_retail_minor,s.confidence,')
edit(p,'from .language import clean_language','from .language import clean_language\nfrom .pricing_rules import MIN_STORE_PRICE_MINOR')
edit(p,'"market_value_minor": None, "last_known_minor": None, "snapshot_id": None,','"market_value_minor": None, "recommended_retail_minor": None, "last_known_minor": None, "snapshot_id": None,')
edit(p,'    else:\n        result.update(status="REFERENCE_ESTIMATE" if estimate else "AVAILABLE", market_value_minor=selected["market_value_minor"],','''    else:
        # Reuse the algorithm output from this SAME eligible snapshot. Never
        # infer it from an asking price, stale per-copy cache or another basis.
        recommended = selected.get("recommended_retail_minor")
        if type(recommended) is int and recommended >= MIN_STORE_PRICE_MINOR:
            result["recommended_retail_minor"] = recommended
        result.update(status="REFERENCE_ESTIMATE" if estimate else "AVAILABLE", market_value_minor=selected["market_value_minor"],''')
edit(p,'        item["market_value_minor"] = reference["market_value_minor"]\n        item["pricing_updated_at"]','        item["market_value_minor"] = reference["market_value_minor"]\n        item["recommended_retail_minor"] = reference["recommended_retail_minor"]\n        item["pricing_updated_at"]')
edit(p,'\ndef reference_top_groups(items, limit=5):','''
def recommended_totals(items):
    """Recommendations and private asking prices are separate, coverage-aware sums.

    Every input is an authorized physical record enriched by the shared resolver.
    Count copies, not catalogue groups; absent evidence is not a zero-price card.
    This function performs no calculation of a new price and no database writes.
    """
    eligible = [item for item in items
                if item.get("reference_value", {}).get("status") in {"AVAILABLE", "REFERENCE_ESTIMATE"}
                and type(item.get("recommended_retail_minor")) is int
                and item["recommended_retail_minor"] >= MIN_STORE_PRICE_MINOR]
    asking = [item["store_price_minor"] for item in items
              if type(item.get("store_price_minor")) is int and item["store_price_minor"] > 0]
    return {
        "active_inventory_count": len(items),
        "active_recommended_count": len(eligible),
        "active_unrecommended_count": len(items) - len(eligible),
        "active_recommended_retail_minor": sum(item["recommended_retail_minor"] for item in eligible) if eligible else None,
        "recommendation_guide_count": sum(item["reference_value"]["status"] == "REFERENCE_ESTIMATE" for item in eligible),
        "recorded_asking_count": len(asking),
        "recorded_asking_value_minor": sum(asking) if asking else None,
    }


def reference_top_groups(items, limit=5):''')
p='backend/app/owner_portal_api.py'
line=next(line for line in texts[p].splitlines() if line.startswith('from .inventory_reference_values import'))
edit(p,line,line+', recommended_totals')
edit(p,'        refs = reference_totals(await reference_portfolio(connection, [owner_id]))\n        summary = dict(summary)','        shared = await reference_portfolio(connection, [owner_id])\n        refs = reference_totals(shared)\n        summary = dict(summary)\n        summary.update(recommended_totals(shared))')
p='backend/app/static/reference-value-display.js'
edit(p,'  description(item) {','''  recommendedMinor(item) {
    const ref = item?.reference_value;
    return ref && ["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref.status)
      && Number.isInteger(ref.recommended_retail_minor) && ref.recommended_retail_minor >= 100
      ? ref.recommended_retail_minor : null;
  },
  recommendationText(item, money) {
    const amount = this.recommendedMinor(item);
    return amount == null ? "Recommendation unavailable"
      : money(amount) + (item.reference_value.status === "REFERENCE_ESTIMATE" ? " · Guide estimate" : "");
  },
  description(item) {''')
p='backend/app/static/owner.html'
edit(p,'                <span>Store / recommended value</span>\n                <strong id="owner-store-value">—</strong>\n                <small>Live store price, or recommended retail while pending</small>','''                <span>Recommended retail</span>
                <strong id="owner-store-value">—</strong>
                <small id="owner-recommendation-note">Automatic recommendations where market evidence is available</small>
                <small id="owner-asking-price-note">Saved asking prices are separate from recommendations</small>''')
for old,new in [('reference-value-display.js?v=shared-v1','reference-value-display.js?v=recommendation-v2'),('owner-inventory.js?v=shared-reference-v10','owner-inventory.js?v=recommendation-v11'),('owner-portal.js?v=shared-reference-v21','owner-portal.js?v=recommendation-v22'),('owner-portal.css?v=owner-v14','owner-portal.css?v=recommendation-v15')]:edit(p,old,new)
edit('backend/app/main.py','reference-value-display.js?v=shared-v1','reference-value-display.js?v=recommendation-v2')
p='backend/app/static/owner-portal.js'
edit(p,'  byId("owner-market-value-note").textContent = unvalued','  byId("owner-market-value").classList.toggle("owner-value-unavailable", Boolean(unvalued && !valued));\n  byId("owner-market-value-note").textContent = unvalued')
edit(p,'  byId("owner-store-value").textContent = formatMoney(\n    summary.active_store_value_minor ?? summary.active_store_price_minor\n  );','''  // Do not mix saved asking prices into the automatic recommendation total.
  // An older response without the new fields must not fall back to that sum.
  const activeCount = Number.isInteger(summary.active_inventory_count) ? summary.active_inventory_count : total;
  const recommendedCount = Number(summary.active_recommended_count || 0);
  const recommendationTotal = summary.active_recommended_retail_minor;
  byId("owner-store-value").textContent = activeCount === 0 ? formatMoney(0)
    : recommendedCount > 0 && Number.isInteger(recommendationTotal) && recommendationTotal > 0
      ? formatMoney(recommendationTotal) : "Unavailable";
  byId("owner-store-value").classList.toggle("owner-value-unavailable", activeCount > 0 && !(recommendedCount > 0 && Number.isInteger(recommendationTotal) && recommendationTotal > 0));
  const recommendationNote = byId("owner-recommendation-note");
  if (recommendationNote) recommendationNote.textContent = activeCount === 0
    ? "Add cards to see automatic recommendations"
    : `Automatic · ${recommendedCount} of ${activeCount} copies priced`
      + (summary.recommendation_guide_count ? ` · ${summary.recommendation_guide_count} guide estimate${summary.recommendation_guide_count === 1 ? "" : "s"}` : "");
  const askingNote = byId("owner-asking-price-note");
  if (askingNote) askingNote.textContent = summary.recorded_asking_count > 0
    && Number.isInteger(summary.recorded_asking_value_minor)
    ? `Saved asking prices: ${formatMoney(summary.recorded_asking_value_minor)} (${summary.recorded_asking_count} copies)`
    : "No asking prices saved · nothing listed by this calculation";''')
edit(p,'      store.textContent = item.store_value_minor == null\n        ? "Store value pending"\n        : "Store / recommended " + formatMoney(item.store_value_minor);','      store.textContent = "Recommended retail: " +\n        (window.DropRateReferenceValue?.recommendationText(item, formatMoney) || "Recommendation unavailable");')
p='backend/app/static/owner-inventory.js'
edit(p,'    content.append(values);\n\n    const publishedOnShopify','''    content.append(values);
    const recommended = window.DropRateReferenceValue?.recommendedMinor(item) ?? null;
    const recommendationNote = el("p", "owner-item-note",
      "Recommended retail: " + (window.DropRateReferenceValue?.recommendationText(item, formatMoney) || "Recommendation unavailable"));
    recommendationNote.dataset.recommendedRetail = "true";
    content.append(recommendationNote);

    const publishedOnShopify''')
edit(p,'    priceInput.value = item.store_price_minor == null ? "" : (item.store_price_minor / 100).toFixed(2);','''    const initialPrice = item.store_price_minor ?? recommended;
    priceInput.value = initialPrice == null ? "" : (initialPrice / 100).toFixed(2);
    let suggestionPrefilled = item.store_price_minor == null && recommended != null;
    priceInput.addEventListener("input", () => { suggestionPrefilled = false; });
    if (saleCondition) saleCondition.addEventListener("change", () => {
      const guide = item.reference_value?.status === "REFERENCE_ESTIMATE";
      const sameBasis = guide ? ["", "Near Mint"].includes(saleCondition.value)
        : saleCondition.value === (item.condition || "");
      if (!sameBasis && suggestionPrefilled) { priceInput.value = ""; suggestionPrefilled = false; }
      if (!sameBasis) recommendationNote.textContent = "Recorded-condition recommendation does not apply to the newly selected condition.";
    });''')
edit(p,'    priceLabel.append(priceInput); sale.append(priceLabel);','''    priceLabel.append(priceInput); sale.append(priceLabel);
    if (recommended != null) sale.append(el("p", "owner-item-note",
      item.store_price_minor == null
        ? "Suggested automatically from current shared evidence. Nothing is saved or listed until you choose a selling action."
        : "Your saved asking price is retained. The automatic recommendation does not overwrite it."));''')
for path,text in texts.items():Path(path).write_text(text)
# Add only a scoped missing-value type treatment, never a new layout.
p=Path('backend/app/static/owner-portal.css');text=p.read_text()
assert 'owner-value-unavailable' not in text
p.write_text(text+'\n/* Readable missing-value labels within the existing compact mobile KPI grid. */\n.owner-portal-page .owner-kpi-card>strong.owner-value-unavailable{font-size:1rem;line-height:1.25;overflow-wrap:anywhere}\n')
p=Path('BUILD_STATUS.md');text=p.read_text();p.write_text('''## Current correction — automatic retail recommendation summary (12 October 2026)

Recommendations now reuse the same eligible algorithm snapshot as the shared market value, rather than an empty per-copy cache. Overview sums recommendations independently of saved asking prices, with explicit copy/guide coverage; item details show and prefill eligible suggestions without overwriting chosen prices or publishing. Null/stale/wrong-profile evidence never becomes a guessed recommendation. Existing daily catalogue jobs already run; no new provider, scheduler, service, migration, rate-limit bypass or stock/price/ownership/finance backfill. #609 shared imagery and #608 collection-first intent are preserved. See docs/AUTOMATIC_RETAIL_RECOMMENDATIONS.md; exact tests, deployment and live readback belong in the release comment. This entry alone is not acceptance evidence.

'''+text)
