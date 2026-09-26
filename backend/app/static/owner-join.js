"use strict";

const OWNER_SESSION_KEY = "drop_rate_owner_session";
const PENDING_OWNER_INVITE_KEY = "drop_rate_pending_owner_invite";

const state = {
  config: null,
  token: null,
  invite: null,
  providers: {google: false, apple: false},
};

const byId = (id) => document.getElementById(id);

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

function setBusy(form, busy) {
  const button = form.querySelector('button[type="submit"]');
  if (!button) return;
  button.disabled = busy;
  button.dataset.label ||= button.textContent;
  button.textContent = busy ? "Please wait…" : button.dataset.label;
}

function showMessage(id, text = "", kind = "") {
  const node = byId(id);
  node.textContent = text;
  node.className = `message${kind ? ` ${kind}` : ""}`;
}

function authRequest(path, options = {}) {
  return fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: state.config.publishable_key,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }).then(readJson);
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

  for (const prefix of ["owner-join", "owner-existing"]) {
    byId(`${prefix}-google`).classList.toggle("hidden", !state.providers.google);
    byId(`${prefix}-apple`).classList.toggle("hidden", !state.providers.apple);
    byId(`${prefix}-social-auth`).classList.toggle(
      "hidden",
      !state.providers.google && !state.providers.apple
    );
  }
}

function inviteToken() {
  const params = new URLSearchParams(window.location.search);
  return params.get("invite") || localStorage.getItem(PENDING_OWNER_INVITE_KEY);
}

function callbackSession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const accessToken = params.get("access_token");
  if (!accessToken) return null;
  return {
    access_token: accessToken,
    refresh_token: params.get("refresh_token"),
    token_type: params.get("token_type") || "bearer",
    expires_in: Number(params.get("expires_in") || 3600),
  };
}

function startOAuth(provider) {
  if (!["google", "apple"].includes(provider) || !state.providers[provider]) {
    showMessage("owner-join-message", "That sign-in provider is not enabled yet.", "error");
    return;
  }
  localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
  const redirectTo = `${window.location.origin}/owner/join?invite=${encodeURIComponent(state.token)}`;
  const authorizeUrl = new URL(`${state.config.supabase_url}/auth/v1/authorize`);
  authorizeUrl.searchParams.set("provider", provider);
  authorizeUrl.searchParams.set("redirect_to", redirectTo);
  window.location.assign(authorizeUrl.toString());
}

async function authenticatedUser(session) {
  return authRequest("/user", {
    headers: {Authorization: `Bearer ${session.access_token}`},
  });
}

async function redeem(session, displayName) {
  const response = await fetch("/api/v1/owner-invites/redeem", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      token: state.token,
      display_name: displayName,
    }),
  });
  const data = await readJson(response);
  const user = await authenticatedUser(session);
  sessionStorage.setItem(
    OWNER_SESSION_KEY,
    JSON.stringify({...session, user: {email: user.email}})
  );
  localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
  return data;
}

async function finishAuthenticatedOnboarding(session, displayName = null) {
  const user = await authenticatedUser(session);
  const resolvedName =
    displayName
    || user.user_metadata?.display_name
    || user.user_metadata?.full_name
    || state.invite?.invited_name;
  if (!user.email || !resolvedName) {
    throw new Error("We could not resolve your verified owner profile.");
  }
  await redeem(session, resolvedName);
  window.location.replace("/owner");
}

function showJoin() {
  byId("owner-invite-loading").classList.add("hidden");
  byId("owner-invite-invalid").classList.add("hidden");
  byId("owner-join-form").classList.remove("hidden");
  byId("owner-join-name").value = state.invite.invited_name || "";

  const commissionPercent = Number(state.invite.commission_bps || 0) / 100;
  byId("owner-invite-summary").textContent =
    `This invitation creates a restricted consignor account. Drop Rate commission: ${commissionPercent.toFixed(2).replace(/\.00$/, "")}%.`;
}

function showInvalid(message) {
  byId("owner-invite-loading").classList.add("hidden");
  byId("owner-join-form").classList.add("hidden");
  byId("owner-existing-login-form").classList.add("hidden");
  byId("owner-invite-invalid").classList.remove("hidden");
  byId("owner-invite-invalid-message").textContent = message;
}

async function initialise() {
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
    await loadSocialProviders();
    state.token = inviteToken();

    if (!state.token) {
      showInvalid("This invitation link is incomplete. Ask Drop Rate for a new owner invite.");
      return;
    }

    localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
    state.invite = await readJson(
      await fetch(`/api/v1/public/owner-invites/${encodeURIComponent(state.token)}`)
    );

    const session = callbackSession();
    if (session) {
      history.replaceState(
        {},
        document.title,
        `/owner/join?invite=${encodeURIComponent(state.token)}`
      );
      await finishAuthenticatedOnboarding(session);
      return;
    }

    showJoin();
  } catch (error) {
    showInvalid(error.message);
  }
}

byId("owner-join-google").addEventListener("click", () => startOAuth("google"));
byId("owner-join-apple").addEventListener("click", () => startOAuth("apple"));
byId("owner-existing-google").addEventListener("click", () => startOAuth("google"));
byId("owner-existing-apple").addEventListener("click", () => startOAuth("apple"));

byId("owner-join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const name = byId("owner-join-name").value.trim();
  const email = byId("owner-join-email").value.trim().toLowerCase();
  const password = byId("owner-join-password").value;

  if (password !== byId("owner-join-confirm-password").value) {
    showMessage("owner-join-message", "The passwords do not match.", "error");
    return;
  }

  setBusy(form, true);
  showMessage("owner-join-message");
  try {
    const redirectTo =
      `${window.location.origin}/owner/join?invite=${encodeURIComponent(state.token)}`;
    const session = await authRequest(
      `/signup?redirect_to=${encodeURIComponent(redirectTo)}`,
      {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          data: {display_name: name},
        }),
      }
    );

    if (session.access_token) {
      await finishAuthenticatedOnboarding(session, name);
      return;
    }

    localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
    showMessage(
      "owner-join-message",
      "Account created. Confirm your email, then return through this invitation to finish onboarding.",
      "success"
    );
  } catch (error) {
    showMessage("owner-join-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

byId("owner-show-existing-login").addEventListener("click", () => {
  byId("owner-existing-email").value = byId("owner-join-email").value;
  byId("owner-join-form").classList.add("hidden");
  byId("owner-existing-login-form").classList.remove("hidden");
});

byId("owner-back-to-join").addEventListener("click", () => {
  byId("owner-existing-login-form").classList.add("hidden");
  byId("owner-join-form").classList.remove("hidden");
});

byId("owner-existing-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage("owner-existing-message");
  try {
    const session = await authRequest("/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({
        email: byId("owner-existing-email").value.trim().toLowerCase(),
        password: byId("owner-existing-password").value,
      }),
    });
    await finishAuthenticatedOnboarding(
      session,
      byId("owner-join-name").value.trim() || state.invite.invited_name
    );
  } catch (error) {
    showMessage("owner-existing-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

initialise();
