"use strict";

state.identityReview = {
  brand: "",
  search: "",
  onlyUnconfirmed: true,
  offset: 0,
  limit: 50,
  total: 0,
  current: null,
};

function identityReviewView() {
  return sellerView("verification");
}

function ensureIdentityReviewUI() {
  const view = identityReviewView();
  if (!view || byId("identity-review-panel")) return;

  const panel = document.createElement("section");
  panel.id = "identity-review-panel";
  panel.className = "inventory-panel";
  panel.innerHTML = `
    <div class="toolbar identity-review-toolbar">
      <label class="search-box"><span>⌕</span><input id="identity-search" type="search" placeholder="Search card, set or collector number…"></label>
      <select id="identity-brand-filter" aria-label="Filter identity groups by brand"><option value="">All brands / TCGs</option></select>
      <label class="identity-toggle"><input id="identity-unconfirmed-only" type="checkbox" checked> Needs verification only</label>
      <button id="identity-refresh" class="ghost-button" type="button">↻ Refresh</button>
    </div>
    <div id="identity-review-message" class="message panel-message" role="status"></div>
    <div id="identity-review-list" class="allocation-list"></div>
    <div class="pagination">
      <button id="identity-previous" class="ghost-button" type="button">← Previous</button>
      <span id="identity-page-label">Page 1</span>
      <button id="identity-next" class="ghost-button" type="button">Next →</button>
    </div>`;
  view.append(panel);

  const dialog = document.createElement("dialog");
  dialog.id = "identity-review-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <div class="modal-card wide">
      <div class="modal-heading">
        <div>
          <p class="eyebrow">Canonical identity check</p>
          <h2 id="identity-dialog-title">Verify physical copies</h2>
          <p id="identity-dialog-meta" class="muted"></p>
        </div>
        <button id="identity-dialog-close" class="icon-button" type="button" aria-label="Close">×</button>
      </div>
      <div class="identity-review-controls">
        <button id="identity-select-unconfirmed" class="ghost-button" type="button">Select all unconfirmed</button>
        <button id="identity-select-confirmed" class="ghost-button" type="button">Select confirmed</button>
        <button id="identity-clear-selection" class="ghost-button" type="button">Clear selection</button>
      </div>
      <div id="identity-copy-list" class="allocation-list"></div>
      <div class="form-grid identity-review-form">
        <label>Optional storage location<select id="identity-storage-location"><option value="">Keep current locations</option></select></label>
        <label>Verified language<select id="identity-language"><option value="">Use current / canonical language</option><option value="English">English (EN)</option><option value="Japanese">Japanese (JP)</option></select></label>
        <label class="full-width">Notes / correction reason<textarea id="identity-notes" maxlength="1000" rows="2" placeholder="Optional when confirming. Required when revoking a previous confirmation."></textarea></label>
      </div>
      <div id="identity-dialog-message" class="message" role="status"></div>
      <div class="modal-actions">
        <button id="identity-revoke" class="ghost-button" type="button" disabled>Mark selected as needs review</button>
        <button id="identity-confirm" class="primary-button compact" type="button" disabled>Confirm selected copies</button>
      </div>
    </div>`;
  document.body.append(dialog);

  let searchTimer;
  byId("identity-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.identityReview.search = event.target.value.trim();
      state.identityReview.offset = 0;
      loadIdentityReviewGroups();
    }, 300);
  });
  byId("identity-brand-filter").addEventListener("change", (event) => {
    state.identityReview.brand = event.target.value;
    state.identityReview.offset = 0;
    loadIdentityReviewGroups();
  });
  byId("identity-unconfirmed-only").addEventListener("change", (event) => {
    state.identityReview.onlyUnconfirmed = event.target.checked;
    state.identityReview.offset = 0;
    loadIdentityReviewGroups();
  });
  byId("identity-refresh").addEventListener("click", () => loadIdentityReviewGroups());
  byId("identity-previous").addEventListener("click", () => {
    state.identityReview.offset = Math.max(0, state.identityReview.offset - state.identityReview.limit);
    loadIdentityReviewGroups();
  });
  byId("identity-next").addEventListener("click", () => {
    if (state.identityReview.offset + state.identityReview.limit < state.identityReview.total) {
      state.identityReview.offset += state.identityReview.limit;
      loadIdentityReviewGroups();
    }
  });
  byId("identity-dialog-close").addEventListener("click", () => dialog.close());
  byId("identity-select-unconfirmed").addEventListener("click", () => setIdentitySelection("unconfirmed"));
  byId("identity-select-confirmed").addEventListener("click", () => setIdentitySelection("confirmed"));
  byId("identity-clear-selection").addEventListener("click", () => setIdentitySelection("none"));
  byId("identity-confirm").addEventListener("click", confirmSelectedIdentityCopies);
  byId("identity-revoke").addEventListener("click", revokeSelectedIdentityCopies);
}

async function populateIdentityBrandFilter() {
  const select = byId("identity-brand-filter");
  if (!select) return;
  const current = state.identityReview.brand;
  const data = await apiRequest("/api/v1/inventory/brands");
  const preferred = ["One Piece", "Pokemon", "Dragon Ball", "Naruto", "Riftbound"];
  const labels = {Pokemon: "Pokémon"};
  const counts = new Map((data.items || []).map((item) => [item.brand, item.count]));
  const discovered = [...counts.keys()].filter((brand) => !preferred.includes(brand)).sort();

  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All brands / TCGs";
  select.append(all);

  [...preferred, ...discovered].forEach((brand) => {
    const option = document.createElement("option");
    option.value = brand;
    const count = counts.get(brand);
    option.textContent = count === undefined
      ? (labels[brand] || brand)
      : `${labels[brand] || brand} (${Number(count).toLocaleString("en-GB")})`;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function renderIdentityReviewGroups(data) {
  state.identityReview.total = data.total_groups || 0;
  const list = byId("identity-review-list");
  list.replaceChildren();

  (data.items || []).forEach((group) => {
    const row = document.createElement("div");
    row.className = "allocation-row identity-group-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = group.name;
    const meta = document.createElement("small");
    meta.textContent = [
      group.brand,
      group.game !== group.brand ? group.game : null,
      group.set_name,
      group.card_number,
      group.variant,
      group.rarity,
    ].filter(Boolean).join(" · ");
    const progress = document.createElement("small");
    progress.textContent = `${group.confirmed_copies}/${group.active_copies} confirmed · ${group.located_copies}/${group.active_copies} located`;
    details.append(title, meta, progress);

    const actions = document.createElement("div");
    actions.className = "identity-group-actions";
    const status = document.createElement("span");
    status.className = group.unconfirmed_copies ? "pill inspection" : "pill approved";
    status.textContent = group.unconfirmed_copies
      ? `${group.unconfirmed_copies} to verify`
      : "Verified";
    const review = document.createElement("button");
    review.type = "button";
    review.className = "ghost-button";
    review.textContent = "Review copies";
    review.addEventListener("click", () => openIdentityReviewGroup(group.catalogue_id));
    actions.append(status, review);
    row.append(details, actions);
    list.append(row);
  });

  if (!(data.items || []).length) {
    const empty = document.createElement("p");
    empty.className = "muted identity-empty";
    empty.textContent = state.identityReview.onlyUnconfirmed
      ? "No identity groups currently need verification for these filters."
      : "No identity groups match these filters.";
    list.append(empty);
  }

  const page = Math.floor(state.identityReview.offset / state.identityReview.limit) + 1;
  const pages = Math.max(1, Math.ceil(state.identityReview.total / state.identityReview.limit));
  byId("identity-page-label").textContent = `Page ${page} of ${pages}`;
  byId("identity-previous").disabled = state.identityReview.offset === 0;
  byId("identity-next").disabled =
    state.identityReview.offset + state.identityReview.limit >= state.identityReview.total;
}

async function loadIdentityReviewGroups() {
  ensureIdentityReviewUI();
  if (!state.session?.access_token || !byId("identity-review-list")) return;
  showMessage("identity-review-message", "Loading verification queue…");
  const params = new URLSearchParams({
    limit: String(state.identityReview.limit),
    offset: String(state.identityReview.offset),
    only_unconfirmed: String(state.identityReview.onlyUnconfirmed),
  });
  if (state.identityReview.brand) params.set("brand", state.identityReview.brand);
  if (state.identityReview.search) params.set("search", state.identityReview.search);

  try {
    const [data] = await Promise.all([
      apiRequest(`/api/v1/identity-review?${params}`),
      populateIdentityBrandFilter(),
    ]);
    renderIdentityReviewGroups(data);
    showMessage("identity-review-message");
  } catch (error) {
    showMessage("identity-review-message", error.message, "error");
  }
}

async function populateIdentityStorageLocations() {
  const select = byId("identity-storage-location");
  const data = await apiRequest("/api/v1/storage-locations?include_inactive=false");
  select.replaceChildren();
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "Keep current locations";
  select.append(blank);
  (data.items || []).filter((item) => item.active).forEach((location) => {
    const option = document.createElement("option");
    option.value = location.id;
    option.textContent = `${location.code} — ${location.label}`;
    select.append(option);
  });
}

function identityPhysicalState(item) {
  if (item.grading_company && item.grade) {
    return `${item.grading_company} ${item.grade}${item.certificate_number ? ` · cert ${item.certificate_number}` : ""}`;
  }
  if (item.condition) return item.condition;
  if (item.seal_status) return item.seal_status === "SEALED" ? "Sealed" : "Unsealed";
  return "Physical state incomplete";
}

function selectedIdentityItems() {
  const current = state.identityReview.current;
  if (!current) return [];
  const selectedIds = new Set(
    [...byId("identity-copy-list").querySelectorAll('input[type="checkbox"]:checked')]
      .map((input) => input.value)
  );
  return current.items.filter((item) => selectedIds.has(item.id));
}

function refreshIdentityReviewActions() {
  const selected = selectedIdentityItems();
  const allUnconfirmed = selected.length > 0 && selected.every((item) => !item.identity_confirmed);
  const allConfirmed = selected.length > 0 && selected.every((item) => item.identity_confirmed);
  byId("identity-confirm").disabled = !allUnconfirmed;
  byId("identity-revoke").disabled = !allConfirmed;
  byId("identity-storage-location").disabled = !allUnconfirmed;
  byId("identity-language").disabled = !allUnconfirmed;
}

function renderIdentityCopies(data) {
  state.identityReview.current = data;
  const catalogue = data.catalogue;
  byId("identity-dialog-title").textContent = catalogue.name;
  byId("identity-dialog-meta").textContent = [
    catalogue.brand,
    catalogue.game !== catalogue.brand ? catalogue.game : null,
    catalogue.set_name,
    catalogue.card_number,
    catalogue.variant,
    catalogue.rarity,
    catalogue.catalogue_language,
  ].filter(Boolean).join(" · ");

  const list = byId("identity-copy-list");
  list.replaceChildren();
  data.items.forEach((item) => {
    const row = document.createElement("label");
    row.className = "allocation-row identity-copy-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.inventory_code;
    const physical = document.createElement("small");
    physical.textContent = [
      identityPhysicalState(item),
      item.language ? `Language: ${item.language}` : "Language not verified",
    ].join(" · ");
    const location = document.createElement("small");
    location.textContent = item.storage_location_code
      ? `${item.storage_location_code} — ${item.storage_location_label || ""}`
      : "Unlocated";
    details.append(title, physical, location);

    const controls = document.createElement("div");
    controls.className = "identity-copy-controls";
    const stateLabel = document.createElement("span");
    stateLabel.className = item.identity_confirmed ? "pill approved" : "pill inspection";
    stateLabel.textContent = item.identity_confirmed ? "Confirmed" : "Needs verification";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = item.id;
    checkbox.setAttribute("aria-label", `Select ${item.inventory_code}`);
    checkbox.addEventListener("change", refreshIdentityReviewActions);
    controls.append(stateLabel, checkbox);
    row.append(details, controls);
    list.append(row);
  });

  byId("identity-notes").value = "";
  byId("identity-storage-location").value = "";
  byId("identity-language").value = "";
  const languageBlank = byId("identity-language").options[0];
  languageBlank.textContent = catalogue.catalogue_language
    ? `Use current / canonical language (${catalogue.catalogue_language})`
    : "Keep current language";
  refreshIdentityReviewActions();
}

async function openIdentityReviewGroup(catalogueId) {
  showMessage("identity-dialog-message", "Loading physical copies…");
  try {
    const [data] = await Promise.all([
      apiRequest(`/api/v1/identity-review/${catalogueId}`),
      populateIdentityStorageLocations(),
    ]);
    renderIdentityCopies(data);
    showMessage("identity-dialog-message");
    byId("identity-review-dialog").showModal();
  } catch (error) {
    showMessage("identity-review-message", error.message, "error");
  }
}

function setIdentitySelection(mode) {
  const current = state.identityReview.current;
  if (!current) return;
  const wanted = new Set(
    current.items
      .filter((item) => mode === "unconfirmed" ? !item.identity_confirmed : mode === "confirmed" ? item.identity_confirmed : false)
      .map((item) => item.id)
  );
  byId("identity-copy-list").querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.checked = wanted.has(input.value);
  });
  refreshIdentityReviewActions();
}

async function refreshIdentityAfterMutation() {
  const catalogueId = state.identityReview.current?.catalogue?.catalogue_id;
  await Promise.all([
    loadIdentityReviewGroups(),
    loadReadiness(),
    loadInventory(),
    typeof loadStorageLocations === "function" ? loadStorageLocations() : Promise.resolve(),
  ]);
  if (catalogueId && byId("identity-review-dialog").open) {
    const data = await apiRequest(`/api/v1/identity-review/${catalogueId}`);
    renderIdentityCopies(data);
  }
}

async function confirmSelectedIdentityCopies() {
  const selected = selectedIdentityItems();
  if (!selected.length || selected.some((item) => item.identity_confirmed)) return;
  const catalogueId = state.identityReview.current.catalogue.catalogue_id;
  byId("identity-confirm").disabled = true;
  showMessage("identity-dialog-message", "Confirming physical identity…");
  try {
    const result = await apiRequest(`/api/v1/identity-review/${catalogueId}/confirm`, {
      method: "POST",
      body: JSON.stringify({
        items: selected.map((item) => ({inventory_id: item.id, version: item.version})),
        storage_location_id: byId("identity-storage-location").value || null,
        language: byId("identity-language").value || null,
        notes: byId("identity-notes").value.trim(),
      }),
    });
    await refreshIdentityAfterMutation();
    showMessage("identity-dialog-message", `${result.confirmed_count} physical cop${result.confirmed_count === 1 ? "y" : "ies"} confirmed with audit evidence.`, "success");
  } catch (error) {
    showMessage("identity-dialog-message", error.message, "error");
    refreshIdentityReviewActions();
  }
}

async function revokeSelectedIdentityCopies() {
  const selected = selectedIdentityItems();
  if (!selected.length || selected.some((item) => !item.identity_confirmed)) return;
  const reason = byId("identity-notes").value.trim();
  if (!reason) {
    showMessage("identity-dialog-message", "Enter a correction reason before revoking identity confirmation.", "error");
    return;
  }
  const catalogueId = state.identityReview.current.catalogue.catalogue_id;
  byId("identity-revoke").disabled = true;
  showMessage("identity-dialog-message", "Revoking confirmation and returning copies to review…");
  try {
    const result = await apiRequest(`/api/v1/identity-review/${catalogueId}/revoke`, {
      method: "POST",
      body: JSON.stringify({
        items: selected.map((item) => ({inventory_id: item.id, version: item.version})),
        reason,
      }),
    });
    await refreshIdentityAfterMutation();
    showMessage("identity-dialog-message", `${result.revoked_count} cop${result.revoked_count === 1 ? "y" : "ies"} returned to identity review.`, "success");
  } catch (error) {
    showMessage("identity-dialog-message", error.message, "error");
    refreshIdentityReviewActions();
  }
}

ensureIdentityReviewUI();

const baseActivateSellerViewIdentity = activateSellerView;
activateSellerView = function activateSellerViewWithIdentity(name, updateHash = false) {
  const result = baseActivateSellerViewIdentity(name, updateHash);
  if (name === "verification") loadIdentityReviewGroups();
  return result;
};

if (identityReviewView() && !identityReviewView().classList.contains("hidden")) {
  loadIdentityReviewGroups();
}
