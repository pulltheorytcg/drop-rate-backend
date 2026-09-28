"use strict";

const SELLER_VIEWS = [
  ["dashboard", "Today", "◈"],
  ["intake", "Add cards", "+"],
  ["inventory", "Inventory", "▣"],
  ["verification", "Review", "✓"],
  ["media", "Photos & condition", "◉"],
  ["sales", "Sales", "↗"],
  ["reports", "Reports", "≋"],
  ["balance", "Payouts", "£"],
  ["settings", "Settings", "⚙"],
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

  const salesDashboard = byId("finance-sales-dashboard");

  const stripePayoutAccount = byId("stripe-payout-account");
  if (stripePayoutAccount) balance.append(stripePayoutAccount);

  const financeMessage = byId("finance-message");
  if (financeMessage) balance.append(financeMessage);

  const stripePayoutQueue = byId("stripe-payout-queue-section");
  if (stripePayoutQueue) balance.append(stripePayoutQueue);

  const salesBody = byId("finance-sales-body");
  if (salesBody) {
    sales.append(makeSellerHeading(
      "Sales performance",
      "Sales",
      "See what you made by day, week, month, quarter, year or any custom date range."
    ));
    if (salesDashboard) sales.append(salesDashboard);
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
    section.setAttribute("role", "tabpanel");
    section.tabIndex = 0;
    section.setAttribute("aria-labelledby", `seller-tab-${key}`);
    views.append(section);
  });
  content.append(views);
  return views;
}

function buildFounderHero() {
  const hero = document.createElement("section");
  hero.className = "founder-hero";
  hero.innerHTML = `
    <div class="founder-hero-copy">
      <p class="eyebrow">Your daily workspace</p>
      <h1>Ready for your next drop?</h1>
      <p class="founder-hero-sub">Add cards. Clear your reviews. Keep your stock moving.</p>
      <div class="founder-hero-actions">
        <button class="primary-button compact" type="button" data-hero-view="intake">+ Add cards</button>
        <button class="ghost-button compact" type="button" data-hero-view="inventory">View inventory →</button>
      </div>
    </div>
    <div class="founder-hero-art" aria-hidden="true">
      <div class="hero-card hero-card-one">
        <div class="hero-card-brand"></div>
        <small>FOUNDER EDITION</small>
      </div>
      <div class="hero-card hero-card-two">
        <div class="hero-card-brand"></div>
        <small>DROP RATE</small>
      </div>
      <div class="hero-energy-lines"></div>
    </div>
  `;
  const brandSource = document.querySelector("#dashboard-view .topbar .dr-logo-image");
  if (brandSource) {
    hero.querySelectorAll(".hero-card-brand").forEach((slot) => {
      const mark = brandSource.cloneNode(true);
      mark.classList.add("hero-card-brand-mark");
      slot.append(mark);
    });
  }
  hero.querySelectorAll("[data-hero-view]").forEach((button) => {
    button.addEventListener("click", () => activateSellerView(button.dataset.heroView, true));
  });
  return hero;
}

function utilityDrawer(title, eyebrow, child, open = false) {
  if (!child) return null;
  const details = document.createElement("details");
  details.className = "utility-drawer";
  details.open = open;
  const summary = document.createElement("summary");
  summary.innerHTML = `
    <div><p class="eyebrow">${eyebrow}</p><strong>${title}</strong></div>
    <span class="utility-chevron" aria-hidden="true">⌄</span>
  `;
  details.append(summary, child);
  return details;
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
  const setOrientation = () => nav.setAttribute("aria-orientation", window.innerWidth > 1000 ? "vertical" : "horizontal");
  setOrientation();
  window.addEventListener("resize", setOrientation);
  SELLER_VIEWS.forEach(([key, label, icon]) => {
    const button = document.createElement("button");
    button.id = `seller-tab-${key}`;
    button.type = "button";
    button.className = "seller-nav-tab";
    button.dataset.targetView = key;
    button.innerHTML = `<span class="seller-nav-icon" aria-hidden="true">${icon}</span><span>${label}</span>`;
    button.setAttribute("aria-controls", `seller-view-${key}`);
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => activateSellerView(key, true));
    nav.append(button);
  });
  nav.addEventListener("keydown", (event) => {
    const tabs = Array.from(nav.querySelectorAll('[role="tab"]'));
    const index = tabs.indexOf(event.target);
    if (index < 0) return;
    let next;
    if (["ArrowDown", "ArrowRight"].includes(event.key)) next = (index + 1) % tabs.length;
    if (["ArrowUp", "ArrowLeft"].includes(event.key)) next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    tabs[next].focus();
    tabs[next].click();
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
  document.dispatchEvent(new CustomEvent("seller-view-changed", {detail: {view: valid}}));
  if (valid === "settings") {
    loadPricingAdapterStatus();
    loadEbaySellerConnection();
  }
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
        <p class="muted">Check which cards have the details and approved photos needed for your store.</p>
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
      <button id="shopify-readiness-verify" class="ghost-button compact" type="button">Review cards</button>
      <button id="shopify-readiness-media" class="primary-button compact" type="button">Photos & condition</button>
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

function appendMediaResolverSummary(container, data) {
  const row = document.createElement("div");
  row.className = "allocation-row";
  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = "Media resolver";
  const note = document.createElement("small");
  note.textContent = [
    `${Number(data.canonical_resolved || 0).toLocaleString("en-GB")} reusable canonical`,
    `${Number(data.first_party_resolved || 0).toLocaleString("en-GB")} first-party`,
    `${Number(data.canonical_media_required || 0).toLocaleString("en-GB")} need reusable image`,
    `${Number(data.physical_capture_required || 0).toLocaleString("en-GB")} need physical photos`,
  ].join(" · ");
  details.append(name, note);
  const status = document.createElement("strong");
  status.textContent = data.policy?.existing_image_first ? "Existing-image first" : "Policy";
  row.append(details, status);
  container.append(row);
}

function appendMediaActionItems(container, items) {
  const visible = (items || []).slice(0, 5);
  if (!visible.length) return;
  const heading = document.createElement("div");
  heading.className = "portfolio-mover-label";
  heading.textContent = "Action required";
  container.append(heading);

  visible.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = [item.name, item.card_number, item.inventory_code].filter(Boolean).join(" · ");
    const note = document.createElement("small");
    note.textContent = [
      item.action_required_reason,
      item.physical_photos_required ? "Physical capture required" : "Reusable canonical image required",
      ...(item.physical_requirement_reasons || []),
    ].filter(Boolean).join(" · ");
    details.append(name, note);
    const status = document.createElement("strong");
    status.textContent = item.physical_photos_required ? "PHOTO" : "MEDIA";
    row.append(details, status);
    container.append(row);
  });
}

function appendResolvedMediaItems(container, items) {
  const visible = (items || []).slice(0, 5);
  if (!visible.length) return;
  const heading = document.createElement("div");
  heading.className = "portfolio-mover-label";
  heading.textContent = "Resolved media";
  container.append(heading);

  visible.forEach((item) => {
    const asset = (item.selected_media || [])[0] || {};
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = [item.name, item.card_number, item.inventory_code].filter(Boolean).join(" · ");
    const note = document.createElement("small");
    note.textContent = [
      item.selection_reason,
      asset.sourceProvider || asset.sourceReference,
      item.rights_tier,
    ].filter(Boolean).join(" · ");
    details.append(name, note);
    const status = document.createElement("strong");
    status.textContent = item.resolution_source === "CANONICAL_STOREFRONT" ? "REUSED" : "CAPTURED";
    row.append(details, status);
    container.append(row);
  });
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
      `${mediaReady.toLocaleString("en-GB")} of ${operationalReady.toLocaleString("en-GB")} core-ready · ${Number(data.canonical_resolved || 0).toLocaleString("en-GB")} reusable · ${Number(data.first_party_resolved || 0).toLocaleString("en-GB")} first-party`;

    container.replaceChildren();
    appendMediaResolverSummary(container, data);
    appendShopifyReadinessBlockers(container, "Core blockers", data.operational_blockers);
    appendShopifyReadinessBlockers(container, "Media blockers", data.media_blockers);
    appendMediaActionItems(container, data.next_media_items);
    appendResolvedMediaItems(container, data.resolved_media_items);
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
  const intake = sellerView("intake");
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

  overview.append(buildFounderHero());
  if (inventoryStats) {
    inventoryStats.classList.add("dashboard-kpi-grid");
    overview.append(inventoryStats);
  }
  const overviewGrid = document.createElement("div");
  overviewGrid.className = "dashboard-overview-grid";
  const intelligence = buildPortfolioIntelligencePanel();
  intelligence.classList.add("dashboard-feature-panel");
  const readiness = buildShopifyReadinessPanel();
  readiness.classList.add("dashboard-feature-panel");
  overviewGrid.append(
    utilityDrawer("Portfolio & market value", "Insights", intelligence),
    utilityDrawer("Shopify listing readiness", "Storefront", readiness)
  );
  overview.append(overviewGrid);
  if (actionPanel) {
    actionPanel.classList.add("dashboard-action-panel");
    overviewGrid.before(actionPanel);
  }

  if (inventoryHeading) {
    const eyebrow = inventoryHeading.querySelector(".eyebrow");
    const title = inventoryHeading.querySelector("h1");
    const muted = inventoryHeading.querySelector(".muted");
    if (eyebrow) eyebrow.textContent = "Stock operations";
    if (title) title.textContent = "Inventory";
    if (muted) muted.textContent = "Find a card, update its details or manage your stock.";
    inventory.append(inventoryHeading);
  }
  if (inventoryPanel) inventory.append(inventoryPanel);
  intake.append(makeSellerHeading("Build your next drop", "Add cards", "Scan a photo, import a spreadsheet or add an item by hand."));
  const intakeMethods = document.createElement("div");
  intakeMethods.className = "intake-methods";
  [["import-inventory-button", "Import a spreadsheet", "Add many cards from a CSV. Check matches before saving."],
    ["new-inventory-button", "Add an item manually", "Search your catalogue or enter a card or sealed product."]].forEach(([id, title, description]) => {
    const button = byId(id);
    if (!button) return;
    const card = document.createElement("article");
    const heading = document.createElement("h2");
    heading.textContent = title;
    const note = document.createElement("p");
    note.textContent = description;
    card.append(heading, note, button);
    intakeMethods.append(card);
  });
  intake.append(intakeMethods);
  const addShortcut = document.createElement("button");
  addShortcut.type = "button";
  addShortcut.className = "primary-button compact";
  addShortcut.textContent = "+ Add cards";
  addShortcut.addEventListener("click", () => activateSellerView("intake", true));
  inventoryHeading?.querySelector(".topbar-actions")?.prepend(addShortcut);
  const inventoryUtilities = document.createElement("div");
  inventoryUtilities.className = "inventory-utilities";
  const locationsDrawer = utilityDrawer("Storage locations", "Organisation", locations);
  const lotsDrawer = utilityDrawer("Purchase lots", "Acquisition accounting", lots);
  if (locationsDrawer) inventoryUtilities.append(locationsDrawer);
  if (lotsDrawer) inventoryUtilities.append(lotsDrawer);
  if (inventoryUtilities.children.length) inventory.append(inventoryUtilities);

  verification.append(makeSellerHeading(
    "Get cards ready",
    "Review cards",
    "Confirm each card's identity. Select matching copies to review them together."
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

  const ebayCard = document.createElement("section");
  ebayCard.id = "ebay-seller-connection-panel";
  ebayCard.className = "inventory-panel";
  ebayCard.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Marketplace channel</p>
        <h2>eBay seller connection</h2>
        <p class="muted">Connect the company seller account once. Drop Rate keeps the long-lived token encrypted and continues to control the exact physical Inventory ID.</p>
      </div>
      <button id="ebay-connection-refresh" class="ghost-button compact" type="button">↻ Refresh</button>
    </div>
    <div id="ebay-connection-message" class="message panel-message" role="status"></div>
    <div id="ebay-connection-status" class="allocation-list">
      <p class="muted">Open Settings while signed in to check the eBay seller connection.</p>
    </div>
    <div id="ebay-connection-actions" class="toolbar">
      <button id="ebay-connect-button" class="ghost-button compact" type="button">Connect eBay seller</button>
      <button id="ebay-complete-setup-button" class="primary-button compact hidden" type="button">Complete eBay setup</button>
    </div>
    <div id="ebay-configuration-panel" class="form-grid hidden">
      <label>Payment policy<select id="ebay-payment-policy"></select></label>
      <label>Fulfilment policy<select id="ebay-fulfillment-policy"></select></label>
      <label>Return policy<select id="ebay-return-policy"></select></label>
      <label>Inventory location<select id="ebay-inventory-location"></select></label>
      <div class="full-width modal-actions">
        <button id="ebay-save-configuration" class="primary-button compact" type="button">Save eBay configuration</button>
      </div>
    </div>`;
  settings.append(ebayCard);

  const ownerInviteCard = document.createElement("section");
  ownerInviteCard.id = "owner-invite-admin-panel";
  ownerInviteCard.className = "inventory-panel";
  ownerInviteCard.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Seller onboarding</p>
        <h2>Invite seller / consignor</h2>
        <p class="muted">Sends a branded email for a restricted OWNER account. This can never grant Founder HQ access.</p>
      </div>
    </div>
    <div class="form-grid">
      <label>Name<input id="owner-invite-name" type="text" maxlength="120" placeholder="Seller or consignor name"></label>
      <label>Email<input id="owner-invite-email" type="email" maxlength="320" placeholder="seller@example.com"></label>
      <label>Commission %<input id="owner-invite-commission" type="number" min="0" max="100" step="0.01" value="10"></label>
      <label>Invite expires in days<input id="owner-invite-expiry" type="number" min="1" max="30" step="1" value="7"></label>
    </div>
    <div id="owner-invite-message" class="message panel-message" role="status"></div>
    <div class="toolbar">
      <button id="owner-invite-create" class="primary-button compact" type="button">Send seller invite</button>
    </div>
    <div id="owner-invite-result" class="form-grid hidden">
      <label class="full-width">Invite link<input id="owner-invite-url" type="text" readonly></label>
      <div class="full-width modal-actions">
        <button id="owner-invite-copy" class="ghost-button compact" type="button">Copy invite link</button>
        <button id="owner-invite-revoke" class="ghost-button compact" type="button">Revoke invite</button>
      </div>
    </div>`;
  settings.append(ownerInviteCard);

  ownerInviteCard.querySelector("#owner-invite-create").addEventListener("click", async () => {
    const button = byId("owner-invite-create");
    const name = byId("owner-invite-name").value.trim();
    const email = byId("owner-invite-email").value.trim().toLowerCase();
    const commissionPercent = Number(byId("owner-invite-commission").value);
    const expiresInDays = Number(byId("owner-invite-expiry").value);

    if (!name || !email || !email.includes("@")) {
      showMessage("owner-invite-message", "Enter a seller name and valid email address.", "error");
      return;
    }
    if (!Number.isFinite(commissionPercent) || commissionPercent < 0 || commissionPercent > 100) {
      showMessage("owner-invite-message", "Commission must be between 0% and 100%.", "error");
      return;
    }

    button.disabled = true;
    showMessage("owner-invite-message", "Creating invite and sending branded email…");
    try {
      const data = await apiRequest("/api/v1/owner-invites", {
        method: "POST",
        body: JSON.stringify({
          invited_name: name,
          invited_email: email,
          commission_bps: Math.round(commissionPercent * 100),
          expires_in_days: expiresInDays,
        }),
      });
      byId("owner-invite-url").value = data.invite_url;
      byId("owner-invite-result").dataset.inviteId = data.id;
      byId("owner-invite-result").classList.remove("hidden");
      const delivery = data.email_delivery || {};
      const sent = delivery.status === "SENT";
      showMessage(
        "owner-invite-message",
        sent
          ? `Branded invite email sent to ${email} at ${commissionPercent}% commission.`
          : `Invite created, but email delivery is ${delivery.status || "NOT_SENT"}. The secure link remains available below.`,
        sent ? "success" : "error"
      );
      if (typeof loadOwnerInvites === "function") await loadOwnerInvites();
    } catch (error) {
      showMessage("owner-invite-message", error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  ownerInviteCard.querySelector("#owner-invite-copy").addEventListener("click", async () => {
    const url = byId("owner-invite-url").value;
    if (!url) return;
    await navigator.clipboard.writeText(url);
    showMessage("owner-invite-message", "Invite link copied.", "success");
  });

  ownerInviteCard.querySelector("#owner-invite-revoke").addEventListener("click", async () => {
    const result = byId("owner-invite-result");
    const inviteId = result.dataset.inviteId;
    if (!inviteId) return;
    try {
      await apiRequest(`/api/v1/owner-invites/${encodeURIComponent(inviteId)}`, {
        method: "DELETE",
      });
      result.classList.add("hidden");
      result.dataset.inviteId = "";
      showMessage("owner-invite-message", "Invite revoked.", "success");
      if (typeof loadOwnerInvites === "function") await loadOwnerInvites();
    } catch (error) {
      showMessage("owner-invite-message", error.message, "error");
    }
  });

  ebayCard.querySelector("#ebay-connection-refresh")
    .addEventListener("click", () => loadEbaySellerConnection());
  ebayCard.querySelector("#ebay-connect-button")
    .addEventListener("click", () => startEbaySellerConnection());
  ebayCard.querySelector("#ebay-complete-setup-button")
    .addEventListener("click", () => completeEbaySellerSetup());
  ebayCard.querySelector("#ebay-save-configuration")
    .addEventListener("click", () => saveEbaySellerConfiguration());

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

function ebayStatusRow(label, value, detail = "") {
  const row = document.createElement("div");
  row.className = "allocation-row";
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = label;
  const note = document.createElement("small");
  note.textContent = detail;
  copy.append(title, note);
  const state = document.createElement("strong");
  state.textContent = value;
  row.append(copy, state);
  return row;
}

function populateEbaySelect(select, items, selected, valueKey, labelBuilder) {
  select.replaceChildren();
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = labelBuilder(item);
    option.selected = item[valueKey] === selected;
    select.append(option);
  });
}

async function loadEbaySellerOptions() {
  const panel = byId("ebay-configuration-panel");
  if (!panel) return;
  try {
    const data = await apiRequest("/api/v1/ebay/oauth/options");
    const selected = data.selected || {};
    populateEbaySelect(
      byId("ebay-payment-policy"),
      data.payment || [],
      selected.payment_policy_id,
      "id",
      (item) => item.name || item.id
    );
    populateEbaySelect(
      byId("ebay-fulfillment-policy"),
      data.fulfillment || [],
      selected.fulfillment_policy_id,
      "id",
      (item) => item.name || item.id
    );
    populateEbaySelect(
      byId("ebay-return-policy"),
      data.return || [],
      selected.return_policy_id,
      "id",
      (item) => item.name || item.id
    );
    populateEbaySelect(
      byId("ebay-inventory-location"),
      data.locations || [],
      selected.merchant_location_key,
      "key",
      (item) => [item.name || item.key, item.postal_code, item.country]
        .filter(Boolean).join(" · ")
    );
    const complete = [
      byId("ebay-payment-policy"),
      byId("ebay-fulfillment-policy"),
      byId("ebay-return-policy"),
      byId("ebay-inventory-location"),
    ].every((select) => select.options.length > 0);
    const discoveryErrors = Object.values(data.errors || {}).filter(Boolean);
    panel.classList.toggle("hidden", !complete);
    if (discoveryErrors.length) {
      showMessage(
        "ebay-connection-message",
        `The eBay seller account is connected, but setup checks still need attention: ${discoveryErrors.join(" · ")}.`,
        "error"
      );
    } else if (!complete) {
      showMessage(
        "ebay-connection-message",
        "The seller account is connected, but eBay is missing at least one compatible payment, fulfilment or return policy, or an enabled inventory location.",
        "error"
      );
    } else if (data.selling_policy_management_opted_in_now) {
      showMessage(
        "ebay-connection-message",
        "Seller account connected. Drop Rate also enabled eBay Business Policies for Inventory API listings.",
        "success"
      );
    }
  } catch (error) {
    panel.classList.add("hidden");
    showMessage("ebay-connection-message", error.message, "error");
  }
}

async function loadEbaySellerConnection() {
  const list = byId("ebay-connection-status");
  const button = byId("ebay-connect-button");
  const configPanel = byId("ebay-configuration-panel");
  if (!list || !button || !state.session?.access_token) return;
  try {
    const [oauth, seller] = await Promise.all([
      apiRequest("/api/v1/ebay/oauth/status"),
      apiRequest("/api/v1/ebay/seller-status"),
    ]);
    list.replaceChildren(
      ebayStatusRow(
        "Seller OAuth",
        oauth.connected ? "CONNECTED" : "NOT CONNECTED",
        oauth.connected
          ? "The long-lived seller grant is encrypted at rest."
          : "One eBay login + consent is required."
      ),
      ebayStatusRow(
        "Seller API verification",
        seller.live_verified ? "READY" : "NOT READY",
        seller.warning || (seller.missing || []).join(" · ") || "Waiting for seller configuration."
      ),
      ebayStatusRow(
        "Live publishing",
        seller.publish_enabled ? "ENABLED" : "LOCKED",
        seller.publish_enabled
          ? "Single-item publishing is enabled."
          : "Publishing stays locked until seller setup and notification verification pass."
      ),
      ebayStatusRow(
        "OAuth callback",
        oauth.runame_configured ? "READY" : "NEEDS RUNAME",
        oauth.callback_endpoint || "Callback endpoint is not configured."
      )
    );
    button.disabled = !oauth.oauth_configured;
    button.textContent = oauth.connected ? "Reconnect eBay seller" : "Connect eBay seller";
    const completeButton = byId("ebay-complete-setup-button");
    if (completeButton) {
      completeButton.classList.toggle(
        "hidden",
        !oauth.connected || seller.live_verified
      );
      completeButton.disabled = !oauth.connected;
    }
    if (!oauth.oauth_configured) {
      button.title = (oauth.missing || []).join(", ");
    } else {
      button.removeAttribute("title");
    }
    if (oauth.connected && !seller.live_verified) {
      await loadEbaySellerOptions();
    } else {
      configPanel.classList.add("hidden");
    }
    showMessage("ebay-connection-message");
  } catch (error) {
    list.textContent = "eBay seller connection status could not be loaded.";
    configPanel.classList.add("hidden");
    showMessage("ebay-connection-message", error.message, "error");
  }
}

async function startEbaySellerConnection() {
  const button = byId("ebay-connect-button");
  if (button) button.disabled = true;
  showMessage("ebay-connection-message", "Preparing secure eBay sign-in…");

  // Open synchronously from the founder click so browser popup protection
  // cannot swallow the seller-consent window while the API generates state.
  const popup = window.open("about:blank", "_blank");
  if (popup) {
    try {
      popup.opener = null;
      popup.document.title = "Connecting eBay…";
      popup.document.body.textContent = "Preparing secure eBay sign-in…";
    } catch (_error) {
      // The popup is still safe to navigate even if the interim DOM is blocked.
    }
  }

  try {
    const result = await apiRequest("/api/v1/ebay/oauth/start", {method: "POST"});
    if (popup && !popup.closed) {
      popup.location.replace(result.authorization_url);
    } else {
      window.location.assign(result.authorization_url);
      return;
    }
    showMessage(
      "ebay-connection-message",
      "eBay sign-in opened in a new tab. Sign in, press Agree, then return here and press Refresh.",
      "success"
    );
  } catch (error) {
    if (popup && !popup.closed) popup.close();
    showMessage("ebay-connection-message", error.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function completeEbaySellerSetup() {
  const button = byId("ebay-complete-setup-button");
  if (button) {
    button.disabled = true;
    button.textContent = "Completing…";
  }
  showMessage(
    "ebay-connection-message",
    "Verifying seller policies, inventory location and ORDER_CONFIRMATION notifications…"
  );
  try {
    await apiRequest("/api/v1/ebay/oauth/complete-setup", {method: "POST"});
    await loadEbaySellerConnection();
    showMessage(
      "ebay-connection-message",
      "eBay seller API verification is READY. Cross-channel order notifications are verified.",
      "success"
    );
  } catch (error) {
    showMessage("ebay-connection-message", error.message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Complete eBay setup";
    }
  }
}

async function saveEbaySellerConfiguration() {
  const fields = {
    payment_policy_id: byId("ebay-payment-policy")?.value || "",
    fulfillment_policy_id: byId("ebay-fulfillment-policy")?.value || "",
    return_policy_id: byId("ebay-return-policy")?.value || "",
    merchant_location_key: byId("ebay-inventory-location")?.value || "",
  };
  if (Object.values(fields).some((value) => !value)) {
    showMessage("ebay-connection-message", "Choose every eBay seller configuration value.", "error");
    return;
  }
  showMessage("ebay-connection-message", "Verifying eBay seller configuration…");
  try {
    await apiRequest("/api/v1/ebay/oauth/configuration", {
      method: "POST",
      body: JSON.stringify(fields),
    });
    await loadEbaySellerConnection();
    showMessage("ebay-connection-message", "eBay seller configuration saved and verified.", "success");
  } catch (error) {
    showMessage("ebay-connection-message", error.message, "error");
  }
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
  await Promise.all([
    loadPricingAdapterStatus(),
    loadEbaySellerConnection(),
    loadPortfolioIntelligence(),
    loadShopifyReadiness(),
  ]);
  return result;
};

window.addEventListener("hashchange", () => activateSellerView(location.hash.replace(/^#/, "") || "dashboard"));
window.addEventListener("DOMContentLoaded", ensureSellerDashboardShell);
ensureSellerDashboardShell();
