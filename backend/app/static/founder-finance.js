"use strict";

const financeMoney = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

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
        <button id="finance-refresh" class="ghost-button" type="button">↻ Refresh finance</button>
        <button id="finance-payout-button" class="primary-button compact" type="button">Request payout</button>
      </div>
    </div>

    <div class="stats-grid">
      <article class="stat-card stat-accent"><span>Available balance</span><strong id="finance-available">£0.00</strong><small>Available to withdraw</small></article>
      <article class="stat-card"><span>Pending balance</span><strong id="finance-pending">£0.00</strong><small>Not yet available</small></article>
      <article class="stat-card"><span>Net profit</span><strong id="finance-net-profit">£0.00</strong><small>After cost, fees & shipping</small></article>
      <article class="stat-card"><span>Cards / items sold</span><strong id="finance-sold-items">0</strong><small>Physical inventory sold</small></article>
    </div>

    <div class="stats-grid">
      <article class="stat-card"><span>Sales revenue</span><strong id="finance-sales-revenue">£0.00</strong><small>After item discounts</small></article>
      <article class="stat-card"><span>Cost of goods</span><strong id="finance-cogs">£0.00</strong><small>Acquisition cost snapshot</small></article>
      <article class="stat-card"><span>Fees</span><strong id="finance-fees">£0.00</strong><small>Platform + payment fees</small></article>
      <article class="stat-card"><span>Shipping cost</span><strong id="finance-shipping-cost">£0.00</strong><small>Fulfilment/postage cost</small></article>
      <article class="stat-card"><span>Refunds</span><strong id="finance-refunds">£0.00</strong><small>Refund ledger entries</small></article>
      <article class="stat-card"><span>Paid out</span><strong id="finance-paid-out">£0.00</strong><small>Completed withdrawals</small></article>
      <article class="stat-card"><span>Reserved for payout</span><strong id="finance-reserved">£0.00</strong><small>Requested / approved payouts</small></article>
      <article class="stat-card"><span>Shipping income</span><strong id="finance-shipping-revenue">£0.00</strong><small>Shipping paid by customers</small></article>
    </div>

    <div id="finance-message" class="message panel-message" role="status"></div>

    <div class="page-heading">
      <div><p class="eyebrow">Sales ledger</p><h3>Recent sales</h3></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Item</th><th>Order</th><th>Revenue</th><th>Cost</th><th>Fees + shipping</th><th>Profit</th><th>Sold</th></tr></thead>
        <tbody id="finance-sales-body"></tbody>
      </table>
    </div>
    <div id="finance-sales-empty" class="empty-state"><div>◇</div><h3>No sales yet</h3><p>Sales will appear here when physical inventory is recorded as sold.</p></div>

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
        <div><p class="eyebrow">Founder withdrawal</p><h2>Request payout</h2><p class="muted">This creates an auditable payout request. No money is moved automatically.</p></div>
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

  byId("finance-refresh").addEventListener("click", loadFounderFinance);
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

function renderFinanceSummary(summary) {
  byId("finance-available").textContent = formatFinanceMoney(summary.available_to_withdraw_minor);
  byId("finance-pending").textContent = formatFinanceMoney(summary.pending_minor);
  byId("finance-net-profit").textContent = formatFinanceMoney(summary.net_profit_minor);
  byId("finance-sold-items").textContent = String(summary.sold_items || 0);
  byId("finance-sales-revenue").textContent = formatFinanceMoney(summary.sales_revenue_minor);
  byId("finance-cogs").textContent = formatFinanceMoney(summary.cost_of_goods_minor);
  byId("finance-fees").textContent = formatFinanceMoney((summary.platform_fees_minor || 0) + (summary.payment_fees_minor || 0));
  byId("finance-shipping-cost").textContent = formatFinanceMoney(summary.shipping_cost_minor);
  byId("finance-refunds").textContent = formatFinanceMoney(summary.refunds_minor);
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
    const feesShipping = (sale.platform_fee_minor || 0) + (sale.payment_fee_minor || 0) + (sale.shipping_cost_minor || 0);
    const soldAt = sale.sold_at ? new Date(sale.sold_at).toLocaleDateString("en-GB") : "—";
    row.innerHTML = `
      <td><strong></strong><small></small></td>
      <td></td><td></td><td></td><td></td><td></td><td></td>`;
    row.cells[0].querySelector("strong").textContent = sale.name || sale.inventory_code;
    row.cells[0].querySelector("small").textContent = [sale.inventory_code, sale.card_number, sale.set_name].filter(Boolean).join(" · ");
    row.cells[1].textContent = sale.order_number || sale.source_reference || "—";
    row.cells[2].textContent = formatFinanceMoney(sale.net_sale_minor);
    row.cells[3].textContent = formatFinanceMoney(sale.cost_basis_minor);
    row.cells[4].textContent = formatFinanceMoney(feesShipping);
    row.cells[5].textContent = formatFinanceMoney(sale.profit_minor);
    row.cells[6].textContent = soldAt;
    body.append(row);
  });
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

async function loadFounderFinance() {
  ensureFounderFinanceUI();
  if (!state.session?.access_token) return;
  showMessage("finance-message", "Loading finance…");
  try {
    const [summary, sales, payouts] = await Promise.all([
      apiRequest("/api/v1/finance/summary"),
      apiRequest("/api/v1/finance/sales?limit=25&offset=0"),
      apiRequest("/api/v1/finance/payouts"),
    ]);
    renderFinanceSummary(summary);
    renderFinanceSales(sales.items || []);
    renderFinancePayouts(payouts.items || []);
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
    showMessage("finance-message", "Payout request created. The amount is now reserved from your available balance.", "success");
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
