/* Founder oversight is read-only; stock mutations stay in the existing own-inventory flow. */
"use strict";
(function () {
  let generation = 0;
  let offset = 0;
  const limit = 40;
  let rows = [];
  const money = value => value == null ? "Pending valuation" : new Intl.NumberFormat("en-GB", {style: "currency", currency: "GBP"}).format(Number(value) / 100);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  function table(title, headings, records) {
    const section = node("section", null, "inventory-panel app-account-section");
    section.append(node("h2", title));
    if (!records.length) { section.append(node("p", "No records for this selection.", "muted")); return section; }
    const wrap = node("div", null, "table-wrap");
    const grid = node("table");
    const head = node("thead");
    const labels = node("tr");
    headings.forEach(label => { const cell = node("th", label); cell.scope = "col"; labels.append(cell); });
    head.append(labels);
    const body = node("tbody");
    records.forEach(values => { const row = node("tr"); values.forEach((value, index) => { const cell = node("td", value ?? "—"); cell.dataset.label = headings[index]; row.append(cell); }); body.append(row); });
    grid.append(head, body); wrap.append(grid); section.append(wrap);
    return section;
  }
  function renderSummary() {
    const owner = byId("accounts-owner").value;
    const selected = rows.filter(row => !owner || row.id === owner);
    const summary = byId("accounts-summary");
    summary.replaceChildren();
    const sum = key => selected.reduce((total, row) => total + Number(row[key] || 0), 0);
    [
      ["Accounts", selected.length], ["Inventory items", sum("inventory_count")],
      ["Sales revenue · all time", money(sum("sales_revenue_minor"))],
      ["Pending balance", money(sum("pending_minor"))],
      ["Available after payout requests", money(sum("available_to_withdraw_minor"))],
      ["Paid out · all time", money(sum("paid_out_minor"))],
      ["Shopify published", sum("shopify_published")], ["eBay live", sum("ebay_live")],
    ].forEach(([label, value]) => { const card = node("article", null, "stat-card"); card.append(node("span", label), node("strong", value)); summary.append(card); });
  }
  async function load(refreshAccounts = false) {
    const session = state.session;
    if (!session?.access_token) return;
    const request = ++generation;
    const account = session.user?.id;
    const current = () => request === generation && state.session?.access_token && state.session.user?.id === account;
    const output = byId("accounts-results");
    const message = byId("accounts-message");
    message.textContent = "Loading accounts…";
    output.replaceChildren();
    byId("accounts-prev").disabled = true;
    byId("accounts-next").disabled = true;
    byId("accounts-page").textContent = "";
    try {
      if (refreshAccounts || !rows.length) {
        const result = await apiRequest("/api/v1/founder/accounts");
        if (!current()) return;
        rows = result.accounts || [];
        const select = byId("accounts-owner");
        const selected = select.value;
        select.replaceChildren(new Option("All accounts", ""));
        rows.forEach(row => select.append(new Option(`${row.display_name}${row.id === result.own_owner_id ? " (you)" : ""}`, row.id)));
        select.value = rows.some(row => row.id === selected) ? selected : "";
      }
      renderSummary();
      const params = new URLSearchParams({limit: String(limit), offset: String(offset)});
      const owner = byId("accounts-owner").value;
      if (owner) params.set("owner_id", owner);
      const mode = byId("accounts-mode").value;
      if (mode === "inventory") params.set("search", byId("accounts-search").value.trim());
      const result = await apiRequest(`/api/v1/founder/accounts/${mode}?${params}`);
      if (!current()) return;
      let hasNext;
      if (mode === "inventory") {
        output.append(table("Inventory", ["Account", "Item", "Status", "Collection", "Market value", "Shopify", "eBay"], (result.items || []).map(item => [item.owner_name, [item.inventory_code, item.name, item.card_number, item.set_name, item.language, item.condition].filter(Boolean).join(" · "), item.status, item.sale_intent === "FOR_SALE" ? "For sale" : "Personal collection", money(item.market_value_minor), item.shopify_state || "Not listed", item.ebay_state || "Not listed"])));
        hasNext = offset + limit < result.total;
        byId("accounts-page").textContent = result.total ? `${offset + 1}–${Math.min(offset + limit, result.total)} of ${result.total}` : "0 items";
      } else {
        output.append(table("Sales · recorded order lines", ["Account", "Order", "Channel", "Status", "Sale price", "Date"], (result.sales || []).map(sale => [sale.owner_name, sale.order_number, sale.source, sale.status, money(sale.sale_price_minor), new Date(sale.created_at).toLocaleDateString("en-GB")])));
        output.append(table("Payout requests", ["Account", "Payout", "Amount", "Status", "Date"], (result.payouts || []).map(payout => [payout.owner_name, payout.payout_code, money(payout.amount_minor), payout.status, new Date(payout.created_at).toLocaleDateString("en-GB")])));
        hasNext = result.sales.length === limit || result.payouts.length === limit;
        byId("accounts-page").textContent = `Page ${Math.floor(offset / limit) + 1} · newest first`;
      }
      byId("accounts-prev").disabled = offset === 0;
      byId("accounts-next").disabled = !hasNext;
      message.textContent = "";
    } catch (error) {
      if (current()) { message.textContent = error.message || "Accounts could not be loaded. Try Refresh."; byId("accounts-summary").replaceChildren(); }
    }
  }
  function init() {
    const view = sellerView("accounts");
    if (!view || byId("accounts-form")) return;
    view.append(makeSellerHeading("Founder oversight", "Accounts", "View inventory, channel listings, sales and payouts across Drop Rate. Manage your own stock from Inventory."));
    const own = node("button", "Manage my inventory", "primary-button compact");
    own.type = "button"; own.addEventListener("click", () => activateSellerView("inventory", true)); view.append(own);
    const form = node("form", null, "app-account-filters"); form.id = "accounts-form";
    form.innerHTML = '<label>Account<select id="accounts-owner"><option value="">All accounts</option></select></label><label>View<select id="accounts-mode"><option value="inventory">Inventory</option><option value="activity">Sales & payouts</option></select></label><label id="accounts-search-label">Search inventory<input id="accounts-search" type="search" maxlength="160" placeholder="Name, set or inventory code"></label><button type="submit" class="ghost-button">Refresh</button>';
    form.addEventListener("submit", event => { event.preventDefault(); offset = 0; load(true); });
    form.querySelectorAll("select").forEach(select => select.addEventListener("change", () => { offset = 0; byId("accounts-search-label").hidden = byId("accounts-mode").value !== "inventory"; load(); }));
    const message = node("p", "Sign in to view accounts.", "message"); message.id = "accounts-message"; message.setAttribute("role", "status");
    const summary = node("div", null, "stats-grid"); summary.id = "accounts-summary";
    const output = node("div"); output.id = "accounts-results";
    const pages = node("div", null, "app-account-pages");
    pages.innerHTML = '<button id="accounts-prev" type="button" class="ghost-button" disabled>Previous</button><span id="accounts-page" aria-live="polite"></span><button id="accounts-next" type="button" class="ghost-button" disabled>Next</button>';
    view.append(form, message, summary, output, pages);
    byId("accounts-prev").addEventListener("click", () => { offset = Math.max(0, offset - limit); load(); });
    byId("accounts-next").addEventListener("click", () => { offset += limit; load(); });
  }
  document.addEventListener("seller-view-changed", event => { init(); if (event.detail.view === "accounts") load(true); });
  window.addEventListener("hub-session-cleared", () => {
    ++generation; rows = []; offset = 0;
    ["accounts-summary", "accounts-results"].forEach(id => byId(id)?.replaceChildren());
    if (byId("accounts-owner")) byId("accounts-owner").replaceChildren(new Option("All accounts", ""));
    if (byId("accounts-message")) byId("accounts-message").textContent = "Sign in to view accounts.";
  });
  const previousReload = reloadDashboard;
  reloadDashboard = async function (...args) {
    const result = await previousReload(...args);
    if (!sellerView("accounts")?.classList.contains("hidden")) await load(true);
    return result;
  };
  init();
})();
