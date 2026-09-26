"use strict";

const OWNER_SESSION_KEY = "drop_rate_owner_session";

const state = {
  config: null,
  session: null,
  providers: {google: false, apple: false},
  inventory: {offset: 0, limit: 50, total: 0, search: "", status: ""},
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
  node.className = `message panel-message${kind ? ` ${kind}` : ""}`;
}

function renderInventoryRows(items) {
  const body = byId("owner-inventory-body");
  body.replaceChildren();

  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.className = "muted";
    cell.textContent = "No inventory matches these filters.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const card = safeText(item.name);
    const cardNumber = item.card_number ? ` #${item.card_number}` : "";
    const variant = item.variant ? ` · ${item.variant}` : "";
    const grade = item.grade
      ? `${safeText(item.grading_company, "Graded")} ${item.grade}`
      : safeText(item.condition);
    const values = [
      safeText(item.inventory_code),
      `${card}${cardNumber}${variant}`,
      `${safeText(item.game)} · ${safeText(item.set_name)}`,
      safeText(item.language),
      grade,
      safeText(item.status),
      formatMoney(item.market_value_minor),
      formatMoney(item.store_price_minor),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
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
  byId("owner-total-inventory").textContent = Number(summary.total_inventory_count || 0).toLocaleString("en-GB");
  byId("owner-market-value").textContent = formatMoney(summary.active_market_value_minor);
  byId("owner-store-value").textContent = formatMoney(summary.active_store_price_minor);
  byId("owner-sold-count").textContent = Number(summary.sold_count || 0).toLocaleString("en-GB");
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
  renderInventoryRows(data.items || []);
  renderInventoryPagination();
}

async function reloadOwnerDashboard() {
  showPortalMessage("Loading your inventory…");
  try {
    await Promise.all([loadOwnerOverview(), loadOwnerInventory()]);
    showPortalMessage();
  } catch (error) {
    showPortalMessage(error.message, "error");
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
  byId("owner-portal-type").textContent = access.owner_type || "OWNER";

  byId("owner-auth-view").classList.add("hidden");
  byId("owner-portal-view").classList.remove("hidden");
  await reloadOwnerDashboard();
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

byId("owner-logout-button").addEventListener("click", () => {
  clearSession();
  byId("owner-portal-view").classList.add("hidden");
  byId("owner-auth-view").classList.remove("hidden");
  byId("owner-password-input").value = "";
  showMessage();
});

initialise();
