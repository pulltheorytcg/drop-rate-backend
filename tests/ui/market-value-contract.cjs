"use strict";
// Market-value selection must never substitute a saved selling price or retail multiplier.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../backend/app/static/reference-value-display.js"), "utf8"), context);
const values = context.window.DropRateReferenceValue;
const money = amount => "GBP " + (amount / 100).toFixed(2);
let checks = 0;
for (const status of ["AVAILABLE", "REFERENCE_ESTIMATE", "CONDITION_REFERENCE", "CATALOGUE_GUIDE"]) {
  const item = {market_value_minor: 100, store_price_minor: 4000, recommended_retail_minor: 9900,
    reference_value: {status, market_value_minor: 1200, recommended_retail_minor: 9900,
      label: "Guide estimate", reason: "Cardmarket trend evidence", basis: "Raw"}};
  const original = JSON.stringify(item);
  assert.equal(values.label(item), "Market value");
  // Deliberately hostile legacy API fixture: every status carries the SAME
  // price, but without an explicit Cardmarket EU guide method only an
  // AVAILABLE source may display it (owner rule 1 labels EU guides only).
  if (status === "AVAILABLE") {
    assert.equal(values.text(item, money), "Value: GBP 12.00");
    assert.equal(values.marketMinor(item), 1200);
  } else {
    assert.equal(values.text(item, money), "Value unavailable");
    assert.equal(values.marketMinor(item), null);
  }
  if (status === "AVAILABLE") assert.match(values.description(item), /Cardmarket trend evidence/);
  else assert.equal(values.description(item), "", "Guide details are not current Market Value copy");
  assert.equal(JSON.stringify(item), original);
  checks++;
}
for (const status of ["STALE", "UNAVAILABLE", "NEEDS_DETAILS"]) {
  assert.equal(values.marketMinor({market_value_minor: 1200, reference_value: {status, market_value_minor: 1200}}), null);
  checks++;
}
for (const item of [
  {store_price_minor: 1200, recommended_retail_minor: 1200},
  {market_value_minor: "1200", recommended_retail_minor: 1200},
  {market_value_minor: 0, store_price_minor: 1200},
]) {
  assert.equal(values.marketMinor(item), null);
  checks++;
}
assert.equal(values.marketMinor({market_value_minor: 19}), null,
  "A bare legacy amount without verified SOLD status is not Market Value");
checks++;
const model = {status: "CATALOGUE_GUIDE", method: "DROP_RATE_UK_EU_MARKET_V1", currency: "GBP",
  shipping_basis: "ITEM_ONLY", physical_valuation_eligible: false, estimate_minor: 1234,
  estimate_low_minor: 1100, estimate_high_minor: 1400, confidence: 0.6,
  observed_at: new Date(Date.now() - 60000).toISOString(),
  expires_at: new Date(Date.now() + 3600000).toISOString()};
assert.equal(values.marketMinor({catalogue_reference: model}), null, "Provisional eBay asking model is not Market Value");
assert.equal(values.label({catalogue_reference: model}), "Market value");
assert.equal(values.text({catalogue_reference: model}, money), "Value unavailable");
assert.equal(values.marketMinor({reference_value: {status: "AVAILABLE", market_value_minor: 900}, catalogue_reference: model}), 900);
checks++;
assert.equal(values.marketMinor({market_value_minor: 1234,
  catalogue_reference: {...model, expires_at: "2000-01-01T00:00:00Z"}}), null);
checks++;
const internalModel = {status:"CATALOGUE_GUIDE", method:"DROP_RATE_COMPUTED_MARKET_V1",market_value_minor:700};
assert.equal(values.marketMinor({catalogue_reference: internalModel}), null);
assert.equal(values.text({catalogue_reference: internalModel}, money), "Value unavailable");
checks++;
// Owner rule 1 (27 Nov 2026): a Cardmarket EU guide is a labelled estimate.
const guide = {status:"REFERENCE_ESTIMATE", method:"CATALOGUE_CARDMARKET_V1", market_value_minor:1200,
  recommended_retail_minor:9900, label:"Estimate · Cardmarket EU guide", reason:"r", basis:"Raw"};
assert.equal(values.text({reference_value: guide}, money), "Estimate: GBP 12.00 · Cardmarket EU guide");
assert.equal(values.marketMinor({reference_value: guide}), 1200, "Snapshot estimates count in totals");
assert.equal(values.displayReference({reference_value: guide}).recommended_retail_minor, null);
const range = {status:"CATALOGUE_GUIDE", method:"CARDMARKET_CATALOGUE_GUIDE", market_value_minor:500, market_value_high_minor:900};
assert.equal(values.text({catalogue_reference: range}, money), "Estimate: GBP 5.00–GBP 9.00 · Cardmarket EU guide");
assert.equal(values.marketMinor({catalogue_reference: range}), null, "Catalogue-wide ranges are display-only");
checks++;
// Owner rule 4: expired values show a dated last-known amount, never a current one.
const stale = {status:"STALE", market_value_minor:null, last_known_minor:1500, checked_at:"2026-11-01T10:00:00Z"};
assert.equal(values.marketMinor({reference_value: stale}), null);
assert.match(values.text({reference_value: stale}, money), /^Last known GBP 15\.00 · /);
assert.equal(values.isHistorical({reference_value: stale}), true);
checks++;
console.log(checks + " market-value source selection checks passed");

