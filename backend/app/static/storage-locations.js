"use strict";

state.storageLocationFilter = "";
state.storageLocations = new Map();
let editingStorageLocation = null;

function ensureStorageLocationUI() {
  if (byId("storage-locations-section")) return;

  const lotsSection = document.querySelector('[aria-labelledby="lots-heading"]');
  const section = document.createElement("section");
  section.id = "storage-locations-section";
  section.className = "inventory-panel";
  section.setAttribute("aria-labelledby", "storage-locations-heading");
  section.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Physical stock control</p>
        <h2 id="storage-locations-heading">Storage Locations</h2>
        <p class="muted">Give every physical item a registered home such as BINDER-01/PAGE-04 or BOX-03/SLOT-18.</p>
      </div>
      <div class="topbar-actions">
        <button id="refresh-locations-button" class="ghost-button" type="button">↻ Refresh locations</button>
        <button id="new-location-button" class="primary-button compact" type="button">New location</button>
      </div>
    </div>
    <div id="locations-message" class="message panel-message" role="status"></div>
    <div id="storage-locations-list" class="allocation-list"><p class="muted">Loading storage locations…</p></div>`;
  lotsSection.insertAdjacentElement("beforebegin", section);

  const toolbar = document.querySelector(".inventory-panel .toolbar");
  const locationFilter = document.createElement("select");
  locationFilter.id = "location-filter";
  locationFilter.setAttribute("aria-label", "Filter by storage location");
  locationFilter.innerHTML = '<option value="">All locations</option><option value="__UNLOCATED__">Unlocated</option>';
  locationFilter.addEventListener("change", () => {
    state.storageLocationFilter = locationFilter.value;
    state.offset = 0;
    loadInventory();
  });
  toolbar.insertBefore(locationFilter, byId("bulk-cost-button"));

  const assignButton = document.createElement("button");
  assignButton.id = "assign-location-button";
  assignButton.className = "ghost-button";
  assignButton.type = "button";
  assignButton.disabled = true;
  assignButton.textContent = "Assign location";
  assignButton.addEventListener("click", openAssignLocationDialog);
  toolbar.insertBefore(assignButton, byId("bulk-cost-button"));

  const conditionInput = byId("edit-location");
  conditionInput.hidden = true;
  const locationSelect = document.createElement("select");
  locationSelect.id = "edit-storage-location";
  locationSelect.setAttribute("aria-label", "Storage location");
  conditionInput.closest("label").append(locationSelect);

  const locationDialog = document.createElement("dialog");
  locationDialog.id = "storage-location-dialog";
  locationDialog.className = "modal";
  locationDialog.innerHTML = `
    <form id="storage-location-form" class="modal-card">
      <div class="modal-heading">
        <div><p class="eyebrow">Physical stock control</p><h2 id="storage-location-dialog-title">New storage location</h2><p class="muted">Codes are permanent identifiers. Use a simple structure you can physically label.</p></div>
        <button class="icon-button" type="button" data-close="storage-location-dialog" aria-label="Close">×</button>
      </div>
      <div class="form-grid">
        <label>Location code<input id="storage-location-code" maxlength="80" placeholder="e.g. BINDER-01/PAGE-04" required></label>
        <label>Type<select id="storage-location-type"><option value="BINDER">Binder</option><option value="BOX">Box</option><option value="SHELF">Shelf</option><option value="DRAWER">Drawer</option><option value="VAULT">Vault</option><option value="DISPLAY">Display</option><option value="OTHER">Other</option></select></label>
        <label class="full-width">Label<input id="storage-location-label" maxlength="160" placeholder="e.g. Pokémon 151 Binder — Page 4" required></label>
        <label class="full-width">Notes<textarea id="storage-location-notes" maxlength="1000" rows="2"></textarea></label>
        <label id="storage-location-active-label" class="check-field full-width hidden"><input id="storage-location-active" type="checkbox"><span>Location is active</span></label>
      </div>
      <div id="storage-location-form-message" class="message" role="status"></div>
      <div class="modal-actions"><button class="ghost-button" type="button" data-close="storage-location-dialog">Cancel</button><button class="primary-button compact" type="submit">Save location</button></div>
    </form>`;
  document.body.append(locationDialog);

  const assignDialog = document.createElement("dialog");
  assignDialog.id = "assign-location-dialog";
  assignDialog.className = "modal";
  assignDialog.innerHTML = `
    <form id="assign-location-form" class="modal-card">
      <div class="modal-heading">
        <div><p class="eyebrow">Bulk stock move</p><h2>Assign storage location</h2><p id="assign-location-meta" class="muted"></p></div>
        <button class="icon-button" type="button" data-close="assign-location-dialog" aria-label="Close">×</button>
      </div>
      <label>Destination<select id="assign-storage-location" required></select></label>
      <div id="assign-location-message" class="message" role="status"></div>
      <div class="modal-actions"><button class="ghost-button" type="button" data-close="assign-location-dialog">Cancel</button><button class="primary-button compact" type="submit">Assign selected stock</button></div>
    </form>`;
  document.body.append(assignDialog);

  document.querySelectorAll('[data-close="storage-location-dialog"]').forEach((button) => button.addEventListener("click", () => locationDialog.close()));
  document.querySelectorAll('[data-close="assign-location-dialog"]').forEach((button) => button.addEventListener("click", () => assignDialog.close()));
  byId("storage-location-form").addEventListener("submit", saveStorageLocation);
  byId("assign-location-form").addEventListener("submit", assignSelectedLocation);
  byId("new-location-button").addEventListener("click", () => openStorageLocationDialog());
  byId("refresh-locations-button").addEventListener("click", loadStorageLocations);
}

function activeStorageLocations() {
  return [...state.storageLocations.values()].filter((location) => location.active);
}

function populateStorageLocationSelects() {
  const active = activeStorageLocations();
  const filter = byId("location-filter");
  const currentFilter = state.storageLocationFilter;
  filter.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All locations";
  filter.append(all);
  const unlocated = document.createElement("option");
  unlocated.value = "__UNLOCATED__";
  unlocated.textContent = "Unlocated";
  filter.append(unlocated);
  active.forEach((location) => {
    const option = document.createElement("option");
    option.value = location.id;
    option.textContent = `${location.code} — ${location.label}`;
    filter.append(option);
  });
  filter.value = [...filter.options].some((option) => option.value === currentFilter) ? currentFilter : "";
  state.storageLocationFilter = filter.value;

  ["edit-storage-location", "assign-storage-location"].forEach((id) => {
    const select = byId(id);
    const current = select.value;
    select.replaceChildren();
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = id === "edit-storage-location" ? "Unlocated" : "Select destination";
    select.append(blank);
    active.forEach((location) => {
      const option = document.createElement("option");
      option.value = location.id;
      option.textContent = `${location.code} — ${location.label}`;
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  });
}

function renderStorageLocations(data) {
  state.storageLocations = new Map(data.items.map((location) => [location.id, location]));
  populateStorageLocationSelects();
  const container = byId("storage-locations-list");
  container.replaceChildren();

  const unlocatedRow = document.createElement("div");
  unlocatedRow.className = "allocation-row";
  const unlocatedDetails = document.createElement("div");
  const unlocatedTitle = document.createElement("strong");
  unlocatedTitle.textContent = "Unlocated inventory";
  const unlocatedMeta = document.createElement("small");
  unlocatedMeta.textContent = `${data.unlocated_count} item${data.unlocated_count === 1 ? "" : "s"} still need a physical location`;
  unlocatedDetails.append(unlocatedTitle, unlocatedMeta);
  const viewUnlocated = document.createElement("button");
  viewUnlocated.className = "ghost-button";
  viewUnlocated.type = "button";
  viewUnlocated.textContent = "View stock";
  viewUnlocated.addEventListener("click", () => filterInventoryByLocation("__UNLOCATED__"));
  unlocatedRow.append(unlocatedDetails, viewUnlocated);
  container.append(unlocatedRow);

  data.items.forEach((location) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${location.code} — ${location.label}`;
    const meta = document.createElement("small");
    meta.textContent = `${location.location_type} · ${location.item_count} item${location.item_count === 1 ? "" : "s"} · ${location.active ? "Active" : "Inactive"}`;
    details.append(title, meta);
    const actions = document.createElement("div");
    const view = document.createElement("button");
    view.className = "ghost-button";
    view.type = "button";
    view.textContent = "View stock";
    view.disabled = !location.item_count;
    view.addEventListener("click", () => filterInventoryByLocation(location.id));
    const edit = document.createElement("button");
    edit.className = "ghost-button";
    edit.type = "button";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => openStorageLocationDialog(location));
    actions.append(view, edit);
    row.append(details, actions);
    container.append(row);
  });
}

async function loadStorageLocations() {
  if (!state.session?.access_token || byId("dashboard-view").classList.contains("hidden")) return;
  showMessage("locations-message", "Loading storage locations…");
  try {
    const data = await apiRequest("/api/v1/storage-locations?include_inactive=true");
    renderStorageLocations(data);
    showMessage("locations-message");
  } catch (error) {
    showMessage("locations-message", error.message, "error");
  }
}

function filterInventoryByLocation(value) {
  state.storageLocationFilter = value;
  byId("location-filter").value = value;
  state.offset = 0;
  loadInventory();
}

function openStorageLocationDialog(location = null) {
  editingStorageLocation = location;
  byId("storage-location-dialog-title").textContent = location ? "Edit storage location" : "New storage location";
  byId("storage-location-code").value = location?.code || "";
  byId("storage-location-code").disabled = Boolean(location);
  byId("storage-location-label").value = location?.label || "";
  byId("storage-location-type").value = location?.location_type || "BINDER";
  byId("storage-location-notes").value = location?.notes || "";
  byId("storage-location-active-label").classList.toggle("hidden", !location);
  byId("storage-location-active").checked = location?.active ?? true;
  showMessage("storage-location-form-message");
  byId("storage-location-dialog").showModal();
}

async function saveStorageLocation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage("storage-location-form-message");
  try {
    let result;
    if (editingStorageLocation) {
      result = await apiRequest(`/api/v1/storage-locations/${editingStorageLocation.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: editingStorageLocation.version,
          label: byId("storage-location-label").value.trim(),
          location_type: byId("storage-location-type").value,
          active: byId("storage-location-active").checked,
          notes: byId("storage-location-notes").value.trim(),
        }),
      });
    } else {
      result = await apiRequest("/api/v1/storage-locations", {
        method: "POST",
        body: JSON.stringify({
          code: byId("storage-location-code").value.trim(),
          label: byId("storage-location-label").value.trim(),
          location_type: byId("storage-location-type").value,
          notes: byId("storage-location-notes").value.trim(),
        }),
      });
    }
    byId("storage-location-dialog").close();
    await loadStorageLocations();
    showMessage("locations-message", `${result.code} saved.`, "success");
  } catch (error) {
    showMessage("storage-location-form-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

function openAssignLocationDialog() {
  const count = state.selected.size;
  if (!count) return;
  populateStorageLocationSelects();
  byId("assign-location-meta").textContent = `${count} selected inventory item${count === 1 ? "" : "s"}`;
  byId("assign-storage-location").value = "";
  showMessage("assign-location-message");
  byId("assign-location-dialog").showModal();
}

async function assignSelectedLocation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const locationId = byId("assign-storage-location").value;
  if (!locationId) {
    showMessage("assign-location-message", "Choose a destination storage location.", "error");
    return;
  }
  setBusy(form, true);
  try {
    const items = [...state.selected.values()].map((item) => ({ inventory_id: item.id, version: item.version }));
    await apiRequest(`/api/v1/storage-locations/${locationId}/assign`, {
      method: "POST",
      body: JSON.stringify({ items }),
    });
    state.selected.clear();
    byId("assign-location-dialog").close();
    await Promise.all([reloadDashboard(), loadStorageLocations()]);
    showMessage("inventory-message", `${items.length} item${items.length === 1 ? "" : "s"} moved to the selected storage location.`, "success");
  } catch (error) {
    showMessage("assign-location-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

ensureStorageLocationUI();

const baseRefreshSelectionControlsStorage = refreshSelectionControls;
refreshSelectionControls = function refreshSelectionControlsWithLocations() {
  baseRefreshSelectionControlsStorage();
  if (byId("assign-location-button")) byId("assign-location-button").disabled = state.selected.size === 0;
};

const baseOpenEditorStorage = openEditor;
openEditor = function openEditorWithStorageLocation(item) {
  baseOpenEditorStorage(item);
  const select = byId("edit-storage-location");
  select.value = item.storage_location_id || "";
  if (item.storage_location_id && ![...select.options].some((option) => option.value === item.storage_location_id)) {
    const option = document.createElement("option");
    option.value = item.storage_location_id;
    option.textContent = item.storage_location_code || item.location || "Current location";
    select.append(option);
    select.value = item.storage_location_id;
  }
};

const baseRenderInventoryStorage = renderInventory;
renderInventory = function renderInventoryWithStorageLocation(data) {
  baseRenderInventoryStorage(data);
  const rows = [...byId("inventory-body").querySelectorAll("tr")];
  rows.forEach((row, index) => {
    const item = data.items[index];
    const meta = row.querySelector(".card-name small");
    if (item && meta) {
      const location = item.storage_location_code || "Unlocated";
      meta.textContent = [meta.textContent, location].filter(Boolean).join(" · ");
    }
  });
};

loadInventory = async function loadInventoryWithStorageLocation() {
  showMessage("inventory-message", "Loading inventory…");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  if (state.brand) params.set("brand", state.brand);
  if (state.issue) params.set("issue", state.issue);
  if (state.storageLocationFilter === "__UNLOCATED__") params.set("unlocated", "true");
  else if (state.storageLocationFilter) params.set("storage_location_id", state.storageLocationFilter);
  try {
    renderInventory(await apiRequest(`/api/v1/inventory?${params}`));
    showMessage("inventory-message");
  } catch (error) {
    showMessage("inventory-message", error.message, "error");
    if (/session|token|expired/i.test(error.message)) logout();
  }
};

const baseApiRequestStorage = apiRequest;
apiRequest = async function apiRequestWithStorageLocation(path, options = {}, retry = true) {
  if (
    options.method === "PATCH"
    && /^\/api\/v1\/inventory\/[0-9a-f-]+$/i.test(path)
    && options.body
    && state.editing
  ) {
    const payload = JSON.parse(options.body);
    delete payload.location;
    payload.storage_location_id = byId("edit-storage-location")?.value || null;
    options = { ...options, body: JSON.stringify(payload) };
  }
  return baseApiRequestStorage(path, options, retry);
};

const storageDashboardObserver = new MutationObserver(() => {
  if (!byId("dashboard-view").classList.contains("hidden")) loadStorageLocations();
});
storageDashboardObserver.observe(byId("dashboard-view"), { attributes: true, attributeFilter: ["class"] });
