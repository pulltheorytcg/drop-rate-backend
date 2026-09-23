"use strict";

let activeImportPreview = null;

function ensureInventoryImportUI() {
  if (byId("import-inventory-button")) return;
  const actions = byId("refresh-button").parentElement;
  const button = document.createElement("button");
  button.id = "import-inventory-button";
  button.className = "ghost-button";
  button.type = "button";
  button.textContent = "Import inventory";
  actions.insertBefore(button, byId("refresh-button"));

  const dialog = document.createElement("dialog");
  dialog.id = "inventory-import-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <form id="inventory-import-form" class="modal-card wide">
      <div class="modal-heading">
        <div><p class="eyebrow">Bulk inventory intake</p><h2>Import inventory</h2><p class="muted">Upload a CSV, review every match, then explicitly commit it to physical inventory.</p></div>
        <button class="icon-button" type="button" data-close="inventory-import-dialog" aria-label="Close">×</button>
      </div>
      <div class="form-grid">
        <label>Import source<select id="import-adapter"><option value="AUTO">Auto detect</option><option value="COLLECTR">Collectr export</option><option value="EBAY_PURCHASES">eBay purchases/account export</option><option value="HOLODEX">HoloDex export</option><option value="GENERIC_CSV">Generic CSV</option></select></label>
        <label>Default game<input id="import-default-game" maxlength="80" placeholder="Optional, e.g. Pokemon"></label>
        <label class="full-width">CSV file<input id="import-file" type="file" accept=".csv,text/csv" required></label>
      </div>
      <div id="import-message" class="message" role="status"></div>
      <div id="import-summary" class="allocation-summary hidden"></div>
      <div id="import-warnings" class="message"></div>
      <div id="import-preview-list" class="allocation-list"></div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" data-close="inventory-import-dialog">Cancel</button>
        <button id="import-preview-button" class="primary-button compact" type="submit">Preview import</button>
        <button id="import-commit-button" class="approve-button hidden" type="button">Commit ready inventory</button>
      </div>
    </form>`;
  document.body.append(dialog);

  button.addEventListener("click", openInventoryImport);
  dialog.querySelectorAll('[data-close="inventory-import-dialog"]').forEach((close) => close.addEventListener("click", () => dialog.close()));
  byId("inventory-import-form").addEventListener("submit", previewInventoryImport);
  byId("import-commit-button").addEventListener("click", commitInventoryImport);
}

function resetInventoryImport() {
  activeImportPreview = null;
  byId("inventory-import-form").reset();
  byId("import-summary").classList.add("hidden");
  byId("import-summary").replaceChildren();
  byId("import-preview-list").replaceChildren();
  byId("import-commit-button").classList.add("hidden");
  showMessage("import-message");
  showMessage("import-warnings");
}

function openInventoryImport() {
  resetInventoryImport();
  byId("inventory-import-dialog").showModal();
}

function importIssueLabel(issue) {
  return issue.replaceAll("_", " ");
}

function renderImportPreview(data) {
  const summary = byId("import-summary");
  summary.classList.remove("hidden");
  summary.innerHTML = `<span>${data.source_rows} source rows · ${data.physical_units} physical items</span><strong>${data.ready_units} ready · ${data.review_rows} rows require review</strong>`;

  if (data.warnings?.length) showMessage("import-warnings", data.warnings.join(" "), "error");
  else showMessage("import-warnings");

  const container = byId("import-preview-list");
  container.replaceChildren();
  data.candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const normalized = candidate.normalized_record;
    const title = document.createElement("strong");
    title.textContent = normalized.name || `Source row ${candidate.source_row}`;
    const meta = document.createElement("small");
    meta.textContent = [normalized.game, normalized.set_name, normalized.card_number, `Qty ${candidate.quantity}`].filter(Boolean).join(" · ");
    details.append(title, meta);
    const state = document.createElement("div");
    state.className = "card-name";
    const status = document.createElement("strong");
    status.textContent = candidate.status === "READY" ? "Ready" : "Action Required";
    const issues = document.createElement("small");
    issues.textContent = candidate.issues?.length ? candidate.issues.map(importIssueLabel).join(", ") : "Matched to catalogue";
    state.append(status, issues);
    row.append(details, state);
    container.append(row);
  });
  if (data.preview_truncated) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "Preview is showing the first 200 rows only. The full batch is stored server-side.";
    container.append(note);
  }
  byId("import-commit-button").classList.toggle("hidden", data.review_rows !== 0);
}

async function previewInventoryImport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = byId("import-file").files[0];
  if (!file) return showMessage("import-message", "Choose a CSV file first.", "error");
  if (file.size > 8_000_000) return showMessage("import-message", "CSV must be smaller than 8 MB.", "error");
  setBusy(form, true);
  showMessage("import-message", "Analysing file and matching catalogue records…");
  try {
    const content = await file.text();
    const data = await apiRequest("/api/v1/imports/preview", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content,
        adapter: byId("import-adapter").value,
        default_game: emptyToNull(byId("import-default-game").value),
      }),
    });
    activeImportPreview = data;
    renderImportPreview(data);
    showMessage("import-message", data.review_rows ? "Preview saved. Resolve Action Required rows before committing." : "Preview is clean and ready to commit.", data.review_rows ? "error" : "success");
  } catch (error) {
    showMessage("import-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

async function commitInventoryImport() {
  if (!activeImportPreview) return;
  const button = byId("import-commit-button");
  button.disabled = true;
  showMessage("import-message", "Creating physical Draft inventory…");
  try {
    const result = await apiRequest(`/api/v1/imports/${activeImportPreview.batch_id}/commit`, {
      method: "POST",
      body: JSON.stringify({ version: activeImportPreview.version }),
    });
    byId("inventory-import-dialog").close();
    await reloadDashboard();
    showMessage("inventory-message", `${result.created_count} physical inventory item${result.created_count === 1 ? "" : "s"} imported as Draft.`, "success");
  } catch (error) {
    showMessage("import-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

ensureInventoryImportUI();
