"use strict";
// Render the real owner/founder weekly panels using synthetic, owner-scoped
// API responses. No provider access, live accounts or price calculations.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {JSDOM} = require("jsdom");
const base = path.join(__dirname, "../../backend/app/static");

function setup(kind) {
  const owner = kind === "owner";
  const markup = owner ? fs.readFileSync(path.join(base, "owner.html"), "utf8")
    .replace(/<script[^>]*><\/script>/g, "") : "<!doctype html><body></body>";
  const dom = new JSDOM(markup, {url: "https://fixture.test/" + (owner ? "owner" : "app"), runScripts: "outside-only"});
  const w = dom.window, context = dom.getInternalVMContext();
  const run = (code) => vm.runInContext(code, context);
  w.fetch = async () => { throw new Error("Unexpected external or provider request"); };
  if (owner) {
    const source = fs.readFileSync(path.join(base, "owner-portal.js"), "utf8")
      .replace(/\ninitialise\(\);\s*$/, "");
    vm.runInContext(source, context);
  } else {
    w.byId = (id) => w.document.getElementById(id);
    w.money = (minor) => new Intl.NumberFormat("en-GB", {style: "currency", currency: "GBP"}).format(minor / 100);
    w.state = {session: {access_token: "synthetic-session"}};
    // Only disable the unrelated page bootstrap; exercise complete production
    // renderer definitions and their actual generated panel markup.
    const source = fs.readFileSync(path.join(base, "dashboard-shell.js"), "utf8")
      .split("const previousReloadDashboardForShell = reloadDashboard;")[0];
    vm.runInContext(source, context);
    run("document.body.append(buildPortfolioIntelligencePanel())");
  }
  const requests = [];
  w.weeklyFixtureRequest = async (url, options) => {
    requests.push({url, options});
    const expected = owner ? "/api/v1/owner/insights" : "/api/v1/inventory/intelligence?top_limit=5&window_days=7";
    assert.equal(url, expected, "Use only the existing owner-scoped endpoint");
    assert.ok(!options?.method || options.method === "GET", "Rendering must not write or trigger a price refresh");
    return w.weeklyFixtureResponse;
  };
  run("apiRequest = window.weeklyFixtureRequest");
  return {
    dom, requests,
    container: () => w.document.getElementById(owner ? "owner-weekly-movers" : "weekly-movers-list"),
    rows: () => [...w.document.querySelectorAll(owner ? "#owner-weekly-movers .owner-insight-row" : ".portfolio-mover-row")],
    async render(summary, gainers = [], decliners = []) {
      w.weeklyFixtureResponse = owner ? {
        top_valued: [], weekly_movers: [...gainers, ...decliners], weekly_window_days: 7, weekly_movers_summary: summary,
      } : {
        totals: {}, top_valuable: [], window_days: 7,
        weekly_movers: {...summary, gainers, decliners},
      };
      const before = JSON.stringify(w.weeklyFixtureResponse);
      await run(owner ? "loadOwnerInsights()" : "loadPortfolioIntelligence()");
      assert.equal(JSON.stringify(w.weeklyFixtureResponse), before, "Presentation must not alter price evidence");
      return this.container().textContent;
    },
  };
}

const summary = (status, extra = {}) => ({
  status, scope: "OWN_COLLECTION", window_days: 7, window_tolerance_days: 1,
  as_of: "2026-11-03T12:00:00Z", owned_item_count: 12, current_value_item_count: 8,
  current_value_product_count: 5, comparable_product_count: 2, comparable_item_count: 5,
  mover_product_count: 2, unchanged_product_count: 0, waiting_for_history_product_count: 3,
  needs_details_item_count: 1, stale_item_count: 1, guide_comparison_count: 1,
  history_ready: true, earliest_baseline_at: "2026-10-27T06:00:00Z", latest_current_at: "2026-11-03T12:00:00Z",
  ...extra,
});
const row = (extra = {}) => ({
  inventory_id: "00000000-0000-4000-8000-000000000001", inventory_code: "FIXTURE-1",
  name: "Exact printing", game: "Pokemon", set_name: "Synthetic set", card_number: "001/100",
  language: "English", condition: "Near Mint", quantity: 3, status: "DRAFT",
  current_value_minor: 1250, baseline_value_minor: 1000,
  current_market_value_minor: 1250, prior_market_value_minor: 1000,
  change_minor: 250, change_pct: "25.00", current_at: "2026-11-03T12:00:00Z",
  baseline_at: "2026-10-27T06:00:00Z", comparison_days: 7.25,
  comparison_kind: "GUIDE_ESTIMATE", comparison_label: "Guide estimate change", method: "CATALOGUE_CARDMARKET_V1",
  ...extra,
});

(async () => {
  let checks = 0;
  for (const kind of ["owner", "founder"]) {
    const fixture = setup(kind);
    try {
      let text = await fixture.render(summary("EMPTY_COLLECTION", {
        owned_item_count: 0, current_value_item_count: 0, current_value_product_count: 0,
        comparable_item_count: 0, comparable_product_count: 0, guide_comparison_count: 0,
        stale_item_count: 0, needs_details_item_count: 0, history_ready: false,
      }));
      assert.match(text, /Your collection is empty/);
      assert.equal(fixture.rows().length, 0);
      assert.doesNotMatch(text, /£0|0%|backfill|whole catalogue/i);
      checks++;

      text = await fixture.render(summary("NO_CURRENT_VALUES", {
        current_value_item_count: 0, current_value_product_count: 0, comparable_item_count: 0,
        comparable_product_count: 0, guide_comparison_count: 0, stale_item_count: 3,
        needs_details_item_count: 2, history_ready: false,
      }));
      assert.match(text, /No current values to compare/);
      assert.match(text, /3 copies have stale evidence/);
      assert.match(text, /Details need confirming for 2 copies/);
      assert.doesNotMatch(text, /£0|0%|No change in comparable values/);
      checks++;

      text = await fixture.render(summary("WAITING_FOR_HISTORY", {
        owned_item_count: 106, current_value_item_count: 6, current_value_product_count: 4,
        comparable_product_count: 0, comparable_item_count: 0, guide_comparison_count: 0,
        stale_item_count: 0, needs_details_item_count: 6, history_ready: false,
      }));
      assert.match(text, /Not enough weekly history/);
      assert.match(text, /6 of 106 copies have current values across 4 distinct items/);
      assert.match(text, /Comparable weekly history covers 0 of 106 copies/);
      assert.doesNotMatch(text, /No current values to compare|No change in comparable values|will appear|backfill/);
      checks++;

      text = await fixture.render(summary("NO_CHANGE", {mover_product_count: 0, unchanged_product_count: 2}));
      assert.match(text, /No change in comparable values/);
      assert.match(text, /only items with matching history/);
      assert.match(text, /5 of 12 copies/);
      assert.match(text, kind === "owner" ? /1 comparison is estimated from Cardmarket data/ : /1 comparison uses a guide estimate/);
      assert.match(text, /27 Oct 2026 to 3 Nov 2026/);
      assert.equal(fixture.rows().length, 0);
      checks++;

      const guide = row();
      const sold = row({
        name: "Another exact printing", quantity: 2, condition: null, grading_company: "PSA", grade: "10",
        current_value_minor: 4500, baseline_value_minor: 5000,
        current_market_value_minor: 4500, prior_market_value_minor: 5000,
        change_minor: -500, change_pct: -10, comparison_kind: "SOLD_MARKET",
        comparison_label: "Market value change", method: "CATALOGUE_EBAY_V4",
      });
      text = await fixture.render(summary("READY"), [guide], [sold]);
      const rows = fixture.rows();
      assert.equal(rows.length, 2, "Grouped copies must not be duplicated in the browser");
      assert.match(text, /Changes are shown only for comparable items in your collection/);
      assert.match(rows[0].textContent, kind === "owner" ? /Market value change · Cardmarket/ : /Guide estimate change · Cardmarket/);
      assert.match(rows[0].textContent, /27 Oct 2026 → 3 Nov 2026 · 7\.25 days/);
      assert.match(rows[0].textContent, /25%/);
      assert.match(rows[0].textContent, /\+£2\.50 per copy/);
      assert.match(rows[0].textContent, kind === "owner" ? /Qty 3/ : /3 copies/);
      assert.doesNotMatch(rows[0].textContent, /75%|£7\.50/);
      assert.match(rows[1].textContent, /Market value change · eBay sold evidence/);
      assert.match(rows[1].textContent, /PSA 10/);
      assert.match(rows[1].textContent, /-£5\.00 per copy/);
      assert.doesNotMatch(text, /CATALOGUE_|LIVE_EBAY|SHARED_CATALOGUE/);
      checks++;

      // Display the supplied change; never infer a percentage from amounts.
      text = await fixture.render(summary("READY"), [row({change_pct: "12.34"})]);
      assert.match(fixture.rows()[0].textContent, /12\.34%/);
      assert.doesNotMatch(fixture.rows()[0].textContent, /25%/);
      checks++;

      // Penny changes on high-value items round to 0.00%, but are still real
      // movement. Use the supplied exact delta for direction and do not show
      // a flat 0% or invent a more precise percentage.
      for (const difference of [1, -1]) {
        const tiny = row({
          baseline_value_minor: 1000000, prior_market_value_minor: 1000000,
          current_value_minor: 1000000 + difference, current_market_value_minor: 1000000 + difference,
          change_minor: difference, change_pct: 0,
        });
        text = await fixture.render(summary("READY"), difference > 0 ? [tiny] : [], difference < 0 ? [tiny] : []);
        const movement = fixture.rows()[0].querySelector(kind === "owner" ? ".owner-movement" : ".portfolio-value-stack strong");
        assert.equal(movement.textContent, `${kind === "owner" ? (difference > 0 ? "↑" : "↓") : (difference > 0 ? "▲" : "▼")} <0.01%`);
        assert.ok(movement.classList.contains(kind === "owner" ? (difference > 0 ? "up" : "down") : (difference > 0 ? "mover-up" : "mover-down")));
        assert.match(fixture.rows()[0].textContent, difference > 0 ? /\+£0\.01 per copy/ : /-£0\.01 per copy/);
        assert.doesNotMatch(fixture.rows()[0].textContent, /(?:→|▲|▼|↑|↓) 0%|NaN/);
        checks++;
      }

      text = await fixture.render(summary("READY"), [row({
        current_value_minor: null, current_market_value_minor: null, prior_market_value_minor: null,
        change_pct: null, change_minor: null, method: null, comparison_label: null,
        comparison_kind: null, baseline_at: "invalid", current_at: null, comparison_days: null,
      })]);
      assert.match(text, /Change unavailable/);
      assert.match(text, /Amount unavailable/);
      assert.match(text, /Source unavailable/);
      assert.match(text, /Evidence dates unavailable/);
      assert.doesNotMatch(fixture.rows()[0].textContent, /£0|0%|NaN|Invalid Date/);
      checks++;

      text = await fixture.render(summary("READY"), [row({
        name: '<img src="x" onerror="alert(1)">', comparison_label: '<b data-injected="yes">Guide estimate change</b>',
      })]);
      // Shared UI ignores provider labels; the legacy dashboard renders them as plain text.
      if (kind === "owner") assert.doesNotMatch(text, /<b data-injected="yes">/);
      else assert.match(text, /<b data-injected="yes">/);
      assert.match(text, kind === "owner" ? /Market value change/ : /Guide estimate change/);
      assert.equal(fixture.container().querySelector('[data-injected="yes"]'), null);
      assert.equal(fixture.container().querySelector('img[src="x"]'), null);
      checks++;

      // A later owner-scoped empty response replaces the previously shown copy.
      text = await fixture.render(summary("EMPTY_COLLECTION", {
        owned_item_count: 0, current_value_item_count: 0, comparable_item_count: 0,
        current_value_product_count: 0, guide_comparison_count: 0, stale_item_count: 0,
        needs_details_item_count: 0, history_ready: false,
      }));
      assert.equal(fixture.rows().length, 0);
      assert.doesNotMatch(text, /Exact printing|Another exact printing|data-injected|Cardmarket/);
      checks++;
      assert.equal(fixture.requests.length, 11);
    } finally {
      fixture.dom.window.close();
    }
  }
  console.log(`Weekly movers UI: ${checks} owner/founder states, exact evidence labels/dates, grouped per-copy changes and read-only response scenarios passed.`);
})().catch((error) => { console.error(error); process.exitCode = 1; });

