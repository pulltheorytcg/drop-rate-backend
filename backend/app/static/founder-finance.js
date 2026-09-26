"use strict";

const financeMoney = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });
const financeDate = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "Europe/London",
});
let financeSalesRange = {preset: "all_time", start: null, end: null};

function formatFinanceMoney(minor) {
  return financeMoney.format(Number(minor || 0) / 100);
}

function financeMinorFromInput(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const amount = Number(text);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  return Math.round(amount * 100);
}

function financeNonnegativeMinorFromInput(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const amount = Number(text);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return Math.round(amount * 100);
}


function ukTodayIso() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function financeShiftDate(iso, days) {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function financeStartOfWeek(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  const day = date.getUTCDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  return financeShiftDate(iso, mondayOffset);
}

function financePresetRange(preset) {
  const today = ukTodayIso();
  if (preset === "all_time") return {start: null, end: null};
  if (preset === "today") return {start: today, end: today};
  if (preset === "yesterday") {
    const yesterday = financeShiftDate(today, -1);
    return {start: yesterday, end: yesterday};
  }
  if (preset === "last_7") return {start: financeShiftDate(today, -6), end: today};
  if (preset === "this_week") return {start: financeStartOfWeek(today), end: today};
  if (preset === "this_month") return {start: `${today.slice(0, 7)}-01`, end: today};
  if (preset === "this_quarter") {
    const [year, month] = today.split("-").map(Number);
    const quarterMonth = Math.floor((month - 1) / 3) * 3 + 1;
    return {
      start: `${year}-${String(quarterMonth).padStart(2, "0")}-01`,
      end: today,
    };
  }
  if (preset === "this_year") return {start: `${today.slice(0, 4)}-01-01`, end: today};
  return {start: null, end: null};
}

function financeSalesQuery(range = financeSalesRange) {
  if (!range.start || !range.end) return "";
  const params = new URLSearchParams({
    start_date: range.start,
    end_date: range.end,
  });
  return `&${params.toString()}`;
}

function financeAnalyticsQuery(range = financeSalesRange) {
  if (!range.start || !range.end) return "";
  const params = new URLSearchParams({
    start_date: range.start,
    end_date: range.end,
  });
  return `?${params.toString()}`;
}

function financeRangeLabel(data) {
  const format = (iso) => iso
    ? financeDate.format(new Date(`${iso}T12:00:00Z`))
    : null;
  const start = data.start_date || data.first_sale_date;
  const end = data.end_date || data.last_sale_date;
  if (!start || !end) return "No recorded sales yet";
  if (start === end) return format(start);
  return `${format(start)} – ${format(end)}`;
}

function ensureFounderFinanceUI() {
  if (byId("founder-finance-panel")) return;
  const stats = document.querySelector("#dashboard-view .stats-grid");
  if (!stats) return;

  const section = document.createElement("section");
  section.id = "founder-finance-panel";
  section.className = "inventory-panel";
  section.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Founder finance</p>
        <h2>Balance & Profit</h2>
        <p class="muted">Deterministic sales, fees, shipping, profit and payout tracking from the Drop Rate ledger.</p>
      </div>
      <div class="topbar-actions">
        <button id="finance-reconcile-pending" class="ghost-button" type="button">Sync pending Shopify fees</button>
        <button id="finance-refresh" class="ghost-button" type="button">↻ Refresh finance</button>
        <button id="finance-payout-button" class="primary-button compact" type="button">Request payout</button>
      </div>
    </div>

    <div class="stats-grid">
      <article class="stat-card stat-accent"><span>Available balance</span><strong id="finance-available">£0.00</strong><small>Available to withdraw</small></article>
      <article class="stat-card"><span>Pending balance</span><strong id="finance-pending">£0.00</strong><small>Not yet available</small></article>
      <article class="stat-card"><span>Net profit</span><strong id="finance-net-profit">£0.00</strong><small id="finance-net-profit-note">After cost, fees, commission & postage</small></article>
      <article class="stat-card"><span>Cards / items sold</span><strong id="finance-sold-items">0</strong><small>Physical inventory sold</small></article>
    </div>

    <div class="stats-grid">
      <article class="stat-card"><span>Sales revenue</span><strong id="finance-sales-revenue">£0.00</strong><small>After item discounts</small></article>
      <article class="stat-card"><span>Cost of goods</span><strong id="finance-cogs">£0.00</strong><small>Acquisition cost snapshot</small></article>
      <article class="stat-card"><span>Fees</span><strong id="finance-fees">£0.00</strong><small id="finance-fees-note">Platform + payment fees</small></article>
      <article class="stat-card"><span>Postage cost</span><strong id="finance-shipping-cost">£0.00</strong><small id="finance-shipping-cost-note">Royal Mail postage</small></article>
      <article class="stat-card"><span>Materials</span><strong id="finance-material-cost">£0.00</strong><small>Packaging + card protection</small></article>
      <article class="stat-card"><span>Drop Rate commission</span><strong id="finance-commission">£0.00</strong><small id="finance-commission-note">Owner commission rate</small></article>
      <article class="stat-card"><span>Refunds</span><strong id="finance-refunds">£0.00</strong><small>Item + shipping refunds</small></article>
      <article class="stat-card"><span>Paid out</span><strong id="finance-paid-out">£0.00</strong><small>Completed withdrawals</small></article>
      <article class="stat-card"><span>Reserved for payout</span><strong id="finance-reserved">£0.00</strong><small>Requested / approved payouts</small></article>
      <article class="stat-card"><span>Shipping income</span><strong id="finance-shipping-revenue">£0.00</strong><small>Shipping paid by customers</small></article>
    </div>

    <section id="finance-sales-dashboard" class="finance-sales-dashboard">
      <div class="sales-range-toolbar">
        <div class="sales-range-title">
          <p class="eyebrow">Sales performance</p>
          <h3>Sales overview</h3>
          <span id="finance-sales-range-label" class="muted">All recorded sales</span>
        </div>
        <div class="sales-range-controls">
          <label>Period
            <select id="finance-sales-preset">
              <option value="all_time">All time</option>
              <option value="today">Today</option>
              <option value="yesterday">Yesterday</option>
              <option value="last_7">Last 7 days</option>
              <option value="this_week">This week</option>
              <option value="this_month">This month</option>
              <option value="this_quarter">This quarter</option>
              <option value="this_year">This year</option>
              <option value="custom">Custom dates</option>
            </select>
          </label>
          <div id="finance-sales-custom-range" class="sales-custom-range hidden">
            <label>From<input id="finance-sales-start" type="date"></label>
            <label>To<input id="finance-sales-end" type="date"></label>
            <button id="finance-sales-apply" class="primary-button compact" type="button">Apply</button>
          </div>
        </div>
      </div>

      <div id="finance-sales-message" class="message panel-message" role="status"></div>

      <div class="sales-kpi-grid">
        <article class="sales-kpi sales-kpi-primary"><span>Total sales</span><strong id="finance-period-sales">£0.00</strong><small>Item revenue after discounts</small></article>
        <article class="sales-kpi"><span>Net revenue</span><strong id="finance-period-net-revenue">£0.00</strong><small>After refunds, incl. shipping income</small></article>
        <article class="sales-kpi"><span>Net profit</span><strong id="finance-period-profit">£0.00</strong><small id="finance-period-profit-note">After COGS, fees, commission & fulfilment</small></article>
        <article class="sales-kpi"><span>Orders</span><strong id="finance-period-orders">0</strong><small id="finance-period-aov">£0.00 gross AOV</small></article>
        <article class="sales-kpi"><span>Items sold</span><strong id="finance-period-items">0</strong><small>Physical inventory items</small></article>
      </div>

      <div class="sales-chart-card">
        <div class="sales-chart-heading">
          <div><strong>Sales over time</strong><small id="finance-sales-chart-grain">Grouped by month</small></div>
        </div>
        <div id="finance-sales-chart" class="sales-chart" aria-label="Sales over time"></div>
      </div>
    </section>

    <section id="finance-settlement-section" class="finance-settlement-section">
      <div class="page-heading">
        <div>
          <p class="eyebrow">Owner settlement</p>
          <h3>Settlement report</h3>
          <p class="muted">Auditable proceeds per order with marketplace fees, Drop Rate commission and refunds shown separately. Acquisition cost affects profit, not payout proceeds.</p>
        </div>
      </div>
      <div id="finance-settlement-message" class="message panel-message" role="status"></div>
      <div class="table-wrap">
        <table class="finance-settlement-table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Reconciliation</th>
              <th>Gross proceeds</th>
              <th>External deductions</th>
              <th>Commission</th>
              <th>Adjustments</th>
              <th>Net owner proceeds</th>
              <th>Cost basis</th>
              <th>Owner profit</th>
              <th>Funds</th>
            </tr>
          </thead>
          <tbody id="finance-settlements-body"></tbody>
        </table>
      </div>
      <div id="finance-settlements-empty" class="empty-state">
        <div>◇</div>
        <h3>No settlements yet</h3>
        <p>Verified owner settlement rows will appear after a physical item is sold.</p>
      </div>
    </section>

    <div id="finance-message" class="message panel-message" role="status"></div>

    <div class="page-heading">
      <div><p class="eyebrow">Sales ledger</p><h3>Recent sales</h3></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Item</th><th>Order</th><th>Revenue</th><th>Cost</th><th>Fees + commission</th><th>Profit</th><th>Sold</th></tr></thead>
        <tbody id="finance-sales-body"></tbody>
      </table>
    </div>
    <div id="finance-sales-empty" class="empty-state"><div>◇</div><h3>No sales yet</h3><p>Sales will appear here when physical inventory is recorded as sold.</p></div>

    <section id="stripe-payout-account" class="finance-settlement-section">
      <div class="page-heading">
        <div>
          <p class="eyebrow">Stripe Connect</p>
          <h3>Payout account</h3>
          <p class="muted">Stripe handles identity verification and bank payout details. Drop Rate decides the exact settlement amount.</p>
        </div>
        <div class="topbar-actions">
          <button id="stripe-payout-sync" class="ghost-button compact" type="button">↻ Refresh Stripe</button>
          <button id="stripe-payout-onboard" class="primary-button compact" type="button">Set up payouts</button>
        </div>
      </div>
      <div id="stripe-payout-message" class="message panel-message" role="status"></div>
      <div class="stats-grid">
        <article class="stat-card"><span>Connect account</span><strong id="stripe-connect-state">NOT CONNECTED</strong><small id="stripe-connect-note">No Stripe payout account yet</small></article>
        <article class="stat-card"><span>Verification</span><strong id="stripe-verification-state">NOT READY</strong><small id="stripe-verification-note">Onboarding required</small></article>
        <article class="stat-card"><span>Transfers</span><strong id="stripe-transfers-state">LOCKED</strong><small>Must be active before approval</small></article>
        <article class="stat-card"><span>Automatic execution</span><strong id="stripe-execution-state">LOCKED</strong><small>Production kill-switch</small></article>
      </div>

      <div class="payout-preference-panel">
        <div class="page-heading">
          <div>
            <p class="eyebrow">Payout preferences</p>
            <h3>Choose payout frequency</h3>
            <p class="muted">Drop Rate controls when eligible owner proceeds are queued. Stripe and your bank still control final settlement timing.</p>
          </div>
        </div>
        <div class="form-grid payout-preference-grid">
          <label>
            Frequency
            <select id="payout-preference-cadence">
              <option value="MANUAL">Manual</option>
              <option value="DAILY">Daily</option>
              <option value="WEEKLY">Weekly</option>
              <option value="FORTNIGHTLY">Every 2 weeks</option>
              <option value="MONTHLY">Monthly</option>
            </select>
          </label>
          <label id="payout-preference-weekday-wrap" class="hidden">
            Day of week
            <select id="payout-preference-weekday">
              <option value="0">Monday</option>
              <option value="1">Tuesday</option>
              <option value="2">Wednesday</option>
              <option value="3">Thursday</option>
              <option value="4">Friday</option>
              <option value="5">Saturday</option>
              <option value="6">Sunday</option>
            </select>
          </label>
          <label id="payout-preference-monthly-wrap" class="hidden">
            Day of month
            <input id="payout-preference-monthly-day" type="number" min="1" max="31" step="1" value="1">
          </label>
        </div>
        <div class="allocation-summary payout-preference-summary">
          <span>Next scheduled payout</span>
          <strong id="payout-preference-next">Manual only</strong>
        </div>
        <p class="muted">Daily means the next eligible payout cycle, not guaranteed next-day bank arrival. Scheduled payouts still require available cleared funds and all payout safety checks.</p>
        <div id="payout-preference-message" class="message panel-message" role="status"></div>
        <button id="payout-preference-save" class="primary-button compact" type="button">Save payout schedule</button>
      </div>
    </section>

    <section id="stripe-payout-queue-section" class="finance-settlement-section">
      <div class="page-heading">
        <div>
          <p class="eyebrow">Payout control</p>
          <h3>Approval queue</h3>
          <p class="muted">Founder review is required before a payout can ever reach Stripe execution.</p>
        </div>
      </div>
      <div id="stripe-payout-queue-message" class="message panel-message" role="status"></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Owner</th><th>Payout</th><th>Amount</th><th>Stripe</th><th>Checks</th><th>Status</th><th></th></tr></thead>
          <tbody id="stripe-payout-queue-body"></tbody>
        </table>
      </div>
      <div id="stripe-payout-queue-empty" class="empty-state"><div>◇</div><h3>No payouts awaiting review</h3><p>Requested or approved payouts will appear here.</p></div>
    </section>

    <div class="page-heading">
      <div><p class="eyebrow">Withdrawals</p><h3>Payout requests</h3><p class="muted">Requests reserve available balance but do not move money automatically.</p></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Payout</th><th>Amount</th><th>Status</th><th>Requested</th><th></th></tr></thead>
        <tbody id="finance-payouts-body"></tbody>
      </table>
    </div>
    <div id="finance-payouts-empty" class="empty-state"><div>◇</div><h3>No payouts requested</h3><p>Your withdrawal history will appear here.</p></div>
  `;
  stats.insertAdjacentElement("afterend", section);

  const dialog = document.createElement("dialog");
  dialog.id = "finance-payout-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <form id="finance-payout-form" class="modal-card">
      <div class="modal-heading">
        <div><p class="eyebrow">Owner payout</p><h2>Request payout</h2><p class="muted">This reserves verified owner proceeds for payout. No money moves until the payout controls allow it.</p></div>
        <button class="icon-button" type="button" data-close="finance-payout-dialog" aria-label="Close">×</button>
      </div>
      <div class="form-grid">
        <label>Amount (£)<input id="finance-payout-amount" type="number" min="0.01" step="0.01" inputmode="decimal" required></label>
        <label class="full-width">Notes<textarea id="finance-payout-notes" maxlength="1000" rows="3" placeholder="Optional payout note"></textarea></label>
      </div>
      <div id="finance-payout-message" class="message" role="status"></div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" data-close="finance-payout-dialog">Cancel</button>
        <button class="primary-button compact" type="submit">Request payout</button>
      </div>
    </form>`;
  document.body.append(dialog);

  byId("finance-reconcile-pending").addEventListener("click", reconcilePendingShopifyFees);
  byId("finance-sales-preset").addEventListener("change", handleFinanceSalesPreset);
  byId("finance-sales-apply").addEventListener("click", applyFinanceCustomRange);
  byId("finance-refresh").addEventListener("click", loadFounderFinance);
  byId("stripe-payout-sync").addEventListener("click", syncStripePayoutAccount);
  byId("stripe-payout-onboard").addEventListener("click", startStripePayoutOnboarding);
  byId("payout-preference-cadence").addEventListener("change", updatePayoutPreferenceFields);
  byId("payout-preference-save").addEventListener("click", savePayoutPreference);
  byId("finance-payout-button").addEventListener("click", () => {
    byId("finance-payout-form").reset();
    showMessage("finance-payout-message");
    dialog.showModal();
  });
  dialog.querySelectorAll('[data-close="finance-payout-dialog"]').forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  byId("finance-payout-form").addEventListener("submit", submitFounderPayout);
}

function renderFinanceSalesAnalytics(data) {
  byId("finance-period-sales").textContent = formatFinanceMoney(data.sales_revenue_minor);
  byId("finance-period-net-revenue").textContent = formatFinanceMoney(data.net_revenue_minor);
  byId("finance-period-orders").textContent = Number(data.orders || 0).toLocaleString("en-GB");
  byId("finance-period-items").textContent = Number(data.sold_items || 0).toLocaleString("en-GB");
  byId("finance-period-aov").textContent =
    `${formatFinanceMoney(data.average_order_value_minor)} gross AOV`;
  byId("finance-sales-range-label").textContent = financeRangeLabel(data);

  const provisionalProfit = formatFinanceMoney(data.net_profit_minor);
  if (data.net_profit_complete) {
    byId("finance-period-profit").textContent = provisionalProfit;
    byId("finance-period-profit-note").textContent = "After COGS, fees, commission & fulfilment";
  } else {
    byId("finance-period-profit").textContent = "Pending";
    byId("finance-period-profit-note").textContent =
      `Provisional ${provisionalProfit} · ${Number(data.unreconciled_external_sales ?? data.unreconciled_shopify_sales ?? 0)} sale(s) awaiting marketplace costs`;
  }

  const grainNames = {day: "day", week: "week", month: "month"};
  byId("finance-sales-chart-grain").textContent =
    `Grouped by ${grainNames[data.bucket] || data.bucket || "period"}`;
  renderFinanceSalesChart(data.series || [], data.bucket || "day");
}

function renderFinanceSalesChart(series, bucket = "day") {
  const chart = byId("finance-sales-chart");
  if (!chart) return;
  chart.replaceChildren();
  chart.classList.toggle("single-point", series.length === 1);
  if (!series.length) {
    const empty = document.createElement("div");
    empty.className = "sales-chart-empty";
    empty.textContent = "No sales in this period.";
    chart.append(empty);
    return;
  }

  const maxSales = Math.max(...series.map((item) => Math.max(Number(item.sales_revenue_minor || 0), 0)), 1);
  const labelOptions = bucket === "month"
    ? { month: "short", year: "2-digit", timeZone: "Europe/London" }
    : { day: "2-digit", month: "short", timeZone: "Europe/London" };
  series.forEach((item) => {
    const column = document.createElement("div");
    column.className = "sales-chart-column";
    const barWrap = document.createElement("div");
    barWrap.className = "sales-chart-bar-wrap";
    const bar = document.createElement("div");
    bar.className = "sales-chart-bar";
    const amount = Math.max(Number(item.sales_revenue_minor || 0), 0);
    bar.style.height = `${Math.max((amount / maxSales) * 100, amount ? 5 : 0)}%`;
    const bucketLabel = financeRangeLabel({start_date: item.bucket_date, end_date: item.bucket_date});
    const orderLabel = `${Number(item.orders || 0).toLocaleString("en-GB")} order(s)`;
    const itemLabel = `${Number(item.sold_items || 0).toLocaleString("en-GB")} item(s)`;
    bar.title = [
      bucketLabel,
      `Sales ${formatFinanceMoney(item.sales_revenue_minor)}`,
      `Net revenue ${formatFinanceMoney(item.net_revenue_minor)}`,
      `Profit ${formatFinanceMoney(item.profit_minor)}`,
      orderLabel,
      itemLabel,
    ].join(" · ");
    bar.setAttribute(
      "aria-label",
      `${bucketLabel}: ${formatFinanceMoney(item.sales_revenue_minor)} sales, ${orderLabel}`
    );
    barWrap.append(bar);

    const label = document.createElement("small");
    const date = new Date(`${item.bucket_date}T12:00:00Z`);
    label.textContent = date.toLocaleDateString("en-GB", labelOptions);
    column.append(barWrap, label);
    chart.append(column);
  });
}

function handleFinanceSalesPreset(event) {
  const preset = event.target.value;
  const custom = byId("finance-sales-custom-range");
  custom.classList.toggle("hidden", preset !== "custom");
  if (preset === "custom") {
    if (!byId("finance-sales-start").value || !byId("finance-sales-end").value) {
      const today = ukTodayIso();
      byId("finance-sales-start").value = financeShiftDate(today, -6);
      byId("finance-sales-end").value = today;
    }
    return;
  }
  const range = financePresetRange(preset);
  financeSalesRange = {preset, ...range};
  loadFinanceSalesRange();
}

function applyFinanceCustomRange() {
  const start = byId("finance-sales-start").value;
  const end = byId("finance-sales-end").value;
  if (!start || !end) {
    showMessage("finance-sales-message", "Choose both a From and To date.", "error");
    return;
  }
  if (end < start) {
    showMessage("finance-sales-message", "The To date cannot be before the From date.", "error");
    return;
  }
  financeSalesRange = {preset: "custom", start, end};
  loadFinanceSalesRange();
}

async function loadFinanceSalesRange() {
  if (!state.session?.access_token) return;
  const preset = byId("finance-sales-preset");
  if (preset && preset.value !== financeSalesRange.preset) preset.value = financeSalesRange.preset;
  try {
    const [analytics, sales] = await Promise.all([
      apiRequest(`/api/v1/finance/sales-analytics${financeAnalyticsQuery()}`),
      apiRequest(`/api/v1/finance/sales?limit=100&offset=0${financeSalesQuery()}`),
    ]);
    renderFinanceSalesAnalytics(analytics);
    renderFinanceSales(sales.items || []);
    showMessage("finance-sales-message");
  } catch (error) {
    showMessage("finance-sales-message", error.message, "error");
  }
}

function renderFinanceSummary(summary) {
  byId("finance-available").textContent = formatFinanceMoney(summary.available_to_withdraw_minor);
  byId("finance-pending").textContent = formatFinanceMoney(summary.pending_minor);
  const provisionalNetProfit = formatFinanceMoney(summary.net_profit_minor);
  if (summary.net_profit_complete) {
    byId("finance-net-profit").textContent = provisionalNetProfit;
    byId("finance-net-profit-note").textContent = "After cost, fees, commission & postage";
  } else {
    byId("finance-net-profit").textContent = "Pending";
    byId("finance-net-profit-note").textContent = `Provisional ${provisionalNetProfit} · awaiting settlement costs`;
  }
  byId("finance-sold-items").textContent = String(summary.sold_items || 0);
  byId("finance-sales-revenue").textContent = formatFinanceMoney(summary.sales_revenue_minor);
  byId("finance-cogs").textContent = formatFinanceMoney(summary.cost_of_goods_minor);

  const recordedFees = (summary.platform_fees_minor || 0) + (summary.payment_fees_minor || 0);
  byId("finance-fees").textContent = summary.fees_complete
    ? formatFinanceMoney(recordedFees)
    : "Pending";
  byId("finance-fees-note").textContent = summary.fees_complete
    ? "Platform + payment fees"
    : `${formatFinanceMoney(recordedFees)} recorded · awaiting marketplace fees`;

  byId("finance-shipping-cost").textContent = summary.shipping_cost_complete
    ? formatFinanceMoney(summary.shipping_cost_minor)
    : "Pending";
  byId("finance-shipping-cost-note").textContent = summary.shipping_cost_complete
    ? "Royal Mail postage"
    : `${formatFinanceMoney(summary.shipping_cost_minor)} recorded · postage not entered`;
  byId("finance-material-cost").textContent = formatFinanceMoney(
    summary.fulfilment_material_cost_minor
  );
  byId("finance-commission").textContent = formatFinanceMoney(summary.commission_minor);
  byId("finance-commission-note").textContent =
    `${(Number(summary.commission_bps || 0) / 100).toFixed(2)}% owner rate · refunds reverse commission proportionally`;
  byId("finance-refunds").textContent = formatFinanceMoney(
    (summary.refunds_minor || 0) + (summary.shipping_refunds_minor || 0)
  );
  byId("finance-paid-out").textContent = formatFinanceMoney(summary.paid_out_minor);
  byId("finance-reserved").textContent = formatFinanceMoney(summary.reserved_payout_minor);
  byId("finance-shipping-revenue").textContent = formatFinanceMoney(summary.shipping_revenue_minor);
  byId("finance-payout-button").disabled = Number(summary.available_to_withdraw_minor || 0) <= 0;
}

function renderFinanceSales(items) {
  const body = byId("finance-sales-body");
  body.replaceChildren();
  byId("finance-sales-empty").classList.toggle("hidden", items.length > 0);
  items.forEach((sale) => {
    const row = document.createElement("tr");
    row.className = "finance-sale-row";
    const feesPostage =
      (sale.platform_fee_minor || 0)
      + (sale.payment_fee_minor || 0)
      + (sale.shipping_cost_minor || 0)
      + (sale.fulfilment_material_cost_minor || 0)
      + (sale.commission_minor || 0);
    const soldAt = sale.sold_at
      ? new Date(sale.sold_at).toLocaleDateString("en-GB")
      : "—";
    const itemMeta = [sale.set_name, sale.card_number, sale.variant]
      .filter(Boolean)
      .join(" · ");
    const shippingPaid = Number(sale.shipping_revenue_minor || 0);
    const costsComplete = Boolean(
      sale.fees_complete && sale.shipping_cost_complete
    );

    row.innerHTML = `
      <td class="finance-item-cell" data-label="Item">
        <strong></strong>
        <small class="finance-item-meta"></small>
        <span class="code finance-item-code"></span>
      </td>
      <td data-label="Order"></td>
      <td class="finance-money-cell" data-label="Revenue"><strong></strong><small></small></td>
      <td data-label="Cost"></td>
      <td class="finance-money-cell" data-label="Fees + commission"><strong></strong><small></small></td>
      <td class="finance-money-cell" data-label="Profit"><strong></strong><small></small></td>
      <td data-label="Sold"></td>`;

    const itemCell = row.cells[0];
    itemCell.querySelector("strong").textContent = sale.name || "Unnamed item";
    itemCell.querySelector(".finance-item-meta").textContent = itemMeta || "—";
    const code = itemCell.querySelector(".finance-item-code");
    code.textContent = sale.inventory_code;
    code.title = sale.inventory_code;

    row.cells[1].textContent = sale.order_number || sale.source_reference || "—";

    const revenueCell = row.cells[2];
    revenueCell.querySelector("strong").textContent = formatFinanceMoney(sale.net_sale_minor);
    revenueCell.querySelector("small").textContent = shippingPaid
      ? `+ ${formatFinanceMoney(shippingPaid)} shipping paid`
      : "No shipping charged";

    row.cells[3].textContent = formatFinanceMoney(sale.cost_basis_minor);

    const costsCell = row.cells[4];
    if (costsComplete) {
      costsCell.querySelector("strong").textContent = formatFinanceMoney(feesPostage);
      costsCell.querySelector("small").textContent =
        `Fees + postage + materials + ${formatFinanceMoney(sale.commission_minor || 0)} commission`;
    } else {
      costsCell.querySelector("strong").textContent = "Pending";
      const pending = [];
      if (!sale.fees_complete) pending.push("fees");
      if (!sale.shipping_cost_complete) pending.push("postage");
      costsCell.querySelector("small").textContent =
        `${formatFinanceMoney(feesPostage)} recorded`;
      const pendingLabel = document.createElement("span");
      pendingLabel.className = "finance-pending-costs";
      pendingLabel.textContent = `Awaiting ${pending.join(" + ")}`;
      costsCell.append(pendingLabel);
    }

    if (["SHOPIFY", "EBAY"].includes(sale.source) && !costsComplete) {
      const actions = document.createElement("div");
      actions.className = "finance-reconcile-actions";
      if (!sale.fees_complete) {
        const feesButton = document.createElement("button");
        feesButton.type = "button";
        feesButton.className = "ghost-button";
        if (sale.source === "SHOPIFY") {
          feesButton.textContent = "Sync fees";
          feesButton.addEventListener("click", () => reconcileShopifyFees(sale));
        } else {
          feesButton.textContent = "Set eBay fees";
          feesButton.addEventListener("click", () => reconcileEbayFees(sale));
        }
        actions.append(feesButton);
      }
      if (!sale.shipping_cost_complete) {
        const setPostage = document.createElement("button");
        setPostage.type = "button";
        setPostage.className = "ghost-button";
        setPostage.textContent = "Set postage";
        setPostage.addEventListener("click", () => reconcileMarketplacePostage(sale));
        actions.append(setPostage);
      }
      costsCell.append(actions);
    }

    const profitCell = row.cells[5];
    if (sale.profit_complete) {
      profitCell.querySelector("strong").textContent = formatFinanceMoney(sale.profit_minor);
      profitCell.querySelector("small").textContent = "Final";
    } else {
      profitCell.querySelector("strong").textContent = "Pending";
      profitCell.querySelector("small").textContent =
        `Provisional ${formatFinanceMoney(sale.profit_minor)}`;
    }

    row.cells[6].textContent = soldAt;
    body.append(row);
  });
}

function renderFinanceSettlements(items) {
  const body = byId("finance-settlements-body");
  if (!body) return;
  body.replaceChildren();
  byId("finance-settlements-empty").classList.toggle("hidden", items.length > 0);

  items.forEach((settlement) => {
    const row = document.createElement("tr");
    row.className = "finance-settlement-row";
    row.innerHTML = `
      <td data-label="Order"><strong></strong><small></small></td>
      <td data-label="Reconciliation"><strong></strong><small></small></td>
      <td data-label="Gross proceeds"></td>
      <td data-label="External deductions"></td>
      <td data-label="Commission"></td>
      <td data-label="Adjustments"></td>
      <td data-label="Net owner proceeds"><strong></strong></td>
      <td data-label="Cost basis"></td>
      <td data-label="Owner profit"><strong></strong></td>
      <td data-label="Funds"><strong></strong><small></small></td>`;

    const orderCell = row.cells[0];
    orderCell.querySelector("strong").textContent =
      settlement.order_number || settlement.source_reference || "—";
    orderCell.querySelector("small").textContent =
      `${settlement.source} · ${settlement.order_status}`;

    const reconciliationCell = row.cells[1];
    reconciliationCell.querySelector("strong").textContent =
      settlement.reconciliation_complete ? "Verified" : "Pending";
    reconciliationCell.querySelector("small").textContent =
      settlement.reconciliation_complete
        ? "All settlement inputs reconciled"
        : (settlement.blockers || []).join(" + ") || "Reconciliation required";

    row.cells[2].textContent = formatFinanceMoney(settlement.gross_proceeds_minor);
    row.cells[3].textContent = formatFinanceMoney(settlement.external_deductions_minor);
    row.cells[4].textContent = formatFinanceMoney(settlement.commission_minor);
    row.cells[5].textContent = formatFinanceMoney(settlement.adjustments_minor);
    row.cells[6].querySelector("strong").textContent =
      formatFinanceMoney(settlement.net_owner_proceeds_minor);
    row.cells[7].textContent = formatFinanceMoney(settlement.effective_cogs_minor);
    row.cells[8].querySelector("strong").textContent =
      formatFinanceMoney(settlement.owner_profit_minor);

    const fundsCell = row.cells[9];
    fundsCell.querySelector("strong").textContent =
      `${formatFinanceMoney(settlement.available_ledger_minor)} available`;
    fundsCell.querySelector("small").textContent =
      `${formatFinanceMoney(settlement.pending_ledger_minor)} pending`;

    body.append(row);
  });
}


let payoutPreferenceVersion = 0;

function updatePayoutPreferenceFields() {
  const cadence = byId("payout-preference-cadence").value;
  byId("payout-preference-weekday-wrap").classList.toggle(
    "hidden",
    !["WEEKLY", "FORTNIGHTLY"].includes(cadence)
  );
  byId("payout-preference-monthly-wrap").classList.toggle(
    "hidden",
    cadence !== "MONTHLY"
  );
}

function formatPayoutScheduleDate(value) {
  if (!value) return "Manual only";
  const date = new Date(value);
  return date.toLocaleString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function renderPayoutPreference(data) {
  const preference = data.preference || data;
  payoutPreferenceVersion = Number(preference.version || 0);
  byId("payout-preference-cadence").value = preference.cadence || "MANUAL";
  if (preference.weekday !== null && preference.weekday !== undefined) {
    byId("payout-preference-weekday").value = String(preference.weekday);
  }
  if (preference.monthly_day !== null && preference.monthly_day !== undefined) {
    byId("payout-preference-monthly-day").value = String(preference.monthly_day);
  }
  byId("payout-preference-next").textContent =
    formatPayoutScheduleDate(preference.next_scheduled_at);
  updatePayoutPreferenceFields();
}

async function loadPayoutPreference() {
  try {
    const result = await apiRequest("/api/v1/payout-preferences");
    renderPayoutPreference(result);
    showMessage("payout-preference-message");
  } catch (error) {
    showMessage("payout-preference-message", error.message, "error");
  }
}

async function savePayoutPreference() {
  const button = byId("payout-preference-save");
  const cadence = byId("payout-preference-cadence").value;
  const payload = {
    cadence,
    weekday: ["WEEKLY", "FORTNIGHTLY"].includes(cadence)
      ? Number(byId("payout-preference-weekday").value)
      : null,
    monthly_day: cadence === "MONTHLY"
      ? Number(byId("payout-preference-monthly-day").value)
      : null,
    version: payoutPreferenceVersion,
  };
  button.disabled = true;
  showMessage("payout-preference-message", "Saving payout schedule…");
  try {
    const result = await apiRequest("/api/v1/payout-preferences", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderPayoutPreference(result);
    showMessage(
      "payout-preference-message",
      "Payout schedule saved. Automatic money movement remains locked until payout execution is enabled.",
      "success"
    );
  } catch (error) {
    showMessage("payout-preference-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function renderStripePayoutStatus(data) {
  const account = data.account || null;
  const blockers = data.blockers || [];
  byId("stripe-connect-state").textContent = data.connected ? "CONNECTED" : "NOT CONNECTED";
  byId("stripe-connect-note").textContent = account
    ? `${account.livemode ? "Live" : "Test"} · ${account.account_type || "EXPRESS"}`
    : (data.configured ? "Ready to create a Stripe payout account" : "Stripe API key not configured");

  byId("stripe-verification-state").textContent = data.ready_for_payouts ? "READY" : "ACTION REQUIRED";
  byId("stripe-verification-note").textContent = data.ready_for_payouts
    ? "Identity and payout requirements satisfied"
    : (blockers.length ? blockers.join(" · ") : "Stripe onboarding required");

  byId("stripe-transfers-state").textContent =
    account?.transfers_capability_status === "ACTIVE" && account?.payouts_enabled
      ? "READY" : "LOCKED";
  byId("stripe-execution-state").textContent =
    data.payout_execution_enabled ? "ENABLED" : "LOCKED";

  const onboard = byId("stripe-payout-onboard");
  onboard.disabled = !data.configured;
  onboard.classList.toggle("hidden", data.ready_for_payouts);
  onboard.textContent = data.connected ? "Continue Stripe onboarding" : "Set up payouts";
}

function renderStripePayoutQueue(items) {
  const body = byId("stripe-payout-queue-body");
  body.replaceChildren();
  byId("stripe-payout-queue-empty").classList.toggle("hidden", items.length > 0);
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = "<td></td><td></td><td></td><td></td><td></td><td></td><td></td>";
    row.cells[0].textContent = item.display_name || "Owner";
    row.cells[1].textContent = item.payout_code;
    row.cells[2].textContent = formatFinanceMoney(item.amount_minor);
    row.cells[3].textContent = item.stripe_status || "NOT CONNECTED";
    row.cells[4].textContent = item.blockers?.length ? item.blockers.join(", ") : "Passed";
    row.cells[5].textContent = item.execution_state || item.status;

    if (item.status === "REQUESTED") {
      const actions = document.createElement("div");
      actions.className = "topbar-actions";
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "primary-button compact";
      approve.textContent = "Approve";
      approve.disabled = !item.eligible_for_approval;
      approve.addEventListener("click", () => approveStripePayout(item));
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "ghost-button compact";
      reject.textContent = "Reject";
      reject.addEventListener("click", () => rejectStripePayout(item));
      actions.append(approve, reject);
      row.cells[6].append(actions);
    }
    body.append(row);
  });
}

async function loadStripePayoutControl() {
  if (!state.session?.access_token) return;
  try {
    const status = await apiRequest("/api/v1/stripe/connect/status");
    renderStripePayoutStatus(status);
    showMessage("stripe-payout-message");
  } catch (error) {
    showMessage("stripe-payout-message", error.message, "error");
  }

  await loadPayoutPreference();

  try {
    const queue = await apiRequest("/api/v1/stripe/payouts/queue");
    renderStripePayoutQueue(queue.items || []);
    showMessage("stripe-payout-queue-message");
  } catch (error) {
    byId("stripe-payout-queue-section").classList.add("hidden");
  }
}

async function startStripePayoutOnboarding() {
  const button = byId("stripe-payout-onboard");
  button.disabled = true;
  showMessage("stripe-payout-message", "Preparing secure Stripe onboarding…");
  try {
    await apiRequest("/api/v1/stripe/connect/account", {method: "POST"});
    const result = await apiRequest("/api/v1/stripe/connect/onboarding-link", {method: "POST"});
    window.location.assign(result.url);
  } catch (error) {
    showMessage("stripe-payout-message", error.message, "error");
    button.disabled = false;
  }
}

async function syncStripePayoutAccount() {
  const button = byId("stripe-payout-sync");
  button.disabled = true;
  try {
    const current = await apiRequest("/api/v1/stripe/connect/status");
    if (current.connected) {
      await apiRequest("/api/v1/stripe/connect/sync", {method: "POST"});
    }
    await loadStripePayoutControl();
  } catch (error) {
    showMessage("stripe-payout-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function approveStripePayout(item) {
  showMessage("stripe-payout-queue-message", `Approving ${item.payout_code}…`);
  try {
    await apiRequest(`/api/v1/stripe/payouts/${item.id}/approve`, {
      method: "POST",
      body: JSON.stringify({version: item.version, reason: ""}),
    });
    await loadFounderFinance();
    showMessage(
      "stripe-payout-queue-message",
      `${item.payout_code} approved and prepared. No money has moved.`,
      "success"
    );
  } catch (error) {
    showMessage("stripe-payout-queue-message", error.message, "error");
  }
}

async function rejectStripePayout(item) {
  const reason = window.prompt("Why is this payout being rejected?");
  if (reason === null) return;
  if (!reason.trim()) {
    showMessage("stripe-payout-queue-message", "A rejection reason is required.", "error");
    return;
  }
  try {
    await apiRequest(`/api/v1/stripe/payouts/${item.id}/reject`, {
      method: "POST",
      body: JSON.stringify({version: item.version, reason: reason.trim()}),
    });
    await loadFounderFinance();
    showMessage("stripe-payout-queue-message", `${item.payout_code} rejected.`, "success");
  } catch (error) {
    showMessage("stripe-payout-queue-message", error.message, "error");
  }
}

function renderFinancePayouts(items) {
  const body = byId("finance-payouts-body");
  body.replaceChildren();
  byId("finance-payouts-empty").classList.toggle("hidden", items.length > 0);
  items.forEach((payout) => {
    const row = document.createElement("tr");
    const requested = payout.requested_at ? new Date(payout.requested_at).toLocaleDateString("en-GB") : "—";
    row.innerHTML = `<td></td><td></td><td></td><td></td><td></td>`;
    row.cells[0].textContent = payout.payout_code;
    row.cells[1].textContent = formatFinanceMoney(payout.amount_minor);
    row.cells[2].textContent = payout.status;
    row.cells[3].textContent = requested;
    if (payout.status === "REQUESTED") {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "ghost-button";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", () => cancelFounderPayout(payout));
      row.cells[4].append(cancel);
    }
    body.append(row);
  });
}

async function reconcilePendingShopifyFees() {
  const button = byId("finance-reconcile-pending");
  if (button) button.disabled = true;
  showMessage("finance-message", "Checking pending Shopify fee settlements…");
  try {
    const result = await apiRequest(
      "/api/v1/finance/shopify/reconcile-pending-fees?limit=25",
      { method: "POST" }
    );
    await loadFounderFinance();
    if (!result.considered) {
      showMessage("finance-message", "No Shopify fee reconciliations are pending.", "success");
      return;
    }
    if (result.blocked) {
      showMessage(
        "finance-message",
        `Checked ${result.considered} order(s): ${result.reconciled} reconciled, ${result.pending} still settling, ${result.blocked} require review.`,
        "error"
      );
      return;
    }
    if (result.pending) {
      showMessage(
        "finance-message",
        `Checked ${result.considered} order(s): ${result.reconciled} reconciled and ${result.pending} still settling at Shopify.`,
        "success"
      );
      return;
    }
    showMessage(
      "finance-message",
      `Shopify fees reconciled for ${result.reconciled} order(s).`,
      "success"
    );
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}


async function reconcileShopifyFees(sale) {
  showMessage("finance-message", `Syncing Shopify fees for ${sale.order_number || "order"}…`);
  try {
    const result = await apiRequest(
      `/api/v1/finance/shopify/orders/${sale.order_id}/reconcile-fees`,
      { method: "POST" }
    );
    await loadFounderFinance();
    if (result.fees_complete) {
      showMessage(
        "finance-message",
        `Shopify fees reconciled: ${formatFinanceMoney(result.payment_fees_minor)}.`,
        "success"
      );
    } else {
      const statuses = (result.unsettled_transaction_statuses || []).join(", ");
      showMessage(
        "finance-message",
        `Recorded known Shopify fees. Final fee settlement is still pending${statuses ? ` (${statuses})` : ""}.`,
        "success"
      );
    }
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  }
}

async function reconcileEbayFees(sale) {
  const value = window.prompt(
    "Total verified eBay selling fees for this order in £.",
    "0.00"
  );
  if (value === null) return;
  const amountMinor = financeNonnegativeMinorFromInput(value);
  if (amountMinor === null) {
    showMessage("finance-message", "Enter a valid eBay fee total of £0.00 or more.", "error");
    return;
  }
  const reference = window.prompt(
    "Fee reference (eBay transaction/payout reference or statement reference):",
    sale.order_number ? `${sale.order_number}-EBAY-FEES` : "EBAY-FEES"
  );
  if (reference === null) return;
  const cleanReference = reference.trim();
  if (!cleanReference) {
    showMessage("finance-message", "An eBay fee reference is required.", "error");
    return;
  }

  showMessage("finance-message", `Recording eBay fees for ${sale.order_number || "order"}…`);
  try {
    const result = await apiRequest(
      `/api/v1/finance/ebay/orders/${sale.order_id}/fees`,
      {
        method: "POST",
        body: JSON.stringify({
          amount_minor: amountMinor,
          reference: cleanReference,
          notes: "Founder-verified eBay selling fees pending automated Finances API reconciliation.",
        }),
      }
    );
    await loadFounderFinance();
    showMessage(
      "finance-message",
      `eBay fees reconciled: ${formatFinanceMoney(result.platform_fees_minor)}.`,
      "success"
    );
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  }
}

async function reconcileShopifyPostage(sale) {
  return reconcileMarketplacePostage(sale);
}

async function reconcileMarketplacePostage(sale) {
  const value = window.prompt(
    "Actual postage / fulfilment cost in £. Enter 0.00 if this order was not shipped.",
    "0.00"
  );
  if (value === null) return;
  const amountMinor = financeNonnegativeMinorFromInput(value);
  if (amountMinor === null) {
    showMessage("finance-message", "Enter a valid postage cost of £0.00 or more.", "error");
    return;
  }

  const reference = window.prompt(
    "Postage reference (label ID, courier reference, or e.g. TEST-NOT-SHIPPED):",
    sale.order_number ? `${sale.order_number}-POSTAGE` : "POSTAGE"
  );
  if (reference === null) return;
  const cleanReference = reference.trim();
  if (!cleanReference) {
    showMessage("finance-message", "A postage reference is required.", "error");
    return;
  }

  showMessage("finance-message", `Recording postage for ${sale.order_number || "order"}…`);
  try {
    const result = await apiRequest(
      `/api/v1/finance/${String(sale.source || "").toLowerCase()}/orders/${sale.order_id}/postage`,
      {
        method: "POST",
        body: JSON.stringify({
          amount_minor: amountMinor,
          reference: cleanReference,
          notes: amountMinor === 0
            ? "Confirmed no postage/fulfilment cost."
            : "Actual postage/fulfilment cost entered by founder.",
        }),
      }
    );
    await loadFounderFinance();
    showMessage(
      "finance-message",
      `Postage ${formatFinanceMoney(amountMinor)} + materials ${formatFinanceMoney(result.fulfilment_material_cost_minor)} reconciled.`,
      "success"
    );
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  }
}


async function loadFounderFinance() {
  ensureFounderFinanceUI();
  if (!state.session?.access_token) return;
  showMessage("finance-message", "Loading finance…");
  try {
    const [summary, analytics, sales, settlements, payouts] = await Promise.all([
      apiRequest("/api/v1/finance/summary"),
      apiRequest(`/api/v1/finance/sales-analytics${financeAnalyticsQuery()}`),
      apiRequest(`/api/v1/finance/sales?limit=100&offset=0${financeSalesQuery()}`),
      apiRequest("/api/v1/finance/settlements?limit=50&offset=0"),
      apiRequest("/api/v1/finance/payouts"),
    ]);
    renderFinanceSummary(summary);
    renderFinanceSalesAnalytics(analytics);
    renderFinanceSales(sales.items || []);
    renderFinanceSettlements(settlements.items || []);
    renderFinancePayouts(payouts.items || []);
    await loadStripePayoutControl();
    showMessage("finance-message");
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  }
}

async function submitFounderPayout(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const amountMinor = financeMinorFromInput(byId("finance-payout-amount").value);
  if (!amountMinor) {
    showMessage("finance-payout-message", "Enter a payout amount greater than £0.00.", "error");
    return;
  }
  setBusy(form, true);
  try {
    await apiRequest("/api/v1/finance/payouts", {
      method: "POST",
      body: JSON.stringify({
        amount_minor: amountMinor,
        notes: byId("finance-payout-notes").value.trim(),
      }),
    });
    byId("finance-payout-dialog").close();
    await loadFounderFinance();
    showMessage("finance-message", "Payout request created and reserved. Founder approval and Stripe readiness are required before any money can move.", "success");
  } catch (error) {
    showMessage("finance-payout-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

async function cancelFounderPayout(payout) {
  showMessage("finance-message", `Cancelling ${payout.payout_code}…`);
  try {
    await apiRequest(`/api/v1/finance/payouts/${payout.id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ version: payout.version }),
    });
    await loadFounderFinance();
    showMessage("finance-message", `${payout.payout_code} cancelled and its reserved balance released.`, "success");
  } catch (error) {
    showMessage("finance-message", error.message, "error");
  }
}

ensureFounderFinanceUI();
const previousReloadDashboardForFinance = reloadDashboard;
reloadDashboard = async function (...args) {
  const result = await previousReloadDashboardForFinance(...args);
  await loadFounderFinance();
  return result;
};
