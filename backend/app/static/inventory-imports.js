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
        <label>Unmarked language<select id="import-default-language"><option value="">Leave for review</option><option value="English">English</option><option value="Japanese">Japanese</option></select></label>
        <label class="full-width">CSV file<input id="import-file" type="file" accept=".csv,text/csv" required></label>
      </div>
      <div id="import-message" class="message" role="status"></div>
      <div id="import-summary" class="allocation-summary hidden"></div>
      <div id="import-warnings" class="message"></div>
      <div id="import-preview-list" class="allocation-list"></div>
      <div id="import-recent-section">
        <p class="eyebrow">Recent import batches</p>
        <div id="import-recent-list" class="allocation-list"></div>
      </div>
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
        default_language: emptyToNull(byId("import-default-language").value),
      }),
    });

    // Preview creation returns a compact response before candidate IDs are known
    // client-side. Re-read the persisted batch so every Action Required row has
    // its immutable candidate ID for explicit resolve/skip actions.
    const stored = await apiRequest(`/api/v1/imports/${data.batch_id}`);
    const candidates = stored.candidates.map(normalizeImportCandidate);
    activeImportPreview = {
      ...data,
      candidates,
      preview_truncated: data.source_rows > candidates.length,
      skipped_rows: data.skipped_rows || 0,
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
        limit: 100,
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
  if (!activeImportPreview) return;
  const button = byId("import-commit-button");
  button.disabled = true;
  showMessage("import-message", "Creating physical Draft inventory…");
  try {
    const batchId = activeImportPreview.batch_id;
    const defaultLanguage = emptyToNull(byId("import-default-language").value);
    const result = await apiRequest(`/api/v1/imports/${batchId}/commit`, {
      method: "POST",
      body: JSON.stringify({ version: activeImportPreview.version }),
    });

    showMessage(
      "import-message",
      `${result.created_count} physical inventory item${result.created_count === 1 ? "" : "s"} created. Running identity, image and pricing enrichment…`
    );

    const enrichment = await runImportEnrichment(batchId, defaultLanguage);
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
    showMessage("import-message", error.message, "error");
  } finally {
    button.disabled = false;
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

