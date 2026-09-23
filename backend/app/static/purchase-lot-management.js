"use strict";

let managedLot = null;

function ensureLotManagementDialog() {
  if (byId("lot-manage-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "lot-manage-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <form id="lot-manage-form" class="modal-card wide">
      <div class="modal-heading">
        <div><p class="eyebrow">Purchase lot</p><h2 id="lot-manage-title">Manage purchase lot</h2><p id="lot-manage-meta" class="muted"></p></div>
        <button class="icon-button" type="button" data-close="lot-manage-dialog" aria-label="Close">×</button>
      </div>
      <div class="form-grid">
        <label class="full-width">Description<input id="manage-description" maxlength="200" required></label>
        <label>Source / seller<input id="manage-source" maxlength="160"></label>
        <label>Purchase date<input id="manage-date" type="date"></label>
        <label>Purchase price (£)<input id="manage-price" type="number" min="0" step="0.01" required></label>
        <label>Fees (£)<input id="manage-fees" type="number" min="0" step="0.01" required></label>
        <label>Shipping (£)<input id="manage-shipping" type="number" min="0" step="0.01" required></label>
        <label>Allocation method<select id="manage-method"><option value="MANUAL">Manual</option><option value="EQUAL">Equal split</option></select></label>
        <label class="full-width">Notes<textarea id="manage-notes" maxlength="2000" rows="2"></textarea></label>
      </div>
      <div class="allocation-summary"><span id="manage-count"></span><strong id="manage-summary"></strong></div>
      <div id="lot-manage-message" class="message" role="status"></div>
      <div class="modal-actions"><button class="ghost-button" type="button" data-close="lot-manage-dialog">Close</button><button class="primary-button compact" type="submit">Save lot details</button></div>
      <hr>
      <div class="modal-heading"><div><p class="eyebrow">Allocated inventory</p><h3>Items in this lot</h3></div></div>
      <div id="manage-items" class="allocation-list"></div>
      <hr>
      <div class="modal-heading"><div><p class="eyebrow">Add inventory</p><h3>Add selected items</h3><p class="muted">Select inventory in the main table, then allocate part or all of this lot's remaining cost.</p></div></div>
      <button id="manage-equal-split" class="ghost-button" type="button">Split remaining cost equally</button>
      <div id="manage-add-items" class="allocation-list"></div>
      <div class="allocation-summary"><span id="manage-add-count"></span><strong id="manage-add-summary"></strong></div>
      <div class="modal-actions"><button id="manage-add-button" class="primary-button compact" type="button">Add selected to lot</button></div>
    </form>`;
  document.body.append(dialog);
  dialog.querySelectorAll("[data-close='lot-manage-dialog']").forEach((button) => button.addEventListener("click", () => dialog.close()));
  byId("lot-manage-form").addEventListener("submit", saveManagedLot);
  byId("manage-equal-split").addEventListener("click", splitManagedRemaining);
  byId("manage-add-button").addEventListener("click", addSelectedToManagedLot);
}

function minorValue(id) {
  return inputToMinor(byId(id).value, false);
}

function eligibleSelectedItems() {
  return [...state.selected.values()].filter((item) => !item.purchase_lot_id);
}

function renderManagedLot() {
  const { lot, items } = managedLot;
  byId("lot-manage-title").textContent = lot.description;
  byId("lot-manage-meta").textContent = [lot.lot_code, lot.source, lot.purchase_date].filter(Boolean).join(" · ");
  byId("manage-description").value = lot.description;
  byId("manage-source").value = lot.source || "";
  byId("manage-date").value = lot.purchase_date || "";
  byId("manage-price").value = minorToInput(lot.purchase_price_minor);
  byId("manage-fees").value = minorToInput(lot.fees_minor);
  byId("manage-shipping").value = minorToInput(lot.shipping_minor);
  byId("manage-method").value = ["MANUAL", "EQUAL"].includes(lot.allocation_method) ? lot.allocation_method : "MANUAL";
  byId("manage-notes").value = lot.notes || "";
  byId("manage-count").textContent = `${lot.item_count} item${lot.item_count === 1 ? "" : "s"}`;
  byId("manage-summary").textContent = lot.remaining_cost_minor === 0
    ? `${money(lot.allocated_cost_minor, lot.currency)} fully allocated`
    : `${money(lot.allocated_cost_minor, lot.currency)} allocated · ${money(lot.remaining_cost_minor, lot.currency)} remaining`;

  const list = byId("manage-items");
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No inventory has been allocated to this lot yet.";
    list.append(empty);
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = [item.inventory_code, item.set_name, item.product_type, item.status].filter(Boolean).join(" · ");
    details.append(title, meta);
    const actions = document.createElement("div");
    const amount = document.createElement("strong");
    amount.textContent = money(item.acquisition_cost_minor, item.currency);
    const detach = document.createElement("button");
    detach.type = "button";
    detach.className = "ghost-button";
    detach.textContent = "Detach";
    detach.addEventListener("click", () => detachManagedItem(item));
    actions.append(amount, detach);
    row.append(details, actions);
    list.append(row);
  });

  renderManagedAddItems();
}

function renderManagedAddItems() {
  const selected = eligibleSelectedItems();
  const list = byId("manage-add-items");
  list.replaceChildren();
  selected.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    row.dataset.id = item.id;
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = [item.inventory_code, item.set_name].filter(Boolean).join(" · ");
    details.append(title, meta);
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "0.01";
    input.placeholder = "Allocated cost";
    input.value = minorToInput(item.acquisition_cost_minor);
    input.addEventListener("input", updateManagedAddSummary);
    row.append(details, input);
    list.append(row);
  });
  byId("manage-add-count").textContent = `${selected.length} selected item${selected.length === 1 ? "" : "s"}`;
  byId("manage-add-button").disabled = selected.length === 0;
  updateManagedAddSummary();
}

function managedAddRows() {
  return [...byId("manage-add-items").querySelectorAll(".allocation-row")];
}

function updateManagedAddSummary() {
  if (!managedLot) return;
  const rows = managedAddRows();
  if (!rows.length) {
    byId("manage-add-summary").textContent = "Select unallocated inventory first";
    return;
  }
  let allocated = 0;
  let incomplete = false;
  rows.forEach((row) => {
    const value = row.querySelector("input").value.trim();
    if (!value) { incomplete = true; return; }
    try { allocated += inputToMinor(value, false); } catch (_error) { incomplete = true; }
  });
  if (incomplete) {
    byId("manage-add-summary").textContent = "Enter an allocated cost for every selected item";
  } else if (allocated > managedLot.lot.remaining_cost_minor) {
    byId("manage-add-summary").textContent = `${money(allocated - managedLot.lot.remaining_cost_minor)} over remaining cost`;
  } else {
    byId("manage-add-summary").textContent = `${money(allocated)} to allocate · ${money(managedLot.lot.remaining_cost_minor - allocated)} will remain`;
  }
}

function splitManagedRemaining() {
  const rows = managedAddRows();
  if (!rows.length) return;
  const amount = managedLot.lot.remaining_cost_minor;
  const base = Math.floor(amount / rows.length);
  let remainder = amount - (base * rows.length);
  rows.forEach((row) => {
    const value = base + (remainder > 0 ? 1 : 0);
    if (remainder > 0) remainder -= 1;
    row.querySelector("input").value = (value / 100).toFixed(2);
  });
  updateManagedAddSummary();
}

async function openManagedLot(lotId) {
  ensureLotManagementDialog();
  showMessage("lots-message", "Loading purchase lot…");
  try {
    managedLot = await apiRequest(`/api/v1/purchase-lots/${lotId}`);
    renderManagedLot();
    showMessage("lot-manage-message");
    byId("lot-manage-dialog").showModal();
    showMessage("lots-message");
  } catch (error) {
    showMessage("lots-message", error.message, "error");
  }
}

async function refreshManagedLot(message = "") {
  const lotId = managedLot.lot.id;
  managedLot = await apiRequest(`/api/v1/purchase-lots/${lotId}`);
  renderManagedLot();
  if (message) showMessage("lot-manage-message", message, "success");
}

async function saveManagedLot(event) {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage("lot-manage-message");
  try {
    const payload = {
      version: managedLot.lot.version,
      description: byId("manage-description").value.trim(),
      source: emptyToNull(byId("manage-source").value),
      purchase_date: byId("manage-date").value || null,
      purchase_price_minor: minorValue("manage-price"),
      fees_minor: minorValue("manage-fees"),
      shipping_minor: minorValue("manage-shipping"),
      allocation_method: byId("manage-method").value,
      notes: byId("manage-notes").value.trim(),
    };
    managedLot = await apiRequest(`/api/v1/purchase-lots/${managedLot.lot.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    renderManagedLot();
    await Promise.all([loadPurchaseLots(), reloadDashboard()]);
    showMessage("lot-manage-message", "Purchase lot updated and audit history recorded.", "success");
  } catch (error) {
    showMessage("lot-manage-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

async function detachManagedItem(item) {
  showMessage("lot-manage-message", `Detaching ${item.inventory_code}…`);
  try {
    await apiRequest(`/api/v1/purchase-lots/${managedLot.lot.id}/items/${item.id}/detach`, {
      method: "POST",
      body: JSON.stringify({ version: managedLot.lot.version, inventory_version: item.version }),
    });
    state.selected.delete(item.id);
    await Promise.all([refreshManagedLot("Item detached. Its acquisition cost is now unknown."), loadPurchaseLots(), reloadDashboard()]);
  } catch (error) {
    showMessage("lot-manage-message", error.message, "error");
  }
}

async function addSelectedToManagedLot() {
  const rows = managedAddRows();
  if (!rows.length) return;
  try {
    const items = rows.map((row) => {
      const item = state.selected.get(row.dataset.id);
      const raw = row.querySelector("input").value.trim();
      if (!raw) throw new Error(`Enter an allocated cost for ${item.name}.`);
      return { inventory_id: item.id, version: item.version, acquisition_cost_minor: inputToMinor(raw, false) };
    });
    const proposed = items.reduce((sum, item) => sum + item.acquisition_cost_minor, 0);
    if (proposed > managedLot.lot.remaining_cost_minor) throw new Error("Allocation exceeds the remaining purchase lot cost.");
    await apiRequest(`/api/v1/purchase-lots/${managedLot.lot.id}/allocate`, {
      method: "POST",
      body: JSON.stringify({ version: managedLot.lot.version, items }),
    });
    items.forEach((item) => state.selected.delete(item.inventory_id));
    await Promise.all([refreshManagedLot(`${items.length} item${items.length === 1 ? "" : "s"} added to the lot.`), loadPurchaseLots(), reloadDashboard()]);
  } catch (error) {
    showMessage("lot-manage-message", error.message, "error");
  }
}

ensureLotManagementDialog();

const baseRenderPurchaseLotsManagement = renderPurchaseLots;
renderPurchaseLots = function renderPurchaseLotsWithManagement(data) {
  baseRenderPurchaseLotsManagement(data);
  const rows = [...byId("purchase-lots-list").querySelectorAll(".allocation-row")];
  rows.forEach((row, index) => {
    const lot = data.items[index];
    if (!lot) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = "Open";
    button.addEventListener("click", () => openManagedLot(lot.id));
    row.append(button);
  });
};

const baseOpenEditorLotManagement = openEditor;
openEditor = function openEditorWithLotManagement(item) {
  baseOpenEditorLotManagement(item);
  if (item.purchase_lot_code) {
    byId("editor-meta").textContent += ` · ${item.purchase_lot_code}`;
  }
};
