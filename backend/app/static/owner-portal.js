"use strict";

const OWNER_SESSION_KEY = "drop_rate_owner_session";

const state = {
  config: null,
  session: null,
  providers: {google: false, apple: false},
  inventory: {offset: 0, limit: 50, total: 0, search: "", status: "", layout: "grid"},
  sales: {offset: 0, limit: 50, total: 0},
  settlements: {offset: 0, limit: 50, total: 0},
  channels: {offset: 0, limit: 60, total: 0, search: "", channel: "ALL"},
  payoutPreferenceVersion: 0,
  financeSummary: null,
  payoutPreference: null,
};

const byId = (id) => document.getElementById(id);

function formatMoney(minor) {
  const value = Number(minor || 0) / 100;
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    maximumFractionDigits: 2,
  }).format(value);
}

function safeText(value, fallback = "—") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function showPortalMessage(text = "", kind = "") {
  const node = byId("owner-portal-message");
  node.textContent = text;
  node.className = `message owner-global-message${kind ? ` ${kind}` : ""}`;
}

function statusClass(value) {
  return String(value || "").trim().toLowerCase();
}

function inventoryCardSubtitle(item) {
  return [
    safeText(item.set_name, ""),
    item.card_number ? `#${item.card_number}` : "",
    safeText(item.variant, ""),
  ].filter(Boolean).join(" · ") || safeText(item.game);
}

function conditionLabel(item) {
  return item.grade
    ? `${safeText(item.grading_company, "Graded")} ${item.grade}`
    : safeText(item.condition);
}

function createCardImage(item, className) {
  const wrap = document.createElement("div");
  wrap.className = className;
  const url = String(item.image_url || "").trim();
  if (url) {
    const image = document.createElement("img");
    image.src = url;
    image.alt = `${safeText(item.name, "Trading card")} reference image`;
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => {
      wrap.replaceChildren();
      const fallback = document.createElement("span");
      fallback.className = "owner-image-placeholder";
      fallback.textContent = safeText(item.game, "DR").slice(0, 3).toUpperCase();
      wrap.append(fallback);
    }, {once: true});
    wrap.append(image);
    return wrap;
  }
  const fallback = document.createElement("span");
  fallback.className = "owner-image-placeholder";
  fallback.textContent = safeText(item.game, "DR").slice(0, 3).toUpperCase();
  wrap.append(fallback);
  return wrap;
}

function renderInventoryRows(items) {
  const body = byId("owner-inventory-body");
  body.replaceChildren();

  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "muted";
    cell.textContent = "No inventory matches these filters.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");

    const cardCell = document.createElement("td");
    const cardWrap = document.createElement("div");
    cardWrap.className = "owner-table-card";
    cardWrap.append(createCardImage(item, "owner-table-mini-image"));
    const cardCopy = document.createElement("div");
    cardCopy.className = "owner-table-card-copy";
    const cardName = document.createElement("strong");
    cardName.textContent = safeText(item.name);
    const cardCode = document.createElement("small");
    cardCode.textContent = `${safeText(item.inventory_code)} · ${inventoryCardSubtitle(item)}`;
    cardCopy.append(cardName, cardCode);
    cardWrap.append(cardCopy);
    cardCell.append(cardWrap);

    const gameCell = document.createElement("td");
    gameCell.textContent = [safeText(item.game, ""), safeText(item.set_name, "")].filter(Boolean).join(" · ") || "—";

    const conditionCell = document.createElement("td");
    conditionCell.textContent = `${conditionLabel(item)} · ${safeText(item.language)}`;

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `owner-status-pill ${statusClass(item.status)}`;
    status.textContent = safeText(item.status);
    statusCell.append(status);

    const marketCell = document.createElement("td");
    marketCell.textContent = formatMoney(item.market_value_minor);
    const storeCell = document.createElement("td");
    const storeValue = item.store_price_minor ?? item.recommended_retail_minor;
    storeCell.textContent = storeValue == null ? "—" : formatMoney(storeValue);

    row.append(cardCell, gameCell, conditionCell, statusCell, marketCell, storeCell);
    body.append(row);
  }
}

function renderInventoryCards(items) {
  const grid = byId("owner-inventory-grid");
  grid.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-inventory-empty";
    const icon = document.createElement("div");
    icon.className = "owner-inventory-empty-icon";
    icon.textContent = "▣";
    const title = document.createElement("strong");
    title.textContent = state.inventory.search || state.inventory.status
      ? "No cards match these filters"
      : "No cards linked yet";
    const copy = document.createElement("span");
    copy.textContent = state.inventory.search || state.inventory.status
      ? "Try clearing your search or choosing another status."
      : "Once Drop Rate links inventory to your seller account, every card will appear here automatically.";
    empty.append(icon, title, copy);
    grid.append(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "owner-inventory-card";

    const imageWrap = document.createElement("div");
    imageWrap.className = "owner-card-image-wrap";
    imageWrap.append(createCardImage(item, "owner-card-thumb"));

    const body = document.createElement("div");
    body.className = "owner-card-body";

    const heading = document.createElement("div");
    heading.className = "owner-card-title-row";
    const title = document.createElement("div");
    title.className = "owner-card-title";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const subtitle = document.createElement("span");
    subtitle.textContent = inventoryCardSubtitle(item);
    title.append(name, subtitle);
    const status = document.createElement("span");
    status.className = `owner-status-pill ${statusClass(item.status)}`;
    status.textContent = safeText(item.status);
    heading.append(title, status);

    const meta = document.createElement("div");
    meta.className = "owner-card-meta";
    const metaValues = [
      ["Condition", conditionLabel(item)],
      ["Language", safeText(item.language)],
      ["Game", safeText(item.game)],
      ["Inventory", safeText(item.inventory_code)],
    ];
    for (const [labelText, valueText] of metaValues) {
      const box = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = labelText;
      const value = document.createElement("strong");
      value.textContent = valueText;
      box.append(label, value);
      meta.append(box);
    }

    const prices = document.createElement("div");
    prices.className = "owner-card-prices";
    const storeValue = item.store_price_minor ?? item.recommended_retail_minor;
    const storeLabel = item.store_price_minor == null && item.recommended_retail_minor != null
      ? "Recommended retail"
      : "Store price";
    for (const [labelText, valueText] of [
      ["Market value", item.market_value_minor == null ? "—" : formatMoney(item.market_value_minor)],
      [storeLabel, storeValue == null ? "—" : formatMoney(storeValue)],
    ]) {
      const box = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = labelText;
      const value = document.createElement("strong");
      value.textContent = valueText;
      box.append(label, value);
      prices.append(box);
    }

    body.append(heading, meta, prices);
    card.append(imageWrap, body);
    grid.append(card);
  }
}

function renderOverviewLatestInventory(items) {
  const container = byId("owner-overview-latest");
  if (!container) return;
  container.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-empty-inline";
    const title = document.createElement("strong");
    title.textContent = "No cards yet";
    const copy = document.createElement("span");
    copy.textContent = "Your latest cards will appear here as soon as inventory is linked to your account.";
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  for (const item of items.slice(0, 4)) {
    const card = document.createElement("article");
    card.className = "owner-latest-card";
    card.append(createCardImage(item, "owner-latest-image"));

    const copy = document.createElement("div");
    copy.className = "owner-latest-copy";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const detail = document.createElement("span");
    detail.textContent = inventoryCardSubtitle(item);
    const status = document.createElement("small");
    status.textContent = safeText(item.status);
    copy.append(name, detail, status);
    card.append(copy);
    container.append(card);
  }
}

function renderInventoryPagination() {
  const {offset, limit, total} = state.inventory;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-inventory-page").textContent = total
    ? `${start}–${end} of ${total}`
    : "0 items";
  byId("owner-inventory-prev").disabled = offset <= 0;
  byId("owner-inventory-next").disabled = offset + limit >= total;
}

async function loadOwnerOverview() {
  const data = await apiRequest("/api/v1/owner/overview");
  const summary = data.summary || {};
  const total = Number(summary.total_inventory_count || 0);
  byId("owner-total-inventory").textContent = total.toLocaleString("en-GB");
  byId("owner-market-value").textContent = formatMoney(summary.active_market_value_minor);
  byId("owner-store-value").textContent = formatMoney(
    summary.active_store_value_minor ?? summary.active_store_price_minor
  );
  byId("owner-sold-count").textContent = Number(summary.sold_count || 0).toLocaleString("en-GB");

  const stages = {
    draft: Number(summary.draft_count || 0),
    inspection: Number(summary.inspection_count || 0),
    approved: Number(summary.approved_count || 0),
    reserved: Number(summary.reserved_count || 0),
  };
  for (const [stage, count] of Object.entries(stages)) {
    const value = byId(`owner-pipeline-${stage}`);
    const bar = byId(`owner-pipeline-${stage}-bar`);
    if (value) value.textContent = count.toLocaleString("en-GB");
    if (bar) bar.style.width = `${total ? Math.min(100, Math.max(4, (count / total) * 100)) : 0}%`;
  }
}

async function loadOwnerInventory() {
  const params = new URLSearchParams({
    limit: String(state.inventory.limit),
    offset: String(state.inventory.offset),
  });
  if (state.inventory.search) params.set("search", state.inventory.search);
  if (state.inventory.status) params.set("status", state.inventory.status);

  const data = await apiRequest(`/api/v1/owner/inventory?${params.toString()}`);
  state.inventory.total = Number(data.total || 0);
  const items = data.items || [];
  renderInventoryRows(items);
  renderInventoryCards(items);
  renderInventoryPagination();
  const totalLabel = byId("owner-inventory-total-label");
  if (totalLabel) totalLabel.textContent = state.inventory.total.toLocaleString("en-GB");
  if (state.inventory.offset === 0 && !state.inventory.search && !state.inventory.status) {
    renderOverviewLatestInventory(items);
  }
}

async function reloadOwnerDashboard() {
  showPortalMessage("Loading your account…");
  try {
    await Promise.all([
      loadOwnerOverview(),
      loadOwnerInventory(),
      loadOwnerFinanceSummary(),
      loadOwnerSales(),
      loadOwnerSettlements(),
      loadOwnerPayouts(),
      loadOwnerPayoutPreference(),
      loadOwnerStripeStatus(),
    ]);
    showPortalMessage();
  } catch (error) {
    showPortalMessage(error.message, "error");
  }
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", {day: "2-digit", month: "short", year: "numeric"});
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function renderEmptyRow(bodyId, colspan, message) {
  const body = byId(bodyId);
  body.replaceChildren();
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.className = "muted";
  cell.textContent = message;
  row.append(cell);
  body.append(row);
}

async function loadOwnerFinanceSummary() {
  const data = await apiRequest("/api/v1/owner/finance/summary");
  byId("owner-sales-revenue").textContent = formatMoney(data.sales_revenue_minor);
  byId("owner-commission-total").textContent = formatMoney(data.commission_minor);
  byId("owner-commission-rate").textContent =
    `Drop Rate commission: ${(Number(data.commission_bps || 0) / 100).toFixed(2).replace(/\.00$/, "")}%`;
  byId("owner-lifetime-proceeds").textContent = formatMoney(data.lifetime_owner_proceeds_minor);
  byId("owner-financial-completeness").textContent =
    data.financials_complete ? "COMPLETE" : `${Number(data.unreconciled_sales || 0)} PENDING`;
  byId("owner-available-balance").textContent = formatMoney(data.available_to_withdraw_minor);
  byId("owner-pending-balance").textContent = formatMoney(data.pending_minor);
  byId("owner-reserved-payouts").textContent = formatMoney(data.reserved_payout_minor);
  byId("owner-paid-out").textContent = formatMoney(data.paid_out_minor);
  byId("owner-overview-balance").textContent = formatMoney(data.available_to_withdraw_minor);
  byId("owner-overview-proceeds").textContent = formatMoney(data.lifetime_owner_proceeds_minor);
  byId("owner-overview-pending").textContent = formatMoney(data.pending_minor);
  byId("owner-overview-paid").textContent = formatMoney(data.paid_out_minor);
}

function otherDeductions(item) {
  return Number(item.platform_fee_minor || item.platform_fees_minor || 0)
    + Number(item.payment_fee_minor || item.payment_fees_minor || 0)
    + Number(item.shipping_cost_minor || 0)
    + Number(item.fulfilment_material_cost_minor || 0)
    + Number(item.refund_minor || item.refunds_minor || 0)
    + Number(item.shipping_refund_minor || item.shipping_refunds_minor || 0)
    - Number(item.adjustment_minor || item.adjustments_minor || 0);
}

function renderSales(items) {
  const body = byId("owner-sales-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-sales-body", 8, "No sales yet.");
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const cardNumber = item.card_number ? ` #${item.card_number}` : "";
    const variant = item.variant ? ` · ${item.variant}` : "";
    const values = [
      formatDate(item.sold_at),
      `${safeText(item.name)}${cardNumber}${variant}`,
      `${safeText(item.source)} · ${safeText(item.order_number)}`,
      formatMoney(item.net_sale_minor),
      formatMoney(item.commission_minor),
      formatMoney(otherDeductions(item)),
      formatMoney(item.owner_proceeds_minor),
      item.financials_complete ? "Complete" : "Reconciling",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderSalesPagination() {
  const {offset, limit, total} = state.sales;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-sales-page").textContent = total ? `${start}–${end} of ${total}` : "0 sales";
  byId("owner-sales-prev").disabled = offset <= 0;
  byId("owner-sales-next").disabled = offset + limit >= total;
}

async function loadOwnerSales() {
  const params = new URLSearchParams({
    limit: String(state.sales.limit),
    offset: String(state.sales.offset),
  });
  const data = await apiRequest(`/api/v1/owner/finance/sales?${params.toString()}`);
  state.sales.total = Number(data.total || 0);
  renderSales(data.items || []);
  renderSalesPagination();
}

function renderSettlements(items) {
  const body = byId("owner-settlements-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-settlements-body", 8, "No settlements yet.");
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const revenue = Number(item.sales_revenue_minor || 0) + Number(item.shipping_revenue_minor || 0);
    const values = [
      `${safeText(item.source)} · ${safeText(item.order_number)}`,
      formatDate(item.placed_at),
      Number(item.item_count || 0).toLocaleString("en-GB"),
      formatMoney(revenue),
      formatMoney(item.commission_minor),
      formatMoney(otherDeductions(item)),
      formatMoney(item.owner_proceeds_minor),
      item.financials_complete ? "Complete" : "Reconciling",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderSettlementPagination() {
  const {offset, limit, total} = state.settlements;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-settlements-page").textContent =
    total ? `${start}–${end} of ${total}` : "0 settlements";
  byId("owner-settlements-prev").disabled = offset <= 0;
  byId("owner-settlements-next").disabled = offset + limit >= total;
}

async function loadOwnerSettlements() {
  const params = new URLSearchParams({
    limit: String(state.settlements.limit),
    offset: String(state.settlements.offset),
  });
  const data = await apiRequest(`/api/v1/owner/finance/settlements?${params.toString()}`);
  state.settlements.total = Number(data.total || 0);
  renderSettlements(data.items || []);
  renderSettlementPagination();
}

function renderPayouts(items) {
  const body = byId("owner-payouts-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-payouts-body", 7, "No payouts yet.");
    return;
  }
  for (const item of items) {
    const row = document.createElement("tr");
    const values = [
      safeText(item.payout_code),
      formatMoney(item.amount_minor),
      item.request_origin === "SCHEDULED" ? "Scheduled" : "Manual",
      safeText(item.status),
      formatDateTime(item.scheduled_for),
      formatDateTime(item.requested_at),
      formatDateTime(item.resolved_at),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

async function loadOwnerPayouts() {
  const data = await apiRequest("/api/v1/owner/finance/payouts");
  renderPayouts(data.items || []);
}

function renderOwnerStripeStatus(data) {
  const account = data.account || null;
  const connected = Boolean(data.connected && account);
  const ready = Boolean(data.ready_for_payouts);
  const transferReady = account?.transfers_capability_status === "ACTIVE";
  const mode = account?.livemode ? "Live" : "Test";

  byId("owner-stripe-account-state").textContent = connected ? "CONNECTED" : "NOT CONNECTED";
  byId("owner-stripe-account-note").textContent = connected
    ? `${mode} · ${safeText(account.account_type, "Express")}`
    : "Set up your payout account";

  byId("owner-stripe-verification-state").textContent = ready ? "READY" : connected ? "PENDING" : "NOT READY";
  byId("owner-stripe-verification-note").textContent = ready
    ? "Identity and payout requirements satisfied"
    : connected
      ? "Complete Stripe verification requirements"
      : "Identity verification required";

  byId("owner-stripe-transfer-state").textContent = transferReady ? "READY" : "LOCKED";

  const button = byId("owner-stripe-onboard");
  button.textContent = ready ? "Payout account ready" : connected ? "Continue Stripe onboarding" : "Set up payouts";
  button.disabled = ready;
}

function showOwnerStripeMessage(text = "", kind = "") {
  const node = byId("owner-stripe-message");
  node.textContent = text;
  node.className = `message owner-card-message${kind ? ` ${kind}` : ""}`;
}

async function loadOwnerStripeStatus() {
  try {
    const data = await apiRequest("/api/v1/stripe/connect/status");
    renderOwnerStripeStatus(data);
    showOwnerStripeMessage();
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
  }
}

async function syncOwnerStripeStatus() {
  const button = byId("owner-stripe-refresh");
  button.disabled = true;
  showOwnerStripeMessage("Refreshing Stripe payout status…");
  try {
    const status = await apiRequest("/api/v1/stripe/connect/status");
    if (status.connected) {
      await apiRequest("/api/v1/stripe/connect/sync", {method: "POST"});
    }
    await loadOwnerStripeStatus();
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function startOwnerStripeOnboarding() {
  const button = byId("owner-stripe-onboard");
  button.disabled = true;
  showOwnerStripeMessage("Preparing secure Stripe onboarding…");
  try {
    let status = await apiRequest("/api/v1/stripe/connect/status");
    if (!status.connected) {
      await apiRequest("/api/v1/stripe/connect/account", {method: "POST"});
      status = await apiRequest("/api/v1/stripe/connect/status");
    }
    if (status.ready_for_payouts) {
      renderOwnerStripeStatus(status);
      showOwnerStripeMessage("Your payout account is ready.", "success");
      return;
    }
    const link = await apiRequest("/api/v1/stripe/connect/onboarding-link", {method: "POST"});
    if (!link.url) throw new Error("Stripe onboarding link was not returned.");
    window.location.assign(link.url);
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
    button.disabled = false;
  }
}

function updateOwnerPayoutFields() {
  const cadence = byId("owner-payout-cadence").value;
  byId("owner-payout-weekday-wrap").classList.toggle(
    "hidden",
    !["WEEKLY", "FORTNIGHTLY"].includes(cadence)
  );
  byId("owner-payout-monthly-wrap").classList.toggle("hidden", cadence !== "MONTHLY");
}

function renderOwnerPayoutPreference(data) {
  const preference = data.preference || data;
  state.payoutPreferenceVersion = Number(preference.version || 0);
  byId("owner-payout-cadence").value = preference.cadence || "MANUAL";
  if (preference.weekday !== null && preference.weekday !== undefined) {
    byId("owner-payout-weekday").value = String(preference.weekday);
  }
  if (preference.monthly_day !== null && preference.monthly_day !== undefined) {
    byId("owner-payout-monthly-day").value = String(preference.monthly_day);
  }
  byId("owner-payout-next").textContent = preference.next_scheduled_at
    ? formatDateTime(preference.next_scheduled_at)
    : "Manual only";
  updateOwnerPayoutFields();
}

async function loadOwnerPayoutPreference() {
  const data = await apiRequest("/api/v1/payout-preferences");
  renderOwnerPayoutPreference(data);
}

async function saveOwnerPayoutPreference() {
  const cadence = byId("owner-payout-cadence").value;
  const payload = {
    cadence,
    weekday: ["WEEKLY", "FORTNIGHTLY"].includes(cadence)
      ? Number(byId("owner-payout-weekday").value)
      : null,
    monthly_day: cadence === "MONTHLY"
      ? Number(byId("owner-payout-monthly-day").value)
      : null,
    version: state.payoutPreferenceVersion,
  };
  const button = byId("owner-payout-save");
  button.disabled = true;
  const message = byId("owner-payout-preference-message");
  message.textContent = "Saving payout schedule…";
  message.className = "message owner-card-message";
  try {
    const data = await apiRequest("/api/v1/payout-preferences", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderOwnerPayoutPreference(data);
    message.textContent = "Payout schedule saved.";
    message.className = "message owner-card-message success";
  } catch (error) {
    message.textContent = error.message;
    message.className = "message owner-card-message error";
  } finally {
    button.disabled = false;
  }
}

function activateOwnerView(view) {
  const views = {
    overview: ["Overview", "Everything you need to track your cards, sales and payouts."],
    inventory: ["Inventory", "Browse and search every physical card linked to your seller account."],
    scan: ["Scan cards", "Use Drop Rate recognition to identify a card, confirm it and add it safely to your inventory."],
    sales: ["Sales", "Understand every sale, deduction and penny allocated to you."],
    balance: ["Payouts", "Manage your payout account, balance and preferred payout schedule."],
    settlements: ["Settlements", "Follow order-by-order allocation and reconciliation."],
  };
  const target = Object.hasOwn(views, view) ? view : "overview";

  document.querySelectorAll("[data-owner-view-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.ownerViewPanel !== target);
  });
  document.querySelectorAll(".owner-nav-item[data-owner-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.ownerView === target);
  });

  byId("owner-page-title").textContent = views[target][0];
  byId("owner-page-subtitle").textContent = views[target][1];
  history.replaceState({}, document.title, target === "overview" ? "/owner" : `/owner#${target}`);
  window.scrollTo({top: 0, behavior: "smooth"});
  if (target === "scan" && typeof window.ownerRecognitionEnter === "function") {
    window.ownerRecognitionEnter();
  }
}

function errorMessage(data) {
  const detail = data?.error_description || data?.msg || data?.detail || data?.message;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return "Something went wrong. Please try again.";
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(data));
  return data;
}

function showMessage(text = "", kind = "") {
  const node = byId("owner-login-message");
  node.textContent = text;
  node.className = `message${kind ? ` ${kind}` : ""}`;
}

function setBusy(form, busy) {
  const button = form.querySelector('button[type="submit"]');
  if (!button) return;
  button.disabled = busy;
  button.dataset.label ||= button.textContent;
  button.textContent = busy ? "Please wait…" : button.dataset.label;
}

async function authRequest(path, options = {}) {
  return readJson(await fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: state.config.publishable_key,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }));
}

function saveSession(session) {
  state.session = session;
  sessionStorage.setItem(OWNER_SESSION_KEY, JSON.stringify(session));
}

function clearSession() {
  state.session = null;
  sessionStorage.removeItem(OWNER_SESSION_KEY);
}

async function refreshSession() {
  if (!state.session?.refresh_token) throw new Error("Your session has expired.");
  const session = await authRequest("/token?grant_type=refresh_token", {
    method: "POST",
    body: JSON.stringify({refresh_token: state.session.refresh_token}),
  });
  saveSession(session);
  return session.access_token;
}

async function apiRequest(path, options = {}, retry = true) {
  const requestOptions = {
    ...options,
    headers: {
      Authorization: `Bearer ${state.session.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };
  let response = await fetch(path, requestOptions);
  if (response.status === 401 && retry) {
    requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
    response = await fetch(path, requestOptions);
  }
  return readJson(response);
}

async function loadSocialProviders() {
  try {
    const settings = await authRequest("/settings");
    const external = settings.external || {};
    state.providers.google = Boolean(external.google);
    state.providers.apple = Boolean(external.apple);
  } catch (_error) {
    state.providers.google = false;
    state.providers.apple = false;
  }

  byId("owner-google").classList.toggle("hidden", !state.providers.google);
  byId("owner-apple").classList.toggle("hidden", !state.providers.apple);
  byId("owner-social-auth").classList.toggle(
    "hidden",
    !state.providers.google && !state.providers.apple
  );
}

function startOAuth(provider) {
  if (!["google", "apple"].includes(provider) || !state.providers[provider]) {
    showMessage("That sign-in provider is not enabled yet.", "error");
    return;
  }
  const authorizeUrl = new URL(`${state.config.supabase_url}/auth/v1/authorize`);
  authorizeUrl.searchParams.set("provider", provider);
  authorizeUrl.searchParams.set("redirect_to", `${window.location.origin}/owner`);
  window.location.assign(authorizeUrl.toString());
}

function parseOAuthSession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (!params.get("access_token") || params.get("type") === "recovery") return false;
  saveSession({
    access_token: params.get("access_token"),
    refresh_token: params.get("refresh_token"),
    token_type: params.get("token_type") || "bearer",
    expires_in: Number(params.get("expires_in") || 3600),
  });
  history.replaceState({}, document.title, window.location.pathname);
  return true;
}

async function hydrateSessionUser() {
  if (!state.session?.access_token) return;
  const user = await authRequest("/user", {
    headers: {Authorization: `Bearer ${state.session.access_token}`},
  });
  state.session.user = user;
  saveSession(state.session);
}

function showOwnerOnboardingWelcome() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("welcome") !== "1") return;

  const panel = byId("owner-onboarding-welcome");
  if (!panel) return;
  panel.classList.remove("hidden");

  byId("owner-welcome-inventory").addEventListener("click", () => {
    activateOwnerView("inventory");
  }, {once: true});
  byId("owner-welcome-payouts").addEventListener("click", () => {
    activateOwnerView("balance");
    byId("owner-stripe-connect-panel")?.scrollIntoView({behavior: "smooth", block: "start"});
  }, {once: true});
  byId("owner-welcome-dismiss").addEventListener("click", () => {
    panel.classList.add("hidden");
  }, {once: true});

  history.replaceState({}, document.title, "/owner");
}


async function openOwnerPortal() {
  const result = await apiRequest("/api/v1/access/me");
  const access = result.access || {};

  if (access.access_role === "PLATFORM_ADMIN" || access.founder_hq_allowed === true) {
    window.location.replace("/");
    return;
  }
  if (access.access_role !== "OWNER" || access.portal !== "OWNER_PORTAL") {
    throw new Error("OWNER_PORTAL_ACCESS_DENIED");
  }

  const name = access.display_name || "Owner";
  byId("owner-portal-name").textContent = name;
  byId("owner-portal-initial").textContent = name.slice(0, 1).toUpperCase();
  byId("owner-portal-email").textContent = state.session?.user?.email || "Owner account";
  byId("owner-overview-name").textContent = name;

  byId("owner-auth-view").classList.add("hidden");
  byId("owner-portal-view").classList.remove("hidden");
  const hashView = window.location.hash.replace("#", "");
  activateOwnerView(["inventory", "scan", "sales", "balance", "settlements"].includes(hashView) ? hashView : "overview");
  await reloadOwnerDashboard();
  showOwnerOnboardingWelcome();
}

async function finishSignIn(session) {
  saveSession(session);
  await hydrateSessionUser();
  await openOwnerPortal();
}

function denyAccess(message) {
  clearSession();
  byId("owner-portal-view").classList.add("hidden");
  byId("owner-auth-view").classList.remove("hidden");
  showMessage(message, "error");
}

async function initialise() {
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
  } catch (_error) {
    showMessage("The owner portal is temporarily unavailable. Please refresh shortly.", "error");
    return;
  }

  await loadSocialProviders();

  if (parseOAuthSession()) {
    try {
      await hydrateSessionUser();
      await openOwnerPortal();
    } catch (error) {
      denyAccess(
        error.message === "OWNER_PORTAL_ACCESS_DENIED"
          || error.message === "No active owner membership"
          ? "This account does not have owner-portal access."
          : "We could not complete social sign in."
      );
    }
    return;
  }

  try {
    const stored = JSON.parse(sessionStorage.getItem(OWNER_SESSION_KEY));
    if (stored?.access_token) {
      state.session = stored;
      await openOwnerPortal();
    }
  } catch (_error) {
    clearSession();
  }
}

byId("owner-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage();
  try {
    const session = await authRequest("/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({
        email: byId("owner-email-input").value.trim().toLowerCase(),
        password: byId("owner-password-input").value,
      }),
    });
    await finishSignIn(session);
  } catch (error) {
    denyAccess(
      error.message === "OWNER_PORTAL_ACCESS_DENIED"
        || error.message === "No active owner membership"
        ? "This account does not have owner-portal access."
        : error.message
    );
  } finally {
    setBusy(form, false);
  }
});

byId("owner-google").addEventListener("click", () => startOAuth("google"));
byId("owner-apple").addEventListener("click", () => startOAuth("apple"));

byId("owner-inventory-refresh").addEventListener("click", async () => {
  state.inventory.search = byId("owner-inventory-search").value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  await reloadOwnerDashboard();
});

byId("owner-inventory-search").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  state.inventory.search = event.currentTarget.value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  await reloadOwnerDashboard();
});

let ownerInventorySearchTimer = null;
byId("owner-inventory-search").addEventListener("input", (event) => {
  window.clearTimeout(ownerInventorySearchTimer);
  ownerInventorySearchTimer = window.setTimeout(async () => {
    state.inventory.search = event.currentTarget.value.trim();
    state.inventory.status = byId("owner-inventory-status").value;
    state.inventory.offset = 0;
    await loadOwnerInventory();
  }, 320);
});

byId("owner-inventory-status").addEventListener("change", async (event) => {
  state.inventory.status = event.currentTarget.value;
  state.inventory.search = byId("owner-inventory-search").value.trim();
  state.inventory.offset = 0;
  await loadOwnerInventory();
});

byId("owner-inventory-prev").addEventListener("click", async () => {
  state.inventory.offset = Math.max(0, state.inventory.offset - state.inventory.limit);
  await loadOwnerInventory();
});

byId("owner-inventory-next").addEventListener("click", async () => {
  if (state.inventory.offset + state.inventory.limit >= state.inventory.total) return;
  state.inventory.offset += state.inventory.limit;
  await loadOwnerInventory();
});

document.querySelectorAll(".owner-nav-item[data-owner-view]").forEach((button) => {
  button.addEventListener("click", () => activateOwnerView(button.dataset.ownerView));
});

document.querySelectorAll("[data-owner-jump]").forEach((button) => {
  button.addEventListener("click", () => activateOwnerView(button.dataset.ownerJump));
});

document.querySelectorAll("[data-owner-inventory-layout]").forEach((button) => {
  button.addEventListener("click", () => {
    const layout = button.dataset.ownerInventoryLayout === "list" ? "list" : "grid";
    state.inventory.layout = layout;
    byId("owner-inventory-grid").classList.toggle("hidden", layout !== "grid");
    byId("owner-inventory-table-wrap").classList.toggle("hidden", layout !== "list");
    document.querySelectorAll("[data-owner-inventory-layout]").forEach((toggle) => {
      toggle.classList.toggle("active", toggle.dataset.ownerInventoryLayout === layout);
    });
  });
});

byId("owner-sales-prev").addEventListener("click", async () => {
  state.sales.offset = Math.max(0, state.sales.offset - state.sales.limit);
  await loadOwnerSales();
});
byId("owner-sales-next").addEventListener("click", async () => {
  if (state.sales.offset + state.sales.limit >= state.sales.total) return;
  state.sales.offset += state.sales.limit;
  await loadOwnerSales();
});
byId("owner-settlements-prev").addEventListener("click", async () => {
  state.settlements.offset = Math.max(0, state.settlements.offset - state.settlements.limit);
  await loadOwnerSettlements();
});
byId("owner-settlements-next").addEventListener("click", async () => {
  if (state.settlements.offset + state.settlements.limit >= state.settlements.total) return;
  state.settlements.offset += state.settlements.limit;
  await loadOwnerSettlements();
});

byId("owner-payout-cadence").addEventListener("change", updateOwnerPayoutFields);
byId("owner-payout-save").addEventListener("click", saveOwnerPayoutPreference);

byId("owner-stripe-refresh").addEventListener("click", syncOwnerStripeStatus);
byId("owner-stripe-onboard").addEventListener("click", startOwnerStripeOnboarding);

byId("owner-logout-button").addEventListener("click", () => {
  clearSession();
  byId("owner-portal-view").classList.add("hidden");
  byId("owner-auth-view").classList.remove("hidden");
  byId("owner-password-input").value = "";
  showMessage();
});

initialise();
