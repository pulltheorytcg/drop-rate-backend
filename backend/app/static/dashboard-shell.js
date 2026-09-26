"use strict";

const SELLER_VIEWS = [
  ["dashboard", "Dashboard"],
  ["inventory", "Inventory"],
  ["verification", "Verify"],
  ["media", "Media"],
  ["sales", "Sales"],
  ["reports", "Reports"],
  ["balance", "Balance"],
  ["settings", "Settings"],
];

function sellerView(name) {
  return document.querySelector(`[data-seller-view="${name}"]`);
}

function makeSellerHeading(eyebrow, title, description) {
  const heading = document.createElement("div");
  heading.className = "page-heading seller-view-heading";
  heading.innerHTML = `<div><p class="eyebrow"></p><h1></h1><p class="muted"></p></div>`;
  heading.querySelector(".eyebrow").textContent = eyebrow;
  heading.querySelector("h1").textContent = title;
  heading.querySelector(".muted").textContent = description;
  return heading;
}

function moveFinanceSections(sales, reports, balance) {
  const finance = byId("founder-finance-panel");
  if (!finance) return;

  const originalHeading = finance.querySelector(":scope > .page-heading");
  const balanceHeading = makeSellerHeading(
    "Founder finance",
    "Balance",
    "Available and pending balance, payout requests and withdrawal history."
  );
  if (originalHeading) {
    const actions = originalHeading.querySelector(".topbar-actions");
    if (actions) balanceHeading.append(actions);
    originalHeading.remove();
  }
  balance.append(balanceHeading);

  const grids = Array.from(finance.querySelectorAll(":scope > .stats-grid"));
  if (grids[0]) balance.append(grids[0]);
  if (grids[1]) {
    reports.append(makeSellerHeading("Performance", "Reports", "Revenue, cost of goods, fees, shipping and realised profit."));
    reports.append(grids[1]);
  }

  const settlementSection = byId("finance-settlement-section");
  if (settlementSection) reports.append(settlementSection);

  const financeMessage = byId("finance-message");
  if (financeMessage) balance.append(financeMessage);

  const salesBody = byId("finance-sales-body");
  if (salesBody) {
    sales.append(makeSellerHeading("Sales ledger", "Sales", "Every physical item sold, with its cost basis, fees and realised profit."));
    const salesTable = salesBody.closest(".table-wrap");
    const salesHeading = salesTable?.previousElementSibling;
    if (salesHeading?.classList.contains("page-heading")) salesHeading.remove();
    if (salesTable) sales.append(salesTable);
    const salesEmpty = byId("finance-sales-empty");
    if (salesEmpty) sales.append(salesEmpty);
  }

  const payoutBody = byId("finance-payouts-body");
  if (payoutBody) {
    const payoutTable = payoutBody.closest(".table-wrap");
    const payoutHeading = payoutTable?.previousElementSibling;
    if (payoutHeading?.classList.contains("page-heading")) balance.append(payoutHeading);
    if (payoutTable) balance.append(payoutTable);
    const payoutsEmpty = byId("finance-payouts-empty");
    if (payoutsEmpty) balance.append(payoutsEmpty);
  }

  finance.classList.add("hidden");
  finance.setAttribute("aria-hidden", "true");
}

function buildSellerViews(content) {
  const existing = byId("seller-views");
  if (existing) return existing;

  const views = document.createElement("div");
  views.id = "seller-views";
  views.className = "seller-views";
  SELLER_VIEWS.forEach(([key]) => {
    const section = document.createElement("section");
    section.id = `seller-view-${key}`;
    section.className = "seller-view hidden";
    section.dataset.sellerView = key;
    section.setAttribute("aria-labelledby", `seller-tab-${key}`);
    views.append(section);
  });
  content.append(views);
  return views;
}

function buildSellerNav() {
  if (byId("seller-nav")) return;
  const dashboard = byId("dashboard-view");
  const topbar = dashboard?.querySelector(".topbar");
  if (!dashboard || !topbar) return;

  const nav = document.createElement("nav");
  nav.id = "seller-nav";
  nav.className = "seller-nav";
  nav.setAttribute("aria-label", "Founder dashboard sections");
  nav.setAttribute("role", "tablist");
  SELLER_VIEWS.forEach(([key, label]) => {
    const button = document.createElement("button");
    button.id = `seller-tab-${key}`;
    button.type = "button";
    button.className = "seller-nav-tab";
    button.dataset.targetView = key;
    button.textContent = label;
    button.setAttribute("aria-controls", `seller-view-${key}`);
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => activateSellerView(key, true));
    nav.append(button);
  });
  topbar.insertAdjacentElement("afterend", nav);
}

function activateSellerView(name, updateHash = false) {
  const valid = SELLER_VIEWS.some(([key]) => key === name) ? name : "dashboard";
  document.querySelectorAll("[data-seller-view]").forEach((section) => {
    const active = section.dataset.sellerView === valid;
    section.classList.toggle("hidden", !active);
    section.setAttribute("aria-hidden", active ? "false" : "true");
  });
  document.querySelectorAll(".seller-nav-tab").forEach((button) => {
    const active = button.dataset.targetView === valid;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });
  if (updateHash) history.replaceState(null, "", `#${valid}`);
  if (valid === "settings") loadPricingAdapterStatus();
}

function buildPortfolioIntelligencePanel() {
  const existing = byId("portfolio-intelligence-panel");
  if (existing) return existing;

  const section = document.createElement("section");
  section.id = "portfolio-intelligence-panel";
  section.className = "inventory-panel portfolio-intelligence-panel";
  section.innerHTML = `
    <div class="page-heading portfolio-intelligence-heading">
      <div>
        <p class="eyebrow">Inventory intelligence</p>
        <h2>Portfolio value</h2>
        <p class="muted">Current market position, highest-value stock and genuine 7-day market movement.</p>
      </div>
    </div>
    <div class="stats-grid portfolio-value-grid">
      <article class="stat-card">
        <span>Inventory market value</span>
        <strong id="portfolio-market-value">—</strong>
        <small id="portfolio-market-coverage">Current physical stock</small>
      </article>
      <article class="stat-card">
        <span>Store price value</span>
        <strong id="portfolio-store-value">—</strong>
        <small id="portfolio-store-coverage">Sellable asking value</small>
      </article>
    </div>
    <div class="portfolio-insight-grid">
      <section class="portfolio-insight-card">
        <div class="portfolio-insight-heading">
          <div><p class="eyebrow">Highest value</p><h3>Top 5 products</h3></div>
        </div>
        <div id="top-valuable-list" class="allocation-list">
          <p class="muted portfolio-empty">Loading value ranking…</p>
        </div>
      </section>
      <section class="portfolio-insight-card">
        <div class="portfolio-insight-heading">
          <div><p class="eyebrow">7-day change</p><h3>Weekly top movers</h3></div>
        </div>
        <div id="weekly-movers-list" class="allocation-list">
          <p class="muted portfolio-empty">Building price history…</p>
        </div>
      </section>
    </div>
  `;
  return section;
}


function buildShopifyReadinessPanel() {
  const existing = byId("shopify-readiness-panel");
  if (existing) return existing;

  const section = document.createElement("section");
  section.id = "shopify-readiness-panel";
  section.className = "inventory-panel portfolio-intelligence-panel";
  section.innerHTML = `
    <div class="page-heading portfolio-intelligence-heading">
      <div>
        <p class="eyebrow">Storefront pipeline</p>
        <h2>Shopify readiness</h2>
        <p class="muted">See how much unsynced stock has cleared the deterministic inventory gates and how much has the required approved media.</p>
      </div>
      <button id="shopify-readiness-refresh" class="ghost-button" type="button">↻ Refresh</button>
    </div>
    <div class="stats-grid portfolio-value-grid">
      <article class="stat-card">
        <span>Sellability ready</span>
        <strong id="shopify-operational-ready">—</strong>
        <small id="shopify-operational-coverage">Identity, condition, approval, cost, price and location</small>
      </article>
      <article class="stat-card">
        <span>Media ready</span>
        <strong id="shopify-media-ready">—</strong>
        <small id="shopify-media-coverage">Approved media policy satisfied</small>
      </article>
    </div>
    <div id="shopify-readiness-blockers" class="allocation-list">
      <p class="muted portfolio-empty">Loading Shopify readiness…</p>
    </div>
    <div class="toolbar">
      <button id="shopify-readiness-verify" class="ghost-button compact" type="button">Open Verify</button>
      <button id="shopify-readiness-media" class="primary-button compact" type="button">Open Media</button>
    </div>
    <p class="muted">This is a local readiness funnel only. Final Shopify completeness still re-checks media, shipping, collections, SEO, remote quantity and publication configuration before activation.</p>
  `;

  section.querySelector("#shopify-readiness-refresh")
    .addEventListener("click", () => loadShopifyReadiness());
  section.querySelector("#shopify-readiness-verify")
    .addEventListener("click", () => activateSellerView("verification", true));
  section.querySelector("#shopify-readiness-media")
    .addEventListener("click", () => {
      activateSellerView("media", true);
    });
  return section;
}

function appendShopifyReadinessBlockers(container, label, blockers) {
  const entries = Object.entries(blockers || {})
    .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]));
  if (!entries.length) return;

  const heading = document.createElement("div");
  heading.className = "portfolio-mover-label";
  heading.textContent = label;
  container.append(heading);

  entries.forEach(([blocker, count]) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = blocker;
    const note = document.createElement("small");
    note.textContent = label === "Core blockers"
      ? "Resolve in Verify / Inventory before Shopify."
      : "Resolve with approved founder or licensed media.";
    details.append(name, note);
    const total = document.createElement("strong");
    total.textContent = Number(count || 0).toLocaleString("en-GB");
    row.append(details, total);
    container.append(row);
  });
}

async function loadShopifyReadiness() {
  if (!state.session?.access_token || !byId("shopify-readiness-panel")) return;
  const container = byId("shopify-readiness-blockers");
  try {
    const data = await apiRequest("/api/v1/shopify/readiness");
    const considered = Number(data.considered || 0);
    const operationalReady = Number(data.operational_ready || 0);
    const mediaReady = Number(data.media_ready || 0);

    byId("shopify-operational-ready").textContent = operationalReady.toLocaleString("en-GB");
    byId("shopify-media-ready").textContent = mediaReady.toLocaleString("en-GB");
    byId("shopify-operational-coverage").textContent =
      `${operationalReady.toLocaleString("en-GB")} of ${considered.toLocaleString("en-GB")} unsynced items pass core gates`;
    byId("shopify-media-coverage").textContent =
      `${mediaReady.toLocaleString("en-GB")} of ${operationalReady.toLocaleString("en-GB")} core-ready items satisfy media policy`;

    container.replaceChildren();
    appendShopifyReadinessBlockers(container, "Core blockers", data.operational_blockers);
    appendShopifyReadinessBlockers(container, "Media blockers", data.media_blockers);
    if (!container.children.length) {
      const ready = document.createElement("p");
      ready.className = "muted portfolio-empty";
      ready.textContent = considered
        ? "All currently unsynced stock has cleared the local core and media gates."
        : "No unsynced inventory is waiting in the local Shopify pipeline.";
      container.append(ready);
    }
  } catch (error) {
    byId("shopify-operational-ready").textContent = "—";
    byId("shopify-media-ready").textContent = "—";
    container.textContent = `Shopify readiness could not be loaded: ${error.message}`;
  }
}

function portfolioIdentityMeta(item) {
  const grade = item.grading_company && item.grade
    ? `${item.grading_company} ${item.grade}`
    : item.condition;
  return [
    item.set_name,
    item.card_number,
    item.language,
    grade,
    Number(item.quantity || 0) > 1 ? `${item.quantity} copies` : null,
  ].filter(Boolean).join(" · ");
}

function renderTopValuable(items) {
  const container = byId("top-valuable-list");
  if (!container) return;
  container.replaceChildren();
  if (!items?.length) {
    const empty = document.createElement("p");
    empty.className = "muted portfolio-empty";
    empty.textContent = "No Market Values are available yet.";
    container.append(empty);
    return;
  }

  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "allocation-row portfolio-ranking-row";

    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = `#${index + 1} ${item.name}`;
    const meta = document.createElement("small");
    meta.textContent = portfolioIdentityMeta(item);
    details.append(name, meta);

    const value = document.createElement("div");
    value.className = "portfolio-value-stack";
    const perUnit = document.createElement("strong");
    perUnit.textContent = money(item.market_value_minor);
    const holding = document.createElement("small");
    holding.textContent = Number(item.quantity || 0) > 1
      ? `${money(item.holding_value_minor)} holding value`
      : "Market Value";
    value.append(perUnit, holding);

    row.append(details, value);
    container.append(row);
  });
}

function moverRow(item, direction) {
  const row = document.createElement("div");
  row.className = "allocation-row portfolio-mover-row";

  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = item.name;
  const meta = document.createElement("small");
  meta.textContent = portfolioIdentityMeta(item);
  details.append(name, meta);

  const value = document.createElement("div");
  value.className = "portfolio-value-stack";
  const change = document.createElement("strong");
  change.className = direction === "up" ? "mover-up" : "mover-down";
  const pct = Math.abs(Number(item.change_pct || 0)).toFixed(1);
  change.textContent = `${direction === "up" ? "▲" : "▼"} ${pct}%`;
  const prices = document.createElement("small");
  prices.textContent = `${money(item.prior_market_value_minor)} → ${money(item.current_market_value_minor)}`;
  value.append(change, prices);

  row.append(details, value);
  return row;
}

function renderWeeklyMovers(data, windowDays) {
  const container = byId("weekly-movers-list");
  if (!container) return;
  container.replaceChildren();

  if (!data?.history_ready) {
    const empty = document.createElement("div");
    empty.className = "portfolio-history-empty";
    const title = document.createElement("strong");
    title.textContent = "Building genuine price history";
    const note = document.createElement("small");
    note.textContent = `Weekly movers will appear once a real ${windowDays}-day Market Value baseline exists. We do not manufacture movement from today's backfill.`;
    empty.append(title, note);
    container.append(empty);
    return;
  }

  const gainers = data.gainers || [];
  const decliners = data.decliners || [];
  if (!gainers.length && !decliners.length) {
    const empty = document.createElement("p");
    empty.className = "muted portfolio-empty";
    empty.textContent = "No Market Value changes were recorded across the comparison window.";
    container.append(empty);
    return;
  }

  if (gainers.length) {
    const label = document.createElement("div");
    label.className = "portfolio-mover-label";
    label.textContent = "Top risers";
    container.append(label, ...gainers.map((item) => moverRow(item, "up")));
  }
  if (decliners.length) {
    const label = document.createElement("div");
    label.className = "portfolio-mover-label";
    label.textContent = "Top fallers";
    container.append(label, ...decliners.map((item) => moverRow(item, "down")));
  }
}

async function loadPortfolioIntelligence() {
  if (!state.session?.access_token) return;
  const marketValue = byId("portfolio-market-value");
  if (!marketValue) return;
  try {
    const data = await apiRequest("/api/v1/inventory/intelligence?top_limit=5&window_days=7");
    const totals = data.totals || {};
    byId("portfolio-market-value").textContent = money(totals.inventory_market_value_minor || 0);
    byId("portfolio-store-value").textContent = money(totals.inventory_store_value_minor || 0);
    byId("portfolio-market-coverage").textContent =
      `${Number(totals.market_valued_item_count || 0).toLocaleString("en-GB")} of ${Number(totals.active_inventory_count || 0).toLocaleString("en-GB")} active items valued`;
    byId("portfolio-store-coverage").textContent =
      `${Number(totals.store_priced_item_count || 0).toLocaleString("en-GB")} active items priced`;
    renderTopValuable(data.top_valuable || []);
    renderWeeklyMovers(data.weekly_movers || {}, Number(data.window_days || 7));
  } catch (error) {
    byId("portfolio-market-value").textContent = "—";
    byId("portfolio-store-value").textContent = "—";
    const top = byId("top-valuable-list");
    const movers = byId("weekly-movers-list");
    if (top) top.textContent = "Inventory intelligence could not be loaded.";
    if (movers) movers.textContent = error.message;
  }
}

function populateSellerViews() {
  const content = byId("dashboard-view")?.querySelector(".dashboard-content");
  if (!content || content.dataset.tabbed === "true") return;

  const originalChildren = Array.from(content.children);
  buildSellerViews(content);
  const overview = sellerView("dashboard");
  const inventory = sellerView("inventory");
  const verification = sellerView("verification");
  const sales = sellerView("sales");
  const reports = sellerView("reports");
  const balance = sellerView("balance");
  const settings = sellerView("settings");

  const inventoryHeading = originalChildren.find((node) => node.classList?.contains("page-heading"));
  const inventoryStats = originalChildren.find((node) => node.classList?.contains("stats-grid"));
  const actionPanel = originalChildren.find((node) => node.classList?.contains("action-panel"));
  const locations = byId("storage-locations-section");
  const lots = byId("purchase-lots-list")?.closest('[aria-labelledby="lots-heading"]');
  const inventoryPanel = Array.from(content.querySelectorAll(":scope > .inventory-panel")).find((node) => !node.id && node !== lots);

  overview.append(makeSellerHeading("Founder overview", "Dashboard", "Your stock position and action-required snapshot."));
  if (inventoryStats) overview.append(inventoryStats);
  overview.append(buildPortfolioIntelligencePanel());
  overview.append(buildShopifyReadinessPanel());
  if (actionPanel) overview.append(actionPanel);

  if (inventoryHeading) {
    const eyebrow = inventoryHeading.querySelector(".eyebrow");
    const title = inventoryHeading.querySelector("h1");
    const muted = inventoryHeading.querySelector(".muted");
    if (eyebrow) eyebrow.textContent = "Stock operations";
    if (title) title.textContent = "Inventory";
    if (muted) muted.textContent = "Add, import, locate, cost and approve every physical item.";
    inventory.append(inventoryHeading);
  }
  if (locations) inventory.append(locations);
  if (lots) inventory.append(lots);
  if (inventoryPanel) inventory.append(inventoryPanel);

  verification.append(makeSellerHeading(
    "Identity control",
    "Verify stock",
    "Physically confirm canonical card identity before pricing, approval or Shopify publishing."
  ));

  moveFinanceSections(sales, reports, balance);

  settings.append(makeSellerHeading("Configuration", "Settings", "Pricing automation and future storefront integrations are controlled here."));
  const pricingCard = document.createElement("section");
  pricingCard.className = "inventory-panel";
  pricingCard.innerHTML = `
    <div class="page-heading">
      <div><p class="eyebrow">Market pricing</p><h2>Pricing engine</h2><p class="muted">Provider evidence flows into Drop Rate first. Store Price is never silently overwritten; future Shopify publishing remains behind pricing policy guardrails.</p></div>
    </div>
    <div id="pricing-adapter-status" class="allocation-list"><p class="muted">Open Settings while signed in to check provider readiness.</p></div>
    <div class="page-heading pricing-subheading">
      <div><p class="eyebrow">Recent calculations</p><h2>Pricing outputs</h2><p class="muted">Latest Market Value and Recommended Retail calculations stored by the backend.</p></div>
    </div>
    <div id="pricing-output-list" class="allocation-list"><p class="muted">No pricing calculations loaded yet.</p></div>`;
  settings.append(pricingCard);

  originalChildren.forEach((node) => {
    if (node.parentElement !== content || node.id === "seller-views" || node.id === "founder-finance-panel") return;
    node.remove();
  });
  content.dataset.tabbed = "true";
}

function pricingStatusText(adapter, ingestionEnabled = false) {
  const adapterState = adapter.status === "ACCESS_REQUIRED"
    ? "Access required"
    : ingestionEnabled
      ? adapter.status
      : "DIAGNOSTIC ONLY";
  const parts = [adapterState];
  parts.push(`${adapter.verified_mapping_count || 0} verified mappings`);
  parts.push(`${adapter.observation_count || 0} observations`);
  if (adapter.latest_run?.status) parts.push(`last run: ${adapter.latest_run.status}`);
  return parts.join(" · ");
}

async function loadPricingAdapterStatus() {
  const container = byId("pricing-adapter-status");
  const output = byId("pricing-output-list");
  if (!container || !output || !state.session?.access_token) return;
  try {
    const [marketData, pricingData] = await Promise.all([
      apiRequest("/api/v1/market/status"),
      apiRequest("/api/v1/pricing/inventory?limit=8&offset=0"),
    ]);

    container.replaceChildren();
    (marketData.items || []).forEach((adapter) => {
      const row = document.createElement("div");
      row.className = "allocation-row";
      const details = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = adapter.source;
      const note = document.createElement("small");
      note.textContent = adapter.note;
      details.append(name, note);
      const stateLabel = document.createElement("small");
      stateLabel.textContent = pricingStatusText(adapter, Boolean(marketData.ingestion_enabled));
      row.append(details, stateLabel);
      container.append(row);
    });

    output.replaceChildren();
    const priced = (pricingData.items || []).filter((item) => item.pricing_updated_at);
    if (!priced.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No pricing snapshots yet. Calculations will appear after market observations are available.";
      output.append(empty);
    } else {
      priced.forEach((item) => {
        const row = document.createElement("div");
        row.className = "allocation-row";
        const details = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = item.name;
        const note = document.createElement("small");
        const sourceText = item.source_count ? `${item.source_count} sources` : "No source count";
        const confidenceText = item.confidence === null || item.confidence === undefined
          ? "No confidence"
          : `${Math.round(Number(item.confidence) * 100)}% confidence`;
        note.textContent = [item.set_name, item.card_number, sourceText, confidenceText].filter(Boolean).join(" · ");
        details.append(name, note);
        const prices = document.createElement("strong");
        prices.textContent = `${money(item.market_value_minor)} market · ${money(item.recommended_retail_minor)} retail`;
        row.append(details, prices);
        output.append(row);
      });
    }
  } catch (error) {
    container.textContent = error.message;
    output.textContent = "Pricing status could not be loaded.";
  }
}

function ensureSellerDashboardShell() {
  if (!byId("dashboard-view") || byId("seller-nav")) return;
  buildSellerNav();
  populateSellerViews();
  const requested = location.hash.replace(/^#/, "");
  activateSellerView(requested || "dashboard");
}

const previousReloadDashboardForShell = reloadDashboard;
reloadDashboard = async function (...args) {
  const result = await previousReloadDashboardForShell(...args);
  await Promise.all([loadPricingAdapterStatus(), loadPortfolioIntelligence(), loadShopifyReadiness()]);
  return result;
};

window.addEventListener("hashchange", () => activateSellerView(location.hash.replace(/^#/, "") || "dashboard"));
window.addEventListener("DOMContentLoaded", ensureSellerDashboardShell);
ensureSellerDashboardShell();
