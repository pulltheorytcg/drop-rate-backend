"use strict";

let conditionReviewItems = [];
let selectedConditionReviewId = "";

function installMediaConditionWorkspace() {
  const media = sellerView("media");
  if (!media || byId("media-condition-workspace")) return;

  const workspace = document.createElement("div");
  workspace.id = "media-condition-workspace";
  workspace.className = "media-workspace";
  workspace.innerHTML = `
    <div class="page-heading seller-view-heading media-page-heading">
      <div>
        <p class="eyebrow">Physical card evidence</p>
        <h1>Media & Condition</h1>
        <p class="muted">Use verified reusable card imagery first. Physical front + back photos are required only for graded, higher-value or exception cards, and remain mandatory whenever policy says physical evidence is needed.</p>
      </div>
      <button id="media-condition-refresh" class="media-refresh-button" type="button" aria-label="Refresh media and condition" title="Refresh">↻</button>
    </div>

    <section class="workflow-strip" aria-label="Media and condition workflow">
      <div class="workflow-step active"><span>1</span><div><strong>Photograph</strong><small>Front + back</small></div></div>
      <div class="workflow-step"><span>2</span><div><strong>Review</strong><small>Identity + condition</small></div></div>
      <div class="workflow-step"><span>3</span><div><strong>Approve</strong><small>Near Mint or verified slab</small></div></div>
      <div class="workflow-step"><span>4</span><div><strong>Storefront</strong><small>Shopify gate clears</small></div></div>
    </section>

    <div id="shopify-media-message" class="message panel-message" role="status"></div>

    <section class="inventory-panel recent-media-card" id="free-media-panel">
      <div class="section-pad media-card-heading">
        <div>
          <p class="eyebrow">Canonical image source</p>
          <h2>Free canonical images</h2>
          <p class="muted">Pokémon uses TCGdex and Japanese One Piece uses Punk Records automatically. Every imported image stays machine-matched until you visually approve it here. Click any card image to inspect the full-size source.</p>
        </div>
        <strong id="free-media-status">Checking…</strong>
      </div>
      <div class="section-pad">
        <div class="toolbar">
          <button id="free-media-preview" class="ghost-button compact" type="button">Preview matches</button>
          <button id="free-media-import" class="primary-button compact" type="button">Import exact matches</button>
          <button id="free-media-shopify" class="ghost-button compact" type="button">Sync images to Shopify</button>
        </div>
        <div id="free-media-results" class="allocation-list">
          <p class="muted portfolio-empty">Free provider status will appear here.</p>
        </div>
      </div>
    </section>

    <section class="media-workspace-grid">
      <article class="inventory-panel media-capture-card">
        <div class="section-pad media-card-heading">
          <div>
            <p class="eyebrow">Capture queue</p>
            <h2>Photograph a card</h2>
            <p class="muted">This queue contains only Inventory IDs that require physical proof. Low-risk raw cards can clear media with an exact rights-approved canonical image instead.</p>
          </div>
        </div>

        <div id="shopify-media-capability" class="allocation-list compact-list"></div>

        <div class="section-pad media-form">
          <label class="field-label">Physical card
            <select id="shopify-media-candidate" aria-label="Choose physical card needing media">
              <option value="">Loading capture queue…</option>
            </select>
          </label>

          <div id="shopify-media-capture-summary" class="capture-summary">
            <p class="muted">Choose a card to start capture.</p>
          </div>

          <div class="media-two-col">
            <label class="field-label">Card side
              <select id="shopify-media-side">
                <option value="FRONT">Front</option>
                <option value="BACK">Back</option>
              </select>
            </label>
            <label class="field-label">Photo context
              <select id="shopify-media-context">
                <option value="">Choose protection…</option>
                <option value="RAW_UNSLEEVED">Raw · no sleeve</option>
                <option value="PENNY_SLEEVE">Penny sleeve</option>
                <option value="TOP_LOADER">Top loader</option>
                <option value="GRADED_SLAB">Graded slab</option>
              </select>
            </label>
          </div>

          <input id="shopify-media-scope" type="hidden" value="INVENTORY_ITEM">

          <label class="photo-drop" for="shopify-media-file">
            <span class="photo-drop-icon">＋</span>
            <strong>Take or choose photo</strong>
            <small>Use a clear, square-on image with all four edges visible.</small>
            <input id="shopify-media-file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
          </label>

          <label class="field-label">Alt text <span>optional</span>
            <input id="shopify-media-alt" type="text" maxlength="500" placeholder="Generated automatically if left blank">
          </label>

          <label class="rights-check">
            <input id="shopify-media-rights" type="checkbox">
            <span>I own or am authorised to use this photograph.</span>
          </label>

          <button id="shopify-media-upload-button" class="primary-button compact media-primary" type="button" disabled>Upload this side</button>

          <div class="media-nav-actions">
            <button id="shopify-media-previous" class="ghost-button compact" type="button" disabled>← Previous</button>
            <button id="shopify-media-next" class="ghost-button compact" type="button" disabled>Next card →</button>
          </div>
        </div>
      </article>

      <article class="inventory-panel condition-review-card">
        <div class="section-pad media-card-heading">
          <div>
            <p class="eyebrow">Sellability gate</p>
            <h2>Condition review</h2>
            <p class="muted">Raw cards only pass if the physical card is Near Mint. Plastic, sleeves and top loaders never count as card condition.</p>
          </div>
        </div>

        <div id="condition-review-stats" class="condition-stats"></div>

        <div class="section-pad condition-review-body">
          <label class="field-label">Card to review
            <select id="condition-review-candidate">
              <option value="">Loading review queue…</option>
            </select>
          </label>

          <div id="condition-review-detail" class="condition-review-detail">
            <div class="media-empty-state">
              <strong>No card selected</strong>
              <span>Cards become reviewable once both physical photos are ready.</span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section class="inventory-panel media-batch-card">
      <div class="section-pad media-card-heading">
        <div>
          <p class="eyebrow">Fast intake</p>
          <h2>Batch photo upload</h2>
          <p class="muted">For larger runs, name each image <strong>INVENTORY-ID-front.jpg</strong> or <strong>INVENTORY-ID-back.jpg</strong>. Keep each batch to one protection type.</p>
        </div>
      </div>
      <div class="section-pad media-batch-controls">
        <label class="field-label">Protection type for this batch
          <select id="shopify-media-batch-context">
            <option value="">Choose protection…</option>
            <option value="RAW_UNSLEEVED">Raw · no sleeve</option>
            <option value="PENNY_SLEEVE">Penny sleeve</option>
            <option value="TOP_LOADER">Top loader</option>
            <option value="GRADED_SLAB">Graded slab</option>
          </select>
        </label>
        <label class="photo-drop compact-drop" for="shopify-media-batch-files">
          <strong>Choose photo batch</strong>
          <small>JPG, PNG or WebP · up to 20 MB each</small>
          <input id="shopify-media-batch-files" type="file" multiple accept="image/jpeg,image/png,image/webp">
        </label>
        <label class="rights-check">
          <input id="shopify-media-batch-rights" type="checkbox">
          <span>These are founder-owned original photographs.</span>
        </label>
        <button id="shopify-media-batch-button" class="primary-button compact" type="button" disabled>Upload validated batch</button>
      </div>
      <div id="shopify-media-batch-preview" class="allocation-list"><p class="muted portfolio-empty">Select files to validate them against the live capture queue.</p></div>
    </section>

    <section class="inventory-panel recent-media-card">
      <div class="section-pad media-card-heading">
        <div>
          <p class="eyebrow">Evidence registry</p>
          <h2>Recent card photos</h2>
          <p class="muted">Rights, approval and Shopify file state remain auditable. This area never publishes a product.</p>
        </div>
      </div>
      <div id="shopify-media-list" class="allocation-list"><p class="muted">No media loaded.</p></div>
    </section>
  `;
  media.append(workspace);

  byId("media-condition-refresh").addEventListener("click", loadMediaConditionWorkspace);
  byId("free-media-preview").addEventListener("click", () => runFreeMediaResolve(false));
  byId("free-media-import").addEventListener("click", () => runFreeMediaResolve(true));
  byId("free-media-shopify").addEventListener("click", syncFreeImagesToShopify);
  byId("shopify-media-candidate").addEventListener("change", applyMediaCandidateDefaults);
  byId("shopify-media-file").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-context").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-side").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-alt").addEventListener("input", refreshShopifyMediaButton);
  byId("shopify-media-rights").addEventListener("change", refreshShopifyMediaButton);
  byId("shopify-media-upload-button").addEventListener("click", uploadFounderMedia);
  byId("shopify-media-previous").addEventListener("click", () => moveMediaCandidate(-1));
  byId("shopify-media-next").addEventListener("click", () => moveMediaCandidate(1));
  byId("shopify-media-batch-files").addEventListener("change", refreshBatchMediaPreview);
  byId("shopify-media-batch-context").addEventListener("change", refreshBatchMediaPreview);
  byId("shopify-media-batch-rights").addEventListener("change", refreshBatchMediaPreview);
  byId("shopify-media-batch-button").addEventListener("click", uploadFounderMediaBatch);
  byId("condition-review-candidate").addEventListener("change", (event) => {
    selectedConditionReviewId = event.target.value || "";
    renderSelectedConditionReview();
  });
}

function conditionStatusLabel(status) {
  const labels = {
    NOT_REVIEWED: "Not reviewed",
    NEEDS_REVIEW: "Needs review",
    NEEDS_RESHOOT: "Reshoot needed",
    VERIFIED_NEAR_MINT: "Near Mint verified",
    VERIFIED_GRADED: "Slab verified",
    REJECTED_BELOW_NEAR_MINT: "Below Near Mint",
  };
  return labels[status] || status || "Not reviewed";
}

function conditionItemLabel(item) {
  const card = [item.name, item.card_number].filter(Boolean).join(" · ");
  const state = item.photo_ready ? conditionStatusLabel(item.condition_review_status) : "Photos incomplete";
  return [card, item.inventory_code, state].filter(Boolean).join(" — ");
}

function renderConditionStats(data) {
  const container = byId("condition-review-stats");
  if (!container) return;
  const counts = data?.counts || {};
  container.replaceChildren();

  [
    ["Ready to review", counts.needs_review || 0],
    ["Verified sellable", counts.verified || 0],
    ["Below NM", counts.below_near_mint || 0],
  ].forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "condition-stat";
    const number = document.createElement("strong");
    number.textContent = Number(value).toLocaleString("en-GB");
    const text = document.createElement("span");
    text.textContent = label;
    card.append(number, text);
    container.append(card);
  });
}

function renderConditionQueue(data) {
  conditionReviewItems = data?.items || [];
  renderConditionStats(data);

  const select = byId("condition-review-candidate");
  if (!select) return;
  const previous = selectedConditionReviewId || select.value;
  select.replaceChildren();

  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = conditionReviewItems.some((item) => item.photo_ready)
    ? "Choose a photographed card…"
    : "No cards have both photos ready yet";
  select.append(blank);

  conditionReviewItems.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = conditionItemLabel(item);
    option.dataset.photoReady = item.photo_ready ? "true" : "false";
    select.append(option);
  });

  if (previous && conditionReviewItems.some((item) => item.id === previous)) {
    select.value = previous;
    selectedConditionReviewId = previous;
  } else {
    const firstReady = conditionReviewItems.find((item) => item.review_ready);
    selectedConditionReviewId = firstReady?.id || "";
    select.value = selectedConditionReviewId;
  }
  renderSelectedConditionReview();
}

function conditionPhoto(side, url, context) {
  const figure = document.createElement("figure");
  figure.className = "condition-photo";
  const frame = document.createElement("div");
  frame.className = "condition-photo-frame";
  if (url) {
    const image = document.createElement("img");
    image.src = url;
    image.alt = `${side.toLowerCase()} photograph of physical trading card`;
    image.loading = "lazy";
    frame.append(image);
  } else {
    const missing = document.createElement("div");
    missing.className = "photo-missing";
    missing.textContent = "Photo not ready";
    frame.append(missing);
  }
  const caption = document.createElement("figcaption");
  const label = document.createElement("strong");
  label.textContent = side;
  const detail = document.createElement("span");
  detail.textContent = context ? context.replaceAll("_", " ").toLowerCase() : "No capture context";
  caption.append(label, detail);
  figure.append(frame, caption);
  return figure;
}

function reviewActionButton(label, className, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

async function submitConditionReview(item, payload) {
  showMessage("shopify-media-message", "Saving condition review…");
  try {
    await apiRequest(`/api/v1/condition-review/${item.id}`, {
      method: "POST",
      body: JSON.stringify({version: Number(item.version), ...payload}),
    });
    showMessage(
      "shopify-media-message",
      payload.decision === "APPROVE_NEAR_MINT"
        ? "Near Mint verified. This card has cleared the condition gate."
        : payload.decision === "VERIFY_GRADED"
          ? "Graded slab verified."
          : payload.decision === "NEEDS_RESHOOT"
            ? "Photo rejected. The selected side has returned to the capture queue."
            : "Card recorded below Near Mint and blocked from sale.",
      payload.decision.includes("APPROVE") || payload.decision.includes("VERIFY")
        ? "success"
        : ""
    );
    await loadMediaConditionWorkspace();
    if (typeof loadShopifyReadiness === "function") {
      await loadShopifyReadiness();
    }
  } catch (error) {
    showMessage("shopify-media-message", error.message, "error");
  }
}

function renderSelectedConditionReview() {
  const container = byId("condition-review-detail");
  if (!container) return;
  container.replaceChildren();

  const item = conditionReviewItems.find((row) => row.id === selectedConditionReviewId);
  if (!item) {
    const empty = document.createElement("div");
    empty.className = "media-empty-state";
    empty.innerHTML = "<strong>No card selected</strong><span>Cards become reviewable once both physical photos are ready.</span>";
    container.append(empty);
    return;
  }

  const header = document.createElement("div");
  header.className = "condition-card-meta";
  const copy = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = item.name || "Trading card";
  const meta = document.createElement("p");
  meta.className = "muted";
  meta.textContent = [
    item.set_name,
    item.card_number,
    item.language,
    item.inventory_code,
    item.is_graded ? [item.grading_company, item.grade].filter(Boolean).join(" ") : "Raw card",
  ].filter(Boolean).join(" · ");
  copy.append(name, meta);

  const badge = document.createElement("span");
  badge.className = `condition-badge ${item.sellable_condition_verified ? "verified" : item.condition_review_status === "REJECTED_BELOW_NEAR_MINT" ? "blocked" : ""}`;
  badge.textContent = conditionStatusLabel(item.condition_review_status);
  header.append(copy, badge);
  container.append(header);

  const photos = document.createElement("div");
  photos.className = "condition-photo-grid";
  photos.append(
    conditionPhoto("FRONT", item.front_image_url, item.front_capture_context),
    conditionPhoto("BACK", item.back_image_url, item.back_capture_context)
  );
  container.append(photos);

  if (!item.photo_ready) {
    const warning = document.createElement("div");
    warning.className = "condition-callout";
    warning.innerHTML = "<strong>Both physical photos are required.</strong><span>Finish the missing side in the capture queue before condition can be verified.</span>";
    container.append(warning);
    return;
  }

  const guide = document.createElement("div");
  guide.className = "condition-guide";
  guide.innerHTML = item.is_graded
    ? "<strong>Check the slab, not a raw condition.</strong><span>Confirm the pictured slab matches the inventory grader and grade. If glare hides the label/card, request a reshoot.</span>"
    : "<strong>Near Mint only.</strong><span>Check corners, edges, whitening, dents, creases and visible surface wear on the card itself. Sleeve or loader marks do not count as card damage.</span>";
  container.append(guide);

  if (item.sellable_condition_verified) {
    const verified = document.createElement("div");
    verified.className = "condition-callout success";
    verified.innerHTML = "<strong>Condition gate passed</strong><span>This does not publish the card. Shopify still re-checks every remaining listing requirement.</span>";
    container.append(verified);
    return;
  }

  const notes = document.createElement("label");
  notes.className = "field-label";
  notes.innerHTML = 'Review note <span>optional</span><textarea id="condition-review-notes" rows="2" maxlength="2000" placeholder="e.g. clean corners; loader has light surface scratches"></textarea>';
  container.append(notes);

  const actions = document.createElement("div");
  actions.className = "condition-actions";

  const getNotes = () => String(byId("condition-review-notes")?.value || "").trim();
  if (item.is_graded) {
    actions.append(
      reviewActionButton("Verify graded slab", "primary-button compact", () => submitConditionReview(item, {
        decision: "VERIFY_GRADED",
        notes: getNotes(),
      }))
    );
  } else {
    actions.append(
      reviewActionButton("Approve Near Mint", "primary-button compact", () => submitConditionReview(item, {
        decision: "APPROVE_NEAR_MINT",
        observed_condition: "Near Mint",
        notes: getNotes(),
      }))
    );

    const rejectGroup = document.createElement("div");
    rejectGroup.className = "condition-reject-group";
    const select = document.createElement("select");
    select.id = "condition-below-nm";
    [
      ["", "If below NM…"],
      ["Lightly Played", "Lightly Played"],
      ["Moderately Played", "Moderately Played"],
      ["Heavily Played", "Heavily Played"],
      ["Damaged", "Damaged"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    });
    const reject = reviewActionButton("Block from sale", "ghost-button danger-button", () => {
      if (!select.value) {
        showMessage("shopify-media-message", "Choose the observed condition before blocking the card.", "error");
        return;
      }
      submitConditionReview(item, {
        decision: "REJECT_BELOW_NEAR_MINT",
        observed_condition: select.value,
        notes: getNotes(),
      });
    });
    rejectGroup.append(select, reject);
    actions.append(rejectGroup);
  }

  const reshoot = document.createElement("div");
  reshoot.className = "condition-reshoot";
  const reshootSelect = document.createElement("select");
  reshootSelect.id = "condition-reshoot-side";
  [["FRONT", "Reshoot front"], ["BACK", "Reshoot back"], ["BOTH", "Reshoot both"]]
    .forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      reshootSelect.append(option);
    });
  const reshootButton = reviewActionButton("Request reshoot", "ghost-button", () => submitConditionReview(item, {
    decision: "NEEDS_RESHOOT",
    reshoot_side: reshootSelect.value,
    notes: getNotes(),
  }));
  reshoot.append(reshootSelect, reshootButton);
  actions.append(reshoot);

  container.append(actions);

  const aiNote = document.createElement("p");
  aiNote.className = "condition-ai-note";
  aiNote.textContent = "AI condition assistance can be added to suggest defects and confidence, but it will not silently approve or change condition. Human verification remains the listing gate.";
  container.append(aiNote);
}

function formatMinorValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
  }).format(Number(value) / 100);
}

function formatMinorRange(minValue, maxValue) {
  if (minValue === null || minValue === undefined) return "—";
  if (maxValue === null || maxValue === undefined || Number(minValue) === Number(maxValue)) {
    return formatMinorValue(minValue);
  }
  return `${formatMinorValue(minValue)} – ${formatMinorValue(maxValue)}`;
}

function canonicalReviewBadge(status) {
  const labels = {
    PENDING: "MACHINE MATCHED",
    APPROVED: "HUMAN VERIFIED",
    REJECTED: "REJECTED",
  };
  return labels[status] || status || "UNKNOWN";
}

function canonicalMetaRow(label, value) {
  const row = document.createElement("div");
  row.className = "canonical-meta-row";
  const key = document.createElement("span");
  key.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value || "—";
  row.append(key, content);
  return row;
}

function canonicalImageFigure(item, previewOnly = false) {
  const figure = document.createElement("a");
  figure.className = "canonical-image-link";
  figure.href = previewOnly ? item.result?.image_url : item.public_source_url;
  figure.target = "_blank";
  figure.rel = "noopener noreferrer";
  figure.title = "Open full-size source image";

  const image = document.createElement("img");
  image.className = "canonical-card-image";
  image.src = figure.href;
  image.alt = [
    item.name,
    item.set_name,
    item.card_number,
    item.language,
  ].filter(Boolean).join(" · ");
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => {
    figure.classList.add("image-error");
    figure.textContent = "Image failed to load";
  });
  figure.append(image);
  return figure;
}

function renderCanonicalPreviewCard(item) {
  const card = document.createElement("article");
  card.className = "canonical-review-card preview";

  card.append(canonicalImageFigure(item, true));

  const body = document.createElement("div");
  body.className = "canonical-review-body";
  const heading = document.createElement("div");
  heading.className = "canonical-review-heading";
  const copy = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = item.name || "Trading card";
  const subtitle = document.createElement("p");
  subtitle.textContent = [
    item.game,
    item.set_name,
    item.card_number,
    item.variant,
    item.language,
  ].filter(Boolean).join(" · ");
  copy.append(title, subtitle);
  const badge = document.createElement("span");
  badge.className = "canonical-review-badge pending";
  badge.textContent = "EXACT MATCH";
  heading.append(copy, badge);
  body.append(heading);

  const meta = document.createElement("div");
  meta.className = "canonical-meta-grid";
  meta.append(
    canonicalMetaRow("Provider", item.provider || item.result?.provider),
    canonicalMetaRow("Provider ID", item.result?.provider_id),
    canonicalMetaRow("Condition", item.condition),
    canonicalMetaRow("Grade", [item.grading_company, item.grade].filter(Boolean).join(" ")),
    canonicalMetaRow("Store price", formatMinorValue(item.store_price_minor)),
    canonicalMetaRow("Market value", formatMinorValue(item.market_value_minor))
  );
  body.append(meta);

  const hint = document.createElement("p");
  hint.className = "canonical-review-hint";
  hint.textContent = "Preview only · import the match before human approval.";
  body.append(hint);
  card.append(body);
  return card;
}

function renderCanonicalReviewCard(item) {
  const card = document.createElement("article");
  card.className = `canonical-review-card ${String(item.approval_status || "").toLowerCase()}`;

  card.append(canonicalImageFigure(item));

  const body = document.createElement("div");
  body.className = "canonical-review-body";

  const heading = document.createElement("div");
  heading.className = "canonical-review-heading";
  const copy = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = item.name || "Trading card";
  const subtitle = document.createElement("p");
  subtitle.textContent = [
    item.game,
    item.set_name,
    item.card_number,
    item.variant,
    item.language,
    item.rarity,
  ].filter(Boolean).join(" · ");
  copy.append(title, subtitle);

  const badge = document.createElement("span");
  badge.className = `canonical-review-badge ${String(item.approval_status || "").toLowerCase()}`;
  badge.textContent = canonicalReviewBadge(item.approval_status);
  heading.append(copy, badge);
  body.append(heading);

  const inventoryCodes = item.inventory_codes || [];
  const shownCodes = inventoryCodes.slice(0, 6);
  const inventoryCodeText = [
    shownCodes.join(", "),
    inventoryCodes.length > shownCodes.length ? `+${inventoryCodes.length - shownCodes.length} more` : "",
  ].filter(Boolean).join(" · ");

  const meta = document.createElement("div");
  meta.className = "canonical-meta-grid";
  meta.append(
    canonicalMetaRow("Inventory copies", String(item.copy_count || 0)),
    canonicalMetaRow("Inventory IDs", inventoryCodeText),
    canonicalMetaRow("Owner", [item.owner_name, item.owner_type].filter(Boolean).join(" · ")),
    canonicalMetaRow("Inventory status", (item.inventory_statuses || []).join(", ")),
    canonicalMetaRow("Condition", (item.conditions || []).join(", ")),
    canonicalMetaRow("Grade", (item.grades || []).join(", ")),
    canonicalMetaRow("Location", (item.locations || []).join(", ")),
    canonicalMetaRow("Store price", formatMinorRange(item.min_store_price_minor, item.max_store_price_minor)),
    canonicalMetaRow("Market value", formatMinorRange(item.min_market_value_minor, item.max_market_value_minor)),
    canonicalMetaRow("Acquisition cost", formatMinorRange(item.min_acquisition_cost_minor, item.max_acquisition_cost_minor)),
    canonicalMetaRow("Provider", item.source_provider),
    canonicalMetaRow("Provider ID", item.provider_asset_id),
    canonicalMetaRow("Shopify file", item.shopify_file_status)
  );
  body.append(meta);

  const source = document.createElement("a");
  source.className = "canonical-source-link";
  source.href = item.source_reference || item.public_source_url;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  source.textContent = "Open provider record/source";
  body.append(source);

  const actions = document.createElement("div");
  actions.className = "canonical-review-actions";

  if (item.approval_status !== "APPROVED") {
    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "primary-button compact";
    approve.textContent = "Approve image";
    approve.addEventListener("click", () => reviewFreeMediaAsset(item, "APPROVE"));
    actions.append(approve);
  }

  if (item.approval_status !== "REJECTED" && item.shopify_file_status === "NOT_UPLOADED") {
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "ghost-button compact danger-button";
    reject.textContent = "Reject image";
    reject.addEventListener("click", () => reviewFreeMediaAsset(item, "REJECT"));
    actions.append(reject);
  }

  if (item.approval_status === "APPROVED") {
    const verified = document.createElement("span");
    verified.className = "canonical-human-verified";
    verified.textContent = "✓ Human verified for Shopify";
    actions.append(verified);
  }

  body.append(actions);
  card.append(body);
  return card;
}

function renderFreeMediaStatus(status) {
  const label = byId("free-media-status");
  const preview = byId("free-media-preview");
  const apply = byId("free-media-import");
  const sync = byId("free-media-shopify");
  const results = byId("free-media-results");
  if (!label || !preview || !apply || !sync || !results) return;

  const configured = Boolean(status?.configured);
  label.textContent = configured ? "FREE · READY" : "UNAVAILABLE";
  preview.disabled = !configured;
  apply.disabled = !configured;
  sync.disabled = !configured;
}

function renderFreeMediaReviewQueue(data) {
  const results = byId("free-media-results");
  const sync = byId("free-media-shopify");
  if (!results) return;
  results.replaceChildren();

  const counts = data?.counts || {};
  const summary = document.createElement("div");
  summary.className = "canonical-review-summary";
  summary.innerHTML = `
    <div><strong>${Number(counts.total || 0)}</strong><span>Imported images</span></div>
    <div><strong>${Number(counts.pending || 0)}</strong><span>Need visual review</span></div>
    <div><strong>${Number(counts.approved || 0)}</strong><span>Human verified</span></div>
    <div><strong>${Number(counts.rejected || 0)}</strong><span>Rejected</span></div>
  `;
  results.append(summary);

  if (sync) {
    sync.disabled = Number(counts.approved || 0) === 0;
    sync.title = Number(counts.approved || 0) === 0
      ? "Approve at least one image before Shopify sync"
      : "Only human-verified images will be synced";
  }

  const note = document.createElement("div");
  note.className = "canonical-review-notice";
  note.innerHTML = "<strong>Visual verification required.</strong><span>Click any image for the full-size source. Approving confirms the artwork matches the card identity shown below it.</span>";
  results.append(note);

  const items = data?.items || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "muted portfolio-empty";
    empty.textContent = "No imported canonical images yet. Preview matches, then import exact matches.";
    results.append(empty);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "canonical-review-grid";
  items.forEach((item) => grid.append(renderCanonicalReviewCard(item)));
  results.append(grid);
}

function renderFreeMediaResolveResult(data) {
  const results = byId("free-media-results");
  if (!results) return;
  results.replaceChildren();

  const summary = document.createElement("div");
  summary.className = "canonical-review-summary";
  summary.innerHTML = `
    <div><strong>${Number(data.resolved || 0)}</strong><span>Exact matches</span></div>
    <div><strong>${Number(data.unresolved || 0)}</strong><span>Unresolved</span></div>
    <div><strong>${Number(data.skipped_physical_policy || 0)}</strong><span>Physical proof</span></div>
    <div><strong>${Number(data.unsupported || 0)}</strong><span>Unsupported</span></div>
  `;
  results.append(summary);

  const resolved = data.resolved_items || [];
  if (resolved.length) {
    const heading = document.createElement("div");
    heading.className = "canonical-section-heading";
    heading.innerHTML = "<strong>Exact visual matches</strong><span>Click each image to inspect it full-size before importing.</span>";
    results.append(heading);

    const grid = document.createElement("div");
    grid.className = "canonical-review-grid";
    resolved.forEach((item) => grid.append(renderCanonicalPreviewCard(item)));
    results.append(grid);
  }

  if ((data.unresolved_items || []).length) {
    const heading = document.createElement("div");
    heading.className = "canonical-section-heading unresolved";
    heading.innerHTML = "<strong>Action required</strong><span>These cards were not assigned an image.</span>";
    results.append(heading);

    const unresolved = document.createElement("div");
    unresolved.className = "allocation-list canonical-unresolved-list";
    (data.unresolved_items || []).forEach((item) => {
      const row = document.createElement("div");
      row.className = "allocation-row";
      const info = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = [item.name, item.card_number, item.language].filter(Boolean).join(" · ");
      const reason = document.createElement("small");
      reason.textContent = item.result?.reason || "Unresolved";
      info.append(name, reason);
      const badge = document.createElement("strong");
      badge.textContent = "ACTION";
      row.append(info, badge);
      unresolved.append(row);
    });
    results.append(unresolved);
  }
}

async function loadFreeMediaReviewQueue() {
  const data = await apiRequest("/api/v1/media/free/review-queue");
  renderFreeMediaReviewQueue(data);
  return data;
}

async function reviewFreeMediaAsset(item, decision) {
  const verb = decision === "APPROVE" ? "Approving" : "Rejecting";
  showMessage("shopify-media-message", `${verb} ${item.name || "image"}…`);
  try {
    await apiRequest(`/api/v1/media/free/review/${item.id}`, {
      method: "POST",
      body: JSON.stringify({
        version: Number(item.version),
        decision,
      }),
    });
    showMessage(
      "shopify-media-message",
      decision === "APPROVE"
        ? "Image visually verified. It is now eligible for Shopify Files sync."
        : "Image rejected. It will not be used for Shopify.",
      decision === "APPROVE" ? "success" : "warning"
    );
    await loadFreeMediaReviewQueue();
    if (typeof loadShopifyReadiness === "function") {
      await loadShopifyReadiness();
    }
  } catch (error) {
    showMessage("shopify-media-message", error.message, "error");
  }
}

async function runFreeMediaResolve(apply) {
  const preview = byId("free-media-preview");
  const importButton = byId("free-media-import");
  preview.disabled = true;
  importButton.disabled = true;
  showMessage("shopify-media-message", apply ? "Importing exact free-provider images…" : "Checking free-provider matches…");
  try {
    const data = await apiRequest("/api/v1/media/free/resolve", {
      method: "POST",
      body: JSON.stringify({ apply, limit: 100 }),
    });
    if (apply) {
      showMessage(
        "shopify-media-message",
        `${data.inserted || 0} image(s) imported for visual review. Nothing was published or synced to Shopify.`,
        data.unresolved ? "warning" : "success"
      );
      await loadFreeMediaReviewQueue();
    } else {
      renderFreeMediaResolveResult(data);
      showMessage(
        "shopify-media-message",
        `${data.resolved || 0} exact visual match(es) found; ${data.unresolved || 0} unresolved.`,
        data.unresolved ? "warning" : ""
      );
    }
  } catch (error) {
    showMessage("shopify-media-message", error.message, "error");
  } finally {
    preview.disabled = false;
    importButton.disabled = false;
  }
}

async function syncFreeImagesToShopify() {
  const button = byId("free-media-shopify");
  button.disabled = true;
  showMessage("shopify-media-message", "Syncing approved free-provider images into Shopify Files…");
  try {
    const data = await apiRequest("/api/v1/media/free/sync-shopify", {
      method: "POST",
      body: JSON.stringify({ limit: 100 }),
    });
    showMessage(
      "shopify-media-message",
      `${data.ready || 0} image(s) ready · ${data.processing || 0} processing · ${data.failed || 0} failed. No products were published.`,
      data.failed ? "warning" : ""
    );
    await loadMediaConditionWorkspace();
  } catch (error) {
    showMessage("shopify-media-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function loadMediaConditionWorkspace() {
  installMediaConditionWorkspace();
  if (!state.session?.access_token || !byId("media-condition-workspace")) return;

  showMessage("shopify-media-message", "Loading physical media and condition queue…");
  try {
    const [capability, mediaData, mediaQueue, conditionData, freeMediaStatus, freeMediaReview] = await Promise.all([
      apiRequest("/api/v1/shopify/media-assets/upload-capability"),
      apiRequest("/api/v1/shopify/media-assets"),
      apiRequest("/api/v1/shopify/media-assets/intake-queue"),
      apiRequest("/api/v1/condition-review/queue"),
      apiRequest("/api/v1/media/free/status"),
      apiRequest("/api/v1/media/free/review-queue"),
    ]);
    renderShopifyMedia(capability, mediaData, mediaQueue);
    renderConditionQueue(conditionData);
    renderFreeMediaStatus(freeMediaStatus);
    renderFreeMediaReviewQueue(freeMediaReview);
    showMessage("shopify-media-message");
  } catch (error) {
    showMessage("shopify-media-message", error.message, "error");
  }
}

installMediaConditionWorkspace();

const baseActivateSellerViewMediaCondition = activateSellerView;
activateSellerView = function activateSellerViewWithMediaCondition(name, updateHash = false) {
  const result = baseActivateSellerViewMediaCondition(name, updateHash);
  if (name === "media") loadMediaConditionWorkspace();
  return result;
};

if (sellerView("media") && !sellerView("media").classList.contains("hidden")) {
  loadMediaConditionWorkspace();
}
