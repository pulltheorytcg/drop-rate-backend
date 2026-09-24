"use strict";

const CARD_CONDITIONS = [
  "Near Mint",
  "Lightly Played",
  "Moderately Played",
  "Heavily Played",
  "Damaged",
];

function gradingLabels() {
  return {
    company: byId("edit-grading-company").closest("label"),
    grade: byId("edit-grade").closest("label"),
    certificate: byId("edit-certificate").closest("label"),
  };
}

function configureCardEditorMode(mode, {clearInactive = false} = {}) {
  const conditionInput = byId("edit-condition");
  const conditionSelect = byId("edit-condition-select");
  const conditionLabel = conditionInput.closest("label");
  const labels = gradingLabels();
  const graded = mode === "GRADED";

  conditionLabel.hidden = graded;
  labels.company.hidden = !graded;
  labels.grade.hidden = !graded;
  labels.certificate.hidden = !graded;

  if (!clearInactive) return;
  if (graded) {
    conditionSelect.value = "";
    conditionInput.value = "";
  } else {
    byId("edit-grading-company").value = "";
    byId("edit-grade").value = "";
    byId("edit-certificate").value = "";
  }
}

function ensureInventoryStateControls() {
  if (byId("edit-condition-select")) return;

  const conditionInput = byId("edit-condition");
  const conditionLabel = conditionInput.closest("label");
  conditionInput.hidden = true;

  const cardStateLabel = document.createElement("label");
  cardStateLabel.id = "edit-card-state-label";
  cardStateLabel.append(document.createTextNode("Card state"));

  const cardStateSelect = document.createElement("select");
  cardStateSelect.id = "edit-card-state";
  [
    ["RAW", "Raw card"],
    ["GRADED", "Graded card"],
  ].forEach(([value, text]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    cardStateSelect.append(option);
  });
  cardStateSelect.addEventListener("change", () => {
    configureCardEditorMode(cardStateSelect.value, {clearInactive: true});
  });
  cardStateLabel.append(cardStateSelect);
  conditionLabel.insertAdjacentElement("beforebegin", cardStateLabel);

  const conditionSelect = document.createElement("select");
  conditionSelect.id = "edit-condition-select";
  conditionSelect.setAttribute("aria-label", "Raw card condition");

  const blankCondition = document.createElement("option");
  blankCondition.value = "";
  blankCondition.textContent = "Select raw condition";
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
}

function configureInventoryStateEditor(item) {
  ensureInventoryStateControls();
  const conditionInput = byId("edit-condition");
  const conditionSelect = byId("edit-condition-select");
  const conditionLabel = conditionInput.closest("label");
  const cardStateLabel = byId("edit-card-state-label");
  const cardStateSelect = byId("edit-card-state");
  const sealLabel = byId("edit-seal-label");
  const sealSelect = byId("edit-seal-status");
  const labels = gradingLabels();

  if (item.product_type === "CARD") {
    cardStateLabel.hidden = false;
    sealLabel.hidden = true;
    sealSelect.value = "";

    const mode = item.grading_company && item.grade ? "GRADED" : "RAW";
    cardStateSelect.value = mode;
    conditionSelect.value = CARD_CONDITIONS.includes(item.condition) ? item.condition : "";
    conditionInput.value = conditionSelect.value;
    configureCardEditorMode(mode);
  } else {
    cardStateLabel.hidden = true;
    conditionLabel.hidden = true;
    labels.company.hidden = true;
    labels.grade.hidden = true;
    labels.certificate.hidden = true;
    sealLabel.hidden = false;
    sealSelect.value = item.seal_status || "";
    conditionSelect.value = "";
    conditionInput.value = "";
    byId("edit-grading-company").value = "";
    byId("edit-grade").value = "";
    byId("edit-certificate").value = "";
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
      const mode = byId("edit-card-state").value;
      payload.seal_status = null;

      if (mode === "GRADED") {
        const company = emptyToNull(byId("edit-grading-company").value);
        const grade = emptyToNull(byId("edit-grade").value);
        if (!company || !grade) {
          throw new Error("Graded cards require both grading company and grade.");
        }
        payload.condition = null;
        payload.grading_company = company;
        payload.grade = grade;
        payload.certificate_number = emptyToNull(byId("edit-certificate").value);
      } else {
        payload.condition = byId("edit-condition-select").value || null;
        payload.grading_company = null;
        payload.grade = null;
        payload.certificate_number = null;
      }
    } else {
      payload.condition = null;
      payload.grading_company = null;
      payload.grade = null;
      payload.certificate_number = null;
      payload.seal_status = byId("edit-seal-status").value || null;
    }

    options = {...options, body: JSON.stringify(payload)};
  }
  return baseApiRequest(path, options, retry);
};
