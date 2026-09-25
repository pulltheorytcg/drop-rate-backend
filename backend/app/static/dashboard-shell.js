"use strict";

const SELLER_VIEWS = [
  ["dashboard", "Dashboard"],
  ["inventory", "Inventory"],
  ["verification", "Verify"],
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
  await loadPricingAdapterStatus();
  return result;
};

window.addEventListener("hashchange", () => activateSellerView(location.hash.replace(/^#/, "") || "dashboard"));
window.addEventListener("DOMContentLoaded", ensureSellerDashboardShell);
ensureSellerDashboardShell();
