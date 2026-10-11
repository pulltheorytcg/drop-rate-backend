"use strict";

/* Seller Hub Inventory → Import. Reuses the canonical founder import engine
   through an owner-only, allowlisted API. No file silently publishes to
   Shopify: an explicit upload adds verified matches as Draft and leaves exceptions for review. */
(() => {
  const $ = (id) => document.getElementById(id);
  const menu = $("owner-import-menu");
  const trigger = $("owner-import-trigger");
  const template = $("owner-import-template");
  if (!menu || !trigger || !template) return;

  const PAGE_SIZE = 40;
  const MAP_FIELDS = [
    ["name", "Card / product name"],
    ["game", "TCG / game"],
    ["set_name", "Set"],
    ["card_number", "Card number"],
    ["quantity", "Quantity"],
    ["variant", "Variant / foil"],
    ["rarity", "Rarity"],
    ["language", "Language"],
    ["condition", "Condition"],
    ["grade", "Grade"],
    ["grading_company", "Grading company"],
    ["certificate_number", "Certificate number"],
    ["purchase_price", "Cost paid"],
    ["seal_status", "Sealed status"],
    ["product_type", "Product type"],
  ];
  const KNOWN_ADAPTERS = new Set(["COLLECTR", "HOLODEX", "GENERIC_CSV", "AUTO"]);
  const state = {
    dialog: null, generation: 0, busy: false, batch: null,
    candidates: [], summary: null, warnings: [], page: 0,
    filter: "ALL", headers: [], fileContents: null,
  };

  const setText = (id, value) => {$(id).textContent = String(value ?? "");};
  const node = (tag, value, className = "") => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    result.textContent = String(value ?? "");
    return result;
  };
  const parseJSON = (v, fallback) => {
    if (typeof v !== "string") return v ?? fallback;
    try {return JSON.parse(v);} catch (_error) {return fallback;}
  };
  const normalizeCandidate = (source) => ({
    ...source,
    normalized_record: parseJSON(source.normalized_record, {}),
    issues: parseJSON(source.issues, []),
  });

  function message(value, mode = "") {
    const current = $("owner-import-message");
    if (!current) return;
    current.textContent = String(value || "");
    current.className = "owner-import-message" + (mode ? " is-" + mode : "");
  }

  function setBusy(active) {
    state.busy = Boolean(active);
    for (const id of ["owner-import-preview", "owner-import-commit"]) {
      const control = $(id);
      if (control) control.disabled = state.busy || (
        id === "owner-import-commit" && !canCommit()
      );
    }
    if ($("owner-import-file")) $("owner-import-file").disabled = state.busy;
  }

  function ensureDialog() {
    if (state.dialog) return state.dialog;
    // Lazy mounting protects pre-existing inventory/scanner dialog order.
    const dialog = template.content.firstElementChild.cloneNode(true);
    document.body.append(dialog);
    state.dialog = dialog;

    $("owner-import-preview").textContent = "Import collection";
    $("owner-import-preview-title").textContent = "Import results";
    $("owner-import-close").addEventListener("click", closeDialog);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog();
    });
    $("owner-import-form").addEventListener("submit", previewFile);
    $("owner-import-file").addEventListener("change", inspectFile);
    $("owner-import-commit").addEventListener("click", commitDrafts);
    $("owner-import-adapter").addEventListener("change", () => {
      if (state.batch) resetPreview();
      updateMappingHelp();
    });
    $("owner-import-filter").addEventListener("change", (event) => {
      state.filter = event.currentTarget.value || "ALL";
      state.page = 0;
      renderCandidates();
    });
    $("owner-import-prev").addEventListener("click", () => {
      state.page = Math.max(0, state.page - 1);
      renderCandidates();
    });
    $("owner-import-next").addEventListener("click", () => {
      state.page += 1;
      renderCandidates();
    });
    $("owner-import-refresh-history").addEventListener("click", loadHistory);
    return dialog;
  }

  function hideMenu() {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }
  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.hidden = !menu.hidden;
    trigger.setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("click", (event) => {
    if (!menu.hidden && !menu.contains(event.target) && event.target !== trigger) hideMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideMenu();
  });
  menu.querySelectorAll("[data-owner-import-adapter]").forEach((button) => {
    button.addEventListener("click", () => openImport(button.dataset.ownerImportAdapter));
  });

  function resetPreview() {
    state.batch = null;
    state.candidates = [];
    state.summary = null;
    state.warnings = [];
    state.page = 0;
    state.filter = "ALL";
    if ($("owner-import-preview-section")) $("owner-import-preview-section").hidden = true;
    if ($("owner-import-commit")) {
      $("owner-import-commit").disabled = true;
      $("owner-import-commit").hidden = true;
    }
    if ($("owner-import-filter")) $("owner-import-filter").value = "ALL";
    if ($("owner-import-rows")) $("owner-import-rows").replaceChildren();
  }

  function closeDialog() {
    state.generation++;
    state.fileContents = null;
    state.headers = [];
    resetPreview();
    if (state.dialog?.open) state.dialog.close();
  }

  async function openImport(adapter) {
    if (!KNOWN_ADAPTERS.has(adapter)) return;
    hideMenu();
    const dialog = ensureDialog();
    state.generation++;
    state.fileContents = null;
    state.headers = [];
    $("owner-import-form").reset();
    $("owner-import-adapter").value = adapter;
    $("owner-import-map-fields").replaceChildren();
    $("owner-import-map-details").open = false;
    resetPreview();
    message("Upload your collection: verified matches are added as Draft; only uncertain rows need confirmation.");
    updateMappingHelp();
    if (!dialog.open) dialog.showModal();
    await loadHistory();
  }

  function updateMappingHelp() {
    const adapter = $("owner-import-adapter")?.value;
    const details = $("owner-import-map-details");
    if (details) details.hidden = adapter === "COLLECTR";
  }

  // Parse only a header record, including quoted delimiter/newline and a
  // UTF-8 BOM; leave authoritative CSV data parsing to FastAPI.
  function readHeaders(contents, delimiter) {
    const input = String(contents || "").replace(/^\uFEFF/, "");
    const result = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < input.length && i < 20000; i++) {
      const char = input[i];
      if (char === '"') {
        if (quoted && input[i + 1] === '"') {field += '"'; i++;}
        else quoted = !quoted;
      } else if (!quoted && char === delimiter) {
        result.push(field.trim()); field = "";
      } else if (!quoted && (char === "\n" || char === "\r")) {
        result.push(field.trim());
        return result.filter(Boolean).slice(0, 80);
      } else {
        field += char;
      }
    }
    if (field.trim()) result.push(field.trim());
    return result.filter(Boolean).slice(0, 80);
  }

  async function inspectFile() {
    state.fileContents = null;
    state.headers = [];
    resetPreview();
    const file = $("owner-import-file").files?.[0];
    $("owner-import-map-fields").replaceChildren();
    if (!file) return;
    if (!/\.(csv|tsv)$/i.test(file.name)) {
      message("Choose a CSV or tab-separated TSV file.", "error");
      return;
    }
    if (file.size > 8_000_000) {
      message("The import limit is 8 MB per file.", "error");
      return;
    }
    const generation = state.generation;
    try {
      const contents = await file.text();
      if (generation !== state.generation || !state.dialog?.open ||
          file !== $("owner-import-file").files?.[0]) return;
      if (contents.length > 8_000_000) throw new Error("File contains more than 8 MB of text.");
      const headers = readHeaders(contents, /\.tsv$/i.test(file.name) ? "\t" : ",");
      if (!headers.length) throw new Error("No column headers were found in this file.");
      state.headers = headers;
      state.fileContents = contents;
      buildMappings(headers);
      message(`${file.name} · ${headers.length} headers detected. Import to add recognised cards and review the remainder.`);
    } catch (_error) {
      message("Could not read this CSV/TSV file. Export again as UTF-8 text.", "error");
    }
  }

  function buildMappings(headers) {
    const container = $("owner-import-map-fields");
    container.replaceChildren();
    for (const [key, label] of MAP_FIELDS) {
      const wrap = node("label", label);
      const select = document.createElement("select");
      select.dataset.ownerImportField = key;
      select.append(node("option", "Auto-detect"));
      select.firstChild.value = "";
      for (const header of headers) {
        const option = node("option", header);
        option.value = header;
        select.append(option);
      }
      wrap.append(select);
      container.append(wrap);
    }
  }

  function chosenMapping() {
    const mapped = {};
    $("owner-import-map-fields").querySelectorAll("[data-owner-import-field]").forEach((select) => {
      if (select.value) mapped[select.dataset.ownerImportField] = select.value;
    });
    return mapped;
  }

  async function requestPreview(event) {
    event.preventDefault();
    await previewFile();
  }

  async function previewFile(event) {
    event?.preventDefault?.();
    if (state.busy) return;
    const file = $("owner-import-file").files?.[0];
    if (!file || !state.fileContents || !state.headers.length) {
      message("Select a valid CSV or TSV file first.", "error");
      return;
    }
    const generation = state.generation;
    setBusy(true);
    message("Checking exact matches and adding recognised Draft copies…");
    try {
      const preview = await apiRequest("/api/v1/owner/imports/upload", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content: state.fileContents,
          adapter: $("owner-import-adapter").value,
          default_game: $("owner-import-game").value || null,
          default_language: $("owner-import-language").value || null,
          column_mapping: chosenMapping(),
        }),
      });
      if (generation !== state.generation || !state.dialog?.open) return;
      const stored = await apiRequest(
        `/api/v1/owner/imports/${encodeURIComponent(preview.batch_id)}`
      );
      if (generation !== state.generation || !state.dialog?.open) return;
      loadPreview(stored, preview);
      message(`${state.summary.added_units} copies added to your inventory. ${state.summary.review_rows} rows need confirmation. Nothing is published.`, "success");
      await refreshInventory();
      await loadHistory();
    } catch (_error) {
      if (generation !== state.generation || !state.dialog?.open) return;
      message("Import could not finish. Check Recent imports for any copies already added and rows still needing review; do not upload it as Other.", "error");
      await loadHistory();
    } finally {
      if (generation === state.generation) setBusy(false);
    }
  }

  function loadPreview(stored, compact = null) {
    if (!stored?.batch || !Array.isArray(stored.candidates)) {
      throw new Error("Invalid stored CSV preview");
    }
    state.batch = {
      id: String(stored.batch.id),
      status: stored.batch.status,
      automatic_intake: Boolean(stored.batch.automatic_intake),
      version: Number(stored.batch.version),
      adapter: stored.batch.adapter,
      source_rows: Number(stored.batch.source_rows || 0),
      physical_units: Number(stored.batch.physical_units || 0),
    };
    state.candidates = stored.candidates.map(normalizeCandidate);
    state.warnings = parseJSON(stored.batch.warnings, []);
    if (!Array.isArray(state.warnings)) state.warnings = [];
    const summary = {
      added_units: state.candidates.filter(x => x.status === "COMMITTED").reduce((total, x) => total + Number(x.quantity || 0), 0),
      review_units: state.candidates.filter(x => x.status === "REVIEW").reduce((total, x) => total + Number(x.quantity || 0), 0),
      ready_units: state.candidates.filter(x => x.status === "READY")
        .reduce((total, x) => total + Number(x.quantity || 0), 0),
      review_rows: state.candidates.filter(x => x.status === "REVIEW").length,
      skipped_rows: state.candidates.filter(x => x.status === "SKIPPED").length,
    };
    // Use authoritative totals when the mutation returns them.
    state.summary = {...summary, ...(compact?.summary || {})};
    state.filter = state.batch.automatic_intake && summary.review_rows ? "REVIEW" : "ALL";
    state.page = 0;
    $("owner-import-filter").value = state.filter;
    $("owner-import-preview-section").hidden = false;
    renderPreview();
  }

  function canCommit() {
    return Boolean(state.batch && state.batch.status === "PREVIEW" &&
      state.summary && Number.isInteger(state.batch.version) && (!state.batch.automatic_intake || state.summary.ready_units > 0));
  }

  function renderPreview() {
    const summary = $("owner-import-summary");
    summary.replaceChildren();
    for (const [value, title] of [
      [state.batch.physical_units, "Copies in source"],
      [state.summary.added_units, "Copies added to inventory"],
      [state.summary.review_rows, `Rows needing review (${state.summary.review_units} copies)`],
    ]) {
      const block = document.createElement("div");
      block.append(node("strong", String(value)), node("span", title));
      summary.append(block);
    }
    setText("owner-import-warnings",
      state.warnings.join(" ") +
      (state.batch.adapter === "COLLECTR"
        ? " Collectr re-exports reconcile changed quantities; do not import the same collection as Other."
        : " Other exports add new physical copies; only exact-file retries are deduplicated.")
    );
    const commit = $("owner-import-commit");
    commit.hidden = state.batch.status !== "PREVIEW" || (state.batch.automatic_intake && !state.summary.ready_units);
    commit.disabled = !canCommit() || state.busy;
    commit.textContent = "Add recognised cards; review the rest";
    renderCandidates();
  }

  function visibleCandidates() {
    return state.filter === "ALL" ? state.candidates :
      state.candidates.filter(x => x.status === state.filter);
  }

  function renderCandidates() {
    const list = $("owner-import-rows");
    list.replaceChildren();
    const candidates = visibleCandidates();
    const pages = Math.max(1, Math.ceil(candidates.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages - 1);
    const start = state.page * PAGE_SIZE;
    const page = candidates.slice(start, start + PAGE_SIZE);
    setText("owner-import-page",
      candidates.length ? `${start + 1}–${Math.min(start + PAGE_SIZE, candidates.length)} of ${candidates.length}` : "0 rows"
    );
    $("owner-import-prev").disabled = state.page === 0;
    $("owner-import-next").disabled = state.page >= pages - 1;
    if (!page.length) {
      list.append(node("p", "No rows match this filter.", "owner-import-warnings"));
      return;
    }
    for (const candidate of page) {
      const normalized = candidate.normalized_record || {};
      const row = document.createElement("article");
      row.className = "owner-import-row";
      const info = document.createElement("div");
      info.append(node("strong", normalized.name || `Source row ${candidate.source_row}`));
      const delta = normalized.reconciliation === "SNAPSHOT_DELTA"
        ? `Previous ${normalized.previous_quantity ?? 0} · Snapshot ${normalized.snapshot_quantity ?? 0} · Add ${Math.max(0, Number(normalized.delta_quantity || 0))}`
        : `Qty ${candidate.quantity || 0}`;
      info.append(node("small", [
        normalized.game, normalized.set_name, normalized.card_number,
        normalized.language, delta,
      ].filter(Boolean).join(" · ")));
      const side = document.createElement("div");
      side.append(node("strong",
        candidate.status === "READY" ? "Ready" :
        candidate.status === "SKIPPED" ? "Skipped" :
        candidate.status === "COMMITTED" ? "Imported" : "Needs review",
        "owner-import-status"));
      if (Array.isArray(candidate.issues) && candidate.issues.length) {
        side.append(node("small", candidate.issues.join(" · ").replace(/_/g, " ")));
      }
      if (candidate.status === "REVIEW" && state.batch.status === "PREVIEW") {
        const actions = document.createElement("div");
        actions.className = "owner-import-row-actions";
        const resolve = node("button", "Find match");
        resolve.type = "button";
        resolve.addEventListener("click", () => openCatalogueMatch(row, candidate));
        const skip = node("button", "Skip");
        skip.type = "button";
        skip.addEventListener("click", () => skipCandidate(candidate, skip));
        actions.append(resolve, skip);
        side.append(actions);
      }
      row.append(info, side);
      list.append(row);
    }
  }

  async function refreshInventory() {
    await Promise.allSettled([
      typeof loadOwnerInventory === "function" ? loadOwnerInventory() : Promise.resolve(),
      typeof loadOwnerOverview === "function" ? loadOwnerOverview() : Promise.resolve(),
    ]);
  }

  async function updateCandidate(result) {
    if (!state.batch || state.batch.id !== String(result.batch_id)) return;
    const generation = state.generation;
    const stored = await apiRequest(`/api/v1/owner/imports/${encodeURIComponent(result.batch_id)}`);
    if (generation !== state.generation || !state.dialog?.open) return;
    loadPreview(stored, result);
    await refreshInventory();
  }

  async function skipCandidate(candidate, button) {
    if (!state.batch || !window.confirm(`Skip source row ${candidate.source_row}? It will not add this physical stock.`)) return;
    const batchId = state.batch.id;
    button.disabled = true;
    try {
      const result = await apiRequest(
        `/api/v1/owner/imports/${encodeURIComponent(batchId)}/candidates/${encodeURIComponent(candidate.id)}/skip`,
        {method: "POST", body: JSON.stringify({version: state.batch.version})}
      );
      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      await updateCandidate(result);
      message(`Source row ${candidate.source_row} will not be added.`, "success");
    } catch (_error) {
      message("This row could not be skipped. Refresh the import preview and retry.", "error");
      button.disabled = false;
    }
  }

  async function openCatalogueMatch(row, candidate) {
    if (row.querySelector(".owner-import-resolver")) return;
    const section = document.createElement("section");
    section.className = "owner-import-resolver";
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search existing card name, number or set";
    input.maxLength = 150;
    const normalized = candidate.normalized_record || {};
    input.value = [normalized.card_number || normalized.name, normalized.set_name]
      .filter(Boolean).join(" ").slice(0, 150);
    const search = node("button", "Search Drop Rate catalogue");
    search.type = "button";
    const languageLabel = node("label", "Confirm language only when missing or conflicting");
    const language = document.createElement("select");
    language.setAttribute("aria-label", "Card language confirmation");
    for (const [value, text] of [["", "Use selected card language"], ["English", "English"], ["Japanese", "Japanese"], ["Chinese", "Chinese"], ["Korean", "Korean"], ["French", "French"], ["German", "German"], ["Italian", "Italian"], ["Spanish", "Spanish"], ["Portuguese", "Portuguese"]]) {
      const option = node("option", text); option.value = value; language.append(option);
    }
    languageLabel.append(language);
    const results = document.createElement("div");
    results.className = "owner-import-resolver-results";
    const runSearch = async () => {
      const term = input.value.trim();
      if (term.length < 2) {
        results.replaceChildren(node("p", "Enter at least two characters."));
        return;
      }
      search.disabled = true;
      results.replaceChildren(node("small", "Searching existing catalogue…"));
      try {
        const url = new URLSearchParams({q: term, product_type: normalized.product_type || "CARD"});
        const data = await apiRequest(`/api/v1/owner/imports/catalogue-search?${url.toString()}`);
        results.replaceChildren();
        if (!Array.isArray(data.items) || !data.items.length) {
          results.append(node("small",
            "No existing match. Ask Drop Rate to review the missing catalogue identity, or skip this source row."));
          return;
        }
        for (const item of data.items) {
          const itemRow = document.createElement("div");
          itemRow.className = "owner-import-resolver-result";
          const description = document.createElement("div");
          description.append(node("strong", item.name || "Catalogue item"));
          description.append(node("small", [
            item.game, item.set_name, item.card_number, item.variant, item.language,
          ].filter(Boolean).join(" · ")));
          const choose = node("button", state.batch.automatic_intake ? "Confirm and add" : "Confirm match");
          choose.type = "button";
          choose.addEventListener("click", () => resolveCandidate(candidate, item.id, choose, language.value || null));
          itemRow.append(description, choose);
          results.append(itemRow);
        }
      } catch (_error) {
        results.replaceChildren(node("small", "Catalogue search unavailable. Try again."));
      } finally {
        search.disabled = false;
      }
    };
    search.addEventListener("click", runSearch);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {event.preventDefault();runSearch();}
    });
    section.append(input, search, languageLabel, results);
    row.append(section);
    input.focus();
    await runSearch();
  }

  async function resolveCandidate(candidate, catalogueId, button, language = null) {
    if (!state.batch) return;
    const batchId = state.batch.id;
    button.disabled = true;
    try {
      const result = await apiRequest(
        `/api/v1/owner/imports/${encodeURIComponent(batchId)}/candidates/${encodeURIComponent(candidate.id)}/resolve`,
        {
          method: "POST",
          body: JSON.stringify({version: state.batch.version, catalogue_id: catalogueId, language}),
        }
      );
      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      await updateCandidate(result);
      message(result.candidate?.status === "COMMITTED" ? "Confirmed card added to your Draft inventory." : "Match saved. Any remaining missing facts still need confirmation.", "success");
    } catch (_error) {
      message("Confirmation could not finish. Refresh the import to check its current result before retrying.", "error");
      button.disabled = false;
    }
  }

  async function commitDrafts() {
    if (!canCommit() || state.busy) return;
    const batchId = state.batch.id;
    setBusy(true);
    message("Creating your Draft physical inventory. Nothing will publish to Shopify.");
    try {
      const result = await apiRequest(
        `/api/v1/owner/imports/${encodeURIComponent(batchId)}/commit`,
        {method: "POST", body: JSON.stringify({version: state.batch.version})}
      );
      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      const stored = await apiRequest(`/api/v1/owner/imports/${encodeURIComponent(batchId)}`);
      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      loadPreview(stored);
      message(`${state.summary.added_units} copies added. ${state.summary.review_rows} rows still need confirmation. Nothing is published.`, "success");
      await loadHistory();
      // Account-level inventory is the only affected UI. Avoid new
      // publication/AI enrichment/settlement side effects.
      await Promise.allSettled([
        typeof loadOwnerInventory === "function" ? loadOwnerInventory() : Promise.resolve(),
        typeof loadOwnerOverview === "function" ? loadOwnerOverview() : Promise.resolve(),
      ]);
    } catch (_error) {
      message("Import could not finish. Refresh this batch to check which copies were already added before retrying.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function loadHistory() {
    if (!state.dialog?.open) return;
    const generation = state.generation;
    const list = $("owner-import-history-list");
    list.replaceChildren(node("small", "Checking previous imports…"));
    try {
      const data = await apiRequest("/api/v1/owner/imports?limit=8");
      if (generation !== state.generation || !state.dialog?.open) return;
      list.replaceChildren();
      const rows = Array.isArray(data.items) ? data.items : [];
      if (!rows.length) {
        list.append(node("small", "No previous collection imports."));
        return;
      }
      for (const entry of rows) {
        const row = document.createElement("div");
        row.className = "owner-import-history-row";
        const copy = document.createElement("div");
        copy.append(node("strong", entry.filename || "CSV import"));
        copy.append(node("small", [
          entry.adapter, entry.source_rows ? `${entry.source_rows} source rows` : "",
          entry.status === "PREVIEW" ? "Review remaining" : entry.status,
        ].filter(Boolean).join(" · ")));
        if (entry.status === "PREVIEW") {
          const resume = node("button", "Resume review");
          resume.type = "button";
          resume.addEventListener("click", async () => {
            resume.disabled = true;
            try {
              const stored = await apiRequest(
                `/api/v1/owner/imports/${encodeURIComponent(entry.id)}`
              );
              if (!state.dialog?.open) return;
              loadPreview(stored);
              message("Import restored. Added copies stay in your inventory; review only the remaining rows.");
            } catch (_error) {
              message("Could not resume this import. Refresh and try again.", "error");
            } finally {
              resume.disabled = false;
            }
          });
          row.append(copy, resume);
        } else {
          row.append(copy, node("small", "Completed"));
        }
        list.append(row);
      }
    } catch (_error) {
      if (generation === state.generation) {
        list.replaceChildren(node("small", "Import history unavailable."));
      }
    }
  }

  document.addEventListener("owner-view-changed", (event) => {
    if (event.detail?.view !== "inventory") {
      hideMenu();
      closeDialog();
    }
  });
  $("owner-logout-button")?.addEventListener("click", () => {
    hideMenu();
    closeDialog();
  }, {capture: true});
})();
