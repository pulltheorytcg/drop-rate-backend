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
    <div id="shopify-webhook-list" class="allocation-list"></div>
    <div class="page-heading pricing-subheading">
      <div>
        <p class="eyebrow">Product completeness</p>
        <h3>Shipping specifications</h3>
        <p class="muted">Configure the verified Shopify shipping weight once for raw and graded cards. New listings inherit the matching profile automatically; missing profiles block publication.</p>
      </div>
    </div>
    <div id="shopify-shipping-profile-list" class="allocation-list"></div>
    <div class="page-heading pricing-subheading">
      <div>
        <p class="eyebrow">Media readiness</p>
        <h3>Canonical reuse + physical-photo queue</h3>
        <p class="muted">Ordinary raw cards can share one rights-approved canonical front image per card identity. Graded cards require item-specific front and back images. No source is copied or approved automatically.</p>
      </div>
    </div>
    <div id="shopify-media-readiness" class="allocation-list"></div>
    <div class="page-heading pricing-subheading">
      <div>
        <p class="eyebrow">Controlled milestone test</p>
        <h3>Single-item Shopify sync</h3>
        <p class="muted">Only an APPROVED, physically verified item can be synced here. Bulk publishing remains locked off.</p>
      </div>
    </div>
    <div class="toolbar">
      <select id="shopify-test-candidate" aria-label="Choose approved inventory for Shopify test">
        <option value="">No eligible approved inventory</option>
      </select>
      <button id="shopify-product-preview-button" class="ghost-button compact" type="button" disabled>Preview Shopify page</button>\n      <button id="shopify-test-sync-button" class="primary-button compact" type="button" disabled>Sync one test item</button>
    </div>
    <div id="shopify-product-preview" class="allocation-list"></div>\n    <div id="shopify-test-status" class="allocation-list"></div>`;
  settings.append(panel);

  byId("shopify-register-button").addEventListener("click", registerShopifyWebhooks);
  byId("shopify-refresh-button").addEventListener("click", loadShopifyStatus);
  byId("shopify-test-candidate").addEventListener("change", refreshShopifyTestButton);
  byId("shopify-product-preview-button").addEventListener("click", previewSelectedShopifyProduct);
  byId("shopify-test-sync-button").addEventListener("click", syncSelectedShopifyTestItem);
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
    const [data, testData, shippingData, mediaData] = await Promise.all([
      apiRequest("/api/v1/shopify/status"),
      apiRequest("/api/v1/shopify/test-sync"),
      apiRequest("/api/v1/shopify/shipping-profiles?include_inactive=true"),
      apiRequest("/api/v1/shopify/media-readiness?limit=12"),
    ]);
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
          ? "Normal/bulk approved-stock publishing is enabled."
          : "Normal/bulk publishing is locked off. The separate guarded single-item test can still run when its own test gate is enabled."
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
    renderShopifyShippingProfiles(shippingData);
    renderShopifyMediaReadiness(mediaData);
    renderShopifyTestCandidates(testData);
    showMessage("shopify-settings-message");
  } catch (error) {
    list.textContent = "Shopify status could not be loaded.";
    webhookList.replaceChildren();
    showMessage("shopify-settings-message", error.message, "error");
  }
}

function shopifyShippingProfileLabel(key) {
  return key === "GRADED_CARD" ? "Graded card" : "Raw card";
}

function renderShopifyShippingProfiles(data) {
  const container = byId("shopify-shipping-profile-list");
  if (!container) return;
  const byKey = new Map((data.items || []).map((item) => [item.profile_key, item]));
  const required = data.required_profile_keys || ["RAW_CARD", "GRADED_CARD"];
  const rows = required.map((key) => {
    const profile = byKey.get(key);
    const row = shopifyStatusRow(
      shopifyShippingProfileLabel(key),
      profile?.active ? "CONFIGURED" : "REQUIRED",
      profile?.active
        ? `${Number(profile.weight_value)} ${String(profile.weight_unit || "").toLowerCase()} · v${profile.version}`
        : "Set an approved Shopify shipping weight before this product form can publish."
    );
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button compact";
    button.textContent = profile ? "Edit" : "Configure";
    button.addEventListener("click", () => configureShopifyShippingProfile(key, profile));
    row.append(button);
    return row;
  });
  container.replaceChildren(...rows);
}

async function configureShopifyShippingProfile(key, existing = null) {
  const currentValue = existing ? String(existing.weight_value) : "";
  const value = window.prompt(
    `Shopify shipping weight for ${shopifyShippingProfileLabel(key)} (number only):`,
    currentValue
  );
  if (value === null) return;
  const weightValue = Number(value);
  if (!Number.isFinite(weightValue) || weightValue <= 0) {
    showMessage("shopify-settings-message", "Enter a shipping weight greater than 0.", "error");
    return;
  }

  const currentUnit = existing?.weight_unit || "GRAMS";
  const unit = window.prompt(
    "Weight unit: GRAMS, KILOGRAMS, OUNCES or POUNDS",
    currentUnit
  );
  if (unit === null) return;
  const weightUnit = unit.trim().toUpperCase();
  if (!["GRAMS", "KILOGRAMS", "OUNCES", "POUNDS"].includes(weightUnit)) {
    showMessage("shopify-settings-message", "Choose a supported Shopify weight unit.", "error");
    return;
  }

  showMessage(
    "shopify-settings-message",
    `Saving ${shopifyShippingProfileLabel(key)} shipping specification…`
  );
  try {
    if (existing) {
      await apiRequest(`/api/v1/shopify/shipping-profiles/${existing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: existing.version,
          label: shopifyShippingProfileLabel(key),
          weight_value: weightValue,
          weight_unit: weightUnit,
          active: true,
        }),
      });
    } else {
      await apiRequest("/api/v1/shopify/shipping-profiles", {
        method: "POST",
        body: JSON.stringify({
          profile_key: key,
          label: shopifyShippingProfileLabel(key),
          weight_value: weightValue,
          weight_unit: weightUnit,
          notes: "Approved deterministic Shopify shipping specification.",
        }),
      });
    }
    await loadShopifyStatus();
    showMessage(
      "shopify-settings-message",
      `${shopifyShippingProfileLabel(key)} shipping specification saved.`,
      "success"
    );
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
  }
}


function mediaQueueLabel(item) {
  return [
    item.name,
    item.card_number,
    item.variant,
    item.language,
  ].filter(Boolean).join(" · ");
}

function renderShopifyMediaReadiness(data) {
  const container = byId("shopify-media-readiness");
  if (!container) return;
  const summary = data.summary || {};
  const rows = [
    shopifyStatusRow(
      "Raw-card media workload",
      `${Number(summary.raw_ready_identities || 0).toLocaleString("en-GB")} / ${Number(summary.raw_unique_identities || 0).toLocaleString("en-GB")} identities ready`,
      [
        `${Number(summary.raw_physical_cards || 0).toLocaleString("en-GB")} physical raw cards`,
        `${Number(summary.raw_physical_covered || 0).toLocaleString("en-GB")} covered by approved canonical media`,
        "one approved canonical front can cover duplicate physical copies",
      ].join(" · ")
    ),
    shopifyStatusRow(
      "Graded-card media workload",
      `${Number(summary.graded_ready_items || 0).toLocaleString("en-GB")} / ${Number(summary.graded_physical_cards || 0).toLocaleString("en-GB")} items ready`,
      "Each graded physical item requires its own approved FRONT + BACK images."
    ),
    shopifyStatusRow(
      "Launch media coverage",
      `${Number(summary.total_ready_physical_cards || 0).toLocaleString("en-GB")} ready · ${Number(summary.total_missing_physical_cards || 0).toLocaleString("en-GB")} missing`,
      data.policy?.rights_rule || "Media remains fail-closed until rights and approval are verified."
    ),
  ];

  (data.canonical_queue || []).forEach((item, index) => {
    rows.push(
      shopifyStatusRow(
        `Canonical priority ${index + 1}`,
        `${Number(item.physical_copies || 0).toLocaleString("en-GB")} physical cop${Number(item.physical_copies || 0) === 1 ? "y" : "ies"}`,
        `${mediaQueueLabel(item)} · ${item.set_name || "Unknown set"} · needs one approved canonical FRONT`
      )
    );
  });

  (data.physical_queue || []).forEach((item, index) => {
    const missingSides = [];
    if (!item.ready_front) missingSides.push("FRONT");
    if (!item.ready_back) missingSides.push("BACK");
    rows.push(
      shopifyStatusRow(
        `Physical-photo priority ${index + 1}`,
        item.inventory_code,
        `${mediaQueueLabel(item)} · ${item.grading_company || "Graded"} ${item.grade || ""} · needs ${missingSides.join(" + ")}`
      )
    );
  });

  container.replaceChildren(...rows);
}


function renderShopifyTestCandidates(data) {
  const select = byId("shopify-test-candidate");
  const status = byId("shopify-test-status");
  if (!select || !status) return;
  select.replaceChildren();
  const candidates = data.candidates || [];
  if (!candidates.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No eligible approved inventory";
    select.append(option);
  } else {
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Choose one approved item…";
    select.append(blank);
    candidates.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.dataset.version = item.version;
      option.dataset.launchReady = item.launch_ready ? "true" : "false";
      option.textContent = [
        item.name,
        item.card_number,
        item.variant,
        item.inventory_code,
        item.store_price_minor == null ? null : `£${(item.store_price_minor / 100).toFixed(2)}`,
        item.launch_ready ? "Launch ready" : "Launch blocked",
      ].filter(Boolean).join(" · ");
      select.append(option);
    });
  }

  const counts = data.counts || {};
  const readiness = data.readiness || {};
  const blockerLabels = {
    "APPROVED status": "Approval",
    "identity confirmation": "Identity confirmation",
    "acquisition cost": "Acquisition cost",
    "raw card condition": "Raw card condition",
    "seal status": "Seal status",
    "card language": "Card language",
    "store price": "Store Price",
    "registered storage location": "Registered storage location",
    "active storage location": "Active storage location",
  };
  const rows = [
    shopifyStatusRow(
      "Single-item test gate",
      data.test_publish_enabled ? "ENABLED" : "LOCKED OFF",
      data.bulk_publish_enabled
        ? "Bulk publishing is enabled — test mode will refuse to run."
        : "Bulk publishing remains locked off."
    ),
    shopifyStatusRow(
      "Test listings",
      `${counts.published_test || 0} live · ${counts.sold_test || 0} sold`,
      `${counts.error_test || 0} error`
    ),
    shopifyStatusRow(
      "Eligible inventory",
      `${readiness.eligible || 0} ready · ${readiness.blocked || 0} blocked`,
      `${readiness.considered || 0} unlinked active inventory items checked with the same rules used by the publish action.`
    ),
  ];
  const launchReadiness = data.launch_readiness || {};
  rows.push(
    shopifyStatusRow(
      "Launch completeness",
      `${launchReadiness.ready || 0} ready · ${launchReadiness.blocked || 0} blocked`,
      [
        `${(launchReadiness.verified_collections || []).length} Shopify collections verified`,
        `${(launchReadiness.shipping_profile_keys || []).length} shipping profiles configured`,
        launchReadiness.media_registry_status === "ACTIVE_FAIL_CLOSED"
          ? "approved media registry active — publishing remains fail-closed"
          : "media registry unavailable — publishing fails closed",
      ].join(" · ")
    )
  );
  Object.entries(launchReadiness.blockers || {})
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0]))
    .forEach(([blocker, count]) => {
      rows.push(
        shopifyStatusRow(
          `Launch · ${blocker}`,
          Number(count).toLocaleString("en-GB"),
          "This blocks Shopify publication but does not change the underlying inventory record."
        )
      );
    });
  Object.entries(readiness.blockers || {})
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0]))
    .forEach(([blocker, count]) => {
      rows.push(
        shopifyStatusRow(
          `Readiness · ${blockerLabels[blocker] || blocker}`,
          Number(count).toLocaleString("en-GB"),
          "Resolve this before the affected inventory can enter the controlled Shopify test."
        )
      );
    });
  const nextItem = (readiness.next_items || [])[0];
  if (nextItem) {
    const itemName = [nextItem.name, nextItem.card_number, nextItem.variant]
      .filter(Boolean)
      .join(" · ");
    rows.push(
      shopifyStatusRow(
        "Closest item to ready",
        nextItem.inventory_code,
        `${itemName || "Inventory item"} · Missing: ${(nextItem.missing || []).join(", ")}`
      )
    );
  }
  status.replaceChildren(...rows);
  select.dataset.testEnabled = data.test_publish_enabled ? "true" : "false";
  refreshShopifyTestButton();
}

function refreshShopifyTestButton() {
  const select = byId("shopify-test-candidate");
  const syncButton = byId("shopify-test-sync-button");
  const previewButton = byId("shopify-product-preview-button");
  if (!select || !syncButton || !previewButton) return;
  const option = select.selectedOptions?.[0];
  const launchReady = option?.dataset?.launchReady === "true";
  previewButton.disabled = !select.value;
  syncButton.disabled =
    !select.value
    || select.dataset.testEnabled !== "true"
    || !launchReady;
}

async function previewSelectedShopifyProduct() {
  const select = byId("shopify-test-candidate");
  const option = select?.selectedOptions?.[0];
  const panel = byId("shopify-product-preview");
  if (!option?.value || !panel) return;

  const button = byId("shopify-product-preview-button");
  button.disabled = true;
  showMessage("shopify-settings-message", "Building Shopify product preview…");
  try {
    const data = await apiRequest(`/api/v1/shopify/product-preview/${option.value}`);
    const plan = data.productPlan || {};
    const completeness = data.productCompleteness || {};
    const seo = plan.seo || {};
    const collections = plan.requiredCollections || [];
    const blockers = [
      ...(data.operationalBlockers || []),
      ...(completeness.blockers || []),
    ];

    panel.replaceChildren(
      shopifyStatusRow(
        "Product title",
        plan.title || "Missing",
        "Customer-facing title generated only from confirmed Drop Rate data."
      ),
      shopifyStatusRow(
        "Category",
        plan.categoryName || "Missing",
        plan.category || "No Shopify taxonomy category mapped."
      ),
      shopifyStatusRow(
        "Organisation",
        [plan.vendor, plan.productType].filter(Boolean).join(" · ") || "Missing",
        `${(plan.tags || []).length} tags · template: ${plan.template || "missing"}`
      ),
      shopifyStatusRow(
        "SEO",
        seo.title || "Missing",
        seo.description || "SEO description missing."
      ),
      shopifyStatusRow(
        "Collections",
        collections.length ? collections.join(" · ") : "Missing",
        completeness.missingCollections?.length
          ? `Missing in Shopify: ${completeness.missingCollections.join(", ")}`
          : "Required Shopify collections exist."
      ),
      shopifyStatusRow(
        "Media",
        completeness.approvedMediaCount > 0 ? "READY" : "BLOCKED",
        `${plan.mediaPolicy || "No policy"} · ${completeness.approvedMediaCount || 0} approved asset(s)`
      ),
      shopifyStatusRow(
        "Shipping",
        completeness.shippingSpec ? "READY" : "BLOCKED",
        completeness.shippingSpec
          ? `${completeness.shippingProfileKey} · ${completeness.shippingSpec.weight.value} ${String(completeness.shippingSpec.weight.unit || "").toLowerCase()}`
          : `Required profile: ${completeness.shippingProfileKey || plan.shippingProfileKey || "missing"}`
      ),
      shopifyStatusRow(
        "Launch gate",
        data.launchReady ? "READY" : "BLOCKED",
        blockers.length ? blockers.join(" · ") : "All required product fields are complete."
      )
    );
    showMessage(
      "shopify-settings-message",
      data.launchReady
        ? "Product plan is launch-complete."
        : "Preview generated. Publication remains blocked until every listed requirement is resolved.",
      data.launchReady ? "success" : ""
    );
  } catch (error) {
    panel.replaceChildren();
    showMessage("shopify-settings-message", error.message, "error");
  } finally {
    refreshShopifyTestButton();
  }
}

async function syncSelectedShopifyTestItem() {
  const select = byId("shopify-test-candidate");
  const option = select?.selectedOptions?.[0];
  if (!option?.value) return;
  const button = byId("shopify-test-sync-button");
  button.disabled = true;
  showMessage("shopify-settings-message", "Creating one guarded Shopify test listing…");
  try {
    const data = await apiRequest(`/api/v1/shopify/test-sync/${option.value}`, {
      method: "POST",
      body: JSON.stringify({version: Number(option.dataset.version)}),
    });
    const item = data.inventory || {};
    showMessage(
      "shopify-settings-message",
      `Single-item Shopify test sync succeeded: ${item.inventory_code || option.value}. Bulk publishing is still locked off.`,
      "success"
    );
    await loadShopifyStatus();
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
    refreshShopifyTestButton();
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
