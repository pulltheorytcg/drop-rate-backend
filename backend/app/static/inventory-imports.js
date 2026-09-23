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

function importCandidateStatus(candidate) {
  if (candidate.status === "READY") return "Ready";
  if (candidate.status === "SKIPPED") return "Skipped";
  return "Action Required";
}

function importCandidateSearchQuery(candidate) {
  const normalized = candidate.normalized_record || {};
  return [normalized.name, normalized.card_number, normalized.set_name]
    .filter(Boolean)
    .join(" ");
}

function applyImportReviewResult(result) {
  if (!activeImportPreview) return;
  activeImportPreview.version = result.version;
  activeImportPreview.ready_units = result.summary.ready_units;
  activeImportPreview.review_rows = result.summary.review_rows;
  activeImportPreview.skipped_rows = result.summary.skipped_rows;

  const index = activeImportPreview.candidates.findIndex((candidate) => candidate.id === result.candidate.id);
  if (index >= 0) activeImportPreview.candidates[index] = result.candidate;
  renderImportPreview(activeImportPreview);
}

async function resolveImportCandidate(candidate, catalogueId) {
  if (!activeImportPreview) return;
  showMessage("import-message", `Resolving source row ${candidate.source_row}…`);
  try {
    const result = await apiRequest(
      `/api/v1/imports/${activeImportPreview.batch_id}/candidates/${candidate.id}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          version: activeImportPreview.version,
          catalogue_id: catalogueId,
        }),
      },
    );
    applyImportReviewResult(result);
    if (result.candidate.status === "READY") {
      showMessage("import-message", `Source row ${candidate.source_row} is resolved and ready.`, "success");
    } else {
      showMessage(
        "import-message",
        `Catalogue identity selected for source row ${candidate.source_row}, but other issues still require action.`,
        "error",
      );
    }
  } catch (error) {
    showMessage("import-message", error.message, "error");
  }
}

async function skipImportCandidate(candidate) {
  if (!activeImportPreview) return;
  const confirmed = window.confirm(
    `Skip source row ${candidate.source_row}? It will not create inventory when this batch is committed.`,
  );
  if (!confirmed) return;

  showMessage("import-message", `Skipping source row ${candidate.source_row}…`);
  try {
    const result = await apiRequest(
      `/api/v1/imports/${activeImportPreview.batch_id}/candidates/${candidate.id}/skip`,
      {
        method: "POST",
        body: JSON.stringify({ version: activeImportPreview.version }),
      },
    );
    applyImportReviewResult(result);
    showMessage("import-message", `Source row ${candidate.source_row} will be skipped.`, "success");
  } catch (error) {
    showMessage("import-message", error.message, "error");
  }
}

function showImportCatalogueSearch(candidate, row) {
  if (row.querySelector("[data-import-resolver]")) return;

  const panel = document.createElement("div");
  panel.dataset.importResolver = "true";
  panel.className = "full-width";

  const input = document.createElement("input");
  input.type = "search";
  input.maxLength = 200;
  input.placeholder = "Search catalogue by card name, number or set";
  input.value = importCandidateSearchQuery(candidate);

  const searchButton = document.createElement("button");
  searchButton.type = "button";
  searchButton.className = "ghost-button";
  searchButton.textContent = "Search catalogue";

  const results = document.createElement("div");
  results.className = "allocation-list";

  const runSearch = async () => {
    const query = input.value.trim();
    if (query.length < 2) {
      results.textContent = "Enter at least 2 characters.";
      return;
    }
    searchButton.disabled = true;
    results.textContent = "Searching…";
    try {
      const data = await apiRequest(`/api/v1/catalogue/search?q=${encodeURIComponent(query)}&limit=8`);
      results.replaceChildren();
      if (!data.items?.length) {
        results.textContent = "No catalogue matches found. Try a shorter card name or card number.";
        return;
      }
      data.items.forEach((item) => {
        const resultRow = document.createElement("div");
        resultRow.className = "allocation-row";
        const description = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = item.name;
        const meta = document.createElement("small");
        meta.textContent = [item.game, item.set_name, item.card_number, item.variant, item.language]
          .filter(Boolean)
          .join(" · ");
        description.append(title, meta);

        const useButton = document.createElement("button");
        useButton.type = "button";
        useButton.className = "primary-button compact";
        useButton.textContent = "Use this match";
        useButton.addEventListener("click", () => resolveImportCandidate(candidate, item.id));
        resultRow.append(description, useButton);
        results.append(resultRow);
      });
    } catch (error) {
      results.textContent = error.message;
    } finally {
      searchButton.disabled = false;
    }
  };

  searchButton.addEventListener("click", runSearch);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch();
    }
  });

  panel.append(input, searchButton, results);
  row.append(panel);
  input.focus();
}

function renderImportPreview(data) {
  const summary = byId("import-summary");
  summary.classList.remove("hidden");
  const skipped = data.skipped_rows ? ` · ${data.skipped_rows} skipped` : "";
  summary.innerHTML = `<span>${data.source_rows} source rows · ${data.physical_units} physical items</span><strong>${data.ready_units} ready · ${data.review_rows} rows require review${skipped}</strong>`;

  if (data.warnings?.length) showMessage("import-warnings", data.warnings.join(" "), "error");
  else showMessage("import-warnings");

  const container = byId("import-preview-list");
  container.replaceChildren();
  data.candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const details = document.createElement("div");
    const normalized = candidate.normalized_record || {};
    const title = document.createElement("strong");
    title.textContent = normalized.name || `Source row ${candidate.source_row}`;
    const meta = document.createElement("small");
    meta.textContent = [normalized.game, normalized.set_name, normalized.card_number, `Qty ${candidate.quantity}`].filter(Boolean).join(" · ");
    details.append(title, meta);

    const state = document.createElement("div");
    state.className = "card-name";
    const status = document.createElement("strong");
    status.textContent = importCandidateStatus(candidate);
    const issues = document.createElement("small");
    issues.textContent = candidate.issues?.length
      ? candidate.issues.map(importIssueLabel).join(", ")
      : candidate.status === "SKIPPED"
        ? "Excluded from this import"
        : "Matched to catalogue";
    state.append(status, issues);

    if (candidate.status === "REVIEW") {
      const actions = document.createElement("div");
      const resolveButton = document.createElement("button");
      resolveButton.type = "button";
      resolveButton.className = "ghost-button";
      resolveButton.textContent = candidate.catalogue_id ? "Change match" : "Resolve match";
      resolveButton.addEventListener("click", () => showImportCatalogueSearch(candidate, row));

      const skipButton = document.createElement("button");
      skipButton.type = "button";
      skipButton.className = "ghost-button";
      skipButton.textContent = "Skip row";
      skipButton.addEventListener("click", () => skipImportCandidate(candidate));
      actions.append(resolveButton, skipButton);
      state.append(actions);
    }

    row.append(details, state);
    container.append(row);
  });

  if (data.preview_truncated) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = `Preview is showing ${data.candidates.length} rows only. The full batch remains stored server-side.`;
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

    // Preview creation returns a compact response before candidate IDs are known
    // client-side. Re-read the persisted batch so every Action Required row has
    // its immutable candidate ID for explicit resolve/skip actions.
    const stored = await apiRequest(`/api/v1/imports/${data.batch_id}`);
    activeImportPreview = {
      ...data,
      candidates: stored.candidates,
      preview_truncated: data.source_rows > stored.candidates.length,
      skipped_rows: 0,
    };
    renderImportPreview(activeImportPreview);
    showMessage(
      "import-message",
      activeImportPreview.review_rows
        ? "Preview saved. Resolve or deliberately skip Action Required rows before committing."
        : "Preview is clean and ready to commit.",
      activeImportPreview.review_rows ? "error" : "success",
    );
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
