"use strict";

const SESSION_KEY = "drop_rate_founder_session";
const PAGE_SIZE = 25;
const state = { config: null, session: null, offset: 0, total: 0, search: "", status: "" };
const byId = (id) => document.getElementById(id);

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
  if (!response.ok) {
    const detail = data.error_description || data.msg || data.detail || data.message;
    throw new Error(typeof detail === "string" ? detail : "Something went wrong. Please try again.");
  }
  return data;
}

async function authRequest(path, options = {}) {
  const response = await fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: { apikey: state.config.publishable_key, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  return readJson(response);
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

async function apiRequest(path, retry = true) {
  let response = await fetch(path, { headers: { Authorization: `Bearer ${state.session.access_token}` } });
  if (response.status === 401 && retry) {
    const token = await refreshSession();
    response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
  }
  return readJson(response);
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

function textCell(label, text, className = "") {
  const td = document.createElement("td");
  td.dataset.label = label;
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

function renderInventory(data) {
  state.total = data.total;
  byId("total-count").textContent = data.total.toLocaleString("en-GB");
  byId("visible-count").textContent = data.items.length.toLocaleString("en-GB");
  byId("stat-owner").textContent = data.owner.display_name;
  byId("owner-name").textContent = data.owner.display_name;
  byId("owner-initial").textContent = data.owner.display_name.slice(0, 1).toUpperCase();
  const body = byId("inventory-body");
  body.replaceChildren();

  data.items.forEach((item) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.dataset.label = "Card";
    const wrap = document.createElement("div");
    wrap.className = "card-name";
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = [item.game, item.card_number, item.variant].filter(Boolean).join(" · ") || "Uncatalogued";
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = item.inventory_code;
    wrap.append(strong, meta, code);
    name.append(wrap);
    row.append(name);
    row.append(textCell("Set", item.set_name || "—", "set-detail"));
    row.append(textCell("Condition", item.grade ? `${item.grading_company} ${item.grade}` : (item.condition || "—")));
    row.append(textCell("Cost", money(item.acquisition_cost_minor, item.currency)));
    row.append(textCell("Store price", money(item.store_price_minor, item.currency)));
    const status = document.createElement("td");
    status.dataset.label = "Status";
    const pill = document.createElement("span");
    pill.className = `pill ${item.status.toLowerCase()}`;
    pill.textContent = item.status.charAt(0) + item.status.slice(1).toLowerCase();
    status.append(pill);
    row.append(status);
    body.append(row);
  });

  byId("empty-state").classList.toggle("hidden", data.items.length !== 0);
  byId("previous-page").disabled = state.offset === 0;
  byId("next-page").disabled = state.offset + PAGE_SIZE >= data.total;
  byId("page-label").textContent = `Page ${Math.floor(state.offset / PAGE_SIZE) + 1} of ${Math.max(1, Math.ceil(data.total / PAGE_SIZE))}`;
}

async function loadInventory() {
  showMessage("inventory-message", "Loading inventory…");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  try {
    const data = await apiRequest(`/api/v1/inventory?${params}`);
    renderInventory(data);
    showMessage("inventory-message");
  } catch (error) {
    showMessage("inventory-message", error.message, "error");
    if (/session|token|expired/i.test(error.message)) logout();
  }
}

async function openDashboard() {
  try {
    const me = await apiRequest("/api/v1/me");
    byId("owner-email").textContent = state.session.user?.email || byId("login-email").value || "Founder account";
    byId("owner-name").textContent = me.owner.display_name;
    byId("auth-view").classList.add("hidden");
    byId("dashboard-view").classList.remove("hidden");
    await loadInventory();
  } catch (error) {
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
  byId("dashboard-view").classList.add("hidden");
  byId("auth-view").classList.remove("hidden");
  showForm("login-form");
  byId("login-password").value = "";
}

async function initialise() {
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
  } catch (_error) {
    showMessage("login-message", "The dashboard is temporarily unavailable. Please refresh shortly.", "error");
    return;
  }
  if (parseRecoverySession()) return;
  try {
    const stored = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (stored?.access_token) { state.session = stored; await openDashboard(); }
  } catch (_error) { clearSession(); }
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(event.currentTarget, true);
  showMessage("login-message");
  try {
    const session = await authRequest("/token?grant_type=password", { method: "POST", body: JSON.stringify({ email: byId("login-email").value.trim(), password: byId("login-password").value }) });
    saveSession(session);
    await openDashboard();
  } catch (error) { showMessage("login-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});

byId("show-reset").addEventListener("click", () => { byId("reset-email").value = byId("login-email").value; showForm("request-reset-form"); });
document.querySelector("[data-back-login]").addEventListener("click", () => showForm("login-form"));
byId("request-reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(event.currentTarget, true);
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
    showMessage("password-message", "Password saved. Opening your inventory…", "success");
    await openDashboard();
  } catch (error) { showMessage("password-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});

let searchTimer;
byId("search-input").addEventListener("input", (event) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = event.target.value.trim(); state.offset = 0; loadInventory(); }, 350); });
byId("status-filter").addEventListener("change", (event) => { state.status = event.target.value; state.offset = 0; loadInventory(); });
byId("previous-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadInventory(); });
byId("next-page").addEventListener("click", () => { if (state.offset + PAGE_SIZE < state.total) { state.offset += PAGE_SIZE; loadInventory(); } });
byId("refresh-button").addEventListener("click", loadInventory);
byId("logout-button").addEventListener("click", logout);

initialise();
