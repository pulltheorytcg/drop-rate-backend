/* Progressive account-form help. Authentication and account writes stay in their existing handlers. */
(() => {
  "use strict";
  const pairs = [
    ["owner-join-password", "owner-join-confirm-password"],
    ["join-password", "join-confirm-password"],
    ["new-password", "confirm-password"],
    ["owner-profile-new-password", "owner-profile-confirm-password"],
  ];
  const policy = [
    ["12 or more characters", value => value.length >= 12],
    ["Uppercase and lowercase", value => /[A-Z]/.test(value) && /[a-z]/.test(value)],
    ["A number", value => /[0-9]/.test(value)],
    ["A symbol", value => /[^A-Za-z0-9\s]/.test(value)],
  ];
  const byId = id => document.getElementById(id);
  function describe(input, id) {
    const values = new Set((input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
    values.add(id);
    input.setAttribute("aria-describedby", [...values].join(" "));
  }
  function enhancePasswords(root = document) {
    root.querySelectorAll('input[type="password"]').forEach(input => {
      if (input.dataset.passwordEnhanced) return;
      input.dataset.passwordEnhanced = "true";
      const label = input.labels?.[0];
      const labelText = label ? [...label.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join(" ").trim() : "";
      if (labelText && !input.hasAttribute("aria-label")) input.setAttribute("aria-label", labelText);
      const wrapper = document.createElement("span");
      wrapper.className = "account-password-field";
      input.before(wrapper);
      wrapper.append(input);
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "account-password-toggle";
      toggle.textContent = "Show";
      toggle.setAttribute("aria-label", "Show password");
      toggle.setAttribute("aria-pressed", "false");
      if (input.id) toggle.setAttribute("aria-controls", input.id);
      toggle.addEventListener("click", event => {
        event.preventDefault();
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        toggle.textContent = show ? "Hide" : "Show";
        toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
        toggle.setAttribute("aria-pressed", String(show));
        input.focus({preventScroll: true});
      });
      wrapper.append(toggle);
    });
    for (const [passwordId, confirmationId] of pairs) {
      const password = byId(passwordId), confirmation = byId(confirmationId);
      if (!password || !confirmation || password.dataset.passwordPolicyEnhanced) continue;
      password.dataset.passwordPolicyEnhanced = "true";
      const requirements = document.createElement("ul");
      requirements.className = "account-password-policy";
      requirements.id = `${passwordId}-requirements`;
      const items = policy.map(([label]) => {
        const li = document.createElement("li");
        li.textContent = label;
        requirements.append(li);
        return li;
      });
      password.closest(".account-password-field").after(requirements);
      describe(password, requirements.id);
      const oldHint = passwordId === "owner-join-password" ? byId("owner-password-hint") : null;
      if (oldHint) {
        oldHint.hidden = true;
        password.setAttribute("aria-describedby", password.getAttribute("aria-describedby").split(/\s+/).filter(id => id !== oldHint.id).join(" "));
      }
      const match = document.createElement("small");
      match.className = "account-password-match";
      match.id = `${confirmationId}-match`;
      match.setAttribute("aria-live", "polite");
      confirmation.closest(".account-password-field").after(match);
      describe(confirmation, match.id);
      const update = () => {
        const value = password.value;
        const missing = policy.filter(([, check], index) => {
          const passed = check(value);
          items[index].classList.toggle("is-met", passed);
          return !passed;
        });
        password.setCustomValidity(value && missing.length ? "Use at least 12 characters with uppercase, lowercase, a number and a symbol." : "");
        const mismatch = Boolean(confirmation.value) && confirmation.value !== value;
        confirmation.setCustomValidity(mismatch ? "The passwords do not match." : "");
        match.textContent = !confirmation.value ? "" : mismatch ? "The passwords do not match yet." : "Passwords match.";
        match.classList.toggle("is-error", mismatch);
        match.classList.toggle("is-match", Boolean(confirmation.value) && !mismatch);
        if (!mismatch) confirmation.removeAttribute("aria-invalid");
        if (!missing.length) password.removeAttribute("aria-invalid");
      };
      password.addEventListener("input", update);
      confirmation.addEventListener("input", update);
      for (const input of [password, confirmation]) {
        input.addEventListener("invalid", () => input.setAttribute("aria-invalid", "true"));
        input.form?.addEventListener("reset", () => queueMicrotask(update));
      }
      update();
    }
  }
  function setAccount(user) {
    const note = byId("owner-profile-signin-help");
    if (!note) return;
    const providers = new Set([
      ...(Array.isArray(user?.app_metadata?.providers) ? user.app_metadata.providers : []),
      ...(Array.isArray(user?.identities) ? user.identities.map(identity => identity.provider) : []),
      user?.app_metadata?.provider,
    ].filter(value => typeof value === "string"));
    const social = ["google", "apple"].filter(value => providers.has(value)).map(value => value === "google" ? "Google" : "Apple");
    // This is guidance only: linked provider metadata does not prove whether a password exists.
    note.textContent = social.length
      ? `Your account is linked to ${social.join(" and ")}. If you also use a Drop Rate password, you can change that password here.`
      : "Use your current password to set a new one. If you use Google or Apple to sign in, you can keep using that sign-in method.";
  }
  function enhanceAccountSecurity() {
    const form = byId("owner-password-form");
    if (!form || form.closest(".account-security-details")) return;
    const details = document.createElement("details");
    details.className = "account-security-details";
    const summary = document.createElement("summary");
    summary.textContent = "Change an existing password";
    form.before(details);
    details.append(summary, form);
    const note = byId("owner-profile-signin-help");
    if (note) details.append(note);
  }
  window.DropRateAccountExperience = Object.freeze({enhance: enhancePasswords, setAccount});
  enhancePasswords();
  enhanceAccountSecurity();
  document.addEventListener("owner-view-changed", event => {
    if (event.detail?.view !== "profile") return;
    enhanceAccountSecurity();
    setAccount(window.PullTheoryHubSession?.read?.()?.user || null);
  });
  window.addEventListener("hub-session-cleared", () => {
    document.querySelectorAll("input[data-password-enhanced]").forEach(input => {
      input.value = "";
      input.type = "password";
      input.dispatchEvent(new Event("input", {bubbles: true}));
      const toggle = input.parentElement.querySelector(".account-password-toggle");
      if (toggle) { toggle.textContent = "Show"; toggle.setAttribute("aria-label", "Show password"); toggle.setAttribute("aria-pressed", "false"); }
    });
    setAccount(null);
  });
})();
