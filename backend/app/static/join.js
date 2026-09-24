"use strict";

const SESSION_KEY = "drop_rate_founder_session";
const PENDING_INVITE_KEY = "drop_rate_pending_founder_invite";

const state = {
  config: null,
  token: null,
  invite: null,
  session: null,
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
  const button = form.querySelector("button[type=submit]");
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

function inviteToken() {
  const params = new URLSearchParams(window.location.search);
  return params.get("invite") || localStorage.getItem(PENDING_INVITE_KEY);
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

async function authenticatedUser(session) {
  return authRequest("/user", {
    headers: {Authorization: `Bearer ${session.access_token}`},
  });
}

async function redeem(session, displayName, email) {
  const response = await fetch("/api/v1/founder-invites/redeem", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      token: state.token,
      display_name: displayName,
      email,
    }),
  });
  const data = await readJson(response);
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({...session, user: {email}}));
  localStorage.removeItem(PENDING_INVITE_KEY);
  return data;
}

async function finishAuthenticatedOnboarding(session, displayName = null, email = null) {
  const user = await authenticatedUser(session);
  const resolvedEmail = email || user.email;
  const resolvedName = displayName || user.user_metadata?.display_name || state.invite?.invited_name;
  if (!resolvedEmail || !resolvedName) throw new Error("We could not resolve your founder profile.");
  await redeem(session, resolvedName, resolvedEmail);
  window.location.replace("/");
}

function showJoin() {
  byId("invite-loading").classList.add("hidden");
  byId("invite-invalid").classList.add("hidden");
  byId("join-form").classList.remove("hidden");
  byId("join-name").value = state.invite.invited_name || "";
  byId("invite-summary").textContent =
    `You’re joining as Founder ${state.invite.founder_slot}. Your inventory and costs will be scoped to your own account.`;
}

function showInvalid(message) {
  byId("invite-loading").classList.add("hidden");
  byId("join-form").classList.add("hidden");
  byId("existing-login-form").classList.add("hidden");
  byId("invite-invalid").classList.remove("hidden");
  byId("invite-invalid-message").textContent = message;
}

async function initialise() {
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
    state.token = inviteToken();
    if (!state.token) {
      showInvalid("This invitation link is incomplete. Ask for a new founder invite.");
      return;
    }
    localStorage.setItem(PENDING_INVITE_KEY, state.token);

    state.invite = await readJson(
      await fetch(`/api/v1/public/founder-invites/${encodeURIComponent(state.token)}`)
    );

    const session = callbackSession();
    if (session) {
      history.replaceState({}, document.title, `/join?invite=${encodeURIComponent(state.token)}`);
      await finishAuthenticatedOnboarding(session);
      return;
    }

    showJoin();
  } catch (error) {
    showInvalid(error.message);
  }
}

byId("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const name = byId("join-name").value.trim();
  const email = byId("join-email").value.trim().toLowerCase();
  const password = byId("join-password").value;

  if (password !== byId("join-confirm-password").value) {
    showMessage("join-message", "The passwords do not match.", "error");
    return;
  }

  setBusy(form, true);
  showMessage("join-message");
  try {
    const redirectTo = `${window.location.origin}/join?invite=${encodeURIComponent(state.token)}`;
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
      await finishAuthenticatedOnboarding(session, name, email);
      return;
    }

    localStorage.setItem(PENDING_INVITE_KEY, state.token);
    showMessage(
      "join-message",
      "Account created. Check your email and confirm your address, then this invitation will finish automatically.",
      "success"
    );
  } catch (error) {
    showMessage("join-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

byId("show-existing-login").addEventListener("click", () => {
  byId("existing-email").value = byId("join-email").value;
  byId("join-form").classList.add("hidden");
  byId("existing-login-form").classList.remove("hidden");
});

byId("back-to-join").addEventListener("click", () => {
  byId("existing-login-form").classList.add("hidden");
  byId("join-form").classList.remove("hidden");
});

byId("existing-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage("existing-message");
  try {
    const email = byId("existing-email").value.trim().toLowerCase();
    const session = await authRequest("/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({
        email,
        password: byId("existing-password").value,
      }),
    });
    await finishAuthenticatedOnboarding(
      session,
      byId("join-name").value.trim() || state.invite.invited_name,
      email
    );
  } catch (error) {
    showMessage("existing-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

initialise();
