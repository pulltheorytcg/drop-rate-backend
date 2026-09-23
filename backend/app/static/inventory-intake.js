"use strict";

const INTAKE_CARD_CONDITIONS = [
  "Near Mint",
  "Lightly Played",
  "Moderately Played",
  "Heavily Played",
  "Damaged",
];

let intakeSelectedCatalogue = null;
let intakeNewCatalogueMode = false;

function ensureInventoryIntakeUI() {
  if (byId("new-inventory-button")) return;

  const heading = document.querySelector("#dashboard-view .dashboard-content > .page-heading");
  const refresh = byId("refresh-button");
  const actions = document.createElement("div");
  actions.className = "topbar-actions";
  refresh.replaceWith(actions);
  actions.append(refresh);

  const addButton = document.createElement("button");
  addButton.id = "new-inventory-button";
  addButton.className = "primary-button compact";
  addButton.type = "button";
  addButton.textContent = "+ Add inventory";
  actions.insertBefore(addButton, refresh);

  const dialog = document.createElement("dialog");
  dialog.id = "inventory-intake-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <form id="inventory-intake-form" class="modal-card wide">
      <div class="modal-heading">
        <div>
          <p class="eyebrow">Physical stock intake</p>
          <h2>Add inventory</h2>
          <p class="muted">Search the canonical catalogue first. Every physical item receives its own Inventory ID and starts as Draft.</p>
        </div>
        <button class="icon-button" type="button" data-close="inventory-intake-dialog" aria-label="Close">×</button>
      </div>

      <section>
        <p class="eyebrow">1 · Identify the product</p>
        <div class="bulk-controls">
          <label>Catalogue search<input id="intake-catalogue-search" type="search" maxlength="200" placeholder="Card name, set or card number"></label>
          <button id="intake-search-button" class="ghost-button" type="button">Search catalogue</button>
          <button id="intake-new-catalogue-button" class="ghost-button" type="button">Create new identity</button>
        </div>
        <div id="intake-catalogue-message" class="message" role="status"></div>
        <div id="intake-selected-catalogue" class="allocation-list"></div>
        <div id="intake-search-results" class="allocation-list"></div>
      </section>

      <section id="intake-new-catalogue-fields" class="hidden">
        <p class="eyebrow">New canonical identity</p>
        <p class="muted">Use this only when the exact product does not already exist in Drop Rate.</p>
        <div class="form-grid">
          <label>Product type<select id="intake-product-type"><option value="CARD">Card</option><option value="SEALED">Sealed product</option><option value="COLLECTION">Collection</option></select></label>
          <label>Game<input id="intake-game" maxlength="80" placeholder="e.g. Pokemon" required></label>
          <label>Name<input id="intake-name" maxlength="300" required></label>
          <label>Set<input id="intake-set" maxlength="200" required></label>
          <label id="intake-card-number-label">Card number<input id="intake-card-number" maxlength="80" placeholder="e.g. 199/165"></label>
          <label>Variant<input id="intake-variant" maxlength="160" placeholder="e.g. Normal, Reverse Holo"></label>
          <label>Rarity<input id="intake-rarity" maxlength="80"></label>
          <label>Catalogue language<input id="intake-catalogue-language" maxlength="80" placeholder="e.g. English"></label>
        </div>
      </section>

      <hr>
      <section>
        <p class="eyebrow">2 · Physical item</p>
        <div class="form-grid">
          <label>Acquisition cost (£)<input id="intake-cost" type="number" min="0" step="0.01" inputmode="decimal" placeholder="Leave blank if unknown"></label>
          <label>Acquisition date<input id="intake-date" type="date"></label>
          <label id="intake-condition-label">Condition<select id="intake-condition"><option value="">Select condition later</option></select></label>
          <label id="intake-seal-label" class="hidden">Seal status<select id="intake-seal-status"><option value="">Select later</option><option value="SEALED">Sealed</option><option value="UNSEALED">Unsealed</option></select></label>
          <label>Physical language<input id="intake-language" maxlength="80" placeholder="e.g. English"></label>
          <label>Storage location<select id="intake-storage-location"><option value="">Unlocated</option></select></label>
          <label>Store price (£)<input id="intake-price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="Can be added later"></label>
          <label id="intake-grading-company-label">Grading company<input id="intake-grading-company" maxlength="40" placeholder="e.g. PSA"></label>
          <label id="intake-grade-label">Grade<input id="intake-grade" maxlength="40" placeholder="e.g. 10"></label>
          <label id="intake-certificate-label">Certificate number<input id="intake-certificate" maxlength="120"></label>
          <label class="full-width">Notes<textarea id="intake-notes" maxlength="2000" rows="2"></textarea></label>
          <label class="check-field full-width"><input id="intake-identity-confirmed" type="checkbox"><span>I have physically checked this item and confirmed its identity.</span></label>
        </div>
      </section>

      <div id="inventory-intake-message" class="message" role="status"></div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" data-close="inventory-intake-dialog">Cancel</button>
        <button class="primary-button compact" type="submit">Create Draft inventory</button>
      </div>
    </form>`;
  document.body.append(dialog);

  INTAKE_CARD_CONDITIONS.forEach((condition) => {
    const option = document.createElement("option");
    option.value = condition;
    option.textContent = condition;
    byId("intake-condition").append(option);
  });

  addButton.addEventListener("click", openInventoryIntake);
  dialog.querySelectorAll('[data-close="inventory-intake-dialog"]').forEach((button) => button.addEventListener("click", () => dialog.close()));
  byId("intake-search-button").addEventListener("click", searchIntakeCatalogue);
  byId("intake-new-catalogue-button").addEventListener("click", () => setIntakeNewCatalogueMode(!intakeNewCatalogueMode));
  byId("intake-product-type").addEventListener("change", updateIntakePhysicalControls);
  byId("inventory-intake-form").addEventListener("submit", submitInventoryIntake);
  byId("intake-catalogue-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchIntakeCatalogue();
    }
  });
}

function resetInventoryIntake() {
  intakeSelectedCatalogue = null;
  intakeNewCatalogueMode = false;
  byId("inventory-intake-form").reset();
  byId("intake-search-results").replaceChildren();
  byId("intake-selected-catalogue").replaceChildren();
  byId("intake-new-catalogue-fields").classList.add("hidden");
  byId("intake-new-catalogue-button").textContent = "Create new identity";
  showMessage("intake-catalogue-message");
  showMessage("inventory-intake-message");
  populateIntakeStorageLocations();
  updateIntakePhysicalControls();
}

function openInventoryIntake() {
  resetInventoryIntake();
  byId("inventory-intake-dialog").showModal();
}

function populateIntakeStorageLocations() {
  const select = byId("intake-storage-location");
  select.replaceChildren();
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "Unlocated";
  select.append(blank);
  if (!state.storageLocations) return;
  [...state.storageLocations.values()]
    .filter((location) => location.active)
    .sort((a, b) => a.code.localeCompare(b.code))
    .forEach((location) => {
      const option = document.createElement("option");
      option.value = location.id;
      option.textContent = `${location.code} — ${location.label}`;
      select.append(option);
    });
}

function selectedIntakeProductType() {
  if (intakeSelectedCatalogue) return intakeSelectedCatalogue.product_type;
  if (intakeNewCatalogueMode) return byId("intake-product-type").value;
  return "CARD";
}

function updateIntakePhysicalControls() {
  const productType = selectedIntakeProductType();
  const isCard = productType === "CARD";
  byId("intake-condition-label").classList.toggle("hidden", !isCard);
  byId("intake-seal-label").classList.toggle("hidden", isCard);
  byId("intake-grading-company-label").classList.toggle("hidden", !isCard);
  byId("intake-grade-label").classList.toggle("hidden", !isCard);
  byId("intake-certificate-label").classList.toggle("hidden", !isCard);
  byId("intake-card-number-label").classList.toggle("hidden", !isCard);
  byId("intake-card-number").required = isCard && intakeNewCatalogueMode;
  if (isCard) {
    byId("intake-seal-status").value = "";
  } else {
    byId("intake-condition").value = "";
    byId("intake-grading-company").value = "";
    byId("intake-grade").value = "";
    byId("intake-certificate").value = "";
  }
}

function setIntakeNewCatalogueMode(enabled) {
  intakeNewCatalogueMode = enabled;
  intakeSelectedCatalogue = null;
  byId("intake-new-catalogue-fields").classList.toggle("hidden", !enabled);
  byId("intake-new-catalogue-button").textContent = enabled ? "Use catalogue search" : "Create new identity";
  byId("intake-selected-catalogue").replaceChildren();
  if (enabled) {
    byId("intake-search-results").replaceChildren();
    showMessage("intake-catalogue-message", "New catalogue identity mode. Drop Rate will still reuse an exact existing match if one already exists.");
  } else {
    showMessage("intake-catalogue-message", "Search and select an existing catalogue product.");
  }
  updateIntakePhysicalControls();
}

function catalogueResultLabel(item) {
  return [item.game, item.name, item.set_name, item.card_number, item.variant, item.rarity, item.language].filter(Boolean).join(" · ");
}

async function searchIntakeCatalogue() {
  const query = byId("intake-catalogue-search").value.trim();
  if (query.length < 2) {
    showMessage("intake-catalogue-message", "Enter at least 2 characters to search.", "error");
    return;
  }
  setIntakeNewCatalogueMode(false);
  showMessage("intake-catalogue-message", "Searching catalogue…");
  try {
    const data = await apiRequest(`/api/v1/catalogue/search?q=${encodeURIComponent(query)}&limit=20`);
    const container = byId("intake-search-results");
    container.replaceChildren();
    if (!data.items.length) {
      showMessage("intake-catalogue-message", "No matching catalogue product found. Check the search, or create a new identity.");
      return;
    }
    data.items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "allocation-row";
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.name;
      const meta = document.createElement("small");
      meta.textContent = catalogueResultLabel(item);
      details.append(title, meta);
      const choose = document.createElement("button");
      choose.type = "button";
      choose.className = "ghost-button";
      choose.textContent = "Select";
      choose.addEventListener("click", () => selectIntakeCatalogue(item));
      row.append(details, choose);
      container.append(row);
    });
    showMessage("intake-catalogue-message", `${data.items.length} catalogue match${data.items.length === 1 ? "" : "es"} found.`);
  } catch (error) {
    showMessage("intake-catalogue-message", error.message, "error");
  }
}

function selectIntakeCatalogue(item) {
  intakeSelectedCatalogue = item;
  intakeNewCatalogueMode = false;
  byId("intake-new-catalogue-fields").classList.add("hidden");
  byId("intake-search-results").replaceChildren();
  const container = byId("intake-selected-catalogue");
  container.replaceChildren();
  const row = document.createElement("div");
  row.className = "allocation-row";
  const details = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.name;
  const meta = document.createElement("small");
  meta.textContent = catalogueResultLabel(item);
  details.append(title, meta);
  const change = document.createElement("button");
  change.type = "button";
  change.className = "ghost-button";
  change.textContent = "Change";
  change.addEventListener("click", () => {
    intakeSelectedCatalogue = null;
    container.replaceChildren();
    showMessage("intake-catalogue-message", "Search and select the correct catalogue product.");
    updateIntakePhysicalControls();
  });
  row.append(details, change);
  container.append(row);
  showMessage("intake-catalogue-message", "Catalogue identity selected.", "success");
  if (!byId("intake-language").value && item.language) byId("intake-language").value = item.language;
  updateIntakePhysicalControls();
}

function intakeMoney(id) {
  const value = byId(id).value.trim();
  return value ? inputToMinor(value, false) : null;
}

function buildNewCataloguePayload() {
  return {
    product_type: byId("intake-product-type").value,
    game: byId("intake-game").value.trim(),
    name: byId("intake-name").value.trim(),
    set_name: byId("intake-set").value.trim(),
    card_number: emptyToNull(byId("intake-card-number").value),
    variant: byId("intake-variant").value.trim(),
    rarity: byId("intake-rarity").value.trim(),
    language: emptyToNull(byId("intake-catalogue-language").value),
  };
}

async function submitInventoryIntake(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!intakeSelectedCatalogue && !intakeNewCatalogueMode) {
    showMessage("inventory-intake-message", "Select an existing catalogue product or choose Create new identity.", "error");
    return;
  }
  setBusy(form, true);
  showMessage("inventory-intake-message", "Creating Draft inventory…");
  try {
    const isCard = selectedIntakeProductType() === "CARD";
    const payload = {
      catalogue_id: intakeSelectedCatalogue?.id || null,
      new_catalogue: intakeNewCatalogueMode ? buildNewCataloguePayload() : null,
      acquisition_cost_minor: intakeMoney("intake-cost"),
      acquisition_date: byId("intake-date").value || null,
      condition: isCard ? (byId("intake-condition").value || null) : null,
      seal_status: isCard ? null : (byId("intake-seal-status").value || null),
      grading_company: isCard ? emptyToNull(byId("intake-grading-company").value) : null,
      grade: isCard ? emptyToNull(byId("intake-grade").value) : null,
      certificate_number: isCard ? emptyToNull(byId("intake-certificate").value) : null,
      language: emptyToNull(byId("intake-language").value),
      storage_location_id: byId("intake-storage-location").value || null,
      store_price_minor: intakeMoney("intake-price"),
      identity_confirmed: byId("intake-identity-confirmed").checked,
      notes: byId("intake-notes").value.trim(),
    };
    const result = await apiRequest("/api/v1/inventory/intake", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    byId("inventory-intake-dialog").close();
    await Promise.all([reloadDashboard(), loadStorageLocations()]);
    const identityNote = result.catalogue_created
      ? " New catalogue identity created."
      : result.catalogue_reused ? " Existing matching catalogue identity reused." : "";
    showMessage("inventory-message", `${result.inventory.inventory_code} created as Draft.${identityNote}`, "success");
  } catch (error) {
    showMessage("inventory-intake-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

ensureInventoryIntakeUI();
