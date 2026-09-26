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
        <p class="eyebrow">Storefront media</p>
        <h3>Founder card photos</h3>
        <p class="muted">Upload founder-owned card images directly into the governed media registry. Rights confirmation is explicit, Shopify file access is verified first, and incomplete media never bypasses the publication gate.</p>
      </div>
    </div>
    <div id="shopify-media-capability" class="allocation-list"></div>
    <div class="toolbar">
      <select id="shopify-media-candidate" aria-label="Choose card needing media">
        <option value="">No media work loaded</option>
      </select>
      <input id="shopify-media-file" type="file" accept="image/jpeg,image/png,image/webp" aria-label="Choose card image">
      <select id="shopify-media-scope" aria-label="Media scope">
        <option value="INVENTORY_ITEM">This physical card</option>
        <option value="CANONICAL_CARD">Canonical card image</option>
      </select>
      <select id="shopify-media-side" aria-label="Card image side">
        <option value="FRONT">Front</option>
        <option value="BACK">Back</option>
      </select>
    </div>
    <div class="toolbar">
      <input id="shopify-media-alt" type="text" maxlength="500" placeholder="Alt text, e.g. Seel 021/094 front">
      <label class="muted"><input id="shopify-media-rights" type="checkbox"> I own or am authorised to use this image</label>
      <button id="shopify-media-upload-button" class="primary-button compact" type="button" disabled>Upload & approve image</button>
    </div>
    <div id="shopify-media-list" class="allocation-list"></div>
    <div class="page-heading pricing-subheading">
      <div>
        <p class="eyebrow">Batch capture</p>
        <h3>Upload a photo batch</h3>
        <p class="muted">Name files with the queue Inventory ID and side, e.g. INV-ABC123...-front.jpg. Raw cards use one canonical FRONT; graded cards use exact FRONT + BACK images.</p>
      </div>
    </div>
    <div class="toolbar">
      <input id="shopify-media-batch-files" type="file" multiple accept="image/jpeg,image/png,image/webp" aria-label="Choose batch card images">
      <label class="muted"><input id="shopify-media-batch-rights" type="checkbox"> These are founder-owned original photographs</label>
      <button id="shopify-media-batch-button" class="primary-button compact" type="button" disabled>Upload media batch</button>
    </div>
    <div id="shopify-media-batch-preview" class="allocation-list"><p class="muted portfolio-empty">Select files to validate them against the live media queue before upload.</p></div>
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
  byId("shopify-media-candidate").addEventListener("change", applyMediaCandidateDefaults);
  byId("shopify-media-file").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-scope").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-side").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-alt").addEventListener("input", refreshShopifyMediaButton);
  byId("shopify-media-rights").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-upload-button").addEventListener("click", uploadFounderMedia);
  byId("shopify-media-batch-files").addEventListener("change", refreshBatchMediaPreview);
  byId("shopify-media-batch-rights").addEventListener("change", refreshBatchMediaPreview);
  byId("shopify-media-batch-button").addEventListener("click", uploadFounderMediaBatch);
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
    const [data, testData, shippingData, mediaCapability, mediaData, mediaQueue] = await Promise.all([
      apiRequest("/api/v1/shopify/status"),
      apiRequest("/api/v1/shopify/test-sync"),
      apiRequest("/api/v1/shopify/shipping-profiles?include_inactive=true"),
      apiRequest("/api/v1/shopify/media-assets/upload-capability"),
      apiRequest("/api/v1/shopify/media-assets"),
      apiRequest("/api/v1/shopify/media-assets/intake-queue"),
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
    renderShopifyTestCandidates(testData);
    renderShopifyMedia(mediaCapability, mediaData, mediaQueue);
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

function shopifyFulfilmentSummary(profile) {
  const dimensions = [
    profile.package_length_mm,
    profile.package_width_mm,
    profile.package_height_mm,
  ];
  const packageText = dimensions.every((value) => Number(value) > 0)
    ? `${dimensions.map(Number).join("×")}mm`
    : "package dimensions not set";
  const components = (profile.cost_components || []).filter(
    (component) => component.active
  );
  const accountingComplete =
    components.length > 0 &&
    components.every(
      (component) => component.accounting_unit_cost_minor_gbp !== null
    );
  const totalMinor = accountingComplete
    ? components.reduce(
        (total, component) =>
          total +
          Number(component.quantity || 0) *
            Number(component.accounting_unit_cost_minor_gbp || 0),
        0
      )
    : null;
  const materialText =
    totalMinor === null
      ? "material costs incomplete"
      : `£${(totalMinor / 100).toFixed(2)} materials`;
  return `${packageText} · ${materialText}`;
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
        ? [
            `${Number(profile.weight_value)} ${String(profile.weight_unit || "").toLowerCase()}`,
            shopifyFulfilmentSummary(profile),
            [profile.carrier, profile.service_name].filter(Boolean).join(" "),
            `v${profile.version}`,
          ].filter(Boolean).join(" · ")
        : "Set an approved Shopify shipping weight before this product form can publish."
    );
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button compact";
    button.textContent = profile ? "Edit" : "Configure";
    button.addEventListener("click", () => configureShopifyShippingProfile(key, profile));
    row.append(button);
    if (profile) {
      const costsButton = document.createElement("button");
      costsButton.type = "button";
      costsButton.className = "ghost-button compact";
      costsButton.textContent = "Costs";
      costsButton.addEventListener("click", () => configureFulfilmentCosts(profile));
      row.append(costsButton);
    }
    return row;
  });
  container.replaceChildren(...rows);
}

function parsePackageDimensions(value) {
  const parts = String(value || "")
    .trim()
    .split(/[x×]/i)
    .map(Number);
  if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part) || part <= 0)) {
    return null;
  }
  return parts;
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

  const currentDimensions = existing?.package_length_mm
    ? [
        Number(existing.package_length_mm),
        Number(existing.package_width_mm),
        Number(existing.package_height_mm),
      ].join("x")
    : "";
  const dimensionsValue = window.prompt(
    "Package dimensions in millimetres (length x width x height):",
    currentDimensions
  );
  if (dimensionsValue === null) return;
  const dimensions = parsePackageDimensions(dimensionsValue);
  if (!dimensions) {
    showMessage("shopify-settings-message", "Enter three positive package dimensions.", "error");
    return;
  }

  const emptyWeightValue = window.prompt(
    "Empty package weight in grams:",
    existing?.empty_package_weight_grams
      ? String(existing.empty_package_weight_grams)
      : ""
  );
  if (emptyWeightValue === null) return;
  const emptyPackageWeight = Number(emptyWeightValue);
  if (!Number.isFinite(emptyPackageWeight) || emptyPackageWeight <= 0) {
    showMessage("shopify-settings-message", "Enter an empty package weight greater than 0.", "error");
    return;
  }

  const carrier = window.prompt("Carrier:", existing?.carrier || "Royal Mail");
  if (carrier === null) return;
  const serviceName = window.prompt(
    "Service:",
    existing?.service_name || "Tracked 48"
  );
  if (serviceName === null) return;

  const profileFields = {
    label: shopifyShippingProfileLabel(key),
    weight_value: weightValue,
    weight_unit: weightUnit,
    package_length_mm: dimensions[0],
    package_width_mm: dimensions[1],
    package_height_mm: dimensions[2],
    empty_package_weight_grams: emptyPackageWeight,
    carrier: carrier.trim(),
    service_name: serviceName.trim(),
  };

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
          ...profileFields,
          active: true,
        }),
      });
    } else {
      await apiRequest("/api/v1/shopify/shipping-profiles", {
        method: "POST",
        body: JSON.stringify({
          profile_key: key,
          ...profileFields,
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

async function configureFulfilmentCosts(profile) {
  const definitions = [
    ["PACKAGING", "Order packaging"],
    ["TOPLOADER", "35pt top loader"],
  ];
  const updates = [];
  for (const [key, label] of definitions) {
    const existing = (profile.cost_components || []).find(
      (component) => component.component_key === key
    );
    const defaultValue = existing?.accounting_unit_cost_minor_gbp === null
      ? ""
      : (Number(existing?.accounting_unit_cost_minor_gbp || 0) / 100).toFixed(2);
    const value = window.prompt(`${label} cost in GBP:`, defaultValue);
    if (value === null) return;
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount < 0) {
      showMessage("shopify-settings-message", "Enter a valid GBP cost.", "error");
      return;
    }
    updates.push({
      key,
      existing,
      body: {
        version: existing?.version || null,
        label,
        quantity: 1,
        unit_cost_gbp: amount.toFixed(2),
        notes: existing?.notes || "Approved fulfilment material cost.",
      },
    });
  }

  showMessage("shopify-settings-message", "Saving fulfilment material costs…");
  try {
    for (const update of updates) {
      await apiRequest(
        `/api/v1/shopify/shipping-profiles/${profile.id}/cost-components/${update.key}`,
        {
          method: "PUT",
          body: JSON.stringify(update.body),
        }
      );
    }
    await loadShopifyStatus();
    showMessage(
      "shopify-settings-message",
      "Fulfilment material costs saved.",
      "success"
    );
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
  }
}


function mediaQueueLabel(item) {
  const identity = [
    item.name,
    item.set_name,
    item.card_number,
    item.language,
  ].filter(Boolean).join(" · ");
  if (item.required_scope === "INVENTORY_ITEM") {
    const grade = [item.grading_company, item.grade].filter(Boolean).join(" ");
    return [identity, grade, item.inventory_code, `needs ${(item.missing_sides || []).join(" + ")}`]
      .filter(Boolean)
      .join(" · ");
  }
  const copies = Number(item.copy_count || 0);
  return [identity, copies > 1 ? `${copies} copies share this image` : "canonical raw-card image"]
    .filter(Boolean)
    .join(" · ");
}

function renderMediaIntakeQueue(data) {
  const select = byId("shopify-media-candidate");
  if (!select) return;

  const previous = select.value;
  select.replaceChildren();
  const items = data?.items || [];

  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = items.length
    ? `Choose media work… (${data.missing_side_count || 0} side${Number(data.missing_side_count || 0) === 1 ? "" : "s"} remaining)`
    : "Media capture queue is clear";
  select.append(blank);

  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.queue_key;
    option.textContent = mediaQueueLabel(item);
    option.dataset.catalogueId = item.catalogue_id || "";
    option.dataset.inventoryId = item.inventory_id || "";
    option.dataset.inventoryCode = item.inventory_code || "";
    option.dataset.mediaScope = item.required_scope || "";
    option.dataset.missingSides = (item.missing_sides || []).join(",");
    option.dataset.cardName = item.name || "";
    option.dataset.cardNumber = item.card_number || "";
    option.dataset.language = item.language || "";
    select.append(option);
  });

  if (previous && [...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
  applyMediaCandidateDefaults();
}

function applyMediaCandidateDefaults() {
  const option = byId("shopify-media-candidate")?.selectedOptions?.[0];
  const scope = byId("shopify-media-scope");
  const side = byId("shopify-media-side");
  const missingSides = String(option?.dataset?.missingSides || "")
    .split(",")
    .filter(Boolean);

  if (scope) {
    if (option?.value && option.dataset.mediaScope) {
      scope.value = option.dataset.mediaScope;
      scope.disabled = true;
    } else {
      scope.disabled = false;
    }
  }
  if (side && missingSides.length) {
    if (!missingSides.includes(side.value)) side.value = missingSides[0];
    side.disabled = missingSides.length === 1;
  } else if (side) {
    side.disabled = false;
  }
  refreshShopifyMediaButton();
}

function renderShopifyMedia(capability, data, queueData) {
  const capabilityPanel = byId("shopify-media-capability");
  const list = byId("shopify-media-list");
  const button = byId("shopify-media-upload-button");
  if (!capabilityPanel || !list || !button) return;

  const ready = capability?.ready === true;
  button.dataset.scopeReady = ready ? "true" : "false";
  const batchButton = byId("shopify-media-batch-button");
  if (batchButton) batchButton.dataset.scopeReady = ready ? "true" : "false";
  capabilityPanel.replaceChildren(
    shopifyStatusRow(
      "Shopify file permission",
      ready ? "READY" : "ACTION REQUIRED",
      ready
        ? "write_files is granted. Founder images can be staged without storing image bytes in Drop Rate."
        : "Grant the Shopify app write_files scope, then use Verify Shopify + Register webhooks before uploading images."
    ),
    shopifyStatusRow(
      "Media capture queue",
      Number(queueData?.missing_side_count || 0).toLocaleString("en-GB"),
      [
        `${queueData?.raw_canonical_groups_pending || 0} raw canonical fronts`,
        `${queueData?.graded_items_pending || 0} graded physical items`,
      ].join(" · ")
    )
  );
  renderMediaIntakeQueue(queueData);

  const assets = (data?.items || []).slice(0, 12);
  if (!assets.length) {
    list.innerHTML = "<p class=\"muted\">No governed media assets yet.</p>";
    refreshShopifyMediaButton();
    return;
  }

  const rows = assets.map((asset) => {
    const scope = asset.scope === "INVENTORY_ITEM" ? "Physical item" : "Canonical card";
    const state = [
      asset.approval_status,
      asset.rights_status,
      asset.shopify_file_status,
    ].filter(Boolean).join(" · ");
    const row = shopifyStatusRow(
      `${scope} · ${asset.side}`,
      state,
      [asset.source_reference, asset.alt_text, `v${asset.version}`].filter(Boolean).join(" · ")
    );
    if (
      asset.approval_status === "APPROVED"
      && asset.rights_status === "VERIFIED"
      && ["NOT_UPLOADED", "UPLOADED", "PROCESSING"].includes(asset.shopify_file_status)
    ) {
      const sync = document.createElement("button");
      sync.type = "button";
      sync.className = "ghost-button compact";
      sync.textContent = asset.shopify_file_status === "PROCESSING"
        ? "Check Shopify"
        : "Sync to Shopify";
      sync.addEventListener("click", () => syncFounderMedia(asset.id, Number(asset.version)));
      row.append(sync);
    }
    return row;
  });
  list.replaceChildren(...rows);
  refreshShopifyMediaButton();
}

function refreshShopifyMediaButton() {
  const button = byId("shopify-media-upload-button");
  const candidate = byId("shopify-media-candidate")?.selectedOptions?.[0];
  const file = byId("shopify-media-file")?.files?.[0];
  const rights = byId("shopify-media-rights")?.checked === true;
  if (!button) return;
  button.disabled =
    button.dataset.scopeReady !== "true"
    || !candidate?.value
    || !file
    || !rights;
}

function founderMediaAltText(option, side) {
  const supplied = String(byId("shopify-media-alt")?.value || "").trim();
  if (supplied) return supplied;
  const cardName = String(option?.textContent || "Trading card").split(" · ")[0].trim();
  return `${cardName} ${String(side || "FRONT").toLowerCase()}`;
}

function parseBatchMediaFilename(filename) {
  const clean = String(filename || "").trim();
  const match = /^(INV-[A-Z0-9]+)[._ -]+(front|back)\.(jpe?g|png|webp)$/i.exec(clean);
  if (!match) return null;
  return {
    inventoryCode: match[1].toUpperCase(),
    side: match[2].toUpperCase(),
  };
}

function batchMediaQueueByInventoryCode() {
  const select = byId("shopify-media-candidate");
  const mapping = new Map();
  if (!select) return mapping;
  [...select.options].forEach((option) => {
    const code = String(option.dataset.inventoryCode || "").trim().toUpperCase();
    if (option.value && code) mapping.set(code, option);
  });
  return mapping;
}

function validateBatchMediaFiles(files) {
  const accepted = new Set(["image/jpeg", "image/png", "image/webp"]);
  const queue = batchMediaQueueByInventoryCode();
  const work = [];
  const errors = [];
  const seen = new Set();

  [...files].forEach((file) => {
    if (!accepted.has(file.type)) {
      errors.push({filename: file.name, reason: "Use JPG, PNG or WebP"});
      return;
    }
    if (file.size <= 0 || file.size > 20 * 1024 * 1024) {
      errors.push({filename: file.name, reason: "Image must be between 1 byte and 20 MB"});
      return;
    }

    const parsed = parseBatchMediaFilename(file.name);
    if (!parsed) {
      errors.push({
        filename: file.name,
        reason: "Filename must be INVENTORY-ID-front/back.jpg, png or webp",
      });
      return;
    }

    const option = queue.get(parsed.inventoryCode);
    if (!option) {
      errors.push({
        filename: file.name,
        reason: "Inventory ID is not present in the current media capture queue",
      });
      return;
    }

    const missingSides = String(option.dataset.missingSides || "")
      .split(",")
      .filter(Boolean);
    if (!missingSides.includes(parsed.side)) {
      errors.push({
        filename: file.name,
        reason: `${parsed.side} is not currently required for this card`,
      });
      return;
    }

    const duplicateKey = `${option.value}:${parsed.side}`;
    if (seen.has(duplicateKey)) {
      errors.push({
        filename: file.name,
        reason: "Duplicate card side in this batch",
      });
      return;
    }
    seen.add(duplicateKey);

    work.push({
      file,
      option,
      side: parsed.side,
      scope: option.dataset.mediaScope || "INVENTORY_ITEM",
      catalogueId: option.dataset.catalogueId || "",
      inventoryId: option.dataset.inventoryId || "",
    });
  });

  return {work, errors};
}

function renderBatchMediaValidation(result) {
  const container = byId("shopify-media-batch-preview");
  if (!container) return;
  container.replaceChildren();

  if (!result.work.length && !result.errors.length) {
    const empty = document.createElement("p");
    empty.className = "muted portfolio-empty";
    empty.textContent = "Select files to validate them against the live media queue before upload.";
    container.append(empty);
    return;
  }

  result.work.forEach((item) => {
    container.append(shopifyStatusRow(
      item.file.name,
      "READY TO UPLOAD",
      [
        item.option.dataset.cardName,
        item.option.dataset.cardNumber,
        item.option.dataset.language,
        item.scope === "CANONICAL_CARD" ? "shared canonical image" : "physical graded item",
        item.side,
      ].filter(Boolean).join(" · ")
    ));
  });
  result.errors.forEach((item) => {
    container.append(shopifyStatusRow(item.filename, "BLOCKED", item.reason));
  });
}

function refreshBatchMediaPreview() {
  const input = byId("shopify-media-batch-files");
  const button = byId("shopify-media-batch-button");
  const rights = byId("shopify-media-batch-rights")?.checked === true;
  if (!button) return;

  const result = validateBatchMediaFiles(input?.files || []);
  renderBatchMediaValidation(result);
  button.disabled =
    button.dataset.scopeReady !== "true"
    || !rights
    || result.work.length === 0
    || result.errors.length > 0;
}

function batchMediaAltText(option, side) {
  return [
    option.dataset.cardName || "Trading card",
    option.dataset.cardNumber || "",
    option.dataset.language || "",
    String(side || "FRONT").toLowerCase(),
  ].filter(Boolean).join(" ");
}

async function uploadFounderMediaWork({file, option, side, scope}) {
  const catalogueId = option.dataset.catalogueId || "";
  const inventoryId = option.dataset.inventoryId || "";
  if (scope === "CANONICAL_CARD" && !catalogueId) {
    throw new Error("Canonical media queue item is missing its catalogue identity.");
  }
  if (scope === "INVENTORY_ITEM" && !inventoryId) {
    throw new Error("Physical media queue item is missing its Inventory ID.");
  }

  const staged = await apiRequest("/api/v1/shopify/media-assets/upload-target", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      mime_type: file.type,
      file_size: file.size,
    }),
  });
  const target = staged.target || {};
  const form = new FormData();
  (target.parameters || []).forEach((parameter) => {
    form.append(parameter.name, parameter.value);
  });
  form.append("file", file);
  const uploadResponse = await fetch(target.url, {method: "POST", body: form});
  if (!uploadResponse.ok) {
    throw new Error(`Shopify staged upload failed (${uploadResponse.status}).`);
  }

  const rightsBasis = "Founder-owned original photograph; rights explicitly confirmed during upload";
  const altText = batchMediaAltText(option, side);
  const created = await apiRequest("/api/v1/shopify/media-assets", {
    method: "POST",
    body: JSON.stringify({
      catalogue_id: scope === "CANONICAL_CARD" ? catalogueId : null,
      inventory_id: scope === "INVENTORY_ITEM" ? inventoryId : null,
      side,
      source_type: "FOUNDER_UPLOAD",
      source_reference: file.name,
      public_source_url: target.resourceUrl,
      rights_basis: rightsBasis,
      alt_text: altText,
    }),
  });
  const approved = await apiRequest(`/api/v1/shopify/media-assets/${created.asset.id}/approve`, {
    method: "POST",
    body: JSON.stringify({
      version: Number(created.asset.version),
      rights_basis: rightsBasis,
      alt_text: altText,
    }),
  });
  return apiRequest(`/api/v1/shopify/media-assets/${approved.asset.id}/sync`, {
    method: "POST",
    body: JSON.stringify({version: Number(approved.asset.version)}),
  });
}

async function uploadFounderMediaBatch() {
  const input = byId("shopify-media-batch-files");
  const button = byId("shopify-media-batch-button");
  const rights = byId("shopify-media-batch-rights")?.checked === true;
  if (!input || !button || !rights) return;

  const validation = validateBatchMediaFiles(input.files || []);
  renderBatchMediaValidation(validation);
  if (!validation.work.length || validation.errors.length) {
    showMessage("shopify-settings-message", "Fix the blocked batch files before upload.", "error");
    return;
  }

  button.disabled = true;
  const outcomes = [];
  for (let index = 0; index < validation.work.length; index += 1) {
    const item = validation.work[index];
    showMessage(
      "shopify-settings-message",
      `Uploading image ${index + 1} of ${validation.work.length}: ${item.file.name}`
    );
    try {
      const result = await uploadFounderMediaWork(item);
      outcomes.push({
        filename: item.file.name,
        status: result.ready ? "READY" : "PROCESSING",
        detail: result.ready
          ? "Rights-approved and ready in Shopify"
          : "Uploaded and approved; Shopify file is still processing",
      });
    } catch (error) {
      outcomes.push({
        filename: item.file.name,
        status: "FAILED",
        detail: error.message,
      });
    }
  }

  const preview = byId("shopify-media-batch-preview");
  if (preview) {
    preview.replaceChildren(...outcomes.map((item) => (
      shopifyStatusRow(item.filename, item.status, item.detail)
    )));
  }
  const readyCount = outcomes.filter((item) => item.status === "READY").length;
  const processingCount = outcomes.filter((item) => item.status === "PROCESSING").length;
  const failedCount = outcomes.filter((item) => item.status === "FAILED").length;
  showMessage(
    "shopify-settings-message",
    `Batch complete: ${readyCount} ready · ${processingCount} processing · ${failedCount} failed.`,
    failedCount ? "error" : "success"
  );

  input.value = "";
  const rightsBox = byId("shopify-media-batch-rights");
  if (rightsBox) rightsBox.checked = false;
  await loadShopifyStatus();
}

async function syncFounderMedia(assetId, version) {
  showMessage("shopify-settings-message", "Checking the image in Shopify…");
  try {
    const result = await apiRequest(`/api/v1/shopify/media-assets/${assetId}/sync`, {
      method: "POST",
      body: JSON.stringify({version}),
    });
    showMessage(
      "shopify-settings-message",
      result.ready
        ? "Image is ready in Shopify and can satisfy the product media gate."
        : "Image reached Shopify and is still processing. Use Check Shopify again shortly.",
      result.ready ? "success" : ""
    );
    await loadShopifyStatus();
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
  }
}

async function uploadFounderMedia() {
  const option = byId("shopify-media-candidate")?.selectedOptions?.[0];
  const fileInput = byId("shopify-media-file");
  const file = fileInput?.files?.[0];
  const scope = byId("shopify-media-scope")?.value || "INVENTORY_ITEM";
  const side = byId("shopify-media-side")?.value || "FRONT";
  const rightsConfirmed = byId("shopify-media-rights")?.checked === true;
  const button = byId("shopify-media-upload-button");
  if (!option?.value || !file || !rightsConfirmed || !button) return;

  const accepted = ["image/jpeg", "image/png", "image/webp"];
  if (!accepted.includes(file.type)) {
    showMessage("shopify-settings-message", "Use a JPG, PNG or WebP image.", "error");
    return;
  }
  if (file.size <= 0 || file.size > 20 * 1024 * 1024) {
    showMessage("shopify-settings-message", "Image must be between 1 byte and 20 MB.", "error");
    return;
  }
  const catalogueId = option.dataset.catalogueId || "";
  const inventoryId = option.dataset.inventoryId || "";
  const requiredScope = option.dataset.mediaScope || scope;
  if (scope !== requiredScope) {
    showMessage("shopify-settings-message", "Media scope changed; reselect the queue item.", "error");
    applyMediaCandidateDefaults();
    return;
  }
  if (scope === "CANONICAL_CARD" && !catalogueId) {
    showMessage("shopify-settings-message", "This card is missing its catalogue identity.", "error");
    return;
  }

  button.disabled = true;
  showMessage("shopify-settings-message", "Preparing secure Shopify image upload…");
  try {
    const synced = await uploadFounderMediaWork({
      file,
      option,
      side,
      scope,
    });
    if (fileInput) fileInput.value = "";
    const rights = byId("shopify-media-rights");
    if (rights) rights.checked = false;
    showMessage(
      "shopify-settings-message",
      synced.ready
        ? "Founder image uploaded, rights-approved and ready in Shopify."
        : "Founder image uploaded and approved. Shopify is still processing it; use Check Shopify to finish verification.",
      synced.ready ? "success" : ""
    );
    await loadShopifyStatus();
  } catch (error) {
    showMessage("shopify-settings-message", error.message, "error");
    refreshShopifyMediaButton();
  }
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
      option.dataset.catalogueId = item.catalogue_id || "";
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
  refreshShopifyMediaButton();
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
