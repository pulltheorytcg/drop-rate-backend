"use strict";

function ownerInviteStatusText(item) {
  if (item.onboarding_status === "ACCEPTED") return "Accepted";
  if (item.onboarding_status === "REVOKED") return "Revoked";
  if (item.onboarding_status === "EXPIRED") return "Expired";
  if (item.email_status === "DELIVERED") return "Delivered";
  if (item.email_status === "SENT") return "Email sent";
  if (item.email_status === "FAILED") return "Email failed";
  return "Invite created";
}

function ownerInviteStatusClass(item) {
  if (item.onboarding_status === "ACCEPTED") return "ready";
  if (
    item.email_status === "FAILED"
    || item.onboarding_status === "EXPIRED"
    || item.onboarding_status === "REVOKED"
  ) {
    return "ended";
  }
  return "";
}

function sellerInviteDeliveryMessage(data, email) {
  const delivery = data?.email_delivery || {};
  if (delivery.status === "SENT") {
    return {
      text: `Branded invite email sent to ${email}.`,
      kind: "success",
    };
  }
  if (delivery.status === "NOT_CONFIGURED") {
    return {
      text: "Invite created, but transactional email is not configured yet. Copy the secure link as a fallback.",
      kind: "error",
    };
  }
  return {
    text: `Invite created, but email delivery is ${delivery.status || "NOT_SENT"}. Copy the secure link or resend after checking email configuration.`,
    kind: "error",
  };
}

async function resendOwnerInvite(item, button) {
  button.disabled = true;
  showMessage(
    "owner-invite-message",
    `Sending a fresh branded invitation to ${item.invited_email}…`
  );
  try {
    const data = await apiRequest(
      `/api/v1/owner-invites/${encodeURIComponent(item.id)}/resend`,
      {method: "POST"}
    );
    const result = byId("owner-invite-result");
    const url = byId("owner-invite-url");
    if (result && url) {
      url.value = data.invite_url || "";
      result.dataset.inviteId = item.id;
      result.classList.remove("hidden");
    }

    const message = sellerInviteDeliveryMessage(data, item.invited_email);
    showMessage("owner-invite-message", message.text, message.kind);
    await loadOwnerInvites();
  } catch (error) {
    showMessage("owner-invite-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function revokeOwnerInviteFromHistory(item, button) {
  button.disabled = true;
  try {
    await apiRequest(
      `/api/v1/owner-invites/${encodeURIComponent(item.id)}`,
      {method: "DELETE"}
    );
    showMessage(
      "owner-invite-message",
      `Invite for ${item.invited_email} revoked.`,
      "success"
    );
    await loadOwnerInvites();
  } catch (error) {
    showMessage("owner-invite-message", error.message, "error");
    button.disabled = false;
  }
}

function renderOwnerInviteHistory(items) {
  const container = byId("owner-invite-history");
  if (!container) return;
  container.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No seller invitations have been created yet.";
    container.append(empty);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.invited_name;
    const detail = document.createElement("small");
    const commission = (Number(item.commission_bps || 0) / 100)
      .toFixed(2)
      .replace(/\.00$/, "");
    const attempts = Number(item.email_attempt_count || 0);
    detail.textContent = [
      item.invited_email,
      `${commission}% commission`,
      `Email: ${item.email_status || "NOT_SENT"}`,
      `${attempts} send attempt${attempts === 1 ? "" : "s"}`,
    ].join(" · ");
    copy.append(name, detail);

    const actions = document.createElement("div");
    actions.className = "toolbar";
    const status = document.createElement("span");
    status.className =
      `channel-status ${ownerInviteStatusClass(item)}`.trim();
    status.textContent = ownerInviteStatusText(item);
    actions.append(status);

    if (item.onboarding_status === "INVITED") {
      const resend = document.createElement("button");
      resend.className = "ghost-button compact";
      resend.type = "button";
      resend.textContent = "Resend";
      resend.addEventListener(
        "click",
        () => resendOwnerInvite(item, resend)
      );

      const revoke = document.createElement("button");
      revoke.className = "ghost-button compact";
      revoke.type = "button";
      revoke.textContent = "Revoke";
      revoke.addEventListener(
        "click",
        () => revokeOwnerInviteFromHistory(item, revoke)
      );
      actions.append(resend, revoke);
    }

    row.append(copy, actions);
    container.append(row);
  });
}

async function loadOwnerInvites() {
  const container = byId("owner-invite-history");
  if (!container || !state.session?.access_token) return;
  try {
    const data = await apiRequest("/api/v1/owner-invites?limit=25");
    renderOwnerInviteHistory(data.items || []);
  } catch (error) {
    container.textContent =
      `Seller invitations could not be loaded: ${error.message}`;
  }
}

function enhanceOwnerInviteAdmin() {
  const panel = byId("owner-invite-admin-panel");
  if (!panel || panel.dataset.emailEnhanced === "true") return;
  panel.dataset.emailEnhanced = "true";

  const heading = panel.querySelector(".page-heading .muted");
  if (heading) {
    heading.textContent =
      "Sends a branded email for a restricted OWNER account. This can never grant Founder HQ access.";
  }

  const create = byId("owner-invite-create");
  if (create) create.textContent = "Send seller invite";

  const historyHeading = document.createElement("div");
  historyHeading.className = "page-heading";
  historyHeading.style.paddingTop = "18px";
  historyHeading.innerHTML =
    '<div><p class="eyebrow">Recent invitations</p><h3>Onboarding status</h3><p class="muted">Email delivery and account acceptance are tracked separately.</p></div>';

  const refresh = document.createElement("button");
  refresh.className = "ghost-button compact";
  refresh.type = "button";
  refresh.textContent = "↻ Refresh";
  refresh.addEventListener("click", () => loadOwnerInvites());
  historyHeading.append(refresh);

  const history = document.createElement("div");
  history.id = "owner-invite-history";
  history.className = "allocation-list";
  const loading = document.createElement("p");
  loading.className = "muted";
  loading.textContent = "Loading seller invitations…";
  history.append(loading);

  panel.append(historyHeading, history);
  loadOwnerInvites();
}

document.addEventListener("seller-view-changed", (event) => {
  if (event.detail?.view === "settings") {
    enhanceOwnerInviteAdmin();
    loadOwnerInvites();
  }
});

window.addEventListener("load", () => {
  enhanceOwnerInviteAdmin();
});
