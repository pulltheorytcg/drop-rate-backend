"use strict";

const marketMappingState = {
  catalogue: null,
  mappings: [],
  candidates: [],
  previewItems: [],
  source: null,
};

function mappingText(value, fallback = "—") {
  const clean = value === null || value === undefined ? "" : String(value).trim();
  return clean || fallback;
}

function shortProviderId(value) {
  const text = mappingText(value);
  return text.length > 72 ? `${text.slice(0, 69)}…` : text;
}

function marketMappingMeta(item) {
  return [item.game, item.set_name, item.card_number, item.variant, item.language]
    .filter(Boolean)
    .join(" · ");
}

function renderCatalogueResults(items) {
  const container = byId("market-mapping-catalogue-results");
  container.replaceChildren();
  if (!items.length) {
    container.textContent = "No catalogue matches found.";
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = marketMappingMeta(item);
    details.append(name, meta);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary-button compact";
    button.textContent = "Map this card";
    button.addEventListener("click", () => selectMarketCatalogue(item));

    row.append(details, button);
    container.append(row);
  });
}

async function searchMarketCatalogue() {
  const input = byId("market-mapping-search");
  const button = byId("market-mapping-search-button");
  const query = input?.value.trim() || "";
  if (query.length < 2) {
    byId("market-mapping-catalogue-results").textContent = "Enter at least 2 characters.";
    return;
  }

  button.disabled = true;
  byId("market-mapping-catalogue-results").textContent = "Searching catalogue…";
  try {
    const data = await apiRequest(`/api/v1/catalogue/search?q=${encodeURIComponent(query)}&limit=10`);
    renderCatalogueResults(data.items || []);
  } catch (error) {
    byId("market-mapping-catalogue-results").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function loadMarketMappings() {
  const container = byId("market-mapping-existing");
  if (!marketMappingState.catalogue) {
    container.textContent = "Select a catalogue card first.";
    return;
  }

  container.textContent = "Loading mappings…";
  try {
    const data = await apiRequest(
      `/api/v1/market/mappings?catalogue_id=${encodeURIComponent(marketMappingState.catalogue.id)}&limit=100`,
    );
    marketMappingState.mappings = data.items || [];
    renderMarketMappings();
    await loadPricingPreviewItems();
  } catch (error) {
    container.textContent = error.message;
  }
}

function mappingDecisionButton(mapping, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = action === "verify" ? "primary-button compact" : "ghost-button";
  button.textContent = action === "verify" ? "Verify mapping" : "Reject";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await apiRequest(`/api/v1/market/mappings/${mapping.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: mapping.version,
          match_confidence: action === "verify" ? 1.0 : 0,
          reason: action === "verify"
            ? "Founder verified in market mapping workbench"
            : "Founder rejected in market mapping workbench",
        }),
      });
      await loadMarketMappings();
      await loadPricingAdapterStatus();
    } catch (error) {
      byId("market-mapping-message").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function renderMarketMappings() {
  const container = byId("market-mapping-existing");
  container.replaceChildren();

  if (!marketMappingState.mappings.length) {
    container.textContent = "No mappings exist for this catalogue card yet.";
    return;
  }

  marketMappingState.mappings.forEach((mapping) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${mapping.source} · ${mapping.match_status}`;
    const meta = document.createElement("small");
    meta.textContent = [
      shortProviderId(mapping.source_product_id),
      mapping.source_variant_id ? `variant: ${mapping.source_variant_id}` : null,
      `confidence: ${Math.round(Number(mapping.match_confidence || 0) * 100)}%`,
    ].filter(Boolean).join(" · ");
    details.append(title, meta);

    const actions = document.createElement("div");
    const unsafeLegacyCardmarket =
      mapping.match_status === "REVIEW" &&
      mapping.source === "CARDMARKET" &&
      String(marketMappingState.catalogue?.game || "").toLowerCase() === "pokemon" &&
      !mapping.source_variant_id;

    if (unsafeLegacyCardmarket) {
      const warning = document.createElement("small");
      warning.textContent = "Missing provider variant — reject and recreate this mapping.";
      actions.append(warning, mappingDecisionButton(mapping, "reject"));
    } else if (mapping.match_status === "REVIEW") {
      actions.append(mappingDecisionButton(mapping, "verify"), mappingDecisionButton(mapping, "reject"));
    } else {
      const status = document.createElement("strong");
      status.textContent = mapping.match_status;
      actions.append(status);
    }
    row.append(details, actions);
    container.append(row);
  });
}

function candidateMeta(candidate) {
  const signals = candidate.match_signals?.length
    ? `signals: ${candidate.match_signals.join(", ")}`
    : "no exact identity signals";
  return [
    candidate.set_name,
    candidate.card_number,
    candidate.rarity,
    candidate.market_price !== null && candidate.market_price !== undefined
      ? `provider price: ${candidate.market_price}`
      : null,
    signals,
    `suggested confidence: ${Math.round(Number(candidate.suggested_confidence || 0) * 100)}%`,
  ].filter(Boolean).join(" · ");
}

async function createReviewMapping(candidate, variantInput, button) {
  if (!marketMappingState.catalogue) return;
  button.disabled = true;
  byId("market-mapping-message").textContent = "Creating REVIEW mapping…";
  try {
    await apiRequest("/api/v1/market/mappings", {
      method: "POST",
      body: JSON.stringify({
        catalogue_id: marketMappingState.catalogue.id,
        source: candidate.source,
        source_product_id: candidate.source_product_id,
        source_variant_id: variantInput.value.trim() || null,
        match_confidence: Number(candidate.suggested_confidence || 0),
        metadata: {
          origin: "MARKET_MAPPING_WORKBENCH",
          discovery_signals: candidate.match_signals || [],
        },
      }),
    });
    byId("market-mapping-message").textContent =
      "REVIEW mapping created. Verify it only after checking the provider identity.";
    marketMappingState.candidates = [];
    byId("market-mapping-candidates").textContent = "Mapping created. Choose another provider or verify the REVIEW mapping above.";
    await loadMarketMappings();
    await loadPricingAdapterStatus();
  } catch (error) {
    byId("market-mapping-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderMarketCandidates() {
  const container = byId("market-mapping-candidates");
  container.replaceChildren();

  if (!marketMappingState.candidates.length) {
    container.textContent = "No provider candidates returned. Try another source.";
    return;
  }

  marketMappingState.candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = mappingText(candidate.name, candidate.source_product_id);
    const meta = document.createElement("small");
    meta.textContent = candidateMeta(candidate);
    const providerId = document.createElement("small");
    providerId.textContent = `Provider ID: ${shortProviderId(candidate.source_product_id)}`;
    details.append(title, meta, providerId);

    const controls = document.createElement("div");
    const variantInput = document.createElement("input");
    variantInput.type = "text";
    variantInput.maxLength = 1000;
    variantInput.placeholder = "Provider variant (optional)";
    variantInput.value = candidate.source_variant_id || "";
    if (
      candidate.source === "CARDMARKET" &&
      String(marketMappingState.catalogue?.game || "").toLowerCase() === "pokemon"
    ) {
      variantInput.readOnly = true;
      variantInput.placeholder = "Cardmarket variant";
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary-button compact";
    button.textContent = "Create REVIEW mapping";
    button.addEventListener("click", () => createReviewMapping(candidate, variantInput, button));

    controls.append(variantInput, button);
    row.append(details, controls);
    container.append(row);
  });
}

async function discoverMarketSource(source) {
  if (!marketMappingState.catalogue) return;
  marketMappingState.source = source;
  const container = byId("market-mapping-candidates");
  container.textContent = `Searching ${source}…`;
  byId("market-mapping-message").textContent =
    "Discovery is non-persistent. A candidate must still become REVIEW and be verified manually.";

  try {
    const data = await apiRequest(
      `/api/v1/market/discovery/${source}?catalogue_id=${encodeURIComponent(marketMappingState.catalogue.id)}`,
    );
    marketMappingState.candidates = data.candidates || [];
    renderMarketCandidates();
  } catch (error) {
    marketMappingState.candidates = [];
    container.textContent = error.message;
  }
}

function previewItemMeta(item) {
  const physical = [
    item.condition ? `Condition: ${item.condition}` : null,
    item.grade ? `Grading: ${item.grading_company || "Graded"} ${item.grade}` : null,
    item.seal_status ? `Seal: ${item.seal_status === "SEALED" ? "Sealed" : "Unsealed"}` : null,
  ].filter(Boolean);
  return [
    item.inventory_code,
    ...physical,
    physical.length ? null : "Physical state incomplete",
    item.language,
    item.identity_confirmed ? "identity confirmed" : "identity unconfirmed",
    item.status,
  ].filter(Boolean).join(" · ");
}

function renderEvidenceSources(container, sources) {
  (sources || []).forEach((source) => {
    const sourceBlock = document.createElement("div");
    sourceBlock.className = "pricing-evidence-source";

    const heading = document.createElement("small");
    heading.textContent = `${source.source} · ${source.status} · ${source.observation_count || 0} observations`;
    sourceBlock.append(heading);

    (source.evidence_sample || []).forEach((evidence) => {
      const row = document.createElement("small");
      const physical = [
        evidence.condition ? `Condition: ${evidence.condition}` : null,
        evidence.grade ? `Grading: ${evidence.grading_company || "Graded"} ${evidence.grade}` : null,
        evidence.seal_status ? `Seal: ${evidence.seal_status === "SEALED" ? "Sealed" : "Unsealed"}` : null,
      ].filter(Boolean);
      row.textContent = [
        evidence.observation_type,
        money(evidence.price_gbp_minor),
        ...physical,
        physical.length ? null : "physical state unspecified",
        evidence.language,
        evidence.source_country,
        evidence.sample_size > 1 ? `sample ${evidence.sample_size}` : null,
      ].filter(Boolean).join(" · ");
      sourceBlock.append(row);
    });

    container.append(sourceBlock);
  });
}

function renderPricingPreviewResult(container, data) {
  container.replaceChildren();
  const headline = document.createElement("strong");
  const details = document.createElement("small");

  if (data.status !== "PREVIEW" || !data.pricing) {
    headline.textContent = "Preview blocked safely";
    details.textContent = [
      ...(data.block_reasons || []),
      ...(data.warnings || []),
    ].join(" · ") || "No comparable live evidence was available.";
    container.append(headline, details);
    renderEvidenceSources(container, data.sources);
    return;
  }

  const pricing = data.pricing;
  headline.textContent =
    `${money(pricing.market_value_minor)} market · ${money(pricing.recommended_retail_minor)} retail`;
  details.textContent = [
    `${money(pricing.quick_sale_minor)} quick sale`,
    `${money(pricing.target_acquisition_minor)} target acquisition`,
    `${Math.round(Number(pricing.confidence || 0) * 100)}% confidence`,
    `${pricing.source_count} sources`,
    `${pricing.observation_count} comparable observations`,
    ...(data.warnings || []),
    ...(pricing.engine_block_reasons || []),
  ].join(" · ");
  container.append(headline, details);
  renderEvidenceSources(container, data.sources);
}

async function runPricingPreview(item, button, resultNode) {
  button.disabled = true;
  button.dataset.label ||= button.textContent;
  button.textContent = "Calculating…";
  resultNode.textContent = "Fetching live evidence and running the deterministic pricing engine…";
  try {
    const data = await apiRequest(`/api/v1/pricing/preview/${item.id}`, {method: "POST"});
    renderPricingPreviewResult(resultNode, data);
  } catch (error) {
    resultNode.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = button.dataset.label;
  }
}

function renderPricingPreviewItems() {
  const container = byId("market-pricing-preview-items");
  if (!container) return;
  container.replaceChildren();

  if (!marketMappingState.previewItems.length) {
    container.textContent = "No active physical inventory copies reference this catalogue card.";
    return;
  }

  const hasVerified = marketMappingState.mappings.some((mapping) => mapping.match_status === "VERIFIED");

  marketMappingState.previewItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.inventory_code;
    const meta = document.createElement("small");
    meta.textContent = previewItemMeta(item);
    const result = document.createElement("div");
    result.className = "pricing-preview-result";
    result.textContent = hasVerified
      ? "Nothing will be saved. Run a live diagnostic preview when ready."
      : "Verify at least one provider mapping before previewing.";
    details.append(title, meta, result);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = "Preview live price";
    button.disabled = !hasVerified;
    button.addEventListener("click", () => runPricingPreview(item, button, result));

    row.append(details, button);
    container.append(row);
  });
}

async function loadPricingPreviewItems() {
  const container = byId("market-pricing-preview-items");
  if (!container || !marketMappingState.catalogue) return;
  container.textContent = "Loading physical copies…";
  try {
    const data = await apiRequest(
      `/api/v1/pricing/preview-items/${encodeURIComponent(marketMappingState.catalogue.id)}`,
    );
    marketMappingState.previewItems = data.items || [];
    renderPricingPreviewItems();
  } catch (error) {
    marketMappingState.previewItems = [];
    container.textContent = error.message;
  }
}

async function selectMarketCatalogue(item) {
  marketMappingState.catalogue = item;
  marketMappingState.candidates = [];

  const selected = byId("market-mapping-selected");
  selected.classList.remove("hidden");
  byId("market-mapping-selected-name").textContent = item.name;
  byId("market-mapping-selected-meta").textContent = marketMappingMeta(item);
  byId("market-mapping-candidates").textContent = "Choose a provider to discover candidates.";
  byId("market-mapping-message").textContent = "";
  await loadMarketMappings();
}

function installMarketMappingWorkbench() {
  if (byId("market-mapping-workbench")) return;
  const settings = byId("seller-view-settings");
  if (!settings) return;

  const panel = document.createElement("section");
  panel.id = "market-mapping-workbench";
  panel.className = "inventory-panel";
  panel.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Identity bridge</p>
        <h2>Market Mapping Workbench</h2>
        <p class="muted">Connect a canonical Drop Rate card to provider identities. Discovery never writes pricing evidence. New mappings start in REVIEW and require an explicit human verification before future ingestion can use them.</p>
      </div>
    </div>
    <div class="toolbar">
      <label class="search-box"><span>⌕</span><input id="market-mapping-search" type="search" maxlength="200" placeholder="Search card name, number or set…"></label>
      <button id="market-mapping-search-button" class="ghost-button" type="button">Search catalogue</button>
    </div>
    <div id="market-mapping-catalogue-results" class="allocation-list"><p class="muted">Search for the canonical card you want to map.</p></div>
    <div id="market-mapping-selected" class="hidden">
      <div class="page-heading pricing-subheading">
        <div><p class="eyebrow">Selected card</p><h2 id="market-mapping-selected-name"></h2><p id="market-mapping-selected-meta" class="muted"></p></div>
        <div class="topbar-actions">
          <button class="ghost-button" type="button" data-market-source="CARDMARKET">Cardmarket</button>
          <button class="ghost-button" type="button" data-market-source="TCGPLAYER">TCGPlayer</button>
          <button class="ghost-button" type="button" data-market-source="COLLECTR">Collectr</button>
        </div>
      </div>
      <p class="muted">eBay sold discovery remains excluded here while the upstream sold endpoint returns empty results. eBay active data remains diagnostic only.</p>
      <div id="market-mapping-message" class="message"></div>
      <div class="page-heading pricing-subheading"><div><p class="eyebrow">Trust decision</p><h3>Existing mappings</h3></div></div>
      <div id="market-mapping-existing" class="allocation-list"></div>
      <div class="page-heading pricing-subheading"><div><p class="eyebrow">Discovery</p><h3>Provider candidates</h3></div></div>
      <div id="market-mapping-candidates" class="allocation-list"></div>
      <div class="page-heading pricing-subheading">
        <div>
          <p class="eyebrow">End-to-end validation</p>
          <h3>Diagnostic pricing preview</h3>
          <p class="muted">Uses the selected card's VERIFIED mappings and a real physical inventory copy. Live evidence is normalized and priced in memory only: no observations, snapshots, Market Value or Store Price are saved.</p>
        </div>
      </div>
      <div id="market-pricing-preview-items" class="allocation-list"><p class="muted">Select a catalogue card to load physical copies.</p></div>
    </div>`;

  settings.append(panel);

  byId("market-mapping-search-button").addEventListener("click", searchMarketCatalogue);
  byId("market-mapping-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchMarketCatalogue();
    }
  });
  panel.querySelectorAll("[data-market-source]").forEach((button) => {
    button.addEventListener("click", () => discoverMarketSource(button.dataset.marketSource));
  });
}

window.addEventListener("DOMContentLoaded", installMarketMappingWorkbench);
installMarketMappingWorkbench();
