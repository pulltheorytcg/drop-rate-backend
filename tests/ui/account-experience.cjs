"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM, VirtualConsole} = require("jsdom");
const root = path.resolve(__dirname, "../..");
const read = name => fs.readFileSync(path.join(root, "backend/app/static", name), "utf8");
const ownerHtml = read("owner-join.html");
const ownerSource = read("owner-join.js");
const accountSource = read("account-experience.js");
const pendingKey = "drop_rate_pending_owner_verification";
const ackKey = "drop_rate_pending_owner_ack";

async function settle(predicate) {
  for (let i = 0; i < 60; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  assert.fail("Account flow did not reach the expected state");
}
function mount({invited = false, hash = "", acknowledged = false, pending = null, resend = [], signup = {}, user = null} = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", error => {
    if (!error.message.includes("Not implemented: navigation")) errors.push(error.message);
  });
  const dom = new JSDOM(ownerHtml, {
    url: `https://hub.example.test/owner/join${invited ? "?invite=fixture-invitation" : ""}${hash}`,
    runScripts: "outside-only", virtualConsole,
  });
  const {window} = dom;
  const calls = [], sessions = [], timers = new Map();
  let now = Date.UTC(2026, 10, 3, 14, 0), timerId = 0;
  window.Date.now = () => now;
  window.setTimeout = (callback, milliseconds) => {
    const id = ++timerId; timers.set(id, {callback, at: now + milliseconds}); return id;
  };
  window.clearTimeout = id => timers.delete(id);
  if (acknowledged) window.localStorage.setItem(ackKey, "1");
  if (pending) window.sessionStorage.setItem(pendingKey, typeof pending === "string" ? pending : JSON.stringify(pending));
  const fixtureUser = user || {id: "fixture-account", email: "collector@example.test", email_confirmed_at: "2026-11-03T14:00:00Z", user_metadata: {display_name: "Casey Collector"}, app_metadata: {provider: "email", providers: ["email"]}};
  window.PullTheoryHubSession = {save: session => sessions.push(session)};
  window.fetch = async (url, options = {}) => {
    url = String(url);
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({url, method: options.method || "GET", body, headers: options.headers});
    let data = {}, status = 200, headers = {};
    if (url === "/api/v1/public-config") data = {supabase_url: "https://auth.example.test", publishable_key: "fixture-public-key"};
    else if (url.endsWith("/auth/v1/settings")) data = {external: {google: true, apple: false}};
    else if (url.startsWith("/api/v1/public/owner-invites/")) data = {invited_name: "Invited Collector", invited_email_masked: "c***@example.test", expires_at: "2100-01-01T00:00:00Z", commission_bps: 1250, acknowledgement_version: 1};
    else if (url.includes("/auth/v1/signup?")) data = signup;
    else if (url.includes("/auth/v1/resend?")) {
      const next = resend.shift() || {};
      if (next.networkError) throw new TypeError("Fixture offline");
      status = next.status || 200; data = next.data || {}; headers = next.headers || {};
    }
    else if (url.endsWith("/auth/v1/user")) data = fixtureUser;
    else if (url.endsWith("/auth/v1/token?grant_type=password")) data = {access_token: "fixture-access", refresh_token: "fixture-refresh"};
    else if (["/api/v1/owner-self-register", "/api/v1/owner-invites/redeem"].includes(url)) data = {owner_id: "fixture-owner"};
    else throw new Error("Unexpected request: " + url);
    return {ok: status >= 200 && status < 300, status, headers: {get: key => headers[key] || null}, json: async () => data};
  };
  window.eval(ownerSource);
  window.eval(accountSource);
  const doc = window.document;
  const fill = (id, value) => {
    const input = doc.getElementById(id); input.value = value;
    input.dispatchEvent(new window.Event("input", {bubbles: true}));
  };
  const submit = id => doc.getElementById(id).dispatchEvent(new window.Event("submit", {bubbles: true, cancelable: true}));
  return {
    dom, window, doc, calls, sessions, errors, fill, submit,
    shown: id => !doc.getElementById(id).classList.contains("hidden"),
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.callback(); }
    },
    async signup(email = "collector@example.test") {
      await settle(() => !doc.getElementById("owner-join-form").classList.contains("hidden"));
      fill("owner-join-name", "Casey Collector"); fill("owner-join-email", email);
      fill("owner-join-password", "PrivatePassword123!"); fill("owner-join-confirm-password", "PrivatePassword123!");
      doc.getElementById("owner-join-ack").checked = true;
      submit("owner-join-form");
      await settle(() => !doc.getElementById("owner-verify-email").classList.contains("hidden"));
    },
    close() { assert.deepEqual(errors, []); dom.window.close(); },
  };
}

(async () => {
  let groups = 0;
  {
    const f = mount(); await f.signup();
    assert.ok(f.shown("owner-verify-email")); assert.ok(!f.shown("owner-join-form"));
    assert.equal(f.doc.getElementById("owner-verify-address").textContent, "collector@example.test");
    assert.equal(f.doc.activeElement.id, "owner-verify-heading");
    assert.equal(f.doc.querySelector('#owner-verify-email [aria-current="step"]').dataset.accountStep, "verify");
    assert.equal(f.doc.getElementById("owner-join-password").value, "");
    assert.equal(f.doc.getElementById("owner-join-confirm-password").value, "");
    const stored = f.window.sessionStorage.getItem(pendingKey);
    assert.ok(stored.includes("collector@example.test")); assert.ok(!stored.includes("PrivatePassword"));
    assert.equal(f.calls.filter(call => call.url.includes("owner-self-register")).length, 0);
    assert.equal(f.sessions.length, 0);
    assert.equal(f.doc.getElementById("owner-verify-resend").disabled, true);
    f.doc.getElementById("owner-verify-resend").dispatchEvent(new f.window.Event("click"));
    assert.equal(f.calls.filter(call => call.url.includes("/resend?")).length, 0);
    f.advance(61000); f.doc.getElementById("owner-verify-resend").click();
    await settle(() => f.doc.getElementById("owner-verify-message").textContent.includes("fresh link"));
    const sent = f.calls.find(call => call.url.includes("/resend?"));
    assert.deepEqual(sent.body, {email: "collector@example.test", type: "signup"});
    assert.equal(new URL(sent.url).searchParams.get("redirect_to"), "https://hub.example.test/owner/join");
    assert.equal(f.doc.getElementById("owner-verify-resend").disabled, true);
    f.close(); groups++;
  }
  {
    const f = mount({invited: true, resend: [{status: 429, headers: {"Retry-After": "120"}, data: {msg: "rate limited"}}, {networkError: true}]});
    await f.signup(); f.advance(61000); f.doc.getElementById("owner-verify-resend").click();
    await settle(() => f.doc.getElementById("owner-verify-message").textContent.includes("Please wait"));
    assert.match(f.doc.getElementById("owner-verify-cooldown").textContent, /120s/);
    const sent = f.calls.find(call => call.url.includes("/resend?"));
    assert.equal(new URL(sent.url).searchParams.get("redirect_to"), "https://hub.example.test/owner/join?invite=fixture-invitation");
    f.advance(61000); f.doc.getElementById("owner-verify-resend").dispatchEvent(new f.window.Event("click"));
    assert.equal(f.calls.filter(call => call.url.includes("/resend?")).length, 1);
    f.advance(60000); f.doc.getElementById("owner-verify-resend").click();
    await settle(() => f.doc.getElementById("owner-verify-message").textContent.includes("could not send"));
    assert.equal(f.doc.getElementById("owner-verify-resend").disabled, false);
    f.close(); groups++;
  }
  {
    const f = mount(); await f.signup("mistyped@example.test");
    f.doc.getElementById("owner-verify-correct").click();
    assert.ok(f.shown("owner-join-form")); assert.ok(!f.shown("owner-verify-email"));
    assert.equal(f.doc.getElementById("owner-join-name").value, "Casey Collector");
    assert.equal(f.doc.getElementById("owner-join-email").value, "mistyped@example.test");
    assert.equal(f.doc.activeElement.id, "owner-join-email");
    assert.equal(f.doc.getElementById("owner-join-password").value, "");
    assert.equal(f.window.sessionStorage.getItem(pendingKey), null);
    assert.equal(f.calls.filter(call => call.method === "POST").length, 1);
    f.close(); groups++;
  }
  {
    const first = mount(); await first.signup();
    const pending = first.window.sessionStorage.getItem(pendingKey); first.close();
    const f = mount({pending, acknowledged: true}); await settle(() => f.shown("owner-verify-email"));
    assert.equal(f.doc.getElementById("owner-verify-resend").disabled, true);
    f.doc.getElementById("owner-verify-continue").click();
    assert.ok(f.shown("owner-existing-login-form"));
    assert.equal(f.doc.getElementById("owner-existing-email").value, "collector@example.test");
    assert.equal(f.doc.getElementById("owner-existing-ack").checked, true);
    f.fill("owner-existing-password", "PrivatePassword123!"); f.submit("owner-existing-login-form");
    await settle(() => f.sessions.length === 1);
    const registration = f.calls.find(call => call.url === "/api/v1/owner-self-register");
    assert.deepEqual(registration.body, {display_name: "Casey Collector", acknowledged: true, acknowledgement_version: 1});
    assert.equal(f.window.sessionStorage.getItem(pendingKey), null);
    f.close(); groups++;
  }
  {
    const f = mount({hash: "#access_token=fixture-access&refresh_token=fixture-refresh", acknowledged: false});
    await settle(() => f.shown("owner-oauth-name-form"));
    assert.equal(f.window.location.hash, "");
    assert.ok(!f.doc.getElementById("owner-oauth-acknowledgement").classList.contains("hidden"));
    assert.match(f.doc.getElementById("owner-oauth-summary").textContent, /commission/);
    f.submit("owner-oauth-name-form");
    assert.equal(f.calls.filter(call => call.url.includes("owner-self-register")).length, 0);
    assert.equal(f.sessions.length, 0);
    assert.match(f.doc.getElementById("owner-oauth-name-message").textContent, /acknowledgement/);
    f.doc.getElementById("owner-oauth-ack").checked = true; f.submit("owner-oauth-name-form");
    await settle(() => f.sessions.length === 1);
    const registration = f.calls.find(call => call.url === "/api/v1/owner-self-register");
    assert.equal(registration.body.acknowledged, true);
    assert.equal(Object.hasOwn(registration.body, "email"), false);
    f.close(); groups++;
  }
  {
    const f = mount({invited: true, hash: "#access_token=fixture-access&refresh_token=fixture-refresh", acknowledged: true});
    await settle(() => f.sessions.length === 1);
    const registration = f.calls.find(call => call.url === "/api/v1/owner-invites/redeem");
    assert.equal(registration.body.token, "fixture-invitation");
    assert.equal(registration.body.acknowledgement_version, 1);
    assert.equal(registration.body.acknowledged, true);
    assert.equal(Object.hasOwn(registration.body, "email"), false);
    assert.equal(f.window.location.hash, "");
    f.close(); groups++;
  }
  {
    const first = mount(); await first.signup(); const pending = first.window.sessionStorage.getItem(pendingKey); first.close();
    const f = mount({pending, hash: "#error=access_denied&error_code=otp_expired&error_description=expired"});
    await settle(() => f.shown("owner-verify-email"));
    assert.equal(f.window.location.hash, "");
    assert.match(f.doc.getElementById("owner-verify-message").textContent, /fresh email/);
    assert.equal(f.calls.filter(call => call.method === "POST").length, 0);
    f.close(); groups++;
  }
  {
    const f = mount({pending: JSON.stringify({email:"collector@example.test",name:"Casey",context:"public",createdAt:1,nextResendAt:2})});
    await settle(() => f.shown("owner-join-form"));
    assert.equal(f.window.sessionStorage.getItem(pendingKey), null);
    assert.equal(f.calls.filter(call => call.method === "POST").length, 0);
    f.close(); groups++;
  }
  {
    const f = mount(); await settle(() => f.shown("owner-join-form"));
    const input = f.doc.getElementById("owner-join-password");
    const confirm = f.doc.getElementById("owner-join-confirm-password");
    const toggle = input.parentElement.querySelector("button");
    assert.equal(input.autocomplete, "new-password");
    assert.equal(input.minLength, 12);
    assert.equal(input.getAttribute("aria-label"), "Password");
    toggle.click(); assert.equal(input.type, "text"); assert.equal(toggle.getAttribute("aria-pressed"), "true");
    toggle.click(); assert.equal(input.type, "password");
    f.fill(input.id, "lowercase123"); assert.ok(input.validationMessage);
    f.fill(input.id, "StrongPassword123!"); assert.equal(input.validationMessage, "");
    f.fill(confirm.id, "WrongPassword123!"); assert.match(confirm.validationMessage, /do not match/);
    f.fill(confirm.id, "StrongPassword123!"); assert.equal(confirm.validationMessage, "");
    assert.match(f.doc.getElementById(`${confirm.id}-match`).textContent, /Passwords match/);
    const count = f.doc.querySelectorAll(".account-password-toggle").length;
    f.window.DropRateAccountExperience.enhance(); assert.equal(f.doc.querySelectorAll(".account-password-toggle").length, count);
    f.window.dispatchEvent(new f.window.Event("hub-session-cleared"));
    assert.equal(input.value, ""); assert.equal(confirm.value, ""); assert.equal(input.type, "password");
    assert.equal(f.calls.filter(call => call.method === "POST").length, 0);
    f.close(); groups++;
  }
  {
    const dom = new JSDOM('<body class="premium-hub"><section><form id="owner-password-form"><input id="existing" type="password" autocomplete="current-password"></form><p id="owner-profile-signin-help"></p></section></body>', {runScripts: "outside-only"});
    dom.window.eval(accountSource);
    const form = dom.window.document.getElementById("owner-password-form");
    assert.ok(form.closest("details")); assert.equal(form.closest("details").open, false);
    assert.equal(form.querySelector("input").hasAttribute("minlength"), false);
    dom.window.DropRateAccountExperience.setAccount({app_metadata:{providers:["google"]}});
    assert.match(dom.window.document.getElementById("owner-profile-signin-help").textContent, /linked to Google/);
    assert.equal(form.hidden, false); assert.equal(form.querySelector("input").disabled, false);
    dom.window.DropRateAccountExperience.setAccount({app_metadata:{providers:["email"]}});
    assert.doesNotMatch(dom.window.document.getElementById("owner-profile-signin-help").textContent, /Supabase|can be added/);
    dom.window.close(); groups++;
  }
  console.log(`Account experience: ${groups} interaction groups passed (isolated auth responses; no real signup, email or account writes).`);
})().catch(error => {console.error(error); process.exitCode = 1;});
