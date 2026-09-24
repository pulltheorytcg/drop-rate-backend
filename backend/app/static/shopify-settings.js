"use strict";

function installShopifySettingsPanel() {
  if (byId("shopify-settings-panel")) return;
  const settings = sellerView("settings");
  if (!settings) return;

  const panel = document.createElement("section");
  panel.id = "shopify-settings-panel";
  panel.className = "inventory-panel";
  panel.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Storefront integration</p>
        <h2>Shopify</h2>
        <p class="muted">Drop Rate remains the inventory source of truth. This connection is read-only until approved stock publishing is explicitly enabled.</p>
      </div>
      <div class="topbar-actions">
        <button id="shopify-register-button" class="primary-button compact" type="button">Verify Shopify + Register webhooks</button>
        <button id="shopify-refresh-button" class="ghost-button" type="button">↻ Refresh</button>
      </div>
    </div>
    <div id="shopify-settings-message" class="message panel-message" role="status"></div>
    <div id="shopify-status-list" class="allocation-list"><p class="muted">Open Settings to load Shopify status.</p></div>
    <div class="page-heading pricing-subheading">
      <div>
        <p class="eyebrow">Webhook boundary</p>
        <h3>Verified event intake</h3>
        <p class="muted">Webhook signatures are verified before JSON is trusted. Delivery IDs are deduplicated, and raw customer/payment payloads are not stored in the delivery ledger.</p>
      </div>
    </div>
    <div id="shopify-webhook-list" class="allocation-list"></div>`;
  settings.append(panel);

  byId("shopify-register-button").addEventListener("click", registerShopifyWebhooks);
  byId("shopify-refresh-button").addEventListener("click", loadShopifyStatus);
}

function shopifyStatusRow(label, value, note = "") {
  const row = document.createElement("div");
  row.className = "allocation-row";
  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = label;
  const description = document.createElement("small");
  description.textContent = note;
  details.append(name, description);
  const status = document.createElement("strong");
  status.textContent = value;
  row.append(details, status);
  return row;
}

async function loadShopifyStatus() {
  installShopifySettingsPanel();
  const list = byId("shopify-status-list");
  const webhookList = byId("shopify-webhook-list");
  if (!list || !webhookList || !state.session?.access_token) return;

  showMessage("shopify-settings-message", "Loading Shopify integration status…");
  try {
    const data = await apiRequest("/api/v1/shopify/status");
    list.replaceChildren(
      shopifyStatusRow(
        "Store configuration",
        data.configured ? "Configured" : "Not connected",
        data.shop_domain || "Shop domain and server-side credentials are not configured yet."
      ),
      shopifyStatusRow(
        "Admin API",
        data.admin_api_configured ? "Ready to probe" : "Credentials required",
        `GraphQL Admin API · ${data.api_version}`
      ),
      shopifyStatusRow(
        "Publishing",
        data.publish_enabled ? "ENABLED" : "LOCKED OFF",
        data.publish_enabled
          ? "Approved inventory may be eligible for publishing."
          : "No product creation or price publishing can run."
      ),
      shopifyStatusRow(
        "Webhook secret",
        data.webhook_secret_configured ? "Configured" : "Required",
        "Used only server-side for HMAC verification."
      ),
      shopifyStatusRow(
        "Webhook destination",
        data.webhook_endpoint_configured ? "Configured" : "Required",
        data.webhook_endpoint || "Canonical HTTPS webhook destination is not configured."
      )
    );

    const deliveries = data.deliveries || {};
    webhookList.replaceChildren(
      shopifyStatusRow(
        "Endpoint",
        data.webhook_path,
        "Use this Drop Rate path for Shopify webhook subscriptions."
      ),
      shopifyStatusRow(
        "Initial topics",
        (data.webhook_topics || []).length.toString(),
        (data.webhook_topics || []).join(" · ")
      ),
      shopifyStatusRow(
        "Verified deliveries",
        Number(deliveries.total_deliveries || 0).toLocaleString("en-GB"),
        [
          `${deliveries.received || 0} received`,
          `${deliveries.processed || 0} processed`,
          `${deliveries.ignored || 0} ignored`,
          `${deliveries.failed || 0} failed`,
        ].join(" · ")
      )
    );
    byId("shopify-register-button").disabled = !data.webhook_registration_ready;
    showMessage("shopify-settings-message");
  } catch (error) {
    list.textContent = "Shopify status could not be loaded.";
    webhookList.replaceChildren();
    showMessage("shopify-settings-message", error.message, "error");
  }
}

async function registerShopifyWebhooks() {
  const button = byId("shopify-register-button");
  button.disabled = true;
  showMessage(
    "shopify-settings-message",
    "Verifying the Shopify Admin API connection and webhook subscriptions…"
  );
  try {
    const data = await apiRequest("/api/v1/shopify/webhooks/register", {method: "POST"});
    const shop = data.shop || {};
    const parts = [
      shop.name,
      shop.myshopify_domain,
      shop.currency_code,
    ].filter(Boolean);
    showMessage(
      "shopify-settings-message",
      `Shopify verified${parts.length ? `: ${parts.join(" · ")}` : ""}. ${data.subscriptions?.length || 0} webhook subscriptions verified; ${data.created_count || 0} created. Publishing remains ${data.publish_enabled ? "enabled" : "locked off"}.`,
      "success"
    );
    await loadShopifyStatus();
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
    button.disabled = false;
  }
}

installShopifySettingsPanel();

const baseActivateSellerViewShopify = activateSellerView;
activateSellerView = function activateSellerViewWithShopify(name, updateHash = false) {
  const result = baseActivateSellerViewShopify(name, updateHash);
  if (name === "settings") loadShopifyStatus();
  return result;
};

if (sellerView("settings") && !sellerView("settings").classList.contains("hidden")) {
  loadShopifyStatus();
}
