"use strict";

const SELLER_VIEWS = [
  ["dashboard", "Dashboard"],
  ["inventory", "Inventory"],
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

function moveFinanceSections(overview, sales, reports, balance) {
  const finance = byId("founder-finance-panel");
  if (!finance) return;

  const grids = Array.from(finance.querySelectorAll(":scope > .stats-grid"));
  if (grids[0]) overview.append(grids[0]);
  if (grids[1]) {
    reports.append(makeSellerHeading("Performance", "Reports", "Revenue, cost of goods, fees, shipping and realised profit."));
    reports.append(grids[1]);
  }

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

  balance.append(makeSellerHeading("Founder finance", "Balance", "Available and pending balance, payout requests and withdrawal history."));
  const financeMessage = byId("finance-message");
  if (financeMessage) balance.append(financeMessage);

  const payoutBody = byId("finance-payouts-body");
  if (payoutBody) {
    const payoutTable = payoutBody.closest(".table-wrap");
    const payoutHeading = payoutTable?.previousElementSibling;
    if (payoutHeading?.classList.contains("page-heading")) balance.append(payoutHeading);
    if (payoutTable) balance.append(payoutTable);
    const payoutsEmpty = byId("finance-payouts-empty");
    if (payoutsEmpty) balance.append(payoutsEmpty);
  }

  const originalHeading = finance.querySelector(":scope > .page-heading");
  if (originalHeading) {
    const actions = originalHeading.querySelector(".topbar-actions");
    if (actions) balance.querySelector(".seller-view-heading")?.append(actions);
    originalHeading.remove();
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
  SELLER_VIEWS.forEach(([key, label]) => {
    const button = document.createElement("button");
    button.id = `seller-tab-${key}`;
    button.type = "button";
    button.className = "seller-nav-tab";
    button.dataset.targetView = key;
    button.textContent = label;
    button.setAttribute("aria-controls", `seller-view-${key}`);
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
  });
  if (updateHash) history.replaceState(null, "", `#${valid}`);
}

function populateSellerViews() {
  const content = byId("dashboard-view")?.querySelector(".dashboard-content");
  if (!content || content.dataset.tabbed === "true") return;

  const originalChildren = Array.from(content.children);
  buildSellerViews(content);
  const overview = sellerView("dashboard");
  const inventory = sellerView("inventory");
  const sales = sellerView("sales");
  const reports = sellerView("reports");
  const balance = sellerView("balance");
  const settings = sellerView("settings");

  const inventoryHeading = originalChildren.find((node) => node.classList?.contains("page-heading"));
  const inventoryStats = originalChildren.find((node) => node.classList?.contains("stats-grid"));
  const actionPanel = originalChildren.find((node) => node.classList?.contains("action-panel"));
  const locations = byId("storage-locations-section");
  const lots = document.querySelector('[aria-labelledby="lots-heading"]');
  const inventoryPanel = Array.from(content.querySelectorAll(":scope > .inventory-panel")).find((node) => !node.id && node !== lots);

  overview.append(makeSellerHeading("Founder overview", "Dashboard", "Your stock, finance and action-required snapshot."));
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

  moveFinanceSections(overview, sales, reports, balance);

  settings.append(makeSellerHeading("Configuration", "Settings", "Pricing automation and future storefront integrations are controlled here."));
  const pricingCard = document.createElement("section");
  pricingCard.className = "inventory-panel";
  pricingCard.innerHTML = `
    <div class="page-heading">
      <div><p class="eyebrow">Market pricing</p><h2>Pricing engine</h2><p class="muted">The deterministic pricing engine is active in Drop Rate. Live marketplace adapters remain disabled until approved provider access is connected.</p></div>
    </div>
    <div id="pricing-adapter-status" class="allocation-list"><p class="muted">Open Settings while signed in to check provider readiness.</p></div>`;
  settings.append(pricingCard);

  originalChildren.forEach((node) => {
    if (node.parentElement === content && node.id !== "seller-views") node.remove();
  });
  content.dataset.tabbed = "true";
}

async function loadPricingAdapterStatus() {
  const container = byId("pricing-adapter-status");
  if (!container || !state.session?.access_token) return;
  try {
    const data = await apiRequest("/api/v1/pricing/adapters");
    container.replaceChildren();
    (data.items || []).forEach((adapter) => {
      const row = document.createElement("div");
      row.className = "allocation-row";
      const details = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = adapter.source;
      const note = document.createElement("small");
      note.textContent = adapter.note;
      details.append(name, note);
      const stateLabel = document.createElement("strong");
      stateLabel.textContent = adapter.status === "ACCESS_REQUIRED" ? "Access required" : adapter.status;
      row.append(details, stateLabel);
      container.append(row);
    });
  } catch (error) {
    container.textContent = error.message;
  }
}

function ensureSellerDashboardShell() {
  if (!byId("dashboard-view") || byId("seller-nav")) return;
  buildSellerNav();
  populateSellerViews();
  const requested = location.hash.replace(/^#/, "");
  activateSellerView(requested || "dashboard");
  loadPricingAdapterStatus();
}

window.addEventListener("hashchange", () => activateSellerView(location.hash.replace(/^#/, "") || "dashboard"));
window.addEventListener("DOMContentLoaded", ensureSellerDashboardShell);
ensureSellerDashboardShell();
