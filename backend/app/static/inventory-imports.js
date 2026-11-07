"use strict";

let activeImportPreview = null;
let inventoryImportGeneration = 0;
let inventoryImportFileRevision = 0;
let inventoryImportBusy = false;

const INVENTORY_IMPORT_MAP_FIELDS = [
  ["name", "Card / product name"], ["game", "TCG / game"],
  ["set_name", "Set"], ["card_number", "Card number"],
  ["quantity", "Quantity"], ["variant", "Variant / foil"],
  ["rarity", "Rarity"], ["language", "Language"],
  ["condition", "Condition"], ["grade", "Grade"],
  ["grading_company", "Grading company"], ["certificate_number", "Certificate number"],
  ["purchase_price", "Cost paid"], ["currency", "Currency"],
  ["seal_status", "Sealed status"], ["product_type", "Product type"],
];

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
        <label>Unmarked language<select id="import-default-language"><option value="">Leave for review</option><option value="English">English</option><option value="Japanese">Japanese</option></select></label>
        <label class="full-width">CSV / TSV file<input id="import-file" type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" required></label>
      </div>
      <details id="import-column-mapping" class="hidden">
        <summary>Column mappings</summary>
        <p class="muted">Choose source columns to override automatic detection. Mappings and defaults apply when you preview or rebuild.</p>
        <div id="import-column-fields" class="form-grid"></div>
      </details>
      <div id="import-message" class="message" role="status"></div>
      <div id="import-summary" class="allocation-summary hidden"></div>
      <div id="import-warnings" class="message"></div>
      <p id="import-rebuild-help" class="muted hidden">Select the original file, correct the mappings or defaults, then rebuild this preview. Rebuilding resets its match and skip choices. Review the new results before committing inventory.</p>
      <div id="import-preview-list" class="allocation-list"></div>
      <div id="import-recent-section">
        <p class="eyebrow">Recent import batches</p>
        <div id="import-recent-list" class="allocation-list"></div>
      </div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" data-close="inventory-import-dialog">Cancel</button>
        <button id="import-new-button" class="ghost-button hidden" type="button">New import</button>
        <button id="import-preview-button" class="primary-button compact" type="submit">Preview import</button>
        <button id="import-rebuild-button" class="primary-button compact hidden" type="button" aria-describedby="import-rebuild-help">Rebuild preview</button>
        <button id="import-commit-button" class="approve-button hidden" type="button">Commit ready inventory</button>
      </div>
    </form>`;
  document.body.append(dialog);

  button.addEventListener("click", openInventoryImport);
  dialog.querySelectorAll('[data-close="inventory-import-dialog"]').forEach((close) => close.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("close", resetInventoryImport);
  byId("inventory-import-form").addEventListener("submit", previewInventoryImport);
  byId("import-file").addEventListener("change", inspectInventoryImportFile);
  byId("import-new-button").addEventListener("click", resetInventoryImport);
  byId("import-rebuild-button").addEventListener("click", rebuildInventoryImport);
  byId("import-commit-button").addEventListener("click", commitInventoryImport);
}

function resetInventoryImport() {
  inventoryImportGeneration += 1;
  inventoryImportFileRevision += 1;
  activeImportPreview = null;
  byId("inventory-import-form").reset();
  byId("import-summary").classList.add("hidden");
  byId("import-summary").replaceChildren();
  byId("import-preview-list").replaceChildren();
  byId("import-column-fields").replaceChildren();
  byId("import-column-mapping").classList.add("hidden");
  byId("import-column-mapping").open = false;
  byId("import-commit-button").classList.add("hidden");
  setInventoryImportBusy(false);
  showMessage("import-message");
  showMessage("import-warnings");
}

function inventoryImportCurrent(generation, batchId = null) {
  return generation === inventoryImportGeneration && byId("inventory-import-dialog").open
    && (batchId === null || activeImportPreview?.batch_id === batchId);
}

function inventoryImportCanRebuild() {
  const data = activeImportPreview;
  return Boolean(data?.rebuild_enabled && data.status === "PREVIEW"
    && !data.automatic_intake && !data.last_auto_apply_version && !data.committed_at
    && !data.candidates.some((candidate) => candidate.status === "COMMITTED"));
}

function updateInventoryImportControls() {
  const active = Boolean(activeImportPreview);
  const rebuild = inventoryImportCanRebuild();
  byId("import-preview-button").classList.toggle("hidden", active);
  byId("import-new-button").classList.toggle("hidden", !active);
  byId("import-rebuild-help").classList.toggle("hidden", !rebuild);
  byId("import-rebuild-button").classList.toggle("hidden", !rebuild);
  byId("import-rebuild-button").disabled = inventoryImportBusy || !byId("import-file").files[0];
  const canCommit = active && activeImportPreview.status === "PREVIEW"
    && activeImportPreview.review_rows === 0 && activeImportPreview.ready_units > 0
    && activeImportPreview.summary_complete;
  byId("import-commit-button").classList.toggle("hidden", !canCommit);
}

function setInventoryImportBusy(busy) {
  inventoryImportBusy = Boolean(busy);
  const form = byId("inventory-import-form");
  form.setAttribute("aria-busy", String(inventoryImportBusy));
  form.querySelectorAll("input, select, button:not([data-close])").forEach((control) => {
    control.disabled = inventoryImportBusy;
  });
  updateInventoryImportControls();
}

// Only inspect the header for mapping choices. The server parses and validates
// the complete source, including the exact bytes required for a rebuild.
function inventoryImportHeaders(contents, delimiter) {
  const input = String(contents || "").replace(/^\uFEFF/, "");
  const headers = [];
  let field = "", quoted = false;
  for (let i = 0; i < input.length && i < 20000; i += 1) {
    const character = input[i];
    if (character === '"') {
      if (quoted && input[i + 1] === '"') { field += '"'; i += 1; }
      else quoted = !quoted;
    } else if (!quoted && character === delimiter) {
      headers.push(field); field = "";
    } else if (!quoted && (character === "\n" || character === "\r")) {
      headers.push(field);
      return [...new Set(headers.filter((value) => value.trim()))].slice(0, 80);
    } else field += character;
  }
  return [];
}

function inventoryImportMappings() {
  const mapping = {};
  byId("import-column-fields").querySelectorAll("[data-import-field]").forEach((select) => {
    if (select.value) mapping[select.dataset.importField] = select.value;
  });
  return mapping;
}

async function inventoryImportFileContents(file) {
  if (!file || !/\.(csv|tsv)$/i.test(file.name)) throw new Error("Choose the original CSV or TSV file.");
  if (file.size > 8_000_000) throw new Error("The import limit is 8 MB per file.");
  const content = await file.text();
  if (content.length > 8_000_000) throw new Error("The import limit is 8 MB per file.");
  return content;
}

async function inspectInventoryImportFile() {
  const generation = inventoryImportGeneration;
  const revision = ++inventoryImportFileRevision;
  const file = byId("import-file").files[0];
  const fields = byId("import-column-fields");
  fields.replaceChildren();
  byId("import-column-mapping").classList.add("hidden");
  updateInventoryImportControls();
  if (!file) return;
  try {
    const content = await inventoryImportFileContents(file);
    if (!inventoryImportCurrent(generation) || revision !== inventoryImportFileRevision
      || file !== byId("import-file").files[0]) return;
    const filename = activeImportPreview?.filename || file.name;
    const headers = inventoryImportHeaders(content, /\.tsv$/i.test(filename) ? "\t" : ",");
    if (!headers.length) throw new Error("No supported header row was found. Check the CSV / TSV export.");
    INVENTORY_IMPORT_MAP_FIELDS.forEach(([key, label]) => {
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      const select = document.createElement("select");
      select.dataset.importField = key;
      ["", ...headers].forEach((header) => {
        const option = document.createElement("option");
        option.value = header;
        option.textContent = header || "Auto-detect";
        select.append(option);
      });
      wrapper.append(select);
      fields.append(wrapper);
    });
    byId("import-column-mapping").classList.remove("hidden");
  } catch (error) {
    if (inventoryImportCurrent(generation) && revision === inventoryImportFileRevision) {
      showMessage("import-message", error.message, "error");
    }
  }
}

function inventoryImportPayload(file, content) {
  return {
    filename: file.name, content, adapter: byId("import-adapter").value,
    default_game: emptyToNull(byId("import-default-game").value),
    default_language: emptyToNull(byId("import-default-language").value),
    column_mapping: inventoryImportMappings(),
  };
}

async function readStoredInventoryImport(batchId, preview = {}) {
  const stored = await apiRequest(`/api/v1/imports/${encodeURIComponent(batchId)}`);
  const candidates = stored.candidates.map(normalizeImportCandidate);
  const fallback = {
    candidate_count: candidates.length,
    ready_units: candidates.filter((row) => row.status === "READY").reduce((sum, row) => sum + row.quantity, 0),
    review_rows: candidates.filter((row) => row.status === "REVIEW").length,
    skipped_rows: candidates.filter((row) => row.status === "SKIPPED").length,
  };
  const summary = stored.summary || fallback;
  return {
    ...preview, ...stored.batch, ...summary, batch_id: stored.batch.id,
    candidates, warnings: importJsonValue(stored.batch.warnings, []),
    rebuild_enabled: stored.rebuild_enabled === true,
    summary_complete: Boolean(stored.summary) || candidates.length < 5000,
    preview_truncated: summary.candidate_count > candidates.length || (!stored.summary && candidates.length === 5000),
  };
}

async function resumeInventoryImport(batchId) {
  if (inventoryImportBusy) return;
  resetInventoryImport();
  const generation = inventoryImportGeneration;
  setInventoryImportBusy(true);
  showMessage("import-message", "Opening saved preview…");
  try {
    const preview = await readStoredInventoryImport(batchId);
    if (!inventoryImportCurrent(generation)) return;
    activeImportPreview = preview;
    byId("import-adapter").value = preview.adapter;
    renderImportPreview(preview);
    showMessage("import-message", `Opened ${preview.filename}. Select its original file to correct the preview settings, or continue reviewing its saved matches.`);
  } catch (error) {
    if (inventoryImportCurrent(generation)) showMessage("import-message", error.message, "error");
  } finally {
    if (inventoryImportCurrent(generation)) setInventoryImportBusy(false);
  }
}

function openInventoryImport() {
  resetInventoryImport();
  byId("inventory-import-dialog").showModal();
  loadRecentImports();
}

function importIssueLabel(issue) {
  return issue.replaceAll("_", " ");
}

function importJsonValue(value, fallback) {
  if (value === null || value === undefined) return fallback;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function normalizeImportCandidate(candidate) {
  return {
    ...candidate,
    normalized_record: importJsonValue(candidate.normalized_record, {}),
    issues: importJsonValue(candidate.issues, []),
  };
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

  const normalizedCandidate = normalizeImportCandidate(result.candidate);
  const index = activeImportPreview.candidates.findIndex((candidate) => candidate.id === normalizedCandidate.id);
  if (index >= 0) activeImportPreview.candidates[index] = normalizedCandidate;
  renderImportPreview(activeImportPreview);
}

async function resolveImportCandidate(candidate, catalogueId) {
  if (!activeImportPreview || inventoryImportBusy
    || !activeImportPreview.candidates.some((row) => row.id === candidate.id)) return;
  const generation = inventoryImportGeneration;
  const batchId = activeImportPreview.batch_id;
  setInventoryImportBusy(true);
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
    if (!inventoryImportCurrent(generation, batchId)) return;
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
    if (inventoryImportCurrent(generation, batchId)) showMessage("import-message", error.message, "error");
  } finally {
    if (inventoryImportCurrent(generation, batchId)) setInventoryImportBusy(false);
  }
}

async function skipImportCandidate(candidate) {
  if (!activeImportPreview || inventoryImportBusy
    || !activeImportPreview.candidates.some((row) => row.id === candidate.id)) return;
  const confirmed = window.confirm(
    `Skip source row ${candidate.source_row}? It will not create inventory when this batch is committed.`,
  );
  if (!confirmed) return;

  const generation = inventoryImportGeneration;
  const batchId = activeImportPreview.batch_id;
  setInventoryImportBusy(true);
  showMessage("import-message", `Skipping source row ${candidate.source_row}…`);
  try {
    const result = await apiRequest(
      `/api/v1/imports/${activeImportPreview.batch_id}/candidates/${candidate.id}/skip`,
      {
        method: "POST",
        body: JSON.stringify({ version: activeImportPreview.version }),
      },
    );
    if (!inventoryImportCurrent(generation, batchId)) return;
    applyImportReviewResult(result);
    showMessage("import-message", `Source row ${candidate.source_row} will be skipped.`, "success");
  } catch (error) {
    if (inventoryImportCurrent(generation, batchId)) showMessage("import-message", error.message, "error");
  } finally {
    if (inventoryImportCurrent(generation, batchId)) setInventoryImportBusy(false);
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
    const reconciliation = normalized.reconciliation === "SNAPSHOT_DELTA"
      ? [
          `Previous ${normalized.previous_quantity ?? 0}`,
          `Snapshot ${normalized.snapshot_quantity ?? candidate.quantity}`,
          `Add ${Math.max(0, Number(normalized.delta_quantity || 0))}`,
        ].join(" · ")
      : `Qty ${candidate.quantity}`;
    meta.textContent = [normalized.game, normalized.set_name, normalized.card_number, reconciliation].filter(Boolean).join(" · ");
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

    if (candidate.status === "REVIEW" && data.status === "PREVIEW") {
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
  updateInventoryImportControls();
}

async function previewInventoryImport(event) {
  event.preventDefault();
  if (inventoryImportBusy) return;
  if (activeImportPreview) {
    showMessage("import-message", "Use Rebuild preview to apply settings to this batch, or New import to choose another file.");
    return;
  }
  const file = byId("import-file").files[0];
  const generation = inventoryImportGeneration;
  setInventoryImportBusy(true);
  showMessage("import-message", "Analysing file and matching catalogue records…");
  try {
    const content = await inventoryImportFileContents(file);
    if (!inventoryImportCurrent(generation)) return;
    const data = await apiRequest("/api/v1/imports/preview", {
      method: "POST",
      body: JSON.stringify(inventoryImportPayload(file, content)),
    });
    if (!inventoryImportCurrent(generation)) return;
    const preview = await readStoredInventoryImport(data.batch_id, data);
    if (!inventoryImportCurrent(generation)) return;
    activeImportPreview = preview;
    renderImportPreview(activeImportPreview);
    showMessage(
      "import-message",
      activeImportPreview.review_rows
        ? "Preview saved. Resolve or deliberately skip Action Required rows before committing."
        : "Preview is clean and ready to commit.",
      activeImportPreview.review_rows ? "error" : "success",
    );
  } catch (error) {
    if (!inventoryImportCurrent(generation)) return;
    if (error.status === 409 && error.detail?.status === "PREVIEW" && typeof error.detail.batch_id === "string") {
      try {
        const preview = await readStoredInventoryImport(error.detail.batch_id);
        if (!inventoryImportCurrent(generation)) return;
        activeImportPreview = preview;
        renderImportPreview(preview);
        showMessage("import-message", inventoryImportCanRebuild()
          ? "This file already has a saved preview. Review the selected settings and choose Rebuild preview to apply them."
          : "This file already has a saved preview. Continue reviewing its saved matches; rebuilding is unavailable.");
      } catch (loadError) {
        if (inventoryImportCurrent(generation)) showMessage("import-message", `Could not reopen the saved preview: ${loadError.message}`, "error");
      }
    } else {
      showMessage("import-message", `${error.message} If a preview was saved, reopen it from Recent import batches.`, "error");
    }
  } finally {
    if (inventoryImportCurrent(generation)) setInventoryImportBusy(false);
  }
}

async function rebuildInventoryImport() {
  if (inventoryImportBusy || !inventoryImportCanRebuild()) return;
  const generation = inventoryImportGeneration;
  const batchId = activeImportPreview.batch_id;
  const version = activeImportPreview.version;
  const file = byId("import-file").files[0];
  setInventoryImportBusy(true);
  showMessage("import-message", "Rebuilding the saved preview and resetting its review choices…");
  let submitted = false;
  try {
    const content = await inventoryImportFileContents(file);
    if (!inventoryImportCurrent(generation, batchId)) return;
    submitted = true;
    const result = await apiRequest(`/api/v1/imports/${encodeURIComponent(batchId)}/rebuild`, {
      method: "POST",
      body: JSON.stringify({ ...inventoryImportPayload(file, content), version }),
    });
    if (!inventoryImportCurrent(generation, batchId)) return;
    const preview = await readStoredInventoryImport(batchId, result);
    if (!inventoryImportCurrent(generation, batchId)) return;
    activeImportPreview = preview;
    renderImportPreview(preview);
    showMessage("import-message", "Preview rebuilt. Previous match and skip choices were reset. Review these results before committing; no inventory has been added.", "success");
    await loadRecentImports();
  } catch (error) {
    if (!inventoryImportCurrent(generation, batchId)) return;
    if (submitted) {
      // A lost response may follow a successful replacement. Re-read before
      // offering any action so old candidate IDs/versions cannot be reused.
      try {
        const preview = await readStoredInventoryImport(batchId);
        if (!inventoryImportCurrent(generation, batchId)) return;
        activeImportPreview = preview;
        renderImportPreview(preview);
        showMessage("import-message", `${error.message} The saved preview has been reloaded; check it before continuing.`, "error");
      } catch (loadError) {
        if (!inventoryImportCurrent(generation, batchId)) return;
        activeImportPreview = null;
        byId("import-preview-list").replaceChildren();
        byId("import-summary").classList.add("hidden");
        showMessage("import-message", `Could not reload the saved preview: ${loadError.message}. Reopen it from Recent import batches before continuing.`, "error");
      }
    } else showMessage("import-message", error.message, "error");
  } finally {
    if (inventoryImportCurrent(generation)) setInventoryImportBusy(false);
  }
}

async function runImportEnrichment(batchId, defaultLanguage, {retryActionRequired = false} = {}) {
  const initial = await apiRequest(`/api/v1/imports/${batchId}/enrichment`);
  const total = Number(initial.stages?.total || 0);
  let remaining = Number(
    initial.states?.find((row) => row.overall_status === "PENDING")?.count || 0
  );
  let processedTotal = 0;
  let failedTotal = 0;
  let rounds = 0;

  while (remaining > 0 && rounds < 100) {
    rounds += 1;
    showMessage(
      "import-message",
      `Enriching imported inventory… ${processedTotal.toLocaleString("en-GB")} / ${total.toLocaleString("en-GB")} processed.`
    );
    const result = await apiRequest(`/api/v1/imports/${batchId}/enrichment/process`, {
      method: "POST",
      body: JSON.stringify({
        limit: 18,
        default_language: defaultLanguage || null,
        retry_action_required: retryActionRequired && rounds === 1,
      }),
    });
    processedTotal += Number(result.processed_count || 0);
    failedTotal += Number(result.failed_count || 0);
    remaining = Number(result.remaining_pending || 0);

    if (
      remaining > 0
      && Number(result.processed_count || 0) === 0
      && Number(result.failed_count || 0) > 0
    ) {
      break;
    }
  }

  const finalStatus = await apiRequest(`/api/v1/imports/${batchId}/enrichment`);
  const actionRequired = Number(
    finalStatus.states?.find((row) => row.overall_status === "ACTION_REQUIRED")?.count || 0
  );
  const complete = Number(
    finalStatus.states?.find((row) => row.overall_status === "COMPLETE")?.count || 0
  );
  return {
    total,
    complete,
    actionRequired,
    remaining: Number(
      finalStatus.states?.find((row) => row.overall_status === "PENDING")?.count || 0
    ),
    failedTotal,
    stages: finalStatus.stages || {},
  };
}

function renderRecentImports(data) {
  const container = byId("import-recent-list");
  if (!container) return;
  container.replaceChildren();
  const items = data.items || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No import batches yet.";
    container.append(empty);
    return;
  }

  items.slice(0, 8).forEach((batch) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = batch.filename || "Import batch";
    const meta = document.createElement("small");
    meta.textContent = [
      batch.adapter,
      `${Number(batch.physical_units || 0).toLocaleString("en-GB")} physical items`,
      String(batch.status || "").replaceAll("_", " "),
    ].filter(Boolean).join(" · ");
    copy.append(title, meta);

    const state = document.createElement("div");
    state.className = "card-name";
    const summary = document.createElement("strong");
    const pending = Number(batch.enrichment_pending || 0);
    const action = Number(batch.enrichment_action_required || 0);
    const complete = Number(batch.enrichment_complete || 0);
    if (batch.status !== "COMMITTED") {
      summary.textContent = "Not committed";
    } else if (!batch.enrichment_total) {
      summary.textContent = "Enrichment not started";
    } else {
      summary.textContent = `${complete} enriched · ${action} action required`;
    }
    state.append(summary);

    if (batch.status === "PREVIEW") {
      const reopen = document.createElement("button");
      reopen.type = "button";
      reopen.className = "ghost-button";
      reopen.textContent = "Open preview";
      reopen.addEventListener("click", () => resumeInventoryImport(batch.id));
      state.append(reopen);
    }

    if (batch.status === "COMMITTED" && (pending > 0 || !batch.enrichment_total || action > 0)) {
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "ghost-button";
      resume.textContent = action > 0 ? "Retry / enrich" : "Resume enrichment";
      resume.addEventListener("click", async () => {
        resume.disabled = true;
        const language = emptyToNull(byId("import-default-language").value);
        showMessage("import-message", "Running import enrichment…");
        try {
          const result = await runImportEnrichment(batch.id, language, {
            retryActionRequired: action > 0,
          });
          showMessage(
            "import-message",
            `Enrichment complete: ${result.complete} complete · ${result.actionRequired} action required${result.remaining ? ` · ${result.remaining} still pending` : ""}.`,
            result.actionRequired || result.remaining ? "error" : "success",
          );
          await Promise.all([loadRecentImports(), refreshActionRequiredBadge(), reloadDashboard()]);
        } catch (error) {
          showMessage("import-message", error.message, "error");
        } finally {
          resume.disabled = false;
        }
      });
      state.append(resume);
    }

    row.append(copy, state);
    container.append(row);
  });
}

async function loadRecentImports() {
  const container = byId("import-recent-list");
  if (!container) return;
  container.textContent = "Loading recent imports…";
  try {
    const data = await apiRequest("/api/v1/imports?limit=8");
    renderRecentImports(data);
  } catch (error) {
    container.textContent = error.message;
  }
}

async function commitInventoryImport() {
  if (!activeImportPreview || inventoryImportBusy || activeImportPreview.status !== "PREVIEW"
    || activeImportPreview.review_rows !== 0 || activeImportPreview.ready_units <= 0
    || !activeImportPreview.summary_complete) return;
  const generation = inventoryImportGeneration;
  const batchId = activeImportPreview.batch_id;
  setInventoryImportBusy(true);
  showMessage("import-message", "Creating physical Draft inventory…");
  try {
    const defaultLanguage = emptyToNull(byId("import-default-language").value);
    const result = await apiRequest(`/api/v1/imports/${batchId}/commit`, {
      method: "POST",
      body: JSON.stringify({ version: activeImportPreview.version }),
    });
    if (!inventoryImportCurrent(generation, batchId)) return;
    activeImportPreview.status = "COMMITTED";
    activeImportPreview.version = result.version || activeImportPreview.version;
    updateInventoryImportControls();

    showMessage(
      "import-message",
      `${result.created_count} physical inventory item${result.created_count === 1 ? "" : "s"} created. Running identity, image and pricing enrichment…`
    );

    const enrichment = await runImportEnrichment(batchId, defaultLanguage);
    if (!inventoryImportCurrent(generation, batchId)) return;
    await Promise.all([reloadDashboard(), refreshActionRequiredBadge(), loadRecentImports()]);

    showMessage(
      "import-message",
      `Import complete: ${enrichment.complete} enriched · ${enrichment.actionRequired} action required${enrichment.remaining ? ` · ${enrichment.remaining} pending` : ""}.`,
      enrichment.actionRequired || enrichment.remaining ? "error" : "success",
    );
    showMessage(
      "inventory-message",
      `${result.created_count} physical inventory item${result.created_count === 1 ? "" : "s"} imported as Draft; post-import enrichment has run.`,
      "success",
    );
  } catch (error) {
    if (inventoryImportCurrent(generation, batchId)) showMessage("import-message", error.message, "error");
  } finally {
    if (inventoryImportCurrent(generation, batchId)) setInventoryImportBusy(false);
  }
}

function ensureActionRequiredUI() {
  if (byId("action-required-button")) return;
  const actions = byId("refresh-button").parentElement;
  const button = document.createElement("button");
  button.id = "action-required-button";
  button.className = "ghost-button";
  button.type = "button";
  button.textContent = "Action Required";
  actions.insertBefore(button, byId("refresh-button"));

  const dialog = document.createElement("dialog");
  dialog.id = "action-required-dialog";
  dialog.className = "modal";
  dialog.innerHTML = `
    <div class="modal-card wide">
      <div class="modal-heading">
        <div><p class="eyebrow">Exceptions, not routine work</p><h2>Action Required</h2><p class="muted">Only unresolved identity, media, pricing and operational exceptions appear here.</p></div>
        <button class="icon-button" type="button" data-close="action-required-dialog" aria-label="Close">×</button>
      </div>
      <div id="action-required-message" class="message" role="status"></div>
      <div id="action-required-list" class="allocation-list"></div>
      <div class="modal-actions">
        <button id="action-required-refresh" class="ghost-button" type="button">Refresh</button>
        <button class="primary-button compact" type="button" data-close="action-required-dialog">Close</button>
      </div>
    </div>`;
  document.body.append(dialog);

  button.addEventListener("click", openActionRequired);
  byId("action-required-refresh").addEventListener("click", loadActionRequired);
  dialog.querySelectorAll('[data-close="action-required-dialog"]').forEach((close) => {
    close.addEventListener("click", () => dialog.close());
  });
}

function renderActionRequired(data) {
  const container = byId("action-required-list");
  container.replaceChildren();
  const items = data.items || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Nothing needs attention right now.";
    container.append(empty);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.title || item.code;
    const meta = document.createElement("small");
    meta.textContent = [item.category, item.severity, item.code]
      .filter(Boolean)
      .join(" · ");
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = item.detail || "";
    const action = document.createElement("small");
    action.textContent = item.recommended_action
      ? "Next: " + item.recommended_action
      : "";
    copy.append(title, meta, detail, action);
    row.append(copy);
    container.append(row);
  });
}

async function loadActionRequired() {
  const container = byId("action-required-list");
  if (!container) return;
  container.textContent = "Loading exceptions…";
  try {
    const data = await apiRequest("/api/v1/action-required?status=OPEN&limit=100");
    renderActionRequired(data);
    showMessage(
      "action-required-message",
      data.total
        ? `${data.total} open exception${data.total === 1 ? "" : "s"}.`
        : "All clear.",
      data.total ? "error" : "success",
    );
  } catch (error) {
    showMessage("action-required-message", error.message, "error");
  }
}

async function refreshActionRequiredBadge() {
  const button = byId("action-required-button");
  if (!button) return;
  try {
    const data = await apiRequest("/api/v1/action-required/summary");
    const total = (data.items || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
    button.textContent = total ? `Action Required (${total})` : "Action Required";
    button.dataset.count = String(total);
  } catch {
    button.textContent = "Action Required";
    delete button.dataset.count;
  }
}

async function openActionRequired() {
  byId("action-required-dialog").showModal();
  await loadActionRequired();
}

ensureInventoryImportUI();
ensureActionRequiredUI();
refreshActionRequiredBadge();

