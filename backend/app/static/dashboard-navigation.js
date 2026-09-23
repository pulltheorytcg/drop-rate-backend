"use strict";

const PORTAL_VIEWS = ["dashboard", "inventory", "sales", "reports", "balance", "settings"];
const portalLabels = {
  dashboard: "Dashboard",
  inventory: "Inventory",
  sales: "Sales",
  reports: "Reports",
  balance: "Balance",
  settings: "Settings",
};

function portalHeading(eyebrow, title, copy, actions = null) {
  const heading = document.createElement("div");
  heading.className = "page-heading portal-page-heading";
  const text = document.createElement("div");
  const eye = document.createElement("p");
  eye.className = "eyebrow";
  eye.textContent = eyebrow;
  const h1 = document.createElement("h1");
  h1.textContent = title;
  const muted = document.createElement("p");
  muted.className = "muted";
  muted.textContent = copy;
  text.append(eye, h1, muted);
  heading.append(text);
  if (actions) heading.append(actions);
  return heading;
}

function portalView(name) {
  const section = document.createElement("section");
  section.id = `portal-${name}-view`;
  section.className = "portal-view";
  section.dataset.portalView = name;
  section.hidden = name !== "dashboard";
  return section;
}

function portalActions() {
  const actions = document.createElement("div");
  actions.className = "topbar-actions";
  const refresh = document.createElement("button");
  refresh.id = "portal-refresh-all";
  refresh.type = "button";
  refresh.className = "ghost-button";
  refresh.textContent = "↻ Refresh dashboard";
  refresh.addEventListener("click", () => reloadDashboard());
  const inventory = document.createElement("button");
  inventory.type = "button";
  inventory.className = "primary-button compact";
  inventory.textContent = "Manage inventory";
  inventory.addEventListener("click", () => showPortalView("inventory"));
  actions.append(refresh, inventory);
  return actions;
}

function settingsPanel() {
  const section = document.createElement("section");
  section.className = "inventory-panel";
  section.id = "portal-settings-panel";
  section.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">System configuration</p>
        <h2>Integrations & pricing</h2>
        <p class="muted">Connections are deliberately separated from the deterministic Drop Rate backend.</p>
      </div>
    </div>
    <div class="settings-status-grid">
      <article class="settings-status-card">
        <div><strong>Market pricing engine</strong><small>Provider-independent pricing foundation</small></div>
        <span class="status-pill status-ready">Ready</span>
      </article>
      <article class="settings-status-card">
        <div><strong>Market data providers</strong><small>eBay · Collectr · TCGplayer · Cardmarket adapters</small></div>
        <span class="status-pill">Not connected</span>
      </article>
      <article class="settings-status-card">
        <div><strong>Shopify</strong><small>Storefront sync intentionally deferred until backend QA is complete</small></div>
        <span class="status-pill">Not connected</span>
      </article>
      <article class="settings-status-card">
        <div><strong>Automatic repricing</strong><small>Guardrailed publishing remains off by default</small></div>
        <span class="status-pill">Off</span>
      </article>
    </div>
  `;
  return section;
}

function buildPortalNavigation() {
  if (byId("portal-navigation")) return;
  ensureFounderFinanceUI();
  if (typeof ensureStorageLocationUI === "function") ensureStorageLocationUI();

  const dashboard = byId("dashboard-view");
  const content = dashboard.querySelector(".dashboard-content");
  if (!content) return;

  const inventoryHeading = [...content.children].find((child) => child.classList?.contains("page-heading"));
  const inventoryStats = [...content.children].find((child) => child.classList?.contains("stats-grid"));
  const actionPanel = content.querySelector(":scope > .action-panel");
  const storageLocations = byId("storage-locations-section");
  const purchaseLots = content.querySelector('[aria-labelledby="lots-heading"]');
  const inventoryTablePanel = content.querySelector(":scope > .inventory-panel .toolbar")?.closest(".inventory-panel");
  const financeRoot = byId("founder-finance-panel");
  const financeOverview = byId("finance-overview-section");
  const financeSales = byId("finance-sales-section");
  const financeRefunds = byId("finance-refunds-section");
  const financeReports = byId("finance-reports-section");
  const financeBalance = byId("finance-balance-section");

  if (!inventoryHeading || !inventoryStats || !actionPanel || !purchaseLots || !inventoryTablePanel || !financeOverview || !financeSales || !financeReports || !financeBalance) {
    console.error("Drop Rate portal could not initialise because one or more required panels are missing.");
    return;
  }

  const nav = document.createElement("nav");
  nav.id = "portal-navigation";
  nav.className = "portal-navigation";
  nav.setAttribute("aria-label", "Founder dashboard sections");
  PORTAL_VIEWS.forEach((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "portal-nav-button";
    button.dataset.portalTarget = name;
    button.setAttribute("aria-controls", `portal-${name}-view`);
    button.setAttribute("aria-selected", name === "dashboard" ? "true" : "false");
    button.textContent = portalLabels[name];
    button.addEventListener("click", () => showPortalView(name));
    nav.append(button);
  });
  dashboard.querySelector(".topbar").insertAdjacentElement("afterend", nav);

  const views = Object.fromEntries(PORTAL_VIEWS.map((name) => [name, portalView(name)]));
  content.replaceChildren(...PORTAL_VIEWS.map((name) => views[name]));

  views.dashboard.append(
    portalHeading("Founder overview", "Dashboard", "A focused view of stock health, profit, balance and anything requiring attention.", portalActions()),
    inventoryStats,
    financeOverview,
    actionPanel,
  );

  views.inventory.append(inventoryHeading);
  if (storageLocations) views.inventory.append(storageLocations);
  views.inventory.append(purchaseLots, inventoryTablePanel);

  views.sales.append(
    portalHeading("Commerce", "Sales", "Sold physical inventory, order performance and auditable refunds / returns."),
    financeSales,
  );
  if (financeRefunds) views.sales.append(financeRefunds);

  views.reports.append(
    portalHeading("Performance", "Reports", "Revenue, realised COGS, fees, shipping and profit from the financial ledger."),
    financeReports,
  );

  views.balance.append(
    portalHeading("Founder funds", "Balance", "See pending, available and reserved funds, then request an auditable payout."),
    financeBalance,
  );

  views.settings.append(
    portalHeading("Configuration", "Settings", "Manage marketplace integrations and pricing controls as they are enabled."),
    settingsPanel(),
  );

  if (financeRoot) {
    financeRoot.hidden = true;
    views.dashboard.append(financeRoot);
  }

  actionPanel.addEventListener("click", (event) => {
    if (event.target.closest("button")) queueMicrotask(() => showPortalView("inventory"));
  });

  window.addEventListener("hashchange", () => showPortalView(portalViewFromHash(), false));
  showPortalView(portalViewFromHash(), false);
}

function portalViewFromHash() {
  const name = window.location.hash.replace(/^#/, "").toLowerCase();
  return PORTAL_VIEWS.includes(name) ? name : "dashboard";
}

function showPortalView(name, updateHash = true) {
  const target = PORTAL_VIEWS.includes(name) ? name : "dashboard";
  PORTAL_VIEWS.forEach((viewName) => {
    const view = byId(`portal-${viewName}-view`);
    if (view) view.hidden = viewName !== target;
    const button = document.querySelector(`[data-portal-target="${viewName}"]`);
    if (button) {
      button.classList.toggle("active", viewName === target);
      button.setAttribute("aria-selected", viewName === target ? "true" : "false");
    }
  });
  if (updateHash && window.location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
  window.scrollTo({ top: 0, behavior: "auto" });
}

buildPortalNavigation();
