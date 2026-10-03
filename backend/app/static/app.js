"use strict";


const PAGE_SIZE = 25;
const ISSUE_LABELS = {
  missing_cost: "Missing cost", missing_condition: "Missing raw condition",
  missing_seal_status: "Missing seal status",
  missing_location: "Missing location", missing_language: "Missing language", missing_price: "Missing store price",
  identity_unconfirmed: "Identity unchecked", approval_ready: "Ready to approve",
};
const state = {
  config: null, session: null, offset: 0, total: 0, search: "", status: "",
  brand: "", saleIntent: "", issue: "", items: new Map(), selected: new Map(), editing: null, readiness: null,
  inventoryView: "visual",
  providers: {google: false, apple: false},
};
const byId = (id) => document.getElementById(id);

function errorMessage(data) {
  const detail = data.error_description || data.msg || data.detail || data.message;
  if (typeof detail === "string") return detail;
  if (detail?.missing) return `${detail.message}: ${detail.missing.join(", ")}.`;
  if (Array.isArray(detail?.blockers)) return detail.blockers.join(" · ");
  if (Array.isArray(detail?.withdrawal_errors)) {
    const channels = detail.withdrawal_errors
      .map((item) => item?.channel)
      .filter(Boolean)
      .join(", ");
    return channels ? `${detail.message} Channels: ${channels}.` : detail.message;
  }
  if (detail?.message) return detail.message;
  return "Something went wrong. Please try again.";
}

function showMessage(id, text = "", kind = "") {
  const node = byId(id);
  node.textContent = text;
  node.className = `message${kind ? ` ${kind}` : ""}${id === "inventory-message" ? " panel-message" : ""}`;
}
function showForm(formId) {
  ["login-form", "request-reset-form", "new-password-form"].forEach((id) => byId(id).classList.toggle("hidden", id !== formId));
}
function setBusy(form, busy) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = busy;
  button.dataset.label ||= button.textContent;
  button.textContent = busy ? "Please wait…" : button.dataset.label;
}
async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(errorMessage(data)); error.status = response.status; error.code = data.code || data.error_code; throw error; }
  return data;
}
async function authRequest(path, options = {}) {
  return readJson(await fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: { apikey: state.config.publishable_key, "Content-Type": "application/json", ...(options.headers || {}) },
  }));
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

  const google = byId("login-google");
  const apple = byId("login-apple");
  google.classList.toggle("hidden", !state.providers.google);
  apple.classList.toggle("hidden", !state.providers.apple);
  byId("login-social-auth").classList.toggle(
    "hidden",
    !state.providers.google && !state.providers.apple
  );
}
function startOAuth(provider) {
  if (!["google", "apple"].includes(provider) || !state.providers[provider]) {
    showMessage("login-message", "That sign-in provider is not enabled yet.", "error");
    return;
  }
  const authorizeUrl = new URL(`${state.config.supabase_url}/auth/v1/authorize`);
  authorizeUrl.searchParams.set("provider", provider);
  authorizeUrl.searchParams.set("redirect_to", `${window.location.origin}/`);
  window.location.assign(authorizeUrl.toString());
}
function parseOAuthSession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (params.get("type") === "recovery" || !params.get("access_token")) return false;
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
function saveSession(session) {
  state.session = session;
  window.PullTheoryHubSession.save(session);
}
function clearSession() {
  window.dropRateCatalogue?.destroy();
  window.dropRateCatalogue = null;
  window.dropRateScanner?.destroy();
  window.dropRateScanner = null;
  state.session = null;
  window.PullTheoryHubSession.clear();
}
async function refreshSession() {
  return window.PullTheoryHubSession.refresh(async () => {
    const previous = state.session;
    try {
      if (!previous?.refresh_token) {
        const error = new Error("Your session has expired.");
        error.sessionExpired = true;
        throw error;
      }
      const session = await authRequest("/token?grant_type=refresh_token", {method:"POST", body:JSON.stringify({refresh_token:previous.refresh_token})});
      if (state.session !== previous) throw new Error("Your account changed. Please sign in again.");
      saveSession(session);
      return session.access_token;
    } catch (error) {
      error.refreshSession = previous;
      error.sessionExpired ||= window.PullTheoryHubSession.isExpiredRefresh(error);
      throw error;
    }
  });
}
async function apiRequest(path, options = {}, retry = true) {
  const requestOptions = {
    ...options,
    headers: { Authorization: `Bearer ${state.session.access_token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  };
  let response = await fetch(path, requestOptions);
  if (response.status === 401 && retry) {
    requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
    response = await fetch(path, requestOptions);
  }
  return readJson(response);
}
async function apiImageBlob(path, retry = true) {
  const requestOptions = {
    headers: { Authorization: `Bearer ${state.session.access_token}` },
  };
  let response = await fetch(path, requestOptions);
  if (response.status === 401 && retry) {
    requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
    response = await fetch(path, requestOptions);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(errorMessage(data));
  }
  return response.blob();
}

function redirectPendingFounderInviteCallback() {
  const pendingInvite = localStorage.getItem("drop_rate_pending_founder_invite");
  if (!pendingInvite || !window.location.hash) return false;

  const params = new URLSearchParams(window.location.hash.slice(1));
  if (!params.get("access_token") || params.get("type") === "recovery") return false;

  window.location.replace(
    `/join?invite=${encodeURIComponent(pendingInvite)}${window.location.hash}`
  );
  return true;
}

function parseRecoverySession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (params.get("type") !== "recovery" || !params.get("access_token")) return false;
  saveSession({ access_token: params.get("access_token"), refresh_token: params.get("refresh_token"), token_type: "bearer", expires_in: Number(params.get("expires_in") || 3600) });
  history.replaceState({}, document.title, window.location.pathname);
  showForm("new-password-form");
  return true;
}
function money(value, currency = "GBP") {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(value / 100);
}
function minorToInput(value) {
  return value === null || value === undefined ? "" : (value / 100).toFixed(2);
}
function inputToMinor(value, allowNull = true) {
  const clean = String(value).trim();
  if (!clean && allowNull) return null;
  if (!/^\d+(\.\d{0,2})?$/.test(clean)) throw new Error("Money values must use no more than two decimal places.");
  return Math.round(Number(clean) * 100);
}
function emptyToNull(value) {
  const clean = value.trim();
  return clean || null;
}
function textCell(label, text, className = "") {
  const td = document.createElement("td");
  td.dataset.label = label;
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

function itemCoreReadiness(item) {
  const checks = [];
  const isCard = item.product_type === "CARD";
  const isGraded = isCard
    && Boolean((item.grading_company || "").trim())
    && Boolean((item.grade || "").trim());

  checks.push({
    label: isCard ? (isGraded ? "Grade" : "Condition") : "Seal",
    ok: isCard
      ? (isGraded || Boolean((item.condition || "").trim()))
      : Boolean(item.seal_status),
  });
  checks.push({ label: "Cost", ok: item.acquisition_cost_minor !== null && item.acquisition_cost_minor !== undefined });
  if (isCard) checks.push({ label: "Language", ok: Boolean((item.language || "").trim()) });
  checks.push({ label: "Location", ok: Boolean(item.storage_location_id) });
  checks.push({ label: "Price", ok: item.store_price_minor !== null && item.store_price_minor !== undefined });
  checks.push({ label: "Identity", ok: Boolean(item.identity_confirmed) });

  return {
    complete: checks.filter((check) => check.ok).length,
    total: checks.length,
    missing: checks.filter((check) => !check.ok).map((check) => check.label),
  };
}

function refreshSelectionControls() {
  const count = state.selected.size;
  byId("selected-count").textContent = String(count);
  byId("bulk-cost-button").disabled = count < 2;
  const visible = [...state.items.values()];
  byId("select-page").checked = visible.length > 0 && visible.every((item) => state.selected.has(item.id));
  byId("select-page").indeterminate = visible.some((item) => state.selected.has(item.id)) && !byId("select-page").checked;
}

function ensureFiveSoldPreviewDialog() {
  let dialog = byId("five-sold-preview-dialog");
  if (dialog) return dialog;

  dialog = document.createElement("dialog");
  dialog.id = "five-sold-preview-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <div class="modal-card wide">
      <div class="modal-heading">
        <div>
          <p class="eyebrow">Read-only pricing check</p>
          <h2 id="five-sold-preview-title">Five latest sold comps</h2>
          <p id="five-sold-preview-meta" class="muted"></p>
        </div>
        <button id="five-sold-preview-close" class="icon-button" type="button" aria-label="Close">×</button>
      </div>
      <div id="five-sold-preview-message" class="message"></div>
      <div id="five-sold-preview-summary" class="allocation-list"></div>
      <div id="five-sold-preview-results" class="allocation-list"></div>
      <div class="modal-actions">
        <button id="five-sold-preview-close-bottom" class="ghost-button" type="button">Close</button>
      </div>
    </div>`;
  document.body.append(dialog);

  const close = () => dialog.close();
  byId("five-sold-preview-close").addEventListener("click", close);
  byId("five-sold-preview-close-bottom").addEventListener("click", close);
  return dialog;
}

function soldCompRow(comp) {
  const row = document.createElement("div");
  row.className = "allocation-row";

  const details = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = comp.title || comp.item_id || "eBay sale";
  const note = document.createElement("small");
  const soldDate = comp.sold_at ? new Date(comp.sold_at).toLocaleDateString("en-GB") : "date unavailable";
  const shipping = comp.shipping_minor === null || comp.shipping_minor === undefined
    ? "shipping unknown"
    : `${money(comp.shipping_minor)} shipping`;
  note.textContent = [soldDate, shipping, comp.item_id ? `eBay ${comp.item_id}` : null]
    .filter(Boolean)
    .join(" · ");
  details.append(title, note);

  const price = document.createElement("strong");
  price.textContent = money(comp.price_minor);
  row.append(details, price);
  return row;
}

async function openFiveSoldPreview(item) {
  const dialog = ensureFiveSoldPreviewDialog();
  byId("five-sold-preview-title").textContent = `${item.name} · five sold preview`;
  byId("five-sold-preview-meta").textContent = [
    item.set_name,
    item.card_number,
    item.language || item.catalogue_language,
    item.variant,
    item.grading_company && item.grade ? `${item.grading_company} ${item.grade}` : item.condition,
    item.inventory_code,
  ].filter(Boolean).join(" · ");
  byId("five-sold-preview-summary").replaceChildren();
  byId("five-sold-preview-results").replaceChildren();
  showMessage("five-sold-preview-message", "Calling Trawl and validating sold listings…");
  dialog.showModal();

  try {
    const data = await apiRequest(
      `/api/v1/pricing/ebay-five-sold/${item.id}/preview`,
      {method: "POST"}
    );

    const summary = byId("five-sold-preview-summary");
    const methodRow = document.createElement("div");
    methodRow.className = "allocation-row";
    const methodDetails = document.createElement("div");
    const methodTitle = document.createElement("strong");
    methodTitle.textContent = data.status === "READY" ? "Five exact sold comps found" : "Preview blocked safely";
    const methodNote = document.createElement("small");
    methodNote.textContent = [
      data.query ? `Query: ${data.query}` : null,
      data.reason || null,
      "Preview only — Store Price has not been changed",
    ].filter(Boolean).join(" · ");
    methodDetails.append(methodTitle, methodNote);
    const methodValue = document.createElement("strong");
    methodValue.textContent = data.status === "READY"
      ? money(data.store_price_minor)
      : `${data.comparable_count || 0}/5 comps`;
    methodRow.append(methodDetails, methodValue);
    summary.append(methodRow);

    const results = byId("five-sold-preview-results");
    const comps = data.comps || [];
    if (comps.length) {
      results.replaceChildren(...comps.map(soldCompRow));
    } else {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No sold listings passed Drop Rate's exact-card matcher.";
      results.replaceChildren(empty);
    }
    showMessage(
      "five-sold-preview-message",
      data.status === "READY"
        ? "Read-only preview complete. Review all five sales before any price is applied."
        : "Read-only preview complete. Nothing was written.",
      data.status === "READY" ? "success" : ""
    );
  } catch (error) {
    showMessage("five-sold-preview-message", error.message, "error");
  }
}

async function listInventoryOnEbay(item, button) {
  const priorLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Listing…";
  showMessage("inventory-message", `Publishing ${item.inventory_code} to eBay…`);
  try {
    const result = await apiRequest(
      `/api/v1/ebay/listings/${item.id}`,
      {method: "POST", body: JSON.stringify({version: item.version})}
    );
    showMessage(
      "inventory-message",
      result.idempotent
        ? `${item.inventory_code} is already live on eBay.`
        : `${item.inventory_code} is live on eBay and linked to this physical Inventory ID.`,
      "success"
    );
    await loadInventory();
  } catch (error) {
    showMessage("inventory-message", error.message, "error");
    button.disabled = false;
    button.textContent = priorLabel;
  }
}

async function changeInventorySaleIntent(item, saleIntent, button) {
  if (["RESERVED", "SOLD"].includes(item.status)) {
    showMessage(
      "inventory-message",
      "Reserved or sold inventory cannot change sale intent.",
      "error"
    );
    return;
  }

  if (
    saleIntent === "PERSONAL_COLLECTION"
    && !window.confirm(
      "Move this item to Personal Collection? Any live eBay or Shopify listing will be withdrawn."
    )
  ) {
    return;
  }

  const priorLabel = button.textContent;
  button.disabled = true;
  button.textContent = saleIntent === "PERSONAL_COLLECTION"
    ? "Moving…"
    : "Unlocking…";
  showMessage(
    "inventory-message",
    saleIntent === "PERSONAL_COLLECTION"
      ? `Protecting ${item.inventory_code} as Personal Collection and withdrawing marketplace listings…`
      : `Moving ${item.inventory_code} back to sellable inventory…`
  );

  try {
    await apiRequest(
      `/api/v1/inventory/${item.id}/sale-intent`,
      {
        method: "POST",
        body: JSON.stringify({
          version: item.version,
          sale_intent: saleIntent,
        }),
      }
    );
    await reloadDashboard(
      saleIntent === "PERSONAL_COLLECTION"
        ? `${item.inventory_code} is now in Personal Collection and is not for sale.`
        : `${item.inventory_code} can be listed for sale again. Nothing was relisted automatically.`
    );
  } catch (error) {
    // PERSONAL_COLLECTION is committed locally before remote channel withdrawal.
    // Reload so the dashboard reflects the fail-closed source-of-truth state.
    await Promise.all([loadReadiness(), loadInventory()]).catch(() => {});
    showMessage("inventory-message", error.message, "error");
    button.disabled = false;
    button.textContent = priorLabel;
  }
}

function saleIntentAction(item) {
  const button = document.createElement("button");
  button.className = "row-button sale-intent-button";
  button.type = "button";

  if (["RESERVED", "SOLD"].includes(item.status)) {
    button.textContent = item.status === "SOLD" ? "Sold" : "Reserved";
    button.disabled = true;
    return button;
  }

  const personal = item.sale_intent === "PERSONAL_COLLECTION";
  button.textContent = personal ? "Move to sell" : "Move to collection";
  button.title = personal
    ? "Return this physical item to sellable inventory. It will not be relisted automatically."
    : "Keep this physical item in your Personal Collection and withdraw live marketplace listings.";
  button.addEventListener("click", () => (
    changeInventorySaleIntent(
      item,
      personal ? "FOR_SALE" : "PERSONAL_COLLECTION",
      button
    )
  ));
  return button;
}

function ebayInventoryAction(item) {
  if (item.sale_intent === "PERSONAL_COLLECTION") {
    const badge = document.createElement("span");
    badge.className = "channel-status ended";
    badge.textContent = "Not for sale";
    badge.title = "Personal Collection inventory cannot be listed on eBay.";
    return badge;
  }

  const stateValue = String(item.ebay_state || "");
  if (stateValue === "LIVE") {
    const badge = document.createElement("span");
    badge.className = "channel-status live";
    badge.textContent = "eBay Live";
    badge.title = [
      item.ebay_listing_id ? `Listing ${item.ebay_listing_id}` : null,
      item.ebay_price_minor !== null && item.ebay_price_minor !== undefined
        ? money(item.ebay_price_minor, "GBP")
        : null,
    ].filter(Boolean).join(" · ");
    return badge;
  }
  if (stateValue === "SOLD") {
    const badge = document.createElement("span");
    badge.className = "channel-status sold";
    badge.textContent = "eBay Sold";
    return badge;
  }
  if (stateValue === "WITHDRAWN" && item.status !== "APPROVED") {
    const badge = document.createElement("span");
    badge.className = "channel-status ended";
    badge.textContent = "eBay Ended";
    return badge;
  }

  const button = document.createElement("button");
  button.className = "row-button ebay-list-button";
  button.type = "button";
  button.textContent = stateValue === "ERROR"
    ? "Retry eBay"
    : stateValue === "WITHDRAWN" ? "Relist eBay" : "List on eBay";
  if (stateValue === "ERROR") {
    button.title = item.ebay_error_code
      ? `Last eBay error: ${item.ebay_error_code}`
      : "The previous eBay action needs attention.";
  }
  button.addEventListener("click", () => listInventoryOnEbay(item, button));
  return button;
}

function setInventoryView(view) {
  state.inventoryView = view === "table" ? "table" : "visual";
  const visual = byId("inventory-visual-grid");
  const table = byId("inventory-table-wrap");
  const visualButton = byId("inventory-view-visual");
  const tableButton = byId("inventory-view-table");
  if (!visual || !table || !visualButton || !tableButton) return;
  const visualActive = state.inventoryView === "visual";
  visual.classList.toggle("hidden", !visualActive);
  table.classList.toggle("hidden", visualActive);
  visualButton.classList.toggle("active", visualActive);
  tableButton.classList.toggle("active", !visualActive);
  visualButton.setAttribute("aria-pressed", visualActive ? "true" : "false");
  tableButton.setAttribute("aria-pressed", visualActive ? "false" : "true");
}

function inventoryImageFigure(item) {
  const figure = document.createElement("button");
  figure.type = "button";
  figure.className = "inventory-card-art";
  figure.setAttribute("aria-label", `Review ${item.name}`);
  figure.addEventListener("click", () => openEditor(item));

  if (!item.card_image_url) {
    const empty = document.createElement("div");
    empty.className = "inventory-card-art-empty";
    empty.innerHTML = "<span>◇</span><strong>No image yet</strong><small>Exact image not assigned yet</small>";
    figure.append(empty);
    return figure;
  }

  const image = document.createElement("img");
  image.alt = [item.name, item.set_name, item.card_number, item.language || item.catalogue_language]
    .filter(Boolean).join(" · ");
  image.decoding = "async";

  const showFailure = () => {
    if (image.isConnected) image.remove();
    if (figure.querySelector(".inventory-card-art-empty")) return;
    const empty = document.createElement("div");
    empty.className = "inventory-card-art-empty error";
    empty.innerHTML = "<span>!</span><strong>Image source needs review</strong><small>Drop Rate could not load the assigned image</small>";
    figure.append(empty);
  };

  const proxyPath = `/api/v1/inventory/${encodeURIComponent(item.id)}/image`;

  let proxyLoadStarted = false;
  const loadFromProxy = () => {
    if (proxyLoadStarted) return;
    proxyLoadStarted = true;
    apiImageBlob(proxyPath)
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        image.addEventListener("load", () => URL.revokeObjectURL(objectUrl), { once: true });
        image.addEventListener("error", () => {
          URL.revokeObjectURL(objectUrl);
          showFailure();
        }, { once: true });
        image.src = objectUrl;
      })
      .catch(showFailure);
  };

  const loadProxyNearViewport = () => {
    image.loading = "lazy";
    if (typeof window.IntersectionObserver !== "function") {
      loadFromProxy();
      return;
    }
    const observer = new window.IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      loadFromProxy();
    }, { rootMargin: "320px 0px" });
    observer.observe(figure);
  };

  const directImageUrl = item.card_image_direct_url || item.card_image_cdn_url;
  figure.append(image);
  if (directImageUrl) {
    image.loading = "lazy";
    image.addEventListener("error", loadFromProxy, { once: true });
    image.src = directImageUrl;
  } else {
    loadProxyNearViewport();
  }

  const badge = document.createElement("span");
  badge.className = `inventory-image-badge ${String(item.card_image_approval_status || "").toLowerCase()}`;
  const graded = Boolean(item.grade || item.grading_company || item.certificate_number);
  const physicalSlabImage = item.card_image_scope === "INVENTORY_ITEM";
  if (graded && !physicalSlabImage) {
    badge.textContent = "Reference art · slab photo required";
    badge.classList.add("needs-slab");
    figure.dataset.imageState = "graded-reference-only";
  } else if (physicalSlabImage) {
    badge.textContent = graded ? "Physical slab image" : "Physical item image";
    figure.dataset.imageState = "physical-item";
  } else {
    badge.textContent = item.card_image_approval_status === "APPROVED"
      ? "Verified image"
      : "Reference image";
    figure.dataset.imageState = "canonical-reference";
  }
  figure.append(badge);
  return figure;
}

function inventoryVisualCard(item) {
  const card = document.createElement("article");
  card.className = "inventory-visual-card";
  card.dataset.inventoryId = item.id;

  const selectWrap = document.createElement("label");
  selectWrap.className = "inventory-card-select";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selected.has(item.id);
  checkbox.setAttribute("aria-label", `Select ${item.name}`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selected.set(item.id, item);
    else state.selected.delete(item.id);
    refreshSelectionControls();
  });
  selectWrap.append(checkbox);
  card.append(selectWrap, inventoryImageFigure(item));

  const body = document.createElement("div");
  body.className = "inventory-visual-card-body";

  const heading = document.createElement("div");
  heading.className = "inventory-card-heading";
  const titleWrap = document.createElement("div");
  const title = document.createElement("button");
  title.type = "button";
  title.className = "inventory-card-title";
  title.textContent = item.name;
  title.addEventListener("click", () => openEditor(item));
  const subtitle = document.createElement("p");
  subtitle.textContent = [
    item.set_name,
    item.card_number,
    item.rarity,
    item.variant,
    item.language || item.catalogue_language,
  ].filter(Boolean).join(" · ") || "Uncatalogued";
  titleWrap.append(title, subtitle);

  const status = document.createElement("span");
  status.className = `pill ${String(item.status || "").toLowerCase()}`;
  status.textContent = item.status
    ? item.status.charAt(0) + item.status.slice(1).toLowerCase()
    : "Unknown";
  heading.append(titleWrap, status);
  body.append(heading);

  const valueRow = document.createElement("div");
  valueRow.className = "inventory-card-values";
  const values = [
    ["Market", money(item.market_value_minor, item.currency)],
    ["Store", money(item.store_price_minor, item.currency)],
    ["Cost", money(item.acquisition_cost_minor, item.currency)],
  ];
  values.forEach(([label, value]) => {
    const box = document.createElement("div");
    const key = document.createElement("span");
    key.textContent = label;
    const amount = document.createElement("strong");
    amount.textContent = value;
    box.append(key, amount);
    valueRow.append(box);
  });
  body.append(valueRow);

  const facts = document.createElement("div");
  facts.className = "inventory-card-facts";
  const factValues = [
    ["Inventory", item.inventory_code],
    ["Intent", item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "For sale"],
    ["Condition", item.grade
      ? [item.grading_company || "Graded", item.grade].filter(Boolean).join(" ")
      : (item.condition || "—")],
    ["Location", item.storage_location_label || item.location || "—"],
    ["Identity", item.identity_confirmed ? "Confirmed" : "Needs verification"],
  ];
  factValues.forEach(([label, value]) => {
    const row = document.createElement("div");
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = value || "—";
    row.append(key, val);
    facts.append(row);
  });
  body.append(facts);

  const readiness = itemCoreReadiness(item);
  const readinessLine = document.createElement("span");
  readinessLine.className = `core-readiness${readiness.complete === readiness.total ? " complete" : ""}`;
  readinessLine.textContent = item.sale_intent === "PERSONAL_COLLECTION"
    ? "Personal collection · not for sale"
    : readiness.complete === readiness.total
      ? `Core ${readiness.complete}/${readiness.total} ✓`
      : `Core ${readiness.complete}/${readiness.total} · Needs ${readiness.missing.join(", ")}`;
  body.append(readinessLine);

  const actions = document.createElement("div");
  actions.className = "inventory-card-actions";
  const review = document.createElement("button");
  review.className = "primary-button compact";
  review.type = "button";
  review.textContent = "Review";
  review.addEventListener("click", () => openEditor(item));
  actions.append(review, saleIntentAction(item));
  if (item.product_type === "CARD") actions.append(ebayInventoryAction(item));
  body.append(actions);

  card.append(body);
  return card;
}

function renderInventory(data) {
  state.total = data.total;
  state.items = new Map(data.items.map((item) => [item.id, item]));
  byId("total-count").textContent = state.readiness?.total?.toLocaleString("en-GB") || data.total.toLocaleString("en-GB");
  byId("owner-name").textContent = data.owner.display_name;
  byId("owner-initial").textContent = data.owner.display_name.slice(0, 1).toUpperCase();
  const body = byId("inventory-body");
  const visualGrid = byId("inventory-visual-grid");
  body.replaceChildren();
  visualGrid.replaceChildren();
  data.items.forEach((item) => {
    visualGrid.append(inventoryVisualCard(item));
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    selectCell.dataset.label = "Select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(item.id);
    checkbox.setAttribute("aria-label", `Select ${item.name}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.set(item.id, item); else state.selected.delete(item.id);
      refreshSelectionControls();
    });
    selectCell.append(checkbox);
    row.append(selectCell);
    const name = document.createElement("td");
    name.dataset.label = "Item";
    const wrap = document.createElement("div");
    wrap.className = "card-name";
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    const meta = document.createElement("small");
    const productLabel = item.product_type === "SEALED"
      ? "Sealed product"
      : item.product_type === "COLLECTION" ? "Collection" : null;
    meta.textContent = [
      productLabel,
      item.brand,
      item.game && item.game !== item.brand ? item.game : null,
      item.card_number,
      item.variant,
    ].filter(Boolean).join(" · ") || "Uncatalogued";
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = item.inventory_code;
    const readiness = itemCoreReadiness(item);
    const readinessLine = document.createElement("span");
    readinessLine.className = `core-readiness${readiness.complete === readiness.total ? " complete" : ""}`;
    readinessLine.textContent = item.sale_intent === "PERSONAL_COLLECTION"
      ? "Personal collection · not for sale"
      : readiness.complete === readiness.total
        ? `Core ${readiness.complete}/${readiness.total} ✓`
        : `Core ${readiness.complete}/${readiness.total} · Needs ${readiness.missing.join(", ")}`;
    wrap.append(strong, meta, code, readinessLine);
    name.append(wrap);
    row.append(name);
    row.append(textCell("Set", item.set_name || "—", "set-detail"));
    row.append(textCell("Condition", item.product_type === "CARD" && !item.grade ? (item.condition || "—") : "—"));
    row.append(textCell("Grading", item.product_type === "CARD" && item.grade ? `${item.grading_company || "Graded"} ${item.grade}` : "—"));
    row.append(textCell("Seal", item.product_type !== "CARD" ? (item.seal_status === "SEALED" ? "Sealed" : item.seal_status === "UNSEALED" ? "Unsealed" : "—") : "—"));
    row.append(textCell("Cost", money(item.acquisition_cost_minor, item.currency)));
    row.append(textCell("Store price", money(item.store_price_minor, item.currency)));
    const status = document.createElement("td");
    status.dataset.label = "Status";
    const pill = document.createElement("span");
    pill.className = `pill ${item.status.toLowerCase()}`;
    pill.textContent = item.status.charAt(0) + item.status.slice(1).toLowerCase();
    status.append(pill);
    if (item.sale_intent === "PERSONAL_COLLECTION") {
      const intent = document.createElement("span");
      intent.className = "channel-status ended";
      intent.textContent = "Personal";
      intent.title = "Personal Collection · not for sale";
      status.append(intent);
    }
    row.append(status);
    const actions = document.createElement("td");
    actions.dataset.label = "Actions";
    const edit = document.createElement("button");
    edit.className = "row-button";
    edit.type = "button";
    edit.textContent = "Review";
    edit.addEventListener("click", () => openEditor(item));
    actions.append(edit, saleIntentAction(item));
    if (item.product_type === "CARD" && item.identity_confirmed) {
      const preview = document.createElement("button");
      preview.className = "row-button";
      preview.type = "button";
      preview.textContent = "5 sold";
      preview.title = "Preview the five newest exact comparable eBay UK sales";
      preview.addEventListener("click", () => openFiveSoldPreview(item));
      actions.append(preview);
    }
    if (item.product_type === "CARD") actions.append(ebayInventoryAction(item));
    row.append(actions);
    body.append(row);
  });
  byId("empty-state").classList.toggle("hidden", data.items.length !== 0);
  setInventoryView(state.inventoryView);
  byId("previous-page").disabled = state.offset === 0;
  byId("next-page").disabled = state.offset + PAGE_SIZE >= data.total;
  byId("page-label").textContent = `Page ${Math.floor(state.offset / PAGE_SIZE) + 1} of ${Math.max(1, Math.ceil(data.total / PAGE_SIZE))}`;
  refreshSelectionControls();
}

function renderReadiness(data) {
  state.readiness = data;
  const workTotal = data.for_sale ?? data.total;
  const actionCount = workTotal - data.approved - data.approval_ready;
  byId("total-count").textContent = data.total.toLocaleString("en-GB");
  byId("action-count").textContent = Math.max(0, actionCount).toLocaleString("en-GB");
  byId("ready-count").textContent = data.approval_ready.toLocaleString("en-GB");
  byId("approved-count").textContent = data.approved.toLocaleString("en-GB");
  const personalOption = byId("sale-intent-filter")?.querySelector(
    'option[value="PERSONAL_COLLECTION"]'
  );
  if (personalOption) {
    personalOption.textContent =
      `Personal collection (${Number(data.personal_collection || 0).toLocaleString("en-GB")})`;
  }
  const container = byId("issue-buttons");
  container.replaceChildren();
  Object.entries(ISSUE_LABELS).forEach(([key, label]) => {
    if (!data[key] && state.issue !== key) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `issue-button${state.issue === key ? " active" : ""}`;
    button.append(document.createTextNode(label));
    const count = document.createElement("strong");
    count.textContent = (data[key] ?? 0).toLocaleString("en-GB");
    button.append(count);
    button.addEventListener("click", () => {
      state.issue = state.issue === key ? "" : key;
      state.offset = 0;
      renderReadiness(state.readiness);
      activateSellerView("inventory", true);
      loadInventory();
    });
    container.append(button);
  });
  if (!container.children.length) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = data.total ? "No outstanding stock checks." : "Add your first cards to get started.";
    container.append(note);
  }
}
async function loadReadiness() {
  renderReadiness(await apiRequest("/api/v1/inventory/readiness"));
}

async function loadBrandOptions() {
  const select = byId("brand-filter");
  const current = state.brand;
  const data = await apiRequest("/api/v1/inventory/brands");
  const preferred = ["One Piece", "Pokemon", "Dragon Ball", "Naruto", "Riftbound"];
  const labels = {Pokemon: "Pokémon"};
  const counts = new Map((data.items || []).map((item) => [item.brand, item.count]));
  const discovered = [...counts.keys()].filter((brand) => !preferred.includes(brand)).sort();
  const brands = [...preferred, ...discovered];

  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All brands / TCGs";
  select.append(all);

  brands.forEach((brand) => {
    const option = document.createElement("option");
    option.value = brand;
    const count = counts.get(brand);
    option.textContent = count === undefined
      ? (labels[brand] || brand)
      : `${labels[brand] || brand} (${Number(count).toLocaleString("en-GB")})`;
    select.append(option);
  });

  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  } else {
    state.brand = "";
    select.value = "";
  }
}

async function loadInventory() {
  showMessage("inventory-message", "Loading inventory…");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  if (state.brand) params.set("brand", state.brand);
  if (state.saleIntent) params.set("sale_intent", state.saleIntent);
  if (state.issue) params.set("issue", state.issue);
  try {
    renderInventory(await apiRequest(`/api/v1/inventory?${params}`));
    showMessage("inventory-message");
  } catch (error) {
    showMessage("inventory-message", error.message, "error");
    if (/session|token|expired/i.test(error.message)) logout();
  }
}
async function reloadDashboard(message = "") {
  await Promise.all([loadReadiness(), loadBrandOptions(), loadInventory()]);
  if (message) showMessage("inventory-message", message, "success");
}

function openEditor(item) {
  state.editing = item;
  byId("editor-title").textContent = item.name;
  const productLabel = item.product_type === "SEALED"
    ? "Sealed product"
    : item.product_type === "COLLECTION" ? "Collection" : "Card";
  byId("editor-meta").textContent = [productLabel, item.set_name, item.card_number, item.inventory_code].filter(Boolean).join(" · ");
  byId("edit-cost").value = minorToInput(item.acquisition_cost_minor);
  byId("edit-date").value = item.acquisition_date || "";
  byId("edit-condition").value = item.condition || "";
  byId("edit-language").value = item.language || item.catalogue_language || "";
  byId("edit-location").value = item.location || "";
  byId("edit-price").value = minorToInput(item.store_price_minor);
  byId("edit-grading-company").value = item.grading_company || "";
  byId("edit-grade").value = item.grade || "";
  byId("edit-certificate").value = item.certificate_number || "";
  const workflowLocked = ["RESERVED", "SOLD"].includes(item.status);
  byId("edit-status").value = item.status;
  byId("edit-status").disabled = item.status === "APPROVED" || workflowLocked;
  byId("edit-notes").value = item.notes || "";
  byId("edit-identity").checked = item.identity_confirmed;
  byId("edit-identity").disabled = true;
  byId("approve-button").disabled = item.status === "APPROVED" || workflowLocked;
  byId("approve-button").textContent =
    item.status === "APPROVED" ? "Already approved" :
    item.status === "RESERVED" ? "Reserved for order" :
    item.status === "SOLD" ? "Sold" : "Approve stock";
  const saveButton = byId("editor-form").querySelector('button[type="submit"]');
  if (saveButton) saveButton.disabled = workflowLocked;
  showMessage(
    "editor-message",
    workflowLocked
      ? (item.status === "RESERVED"
          ? "This physical item is reserved for an order. Release or consume its reservation before editing it."
          : "Sold inventory is historical and cannot be edited.")
      : ""
  );
  byId("editor-dialog").showModal();
}
async function saveEditor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (["RESERVED", "SOLD"].includes(state.editing?.status)) {
    showMessage("editor-message", "Reserved or sold inventory cannot be edited here.", "error");
    return;
  }
  setBusy(form, true);
  showMessage("editor-message");
  try {
    const company = emptyToNull(byId("edit-grading-company").value);
    const grade = emptyToNull(byId("edit-grade").value);
    if ((company === null) !== (grade === null)) throw new Error("Grading company and grade must both be filled in, or both left blank.");
    const payload = {
      version: state.editing.version,
      acquisition_cost_minor: inputToMinor(byId("edit-cost").value),
      acquisition_date: byId("edit-date").value || null,
      condition: emptyToNull(byId("edit-condition").value),
      language: emptyToNull(byId("edit-language").value),
      location: emptyToNull(byId("edit-location").value),
      store_price_minor: inputToMinor(byId("edit-price").value),
      grading_company: company, grade,
      certificate_number: emptyToNull(byId("edit-certificate").value),
      notes: byId("edit-notes").value.trim(),
    };
    if (state.editing.status !== "APPROVED") payload.status = byId("edit-status").value;
    await apiRequest(`/api/v1/inventory/${state.editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
    state.selected.delete(state.editing.id);
    byId("editor-dialog").close();
    await reloadDashboard("Changes saved and audit history recorded.");
  } catch (error) { showMessage("editor-message", error.message, "error"); }
  finally { setBusy(form, false); }
}
async function approveEditingItem() {
  showMessage("editor-message", "Checking approval requirements…");
  byId("approve-button").disabled = true;
  try {
    await apiRequest(`/api/v1/inventory/${state.editing.id}/approve`, {
      method: "POST", body: JSON.stringify({ version: state.editing.version }),
    });
    state.selected.delete(state.editing.id);
    byId("editor-dialog").close();
    await reloadDashboard("Stock item approved.");
  } catch (error) {
    showMessage("editor-message", error.message, "error");
    byId("approve-button").disabled = false;
  }
}

function openBulkDialog() {
  const items = [...state.selected.values()];
  byId("bulk-item-count").textContent = `${items.length} selected cards`;
  byId("bulk-total").value = "";
  byId("bulk-date").value = "";
  const list = byId("allocation-list");
  list.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    row.dataset.id = item.id;
    const details = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    const small = document.createElement("small");
    small.textContent = [item.set_name, item.inventory_code].filter(Boolean).join(" · ");
    details.append(strong, small);
    const input = document.createElement("input");
    input.type = "number"; input.min = "0"; input.step = "0.01";
    input.value = minorToInput(item.acquisition_cost_minor) || "0.00";
    input.setAttribute("aria-label", `Allocated cost for ${item.name}`);
    input.addEventListener("input", updateAllocationRemaining);
    row.append(details, input);
    list.append(row);
  });
  showMessage("bulk-message");
  updateAllocationRemaining();
  byId("bulk-dialog").showModal();
}
function allocationRows() {
  return [...byId("allocation-list").querySelectorAll(".allocation-row")];
}
function splitEqually() {
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const rows = allocationRows();
    const base = Math.floor(total / rows.length);
    let remainder = total - (base * rows.length);
    rows.forEach((row) => {
      const amount = base + (remainder > 0 ? 1 : 0);
      if (remainder > 0) remainder -= 1;
      row.querySelector("input").value = (amount / 100).toFixed(2);
    });
    updateAllocationRemaining();
  } catch (error) { showMessage("bulk-message", error.message, "error"); }
}
function updateAllocationRemaining() {
  const summary = byId("bulk-remaining");
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const allocated = allocationRows().reduce((sum, row) => sum + inputToMinor(row.querySelector("input").value, false), 0);
    const remaining = total - allocated;
    summary.textContent = remaining === 0 ? "Fully allocated" : `${money(Math.abs(remaining))} ${remaining > 0 ? "remaining" : "over"}`;
    summary.className = remaining === 0 ? "ok" : "error";
    byId("bulk-save").disabled = remaining !== 0;
  } catch (_error) {
    summary.textContent = "Enter a valid total";
    summary.className = "error";
    byId("bulk-save").disabled = true;
  }
}
async function saveBulkAllocation(event) {
  event.preventDefault();
  setBusy(event.currentTarget, true);
  showMessage("bulk-message");
  try {
    const total = inputToMinor(byId("bulk-total").value, false);
    const items = allocationRows().map((row) => {
      const selected = state.selected.get(row.dataset.id);
      return { inventory_id: selected.id, version: selected.version, acquisition_cost_minor: inputToMinor(row.querySelector("input").value, false) };
    });
    if (items.reduce((sum, item) => sum + item.acquisition_cost_minor, 0) !== total) throw new Error("Every penny of the purchase total must be allocated.");
    await apiRequest("/api/v1/inventory/bulk-cost", {
      method: "POST",
      body: JSON.stringify({ total_cost_minor: total, acquisition_date: byId("bulk-date").value || null, items }),
    });
    state.selected.clear();
    byId("bulk-dialog").close();
    await reloadDashboard(`Acquisition cost allocated across ${items.length} cards.`);
  } catch (error) { showMessage("bulk-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
}

async function openDashboard() {
  try {
    const access = await apiRequest("/api/v1/access/me");
    if (access.access?.access_role === "OWNER" && access.access?.portal === "OWNER_PORTAL") {
      state.routing=true;
      window.location.replace("/owner" + window.location.search + window.location.hash);
      return;
    }
    if (!access.access?.founder_hq_allowed) {
      throw new Error("FOUNDER_HQ_ACCESS_DENIED");
    }
    const me = await apiRequest("/api/v1/me");
    byId("owner-email").textContent = state.session.user?.email || byId("login-email").value || "Founder account";
    byId("owner-name").textContent = me.owner.display_name;
    byId("auth-view").classList.add("hidden");
    byId("dashboard-view").classList.remove("hidden");
    document.body.classList.remove("hub-restoring");
    document.dispatchEvent(new Event("hub-ready"));
    // A data-panel failure must not destroy an authenticated session.
    try { await reloadDashboard(); }
    catch (error) { showMessage("inventory-message", "Some data could not load. Use Refresh to try again. " + error.message, "error"); }
  } catch (error) {
    if ("refreshSession" in error && state.session !== error.refreshSession) return;
    const denied = error.message === "FOUNDER_HQ_ACCESS_DENIED"
      || error.message === "No active owner membership"
      || error.message === "Platform administrator access required";
    const expired = error.sessionExpired || [401,403].includes(error.status);
    if (denied || expired) clearSession();
    document.body.classList.remove("hub-restoring");
    byId("dashboard-view").classList.add("hidden");
    byId("auth-view").classList.remove("hidden");
    showForm("login-form");
    showMessage(
      "login-message",
      denied
        ? "This account is not authorised for Founder HQ."
        : expired ? "Your session has expired. Please sign in again."
          : "We couldn’t open your workspace. Your session is kept; refresh to retry or sign in again.",
      "error"
    );
  }
}
function logout() {
  clearSession();
  state.offset = 0;
  state.selected.clear();
  byId("dashboard-view").classList.add("hidden");
  byId("auth-view").classList.remove("hidden");
  showForm("login-form");
  byId("login-password").value = "";
  document.body.classList.remove("hub-restoring");
  history.replaceState({}, "", "/app");
}
async function initialiseSession() {
  const notice=sessionStorage.getItem("drop-rate-signin-notice");if(notice){showMessage("login-message",notice,"error");sessionStorage.removeItem("drop-rate-signin-notice");}
  if(!window.PullTheoryHubSession.read()?.access_token && !window.location.hash.includes("access_token=")) document.body.classList.remove("hub-restoring");
  try { state.config = await readJson(await fetch("/api/v1/public-config")); }
  catch (_error) { showMessage("login-message", "The dashboard is temporarily unavailable. Please refresh shortly.", "error"); return; }

  loadSocialProviders();

  if (redirectPendingFounderInviteCallback()) return;
  if (parseRecoverySession()) return;
  if (parseOAuthSession()) {
    try {
      await hydrateSessionUser();
      await openDashboard();
    } catch (_error) {
      clearSession();
      showMessage("login-message", "We could not complete social sign in.", "error");
    }
    return;
  }

  try {
    const stored = window.PullTheoryHubSession.read();
    if (stored?.access_token) { state.session = stored; await openDashboard(); }
  } catch (_error) { clearSession(); }
}

byId("login-google").addEventListener("click", () => startOAuth("google"));
byId("login-apple").addEventListener("click", () => startOAuth("apple"));

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setBusy(event.currentTarget, true); showMessage("login-message");
  try {
    const session = await readJson(await fetch("/api/v1/public/owner-session", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({identifier:byId("login-email").value.trim(), password:byId("login-password").value})}));
    saveSession(session); await openDashboard();
  } catch (error) { showMessage("login-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});
byId("show-reset").addEventListener("click", () => { byId("reset-email").value = byId("login-email").value; showForm("request-reset-form"); });
document.querySelector("[data-back-login]").addEventListener("click", () => showForm("login-form"));
byId("request-reset-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setBusy(event.currentTarget, true);
  try {
    await authRequest("/recover", { method: "POST", body: JSON.stringify({ email: byId("reset-email").value.trim(), redirect_to: `${window.location.origin}/` }) });
    showMessage("reset-message", "Recovery email sent. Check your inbox and junk folder.", "success");
  } catch (error) { showMessage("reset-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});
byId("new-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = byId("new-password").value;
  if (password !== byId("confirm-password").value) { showMessage("password-message", "The passwords do not match.", "error"); return; }
  setBusy(event.currentTarget, true);
  try {
    await authRequest("/user", { method: "PUT", headers: { Authorization: `Bearer ${state.session.access_token}` }, body: JSON.stringify({ password }) });
    showMessage("password-message", "Password saved. Opening your inventory…", "success"); await openDashboard();
  } catch (error) { showMessage("password-message", error.message, "error"); }
  finally { setBusy(event.currentTarget, false); }
});

let searchTimer;
byId("search-input").addEventListener("input", (event) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = event.target.value.trim(); state.offset = 0; loadInventory(); }, 350); });
byId("brand-filter").addEventListener("change", (event) => { state.brand = event.target.value; state.offset = 0; loadInventory(); });
byId("status-filter").addEventListener("change", (event) => { state.status = event.target.value; state.offset = 0; loadInventory(); });
byId("sale-intent-filter").addEventListener("change", (event) => { state.saleIntent = event.target.value; state.offset = 0; loadInventory(); });
byId("inventory-view-visual").addEventListener("click", () => setInventoryView("visual"));
byId("inventory-view-table").addEventListener("click", () => setInventoryView("table"));
byId("previous-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadInventory(); });
byId("next-page").addEventListener("click", () => { if (state.offset + PAGE_SIZE < state.total) { state.offset += PAGE_SIZE; loadInventory(); } });
byId("refresh-button").addEventListener("click", () => reloadDashboard());
byId("logout-button").addEventListener("click", logout);
byId("editor-form").addEventListener("submit", saveEditor);
byId("approve-button").addEventListener("click", approveEditingItem);
byId("bulk-cost-button").addEventListener("click", openBulkDialog);
byId("bulk-form").addEventListener("submit", saveBulkAllocation);
byId("equal-split").addEventListener("click", splitEqually);
byId("bulk-total").addEventListener("input", updateAllocationRemaining);
byId("select-page").addEventListener("change", (event) => {
  state.items.forEach((item) => { if (event.target.checked) state.selected.set(item.id, item); else state.selected.delete(item.id); });
  loadInventory();
});
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => byId(button.dataset.close).close()));

async function initialise() {
  try { await initialiseSession(); }
  finally { if(!state.routing)document.body.classList.remove("hub-restoring"); }
}
initialise();
