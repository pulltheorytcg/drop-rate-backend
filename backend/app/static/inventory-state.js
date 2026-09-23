"use strict";

const CARD_CONDITIONS = [
  "Near Mint",
  "Lightly Played",
  "Moderately Played",
  "Heavily Played",
  "Damaged",
];

function ensureInventoryStateControls() {
  if (byId("edit-condition-select")) return;

  const conditionInput = byId("edit-condition");
  const conditionLabel = conditionInput.closest("label");
  conditionInput.hidden = true;

  const conditionSelect = document.createElement("select");
  conditionSelect.id = "edit-condition-select";
  conditionSelect.setAttribute("aria-label", "Card condition");

  const blankCondition = document.createElement("option");
  blankCondition.value = "";
  blankCondition.textContent = "Select card condition";
  conditionSelect.append(blankCondition);

  CARD_CONDITIONS.forEach((condition) => {
    const option = document.createElement("option");
    option.value = condition;
    option.textContent = condition;
    conditionSelect.append(option);
  });

  conditionSelect.addEventListener("change", () => {
    conditionInput.value = conditionSelect.value;
  });
  conditionLabel.append(conditionSelect);

  const sealLabel = document.createElement("label");
  sealLabel.id = "edit-seal-label";
  sealLabel.append(document.createTextNode("Seal status"));

  const sealSelect = document.createElement("select");
  sealSelect.id = "edit-seal-status";
  [
    ["", "Select seal status"],
    ["SEALED", "Sealed"],
    ["UNSEALED", "Unsealed"],
  ].forEach(([value, text]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    sealSelect.append(option);
  });
  sealSelect.addEventListener("change", () => {
    conditionInput.value = sealSelect.value === "SEALED"
      ? "Sealed"
      : sealSelect.value === "UNSEALED" ? "Unsealed" : "";
  });
  sealLabel.append(sealSelect);
  conditionLabel.insertAdjacentElement("afterend", sealLabel);
}

async function loadInventoryState(items) {
  if (!items.length || !state.session?.access_token) return;
  const ids = items.map((item) => item.id).join(",");
  const data = await apiRequest(`/api/v1/inventory/state?ids=${encodeURIComponent(ids)}`);
  const byInventoryId = new Map(data.items.map((item) => [item.id, item]));

  items.forEach((item) => {
    const extra = byInventoryId.get(item.id);
    if (!extra) return;
    Object.assign(item, extra);
    const stored = state.items.get(item.id);
    if (stored) Object.assign(stored, extra);
    const selected = state.selected.get(item.id);
    if (selected) Object.assign(selected, extra);
  });

  const rows = [...byId("inventory-body").querySelectorAll("tr")];
  rows.forEach((row, index) => {
    const item = items[index];
    if (!item || !row.children[3]) return;
    const display = item.product_type === "CARD"
      ? (item.grade ? `${item.grading_company} ${item.grade}` : (item.condition || "—"))
      : (item.seal_status === "SEALED" ? "Sealed" : item.seal_status === "UNSEALED" ? "Unsealed" : "—");
    row.children[3].textContent = display;
  });
}

function configureInventoryStateEditor(item) {
  ensureInventoryStateControls();
  const conditionInput = byId("edit-condition");
  const conditionSelect = byId("edit-condition-select");
  const conditionLabel = conditionInput.closest("label");
  const sealLabel = byId("edit-seal-label");
  const sealSelect = byId("edit-seal-status");

  if (item.product_type === "CARD") {
    conditionLabel.hidden = false;
    conditionSelect.value = CARD_CONDITIONS.includes(item.condition) ? item.condition : "";
    conditionInput.value = conditionSelect.value;
    sealLabel.hidden = true;
    sealSelect.value = "";
  } else {
    conditionLabel.hidden = true;
    sealLabel.hidden = false;
    sealSelect.value = item.seal_status || "";
    conditionInput.value = sealSelect.value === "SEALED"
      ? "Sealed"
      : sealSelect.value === "UNSEALED" ? "Unsealed" : "";
  }
}

ensureInventoryStateControls();

const baseRenderInventory = renderInventory;
renderInventory = function renderInventoryWithState(data) {
  baseRenderInventory(data);
  loadInventoryState(data.items).catch((error) => {
    showMessage("inventory-message", error.message, "error");
  });
};

const baseOpenEditor = openEditor;
openEditor = function openEditorWithState(item) {
  baseOpenEditor(item);
  configureInventoryStateEditor(item);
  if (item.seal_status === undefined) {
    loadInventoryState([item])
      .then(() => configureInventoryStateEditor(item))
      .catch((error) => showMessage("editor-message", error.message, "error"));
  }
};

const baseApiRequest = apiRequest;
apiRequest = async function apiRequestWithInventoryState(path, options = {}, retry = true) {
  if (
    options.method === "PATCH"
    && /^\/api\/v1\/inventory\/[0-9a-f-]+$/i.test(path)
    && options.body
    && state.editing
  ) {
    const payload = JSON.parse(options.body);
    if (state.editing.product_type === "CARD") {
      const selectedCondition = byId("edit-condition-select").value;
      payload.condition = selectedCondition || null;
      payload.seal_status = null;
    } else {
      const sealStatus = byId("edit-seal-status").value || null;
      payload.seal_status = sealStatus;
      payload.condition = sealStatus === "SEALED"
        ? "Sealed"
        : sealStatus === "UNSEALED" ? "Unsealed" : null;
    }
    options = { ...options, body: JSON.stringify(payload) };
  }
  return baseApiRequest(path, options, retry);
};
