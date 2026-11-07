"use strict";

const PENDING_OWNER_INVITE_KEY = "drop_rate_pending_owner_invite";
const PENDING_OWNER_ACK_KEY = "drop_rate_pending_owner_ack";
const PENDING_OWNER_VERIFICATION_KEY = "drop_rate_pending_owner_verification";
const RESEND_COOLDOWN_MS = 60 * 1000;
const VERIFICATION_CONTEXT_TTL_MS = 24 * 60 * 60 * 1000;

const state = {
  config: null,
  token: null,
  invite: null,
  pendingSocialSession: null,
  providers: {google: false, apple: false},
  acknowledgementVersion: 1,
  verification: null,
  resendTimer: null,
  resending: false,
  completionNeedsAcknowledgement: false,
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
  if (!response.ok) {
    const error = new Error(errorMessage(data));
    error.status = response.status;
    const retryAfter = response.headers?.get?.("Retry-After");
    const seconds = Number(retryAfter);
    error.retryAfterMs = retryAfter && Number.isFinite(seconds)
      ? Math.max(0, seconds * 1000)
      : Math.max(0, Date.parse(retryAfter || "") - Date.now()) || 0;
    throw error;
  }
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

function setAccountStep(step) {
  const order = ["account", "verify", "ready"];
  for (const node of document.querySelectorAll?.("[data-account-step]") || []) {
    const current = node.dataset.accountStep === step;
    if (current) node.setAttribute("aria-current", "step");
    else node.removeAttribute("aria-current");
    node.classList.toggle("is-complete", order.indexOf(node.dataset.accountStep) < order.indexOf(step));
  }
}

function showAccountPanel(id) {
  for (const panelId of ["owner-invite-loading", "owner-invite-invalid", "owner-join-form", "owner-verify-email", "owner-existing-login-form", "owner-oauth-name-form"]) {
    const panel = byId(panelId);
    if (panelId === id) panel?.classList.remove("hidden");
    else panel?.classList.add("hidden");
  }
}

function verificationContext() {
  // This binds draft UI state to the visible invitation without storing another invitation token.
  return state.token
    ? `invite:${state.invite?.invited_email_masked || ""}:${state.invite?.expires_at || ""}`
    : "public";
}

function persistVerification() {
  try {
    if (state.verification) sessionStorage.setItem(PENDING_OWNER_VERIFICATION_KEY, JSON.stringify(state.verification));
    else sessionStorage.removeItem(PENDING_OWNER_VERIFICATION_KEY);
  } catch (_) { /* Account creation still works if browser storage is unavailable. */ }
}

function restoreVerification() {
  try {
    const pending = JSON.parse(sessionStorage.getItem(PENDING_OWNER_VERIFICATION_KEY) || "null");
    if (pending && typeof pending.email === "string" && pending.email.length <= 320
        && typeof pending.name === "string" && pending.name.length <= 120
        && pending.context === verificationContext()
        && Number.isFinite(pending.createdAt) && pending.createdAt <= Date.now()
        && Date.now() - pending.createdAt < VERIFICATION_CONTEXT_TTL_MS
        && Number.isFinite(pending.nextResendAt)) {
      state.verification = pending;
      return true;
    }
  } catch (_) { /* A draft is optional, never an authenticated session. */ }
  clearVerification();
  return false;
}

function clearVerification() {
  state.verification = null;
  if (state.resendTimer) window.clearTimeout(state.resendTimer);
  state.resendTimer = null;
  persistVerification();
}

function confirmationRedirect() {
  return `${window.location.origin}/owner/join${state.token ? `?invite=${encodeURIComponent(state.token)}` : ""}`;
}

function refreshResendControl() {
  if (state.resendTimer) window.clearTimeout(state.resendTimer);
  state.resendTimer = null;
  const button = byId("owner-verify-resend");
  if (!button) return;
  const seconds = Math.max(0, Math.ceil(((state.verification?.nextResendAt || 0) - Date.now()) / 1000));
  button.disabled = !state.verification || state.resending || seconds > 0;
  button.textContent = state.resending ? "Sending…" : "Resend confirmation email";
  byId("owner-verify-cooldown").textContent = seconds ? `You can request another email in ${seconds}s.` : "";
  if (seconds && !byId("owner-verify-email").classList.contains("hidden")) {
    state.resendTimer = window.setTimeout(refreshResendControl, 1000);
  }
}

function showVerification({focus = true} = {}) {
  if (!state.verification) return;
  showAccountPanel("owner-verify-email");
  setAccountStep("verify");
  byId("owner-verify-address").textContent = state.verification.email;
  refreshResendControl();
  if (focus) byId("owner-verify-heading").focus();
}

function showExistingLogin(email = "") {
  byId("owner-existing-email").value = email || byId("owner-join-email").value;
  byId("owner-existing-ack").checked = byId("owner-join-ack").checked
    || Number(localStorage.getItem(PENDING_OWNER_ACK_KEY) || 0) === Number(state.acknowledgementVersion);
  byId("owner-existing-summary").textContent = inviteSummaryText();
  showAccountPanel("owner-existing-login-form");
  byId("owner-existing-password").focus();
}

async function resendConfirmation() {
  if (!state.verification || state.resending || state.verification.nextResendAt > Date.now()) return;
  const pending = state.verification;
  state.resending = true;
  refreshResendControl();
  showMessage("owner-verify-message");
  try {
    // Supabase auth-js resend() uses POST /resend?redirect_to=… with {email,type}.
    await authRequest(`/resend?redirect_to=${encodeURIComponent(confirmationRedirect())}`, {
      method: "POST", body: JSON.stringify({email: pending.email, type: "signup"}),
    });
    if (state.verification !== pending) return;
    pending.nextResendAt = Date.now() + RESEND_COOLDOWN_MS;
    persistVerification();
    showMessage("owner-verify-message", "If this address is waiting for confirmation, a fresh link is on its way. Use the newest email.", "success");
  } catch (error) {
    if (state.verification !== pending) return;
    if (error.status === 429) {
      pending.nextResendAt = Date.now() + Math.max(RESEND_COOLDOWN_MS, error.retryAfterMs || 0);
      persistVerification();
      showMessage("owner-verify-message", "Please wait before requesting another confirmation email.", "error");
    } else {
      showMessage("owner-verify-message", "We could not send another email. Check your connection and try again.", "error");
    }
  } finally {
    state.resending = false;
    refreshResendControl();
  }
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
  const explicitToken = params.get("invite");
  if (explicitToken) return explicitToken;

  const callback = new URLSearchParams(window.location.hash.slice(1));
  if (callback.get("access_token")) {
    return localStorage.getItem(PENDING_OWNER_INVITE_KEY);
  }
  return null;
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

function acknowledgementAccepted(prefix) {
  return Boolean(byId(`${prefix}-ack`)?.checked);
}

function savePendingAcknowledgement() {
  localStorage.setItem(
    PENDING_OWNER_ACK_KEY,
    String(state.acknowledgementVersion)
  );
}

function startOAuth(provider, prefix) {
  const messageId =
    prefix === "owner-existing" ? "owner-existing-message" : "owner-join-message";
  if (!["google", "apple"].includes(provider) || !state.providers[provider]) {
    showMessage(messageId, "That sign-in provider is not enabled yet.", "error");
    return;
  }
  if (!acknowledgementAccepted(prefix)) {
    showMessage(
      messageId,
      "Please confirm the seller onboarding acknowledgement before continuing.",
      "error"
    );
    return;
  }

  if (state.token) {
    localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
  } else {
    localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
  }
  savePendingAcknowledgement();
  const redirectTo = state.token
    ? `${window.location.origin}/owner/join?invite=${encodeURIComponent(state.token)}`
    : `${window.location.origin}/owner/join`;
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

async function completeSellerRegistration(session, displayName) {
  const inviteMode = Boolean(state.token);
  const endpoint = inviteMode
    ? "/api/v1/owner-invites/redeem"
    : "/api/v1/owner-self-register";
  const body = inviteMode
    ? {
        token: state.token,
        display_name: displayName,
        acknowledged: true,
        acknowledgement_version: state.acknowledgementVersion,
      }
    : {
        display_name: displayName,
        acknowledged: true,
        acknowledgement_version: state.acknowledgementVersion,
      };

  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await readJson(response);
  const user = await authenticatedUser(session);
  window.PullTheoryHubSession.save({...session, user: {id: user.id, email: user.email}});
  localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
  localStorage.removeItem(PENDING_OWNER_ACK_KEY);
  clearVerification();
  return data;
}

function requestSocialDisplayName(session, displayName = "", needsAcknowledgement = false) {
  // Apple web OAuth never supplies a full name. Keep the verified session
  // only in memory until onboarding succeeds; do not save it as an owner yet.
  state.pendingSocialSession = session;
  state.completionNeedsAcknowledgement = needsAcknowledgement;
  showAccountPanel("owner-oauth-name-form");
  setAccountStep("ready");
  byId("owner-oauth-name").value = displayName || state.invite?.invited_name || "";
  const acknowledgement = byId("owner-oauth-acknowledgement");
  if (needsAcknowledgement) acknowledgement.classList.remove("hidden");
  else acknowledgement.classList.add("hidden");
  byId("owner-oauth-ack").required = needsAcknowledgement;
  byId("owner-oauth-summary").textContent = inviteSummaryText();
  byId("owner-oauth-name").focus();
}

async function finishAuthenticatedOnboarding(session, displayName = null) {
  const pendingAck = Number(localStorage.getItem(PENDING_OWNER_ACK_KEY) || 0);
  if (pendingAck !== Number(state.acknowledgementVersion || 1)) {
    throw new Error(
      "Please return to the invitation and confirm the seller onboarding acknowledgement."
    );
  }

  const user = await authenticatedUser(session);
  const name =
    displayName
    || user.user_metadata?.display_name
    || user.user_metadata?.full_name
    || state.invite?.invited_name;
  if (!user.email) {
    throw new Error("We could not resolve your verified seller email.");
  }
  const resolvedName = typeof name === "string" ? name.trim() : "";
  if (!resolvedName) {
    requestSocialDisplayName(session);
    return;
  }
  await completeSellerRegistration(session, resolvedName);
  setAccountStep("ready");
  window.location.replace("/owner?welcome=1");
}

function inviteSummaryText() {
  const commissionPercent = Number(state.invite?.commission_bps ?? 1000) / 100;
  if (!state.token) {
    return [
      `Drop Rate commission: ${commissionPercent.toFixed(2).replace(/\.00$/, "")}%`,
      "Applies when you choose to sell",
      "Your collection and account stay private",
    ].join(" · ");
  }

  const expiry = new Date(state.invite?.expires_at);
  const expiryText = Number.isNaN(expiry.getTime())
    ? "the date shown in your invitation"
    : expiry.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });

  return [
    `Invited email: ${state.invite?.invited_email_masked || "your invited email"}`,
    `Drop Rate commission: ${commissionPercent.toFixed(2).replace(/\.00$/, "")}%`,
    `Expires: ${expiryText}`,
  ].join(" · ");
}

function showJoin() {
  showAccountPanel("owner-join-form");
  setAccountStep("account");
  byId("owner-join-name").value ||= state.invite?.invited_name || "";
  state.acknowledgementVersion = Number(
    state.invite?.acknowledgement_version || 1
  );

  const summary = inviteSummaryText();
  byId("owner-invite-summary").textContent = summary;
  byId("owner-existing-summary").textContent = summary;
}

function showInvalid(message) {
  showAccountPanel("owner-invite-invalid");
  byId("owner-invite-invalid-message").textContent = message;
}

async function initialise() {
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
    await loadSocialProviders();
    state.token = inviteToken();

    if (state.token) {
      localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
      state.invite = await readJson(
        await fetch(
          `/api/v1/public/owner-invites/${encodeURIComponent(state.token)}`
        )
      );
      state.acknowledgementVersion = Number(
        state.invite.acknowledgement_version || 1
      );
    } else {
      localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
      state.invite = {
        commission_bps: 1000,
        acknowledgement_version: 1,
      };
      state.acknowledgementVersion = 1;
    }

    const callbackParams = new URLSearchParams(window.location.hash.slice(1));
    const session = callbackSession();
    if (session) {
      const cleanPath = state.token
        ? `/owner/join?invite=${encodeURIComponent(state.token)}`
        : "/owner/join";
      history.replaceState({}, document.title, cleanPath);
      if (Number(localStorage.getItem(PENDING_OWNER_ACK_KEY) || 0) !== Number(state.acknowledgementVersion)) {
        const user = await authenticatedUser(session);
        if (!user.email) throw new Error("We could not resolve your verified seller email.");
        requestSocialDisplayName(session, user.user_metadata?.display_name || user.user_metadata?.full_name || "", true);
        return;
      }
      await finishAuthenticatedOnboarding(session);
      return;
    }

    if (callbackParams.has("error") || callbackParams.has("error_code")) {
      history.replaceState({}, document.title, state.token ? `/owner/join?invite=${encodeURIComponent(state.token)}` : "/owner/join");
      if (restoreVerification()) {
        showVerification();
        showMessage("owner-verify-message", "That confirmation link could not be used. Request a fresh email below and open the newest link.", "error");
      } else {
        showJoin();
        showMessage("owner-join-message", "That confirmation link could not be used. If you already created an account, sign in below to continue.", "error");
      }
      return;
    }
    if (restoreVerification()) {
      showVerification({focus: false});
      return;
    }
    showJoin();
  } catch (error) {
    showInvalid(error.message);
  }
}

byId("owner-join-google").addEventListener(
  "click",
  () => startOAuth("google", "owner-join")
);
byId("owner-join-apple").addEventListener(
  "click",
  () => startOAuth("apple", "owner-join")
);
byId("owner-existing-google").addEventListener(
  "click",
  () => startOAuth("google", "owner-existing")
);
byId("owner-existing-apple").addEventListener(
  "click",
  () => startOAuth("apple", "owner-existing")
);

byId("owner-oauth-name-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const name = byId("owner-oauth-name").value.trim();
  if (!state.pendingSocialSession || !name) {
    showMessage("owner-oauth-name-message", "Please enter your name to finish setting up.", "error");
    return;
  }
  if (state.completionNeedsAcknowledgement) {
    if (!byId("owner-oauth-ack").checked) {
      showMessage("owner-oauth-name-message", "Please confirm the account acknowledgement to continue.", "error");
      return;
    }
    savePendingAcknowledgement();
  }
  setBusy(form, true);
  showMessage("owner-oauth-name-message");
  try {
    await finishAuthenticatedOnboarding(state.pendingSocialSession, name);
  } catch (error) {
    showMessage("owner-oauth-name-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

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
  if (!acknowledgementAccepted("owner-join")) {
    showMessage(
      "owner-join-message",
      "Please confirm the seller onboarding acknowledgement.",
      "error"
    );
    return;
  }

  if (state.token) {
    localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
  } else {
    localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
  }
  savePendingAcknowledgement();
  setBusy(form, true);
  showMessage("owner-join-message");
  try {
    const redirectTo = confirmationRedirect();
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

    state.verification = {email, name, context: verificationContext(), createdAt: Date.now(), nextResendAt: Date.now() + RESEND_COOLDOWN_MS};
    persistVerification();
    for (const id of ["owner-join-password", "owner-join-confirm-password"]) {
      byId(id).value = "";
      byId(id).dispatchEvent(new Event("input", {bubbles: true}));
    }
    showVerification();
  } catch (error) {
    showMessage("owner-join-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

byId("owner-show-existing-login").addEventListener("click", () => {
  if (!state.token) { window.location.assign("/app"); return; }
  showExistingLogin();
});

byId("owner-verify-resend").addEventListener("click", resendConfirmation);
byId("owner-verify-continue").addEventListener("click", () => {
  if (state.verification) {
    byId("owner-join-name").value = state.verification.name;
    showExistingLogin(state.verification.email);
  }
});
byId("owner-verify-correct").addEventListener("click", () => {
  const pending = state.verification;
  clearVerification();
  showJoin();
  if (pending) {
    byId("owner-join-name").value = pending.name;
    byId("owner-join-email").value = pending.email;
  }
  byId("owner-join-password").value = "";
  byId("owner-join-confirm-password").value = "";
  showMessage("owner-join-message", "Correct the email address, then create your account with that address.");
  byId("owner-join-email").focus();
  byId("owner-join-email").select();
});

byId("owner-back-to-join").addEventListener("click", () => {
  byId("owner-join-ack").checked = byId("owner-existing-ack").checked;
  byId("owner-existing-login-form").classList.add("hidden");
  if (state.verification) showVerification();
  else showJoin();
});

byId("owner-existing-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!acknowledgementAccepted("owner-existing")) {
    showMessage(
      "owner-existing-message",
      "Please confirm the seller onboarding acknowledgement.",
      "error"
    );
    return;
  }

  if (state.token) {
    localStorage.setItem(PENDING_OWNER_INVITE_KEY, state.token);
  } else {
    localStorage.removeItem(PENDING_OWNER_INVITE_KEY);
  }
  savePendingAcknowledgement();
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
      byId("owner-join-name").value.trim() || state.invite?.invited_name || null
    );
  } catch (error) {
    showMessage("owner-existing-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
});

initialise();
