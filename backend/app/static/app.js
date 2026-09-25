"use strict";

const SESSION_KEY = "drop_rate_founder_session";
const PAGE_SIZE = 25;
const ISSUE_LABELS = {
  missing_cost: "Missing cost", missing_condition: "Missing raw condition",
  missing_seal_status: "Missing seal status",
  missing_location: "Missing location", missing_language: "Missing language", missing_price: "Missing store price",
  identity_unconfirmed: "Identity unchecked", approval_ready: "Ready to approve",
};
const state = {
  config: null, session: null, offset: 0, total: 0, search: "", status: "",
  brand: "", issue: "", items: new Map(), selected: new Map(), editing: null, readiness: null,
};
const byId = (id) => document.getElementById(id);

function errorMessage(data) {
  const detail = data.error_description || data.msg || data.detail || data.message;
  if (typeof detail === "string") return detail;
  if (detail?.missing) return `${detail.message}: ${detail.missing.join(", ")}.`;
  if (detail?.message) return detail.message;
  return "Something went wrong. Please try again.";
}

function showMessage(id, text = "", kind = "") {
  const node = byId(id);
  node.textContent = text;
  node.className = `message${kind ? ` ${kind}` : ""}${id === "inventory-message" ? " panel-message" : ""}`;
}
function showForm(formId) {
  ["login-form", "request-reset-form", "new-password-form"].forEach((id) => byId(id).classList.toggle("hidden", id !== formId));
}
function setBusy(form, busy) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = busy;
  button.dataset.label ||= button.textContent;
  button.textContent = busy ? "Please wait…" : button.dataset.label;
}
async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(data));
  return data;
}
async function authRequest(path, options = {}) {
  return readJson(await fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: { apikey: state.config.publishable_key, "Content-Type": "application/json", ...(options.headers || {}) },
  }));
}
function saveSession(session) {
  state.session = session;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}
function clearSession() {
  state.session = null;
  sessionStorage.removeItem(SESSION_KEY);
}
async function refreshSession() {
  if (!state.session?.refresh_token) throw new Error("Your session has expired.");
  const session = await authRequest("/token?grant_type=refresh_token", { method: "POST", body: JSON.stringify({ refresh_token: state.session.refresh_token }) });
  saveSession(session);
  return session.access_token;
}
async function apiRequest(path, options = {}, retry = true) {
  const requestOptions = {
    ...options,
    headers: { Authorization: `Bearer ${state.session.access_token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  };
  let response = await fetch(path, requestOptions);
  if (response.status === 401 && retry) {
    requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
    response = await fetch(path, requestOptions);
  }
  return readJson(response);
}
function redirectPendingFounderInviteCallback() {
  const pendingInvite = localStorage.getItem("drop_rate_pending_founder_invite");
  if (!pendingInvite || !window.location.hash) return false;

  const params = new URLSearchParams(window.location.hash.slice(1));
  if (!params.get("access_token") || params.get("type") === "recovery") return false;

  window.location.replace(
    `/join?invite=${encodeURIComponent(pendingInvite)}${window.location.hash}`
  );
  return true;
}

function parseRecoverySession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (params.get("type") !== "recovery" || !params.get("access_token")) return false;
  saveSession({ access_token: params.get("access_token"), refresh_token: params.get("refresh_token"), token_type: "bearer", expires_in: Number(params.get("expires_in") || 3600) });
  history.replaceState({}, document.title, window.location.pathname);
  showForm("new-password-form");
  return true;
}
function money(value, currency = "GBP") {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(value / 100);
}
function minorToInput(value) {
  return value === null || value === undefined ? "" : (value / 100).toFixed(2);
}
function inputToMinor(value, allowNull = true) {
  const clean = String(value).trim();
  if (!clean && allowNull) return null;
  if (!/^\d+(\.\d{0,2})?$/.test(clean)) throw new Error("Money values must use no more than two decimal places.");
  return Math.round(Number(clean) * 100);
}
function emptyToNull(value) {
  const clean = value.trim();
  return clean || null;
}
function textCell(label, text, className = "") {
  const td = document.createElement("td");
  td.dataset.label = label;
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

function itemCoreReadiness(item) {
  const checks = [];
  const isCard = item.product_type === "CARD";
  const isGraded = isCard
    && Boolean((item.grading_company || "").trim())
    && Boolean((item.grade || "").trim());

  checks.push({
    label: isCard ? (isGraded ? "Grade" : "Condition") : "Seal",
    ok: isCard
      ? (isGraded || Boolean((item.condition || "").trim()))
      : Boolean(item.seal_status),
  });
  checks.push({ label: "Cost", ok: item.acquisition_cost_minor !== null && item.acquisition_cost_minor !== undefined });
  if (isCard) checks.push({ label: "Language", ok: Boolean((item.language || "").trim()) });
  checks.push({ label: "Location", ok: Boolean(item.storage_location_id) });
  checks.push({ label: "Price", ok: item.store_price_minor !== null && item.store_price_minor !== undefined });
  checks.push({ label: "Identity", ok: Boolean(item.identity_confirmed) });

  return {
    complete: checks.filter((check) => check.ok).length,
    total: checks.length,
    missing: checks.filter((check) => !check.ok).map((check) => check.label),
  };
}

function refreshSelectionControls() {
  const count = state.selected.size;
  byId("selected-count").textContent = String(count);
  byId("bulk-cost-button").disabled = count < 2;
  const visible = [...state.items.values()];
  byId("select-page").checked = visible.length > 0 && visible.every((item) => state.selected.has(item.id));
  byId("select-page").indeterminate = visible.some((item) => state.selected.has(item.id)) && !byId("select-page").checked;
}

function renderInventory(data) {
  state.total = data.total;
  state.items = new Map(data.items.map((item) => [item.id, item]));
  byId("total-count").textContent = state.readiness?.total?.toLocaleString("en-GB") || data.total.toLocaleString("en-GB");
  byId("owner-name").textContent = data.owner.display_name;
  byId("owner-initial").textContent = data.owner.display_name.slice(0, 1).toUpperCase();
  const body = byId("inventory-body");
  body.replaceChildren();
  data.items.forEach((item) => {
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    selectCell.dataset.label = "Select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(item.id);
    checkbox.setAttribute("aria-label", `Select ${item.name}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.set(item.id, item); else state.selected.delete(item.id);
      refreshSelectionControls();
    });
    selectCell.append(checkbox);
    row.append(selectCell);
    const name = document.createElement("td");
    name.dataset.label = "Item";
    const wrap = document.createElement("div");
    wrap.className = "card-name";
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    const meta = document.createElement("small");
    const productLabel = item.product_type === "SEALED"
      ? "Sealed product"
      : item.product_type === "COLLECTION" ? "Collection" : null;
    meta.textContent = [
      productLabel,
      item.brand,
      item.game && item.game !== item.brand ? item.game : null,
      item.card_number,
      item.variant,
    ].filter(Boolean).join(" · ") || "Uncatalogued";
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = item.inventory_code;
    const readiness = itemCoreReadiness(item);
    const readinessLine = document.createElement("span");
    readinessLine.className = `core-readiness${readiness.complete === readiness.total ? " complete" : ""}`;
    readinessLine.textContent = readiness.complete === readiness.total
      ? `Core ${readiness.complete}/${readiness.total} ✓`
      : `Core ${readiness.complete}/${readiness.total} · Needs ${readiness.missing.join(", ")}`;
    wrap.append(strong, meta, code, readinessLine);
    name.append(wrap);
    row.append(name);
    row.append(textCell("Set", item.set_name || "—", "set-detail"));
    row.append(textCell("Condition", item.product_type === "CARD" && !item.grade ? (item.condition || "—") : "—"));
    row.append(textCell("Grading", item.product_type === "CARD" && item.grade ? `${item.grading_company || "Graded"} ${item.grade}` : "—"));
    row.append(textCell("Seal", item.product_type !== "CARD" ? (item.seal_status === "SEALED" ? "Sealed" : item.seal_status === "UNSEALED" ? "Unsealed" : "—") : "—"));
    row.append(textCell("Cost", money(item.acquisition_cost_minor, item.currency)));
    row.append(textCell("Store price", money(item.store_price_minor, item.currency)));
    const status = document.createElement("td");
    status.dataset.label = "Status";
    const pill = document.createElement("span");
    pill.className = `pill ${item.status.toLowerCase()}`;
    pill.textContent = item.status.charAt(0) + item.status.slice(1).toLowerCase();
    status.append(pill);
    row.append(status);
    const actions = document.createElement("td");
    actions.dataset.label = "Actions";
    const edit = document.createElement("button");
    edit.className = "row-button";
    edit.type = "button";
    edit.textContent = "Review";
    edit.addEventListener("click", () => openEditor(item));
    actions.append(edit);
    row.append(actions);
    body.append(row);
  });
  byId("empty-state").classList.toggle("hidden", data.items.length !== 0);
  byId("previous-page").disabled = state.offset === 0;
  byId("next-page").disabled = state.offset + PAGE_SIZE >= data.total;
  byId("page-label").textContent = `Page ${Math.floor(state.offset / PAGE_SIZE) + 1} of ${Math.max(1, Math.ceil(data.total / PAGE_SIZE))}`;
  refreshSelectionControls();
}

function renderReadiness(data) {
  state.readiness = data;
  const actionCount = data.total - data.approved - data.approval_ready;
  byId("total-count").textContent = data.total.toLocaleString("en-GB");
  byId("action-count").textContent = Math.max(0, actionCount).toLocaleString("en-GB");
  byId("ready-count").textContent = data.approval_ready.toLocaleString("en-GB");
  byId("approved-count").textContent = data.approved.toLocaleString("en-GB");
  const container = byId("issue-buttons");
  container.replaceChildren();
  Object.entries(ISSUE_LABELS).forEach(([key, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `issue-button${state.issue === key ? " active" : ""}`;
    button.append(document.createTextNode(label));
    const count = document.createElement("strong");
    count.textContent = (data[key] ?? 0).toLocaleString("en-GB");
    button.append(count);
    button.addEventListener("click", () => {
      state.issue = state.issue === key ? "" : key;
      state.offset = 0;
      renderReadiness(state.readiness);
      loadInventory();
    });
    container.append(button);
  });
}
async function loadReadiness() {
  renderReadiness(await apiRequest("/api/v1/inventory/readiness"));
}

async function loadBrandOptions() {
  const select = byId("brand-filter");
  const current = state.brand;
  const data = await apiRequest("/api/v1/inventory/brands");
  const preferred = ["One Piece", "Pokemon", "Dragon Ball", "Naruto", "Riftbound"];
  const labels = {Pokemon: "Pokémon"};
  const counts = new Map((data.items || []).map((item) => [item.brand, item.count]));
  const discovered = [...counts.keys()].filter((brand) => !preferred.includes(brand)).sort();
  const brands = [...preferred, ...discovered];

  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All brands / TCGs";
  select.append(all);

  brands.forEach((brand) => {
    const option = document.createElement("option");
    option.value = brand;
    const count = counts.get(brand);
    option.textContent = count === undefined
      ? (labels[brand] || brand)
      : `${labels[brand] || brand} (${Number(count).toLocaleString("en-GB")})`;
    select.append(option);
  });

  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  } else {
    state.brand = "";
    select.value = "";
  }
}

async function loadInventory() {
  showMessage("inventory-message", "Loading inventory…");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  if (state.brand) params.set("brand", state.brand);
  if (state.issue) params.set("issue", state.issue);
  try {
    renderInventory(await apiRequest(`/api/v1/inventory?${params}`));
    showMessage("inventory-message");
  } catch (error) {
    showMessage("inventory-message", error.message, "error");
    if (/session|token|expired/i.test(error.message)) logout();
  }
}
async function reloadDashboard(message = "") {
  await Promise.all([loadReadiness(), loadBrandOptions(), loadInventory()]);
  if (message) showMessage("inventory-message", message, "success");
}

function openEditor(item) {
  state.editing = item;
  byId("editor-title").textContent = item.name;
  const productLabel = item.product_type === "SEALED"
    ? "Sealed product"
    : item.product_type === "COLLECTION" ? "Collection" : "Card";
  byId("editor-meta").textContent = [productLabel, item.set_name, item.card_number, item.inventory_code].filter(Boolean).join(" · ");
  byId("edit-cost").value = minorToInput(item.acquisition_cost_minor);
  byId("edit-date").value = item.acquisition_date || "";
  byId("edit-condition").value = item.condition || "";
  byId("edit-language").value = item.language || item.catalogue_language || "";
  byId("edit-location").value = item.location || "";
  byId("edit-price").value = minorToInput(item.store_price_minor);
  byId("edit-grading-company").value = item.grading_company || "";
  byId("edit-grade").value = item.grade || "";
  byId("edit-certificate").value = item.certificate_number || "";
  const workflowLocked = ["RESERVED", "SOLD"].includes(item.status);
  byId("edit-status").value = item.status;
  byId("edit-status").disabled = item.status === "APPROVED" || workflowLocked;
  byId("edit-notes").value = item.notes || "";
  byId("edit-identity").checked = item.identity_confirmed;
  byId("edit-identity").disabled = true;
  byId("approve-button").disabled = item.status === "APPROVED" || workflowLocked;
  byId("approve-button").textContent =
    item.status === "APPROVED" ? "Already approved" :
    item.status === "RESERVED" ? "Reserved for order" :
    item.status === "SOLD" ? "Sold" : "Approve stock";
  const saveButton = byId("editor-form").querySelector('button[type="submit"]');
  if (saveButton) saveButton.disabled = workflowLocked;
  showMessage(
    "editor-message",
    workflowLocked
      ? (item.status === "RESERVED"
          ? "This physical item is reserved for an order. Release or consume its reservation before editing it."
          : "Sold inventory is historical and cannot be edited.")
      : ""
  );
  byId("editor-dialog").showModal();
}
async function saveEditor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (["RESERVED", "SOLD"].includes(state.editing?.status)) {
    showMessage("editor-message", "Reserved or sold inventory cannot be edited here.", "error");
    return;
  }
  setBusy(form, true);
  showMessage("editor-message");
  try {
    const company = emptyToNull(byId("edit-grading-company").value);
    const grade = emptyToNull(byId("edit-grade").value);
    if ((company === null) !== (grade === null)) throw new Error("Grading company and grade must both be filled in, or both left blank.");
    const payload = {
      version: state.editing.version,
      acquisition_cost_minor: inputToMinor(byId("edit-cost").value),
      acquisition_date: byId("edit-date").value || null,
      condition: emptyToNull(byId("edit-condition").value),
      language: emptyToNull(byId("edit-language").value),
      location: emptyToNull(byId("edit-location").value),
      store_price_minor: inputToMinor(byId("edit-price").value),
      grading_company: company, grade,
      certificate_number: emptyToNull(byId("edit-certificate").value),
      notes: byId("edit-notes").value.trim(),
    };
    if (state.editing.status !== "APPROVED") payload.status = byId("edit-status").value;
    await apiRequest(`/api/v1/inventory/${state.editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
    state.selected.delete(state.editing.id);
    byId("editor-dialog").close();
    await reloadDashboard("Changes saved and audit history recorded.");
  } catch (error) { showMessage("editor-message", error.message, "error"); }
  finally { setBusy(form, false); }
}
async function approveEditingItem() {
  showMessage("editor-message", "Checking approval requirements…");
  byId("approve-button").disabled = true;
  try {
    await apiRequest(`/api/v1/inventory/${state.editing.id}/approve`, {
      method: "POST", body: JSON.stringify({ version: state.editing.version }),
    });
    state.selected.delete(state.editing.id);
    byId("editor-dialog").close();
    await reloadDashboard("Stock item approved.");
  } catch (error) {
    showMessage("editor-message", error.message, "error");
    byId("approve-button").disabled = false;
  }
}

function openBulkDialog() {
  const items = [...state.selected.values()];
  byId("bulk-item-count").textContent = `${items.length} selected cards`;
  byId("bulk-total").value = "";
  byId("bulk-date").value = "";
  const list = byId("allocation-list");
  list.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    row.dataset.id = item.id;
    const details = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    const small = document.createElement("small");
    small.textContent = [item.set_name, item.inventory_code].filter(Boolean).join(" · ");
    details.append(strong, small);
    const input = document.createElement("input");
    input.type = "number"; input.min = "0"; input.step = "0.01";
    input.value = minorToInput(item.acquisition_cost_minor) || "0.00";
    input.setAttribute("aria-label", `Allocated cost for ${item.name}`);
    input.addEventListener("input", updateAllocationRemaining);
    row.append(details, input);
    list.append(row);
  });
  showMessage("bulk-message");
  updateAllocationRemaining();
  byId("bulk-dialog").showModal();
}
function allocationRows() {
  return [...byId("allocation-list").querySelectorAll(".allocation-row")];
}
function splitEqually() {
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const rows = allocationRows();
    const base = Math.floor(total / rows.length);
    let remainder = total - (base * rows.length);
    rows.forEach((row) => {
      const amount = base + (remainder > 0 ? 1 : 0);
      if (remainder > 0) remainder -= 1;
      row.querySelector("input").value = (amount / 100).toFixed(2);
    });
    updateAllocationRemaining();
  } catch (error) { showMessage("bulk-message", error.message, "error"); }
}
function updateAllocationRemaining() {
  const summary = byId("bulk-remaining");
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const allocated = allocationRows().reduce((sum, row) => sum + inputToMinor(row.querySelector("input").value, false), 0);
    const remaining = total - allocated;
    summary.textContent = remaining === 0 ? "Fully allocated" : `${money(Math.abs(remaining))} ${remaining > 0 ? "remaining" : "over"}`;
    summary.className = remaining === 0 ? "ok" : "error";
    byId("bulk-save").disabled = remaining !== 0;
  } catch (_error) {
    summary.textContent = "Enter a valid total";
    summary.className = "error";
    byId("bulk-save").disabled = true;
  }
}
async function saveBulkAllocation(event) {
  event.preventDefault();
  setBusy(event.currentTarget, true);
  showMessage("bulk-message");
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const items = allocationRows().map((row) => {
      const selected = state.selected.get(row.dataset.id);
      return { inventory_id: selected.id, version: selected.version, acquisition_cost_minor: inputToMinor(row.querySelector("input").value, false) };
    });
    if (items.reduce((sum, item) => sum + item.acquisition_cost_minor, 0) !== total) throw new Error("Every penny of the purchase total must be allocated.");
    await apiRequest("/api/v1/inventory/bulk-cost", {
      method: "POST",
      body: JSON.stringify({ total_cost_minor: total, acquisition_date: byId("bulk-date").value || null, items }),
    });
    state.selected.clear();
    byId("bulk-dialog").close();
    await reloadDashboard(`Acquisition cost allocated across ${items.length} cards.`);
  } catch (error) { showMessage("bulk-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
}

async function openDashboard() {
  try {
    const me = await apiRequest("/api/v1/me");
    byId("owner-email").textContent = state.session.user?.email || byId("login-email").value || "Founder account";
    byId("owner-name").textContent = me.owner.display_name;
    byId("auth-view").classList.add("hidden");
    byId("dashboard-view").classList.remove("hidden");
    await reloadDashboard();
  } catch (_error) {
    clearSession();
    byId("dashboard-view").classList.add("hidden");
    byId("auth-view").classList.remove("hidden");
    showForm("login-form");
    showMessage("login-message", "Please sign in to continue.", "error");
  }
}
function logout() {
  clearSession();
  state.offset = 0;
  state.selected.clear();
  byId("dashboard-view").classList.add("hidden");
  byId("auth-view").classList.remove("hidden");
  showForm("login-form");
  byId("login-password").value = "";
}
async function initialise() {
  try { state.config = await readJson(await fetch("/api/v1/public-config")); }
  catch (_error) { showMessage("login-message", "The dashboard is temporarily unavailable. Please refresh shortly.", "error"); return; }
  if (redirectPendingFounderInviteCallback()) return;
  if (parseRecoverySession()) return;
  try {
    const stored = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (stored?.access_token) { state.session = stored; await openDashboard(); }
  } catch (_error) { clearSession(); }
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setBusy(event.currentTarget, true); showMessage("login-message");
  try {
    const session = await authRequest("/token?grant_type=password", { method: "POST", body: JSON.stringify({ email: byId("login-email").value.trim(), password: byId("login-password").value }) });
    saveSession(session); await openDashboard();
  } catch (error) { showMessage("login-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});
byId("show-reset").addEventListener("click", () => { byId("reset-email").value = byId("login-email").value; showForm("request-reset-form"); });
document.querySelector("[data-back-login]").addEventListener("click", () => showForm("login-form"));
byId("request-reset-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setBusy(event.currentTarget, true);
  try {
    await authRequest("/recover", { method: "POST", body: JSON.stringify({ email: byId("reset-email").value.trim(), redirect_to: `${window.location.origin}/` }) });
    showMessage("reset-message", "Recovery email sent. Check your inbox and junk folder.", "success");
  } catch (error) { showMessage("reset-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});
byId("new-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = byId("new-password").value;
  if (password !== byId("confirm-password").value) { showMessage("password-message", "The passwords do not match.", "error"); return; }
  setBusy(event.currentTarget, true);
  try {
    await authRequest("/user", { method: "PUT", headers: { Authorization: `Bearer ${state.session.access_token}` }, body: JSON.stringify({ password }) });
    showMessage("password-message", "Password saved. Opening your inventory…", "success"); await openDashboard();
  } catch (error) { showMessage("password-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});

let searchTimer;
byId("search-input").addEventListener("input", (event) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = event.target.value.trim(); state.offset = 0; loadInventory(); }, 350); });
byId("brand-filter").addEventListener("change", (event) => { state.brand = event.target.value; state.offset = 0; loadInventory(); });
byId("status-filter").addEventListener("change", (event) => { state.status = event.target.value; state.offset = 0; loadInventory(); });
byId("previous-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadInventory(); });
byId("next-page").addEventListener("click", () => { if (state.offset + PAGE_SIZE < state.total) { state.offset += PAGE_SIZE; loadInventory(); } });
byId("refresh-button").addEventListener("click", () => reloadDashboard());
byId("logout-button").addEventListener("click", logout);
byId("editor-form").addEventListener("submit", saveEditor);
byId("approve-button").addEventListener("click", approveEditingItem);
byId("bulk-cost-button").addEventListener("click", openBulkDialog);
byId("bulk-form").addEventListener("submit", saveBulkAllocation);
byId("equal-split").addEventListener("click", splitEqually);
byId("bulk-total").addEventListener("input", updateAllocationRemaining);
byId("select-page").addEventListener("change", (event) => {
  state.items.forEach((item) => { if (event.target.checked) state.selected.set(item.id, item); else state.selected.delete(item.id); });
  loadInventory();
});
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => byId(button.dataset.close).close()));

initialise();
