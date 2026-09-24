"use strict";

const MARKET_SMOKE_CASES = [
  {
    id: "pokemon-raw-normal",
    label: "Pokémon raw · Absol 063/094 · Normal",
    source: "EBAY",
    catalogue_id: "5cc2da17-f1f8-4add-8e53-ef78237ec689",
    source_variant_id: "Normal",
    mapping: {
      query: "Absol 063/094",
      required_title_terms: ["Absol", "063/094"],
      forbidden_title_terms: ["reverse", "graded", "PSA", "CGC", "BGS", "proxy", "custom", "digital"],
      language: "English",
      include_sold: false,
      include_active: true,
    },
  },
  {
    id: "pokemon-raw-reverse",
    label: "Pokémon raw · Absol 063/094 · Reverse Holofoil",
    source: "EBAY",
    catalogue_id: "62a2d049-cebb-4c14-a7db-e7f3bd63af58",
    source_variant_id: "Reverse Holofoil",
    mapping: {
      query: "Absol 063/094 Reverse",
      required_title_terms: ["Absol", "063/094", "Reverse"],
      forbidden_title_terms: ["graded", "PSA", "CGC", "BGS", "proxy", "custom", "digital"],
      language: "English",
      include_sold: false,
      include_active: true,
    },
  },
  {
    id: "pokemon-graded",
    label: "Pokémon graded · Charizard V 019/189 · PSA 9",
    source: "EBAY",
    catalogue_id: "9e4574cf-00e5-4739-a576-822caefd547e",
    source_variant_id: "Holofoil",
    mapping: {
      query: "Charizard V 019/189",
      required_title_terms: ["Charizard V", "019/189"],
      forbidden_title_terms: ["proxy", "custom", "digital"],
      grading_company: "PSA",
      grade: "9",
      language: "English",
      include_sold: false,
      include_active: true,
    },
  },
  {
    id: "one-piece-raw",
    label: "One Piece raw · Monkey.D.Luffy OP05-119 · SEC",
    source: "EBAY",
    catalogue_id: "0a9e70d9-fd75-4ec5-9837-673fc0a97014",
    source_variant_id: "Foil",
    mapping: {
      query: "Luffy OP05-119",
      required_title_terms: ["Monkey D Luffy", "OP05-119", "SEC"],
      forbidden_title_terms: ["SR", "manga", "parallel", "alternate", "alt art", "anniversary", "wanted", "reprint", "premium booster", "the best", "PSA", "CGC", "BGS", "proxy", "custom", "digital"],
      language: "English",
      include_sold: false,
      include_active: true,
    },
  },
  {
    id: "one-piece-graded",
    label: "One Piece graded · Monkey.D.Luffy ST10-006 · PSA 9",
    source: "EBAY",
    catalogue_id: "a36d35d2-2e34-4483-8ee0-fee1e4674b10",
    source_variant_id: "Foil",
    mapping: {
      query: "Luffy ST10-006",
      required_title_terms: ["Monkey D Luffy", "ST10-006", "3rd Anniversary"],
      forbidden_title_terms: ["proxy", "custom", "digital"],
      grading_company: "PSA",
      grade: "9",
      language: "English",
      include_sold: false,
      include_active: true,
    },
  },
  {
    id: "one-piece-collection-ace",
    label: "One Piece packaged · Tin Pack Set Vol. 2 -Portgas.D.Ace-",
    blocked: "Missing seal_status in inventory. Provider query deliberately skipped until physical seal state is confirmed.",
  },
  {
    id: "one-piece-collection-premium",
    label: "One Piece packaged · Premium Card Collection -6 assort vol.1-",
    blocked: "Missing seal_status in inventory. Provider query deliberately skipped until physical seal state is confirmed.",
  },
];

function marketSmokeResultRow(testCase) {
  const row = document.createElement("div");
  row.className = "allocation-row";
  row.dataset.smokeCase = testCase.id;

  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = testCase.label;
  const note = document.createElement("small");
  note.textContent = testCase.blocked ? testCase.blocked : "Waiting to run";
  details.append(name, note);

  const status = document.createElement("small");
  status.textContent = testCase.blocked ? "BLOCKED · safe" : "Pending";
  row.append(details, status);
  return row;
}

function describeSmokeResult(data) {
  if (data.status === "FAILED") {
    return data.error?.detail || "Provider test failed safely.";
  }
  if (data.status === "BLOCKED") {
    return "No exact matching observations returned. Nothing was persisted.";
  }
  const counts = data.counts_by_type || {};
  const countText = Object.entries(counts).map(([type, count]) => `${count} ${type}`).join(" · ") || "0 observations";
  const range = data.price_summary_gbp;
  const priceText = range
    ? `${money(range.min_minor)} min · ${money(range.median_minor)} median · ${money(range.max_minor)} max`
    : "No price range";
  return `${countText} · ${priceText}`;
}

async function runMarketSmokeMatrix() {
  const button = byId("market-smoke-run");
  const results = byId("market-smoke-results");
  if (!button || !results || !state.session?.access_token) return;

  button.disabled = true;
  button.dataset.label ||= button.textContent;
  button.textContent = "Testing live market data…";

  results.replaceChildren(...MARKET_SMOKE_CASES.map(marketSmokeResultRow));

  for (const testCase of MARKET_SMOKE_CASES) {
    if (testCase.blocked) continue;
    const row = results.querySelector(`[data-smoke-case="${testCase.id}"]`);
    const note = row?.querySelector("div small");
    const status = row?.querySelector(":scope > small");
    if (note) note.textContent = "Calling live provider…";
    if (status) status.textContent = "Running";

    try {
      const data = await apiRequest(`/api/v1/market/smoke-test/${testCase.source}`, {
        method: "POST",
        body: JSON.stringify({
          catalogue_id: testCase.catalogue_id,
          source_product_id: JSON.stringify(testCase.mapping),
          source_variant_id: testCase.source_variant_id,
        }),
      });
      if (note) {
        note.textContent = describeSmokeResult(data);
        const sampleTitle = data.samples?.[0]?.title;
        if (sampleTitle) note.textContent += ` · sample: ${sampleTitle}`;
      }
      if (status) status.textContent = `${data.status} · ${data.observation_count || 0} observations`;
    } catch (error) {
      if (note) note.textContent = error.message;
      if (status) status.textContent = "FAILED safely";
    }
  }

  button.disabled = false;
  button.textContent = button.dataset.label;
}

function providerProbeRow(item) {
  const row = document.createElement("div");
  row.className = "allocation-row";

  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = item.label;
  const note = document.createElement("small");
  const sample = item.samples?.[0];
  const sampleName = sample?.title || sample?.name || sample?.product_name || sample?.card_name || "";
  note.textContent = item.error?.detail || `${item.result_count || 0} results${sampleName ? ` · sample: ${sampleName}` : ""}`;
  details.append(name, note);

  const status = document.createElement("small");
  status.textContent = item.status;
  row.append(details, status);
  return row;
}

async function runProviderProbe() {
  const button = byId("market-provider-probe-run");
  const results = byId("market-provider-probe-results");
  if (!button || !results || !state.session?.access_token) return;

  button.disabled = true;
  button.dataset.label ||= button.textContent;
  button.textContent = "Probing providers…";
  results.textContent = "Calling official eBay UK active plus supporting providers…";

  try {
    const data = await apiRequest("/api/v1/market/provider-probe", {method: "POST"});
    results.replaceChildren(...(data.results || []).map(providerProbeRow));
  } catch (error) {
    results.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = button.dataset.label;
  }
}

function installMarketSmokePanel() {
  if (byId("market-smoke-panel")) return;
  const settings = byId("seller-view-settings");
  if (!settings) return;

  const panel = document.createElement("section");
  panel.id = "market-smoke-panel";
  panel.className = "inventory-panel";
  panel.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Live validation</p>
        <h2>Market data smoke tests</h2>
        <p class="muted">Fetch live official eBay UK active-listing evidence for a small mixed sample without adding observations or changing Market Value. This validates OAuth, EBAY_GB routing and deterministic identity matching. Sold-history access remains a separate restricted capability and is never inferred from active listings.</p>
      </div>
      <div class="topbar-actions">
        <button id="market-smoke-run" class="primary-button" type="button">Run smoke tests</button>
      </div>
    </div>
    <div id="market-smoke-results" class="allocation-list"></div>
    <div class="page-heading" style="margin-top: 1rem;">
      <div>
        <p class="eyebrow">Provider isolation</p>
        <h3>Cross-provider live probe</h3>
        <p class="muted">Runs non-persistent provider checks. eBay active uses the official Browse API; sold-history availability is reported separately. Cardmarket, TCGPlayer and Collectr remain independent provider checks.</p>
      </div>
      <div class="topbar-actions">
        <button id="market-provider-probe-run" class="secondary-button" type="button">Probe providers</button>
      </div>
    </div>
    <div id="market-provider-probe-results" class="allocation-list"></div>`;
  settings.append(panel);

  const results = byId("market-smoke-results");
  results.replaceChildren(...MARKET_SMOKE_CASES.map(marketSmokeResultRow));
  byId("market-smoke-run").addEventListener("click", runMarketSmokeMatrix);
  byId("market-provider-probe-run").addEventListener("click", runProviderProbe);
}

window.addEventListener("DOMContentLoaded", installMarketSmokePanel);
installMarketSmokePanel();