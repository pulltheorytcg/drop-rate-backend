"use strict";

state.recognition = {
  status: null,
  imageDataUrl: null,
  fileName: "",
  busy: false,
};

function recognitionView() {
  return sellerView("verification");
}

function ensureRecognitionScannerUI() {
  const view = recognitionView();
  if (!view || byId("recognition-scanner-panel")) return;

  const panel = document.createElement("section");
  panel.id = "recognition-scanner-panel";
  panel.className = "inventory-panel recognition-scanner-panel";
  panel.innerHTML = `
    <div class="page-heading">
      <div>
        <p class="eyebrow">Recognition Engine v1</p>
        <h2>Scan a card</h2>
        <p class="muted">AI extracts evidence; Drop Rate independently resolves the exact printing. Nothing is auto-approved or written to inventory.</p>
      </div>
      <span id="recognition-status-badge" class="pill inspection">Checking…</span>
    </div>
    <div class="recognition-scan-grid">
      <div class="recognition-upload-card">
        <label class="recognition-dropzone" for="recognition-file">
          <input id="recognition-file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
          <span class="recognition-drop-icon">◎</span>
          <strong>Take or upload a card photo</strong>
          <small>Front of card · JPEG, PNG or WebP · keep the card flat and readable</small>
        </label>
        <div id="recognition-preview-wrap" class="recognition-preview-wrap hidden">
          <img id="recognition-preview" alt="Card photo selected for recognition">
          <div>
            <strong id="recognition-file-name"></strong>
            <small id="recognition-file-meta"></small>
          </div>
        </div>
        <div class="toolbar">
          <button id="recognition-scan" class="primary-button compact" type="button" disabled>Recognise exact printing</button>
          <button id="recognition-clear" class="ghost-button compact" type="button" disabled>Clear</button>
        </div>
        <div id="recognition-message" class="message panel-message" role="status"></div>
      </div>
      <div id="recognition-result" class="recognition-result">
        <div class="recognition-empty">
          <strong>No scan yet</strong>
          <span>The result will show the top printing, runner-up, confidence evidence and any safety blockers.</span>
        </div>
      </div>
    </div>
    <details class="utility-drawer recognition-history-drawer">
      <summary>
        <div><p class="eyebrow">Audit trail</p><strong>Recent recognition runs</strong></div>
        <span class="utility-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div id="recognition-history" class="allocation-list"><p class="muted">Open Verify to load recent scans.</p></div>
    </details>
  `;

  const identityPanel = byId("identity-review-panel");
  if (identityPanel) view.insertBefore(panel, identityPanel);
  else view.append(panel);

  byId("recognition-file").addEventListener("change", handleRecognitionFile);
  byId("recognition-scan").addEventListener("click", runRecognitionScan);
  byId("recognition-clear").addEventListener("click", clearRecognitionScan);
}

function recognitionMoney(minor) {
  if (minor === null || minor === undefined) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
  }).format(Number(minor) / 100);
}

function recognitionPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function recognitionDecisionLabel(decision) {
  return {
    EXACT_CANDIDATE: "EXACT CANDIDATE",
    NEEDS_REVIEW: "NEEDS REVIEW",
    NO_MATCH: "NO MATCH",
    FAILED: "FAILED",
  }[decision] || decision || "PENDING";
}

async function loadRecognitionStatus() {
  ensureRecognitionScannerUI();
  const badge = byId("recognition-status-badge");
  if (!badge || !state.session?.access_token) return;
  try {
    const data = await apiRequest("/api/v1/recognition/status");
    state.recognition.status = data;
    badge.className = data.configured ? "pill approved" : "pill inspection";
    badge.textContent = data.configured ? `${data.vision_model} · READY` : "VISION KEY REQUIRED";
    byId("recognition-scan").disabled = !data.configured || !state.recognition.imageDataUrl;
    if (!data.configured) {
      showMessage(
        "recognition-message",
        "Recognition Engine is installed, but the OpenAI vision API key has not been configured on Railway yet.",
        "warning"
      );
    }
  } catch (error) {
    badge.className = "pill inspection";
    badge.textContent = "UNAVAILABLE";
    showMessage("recognition-message", error.message, "error");
  }
}

function handleRecognitionFile(event) {
  const file = event.target.files?.[0];
  if (!file) {
    clearRecognitionScan();
    return;
  }

  const allowed = new Set(["image/jpeg", "image/png", "image/webp"]);
  const maxBytes = Number(state.recognition.status?.max_image_bytes || 8_000_000);
  if (!allowed.has(file.type)) {
    showMessage("recognition-message", "Use a JPEG, PNG or WebP card photo.", "error");
    event.target.value = "";
    return;
  }
  if (file.size > maxBytes) {
    showMessage(
      "recognition-message",
      `Image is too large. Maximum is ${(maxBytes / 1_000_000).toFixed(1)} MB.`,
      "error"
    );
    event.target.value = "";
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    state.recognition.imageDataUrl = String(reader.result || "");
    state.recognition.fileName = file.name || "Card photo";
    byId("recognition-preview").src = state.recognition.imageDataUrl;
    byId("recognition-file-name").textContent = state.recognition.fileName;
    byId("recognition-file-meta").textContent =
      `${file.type.replace("image/", "").toUpperCase()} · ${(file.size / 1_000_000).toFixed(2)} MB`;
    byId("recognition-preview-wrap").classList.remove("hidden");
    byId("recognition-clear").disabled = false;
    byId("recognition-scan").disabled =
      !state.recognition.status?.configured || state.recognition.busy;
    showMessage("recognition-message");
  };
  reader.onerror = () => {
    showMessage("recognition-message", "The card photo could not be read.", "error");
  };
  reader.readAsDataURL(file);
}

function clearRecognitionScan() {
  state.recognition.imageDataUrl = null;
  state.recognition.fileName = "";
  byId("recognition-file").value = "";
  byId("recognition-preview").removeAttribute("src");
  byId("recognition-preview-wrap").classList.add("hidden");
  byId("recognition-scan").disabled = true;
  byId("recognition-clear").disabled = true;
  byId("recognition-result").innerHTML = `
    <div class="recognition-empty">
      <strong>No scan yet</strong>
      <span>The result will show the top printing, runner-up, confidence evidence and any safety blockers.</span>
    </div>`;
  showMessage("recognition-message");
}

function recognitionCandidateCard(candidate, label) {
  if (!candidate) return null;
  const snapshot = candidate.candidate_snapshot || {};
  const card = document.createElement("article");
  card.className = "recognition-candidate-card";

  const imageUrl = snapshot.reference_image_url;
  if (imageUrl) {
    const link = document.createElement("a");
    link.href = imageUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "recognition-candidate-image";
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = [snapshot.name, snapshot.card_number, snapshot.language].filter(Boolean).join(" · ");
    image.loading = "lazy";
    link.append(image);
    card.append(link);
  }

  const body = document.createElement("div");
  body.className = "recognition-candidate-body";
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = label;
  const title = document.createElement("strong");
  title.textContent = snapshot.name || candidate.provider_id || "Candidate";
  const meta = document.createElement("small");
  meta.textContent = [
    snapshot.game,
    snapshot.set_name,
    snapshot.card_number,
    snapshot.variant,
    snapshot.rarity,
    snapshot.language,
  ].filter(Boolean).join(" · ");
  const score = document.createElement("div");
  score.className = "recognition-score";
  score.innerHTML = `<span>Evidence score</span><strong>${recognitionPercent(candidate.score)}</strong>`;
  body.append(eyebrow, title, meta, score);
  card.append(body);
  return card;
}

function renderRecognitionSignals(candidate) {
  const signals = candidate?.signals || {};
  const rows = document.createElement("div");
  rows.className = "recognition-signal-grid";
  [
    ["Game", signals.game],
    ["Card number", signals.card_number],
    ["Language", signals.language],
    ["Name", signals.name],
    ["Set", signals.set],
    ["Rarity", signals.rarity],
    ["Card type", signals.card_type],
    ["Art treatment", signals.art],
    ["Finish", signals.finish],
    ["Provider", signals.provider],
    ["Visual", signals.visual],
  ].forEach(([label, signal]) => {
    if (!signal) return;
    const row = document.createElement("div");
    const value = signal.match;
    row.innerHTML = `<span>${label}</span><strong>${recognitionPercent(value)}</strong>`;
    rows.append(row);
  });
  return rows;
}

function renderRecognitionResult(data) {
  const result = byId("recognition-result");
  result.replaceChildren();
  const run = data.run || {};
  const candidates = data.candidates || [];
  const top = candidates.find((item) => item.catalogue_id === run.top_catalogue_id)
    || candidates.find((item) => item.rank === 1 && item.source_kind === "CATALOGUE")
    || null;
  const runner = candidates
    .filter((item) => item.source_kind === "CATALOGUE" && item.id !== top?.id)
    .sort((a, b) => Number(a.rank) - Number(b.rank))[0] || null;

  const summary = document.createElement("div");
  summary.className = `recognition-decision ${String(run.decision || run.status || "").toLowerCase()}`;
  const label = document.createElement("strong");
  label.textContent = recognitionDecisionLabel(run.decision || run.status);
  const detail = document.createElement("span");
  detail.textContent = run.decision === "EXACT_CANDIDATE"
    ? "The evidence supports one exact printing. This is still a candidate — inventory was not changed."
    : run.decision === "NEEDS_REVIEW"
      ? "The engine refused to choose silently. Review the evidence and competing printing(s)."
      : run.decision === "NO_MATCH"
        ? "No local exact printing passed the hard identity gates."
        : "Recognition could not complete.";
  summary.append(label, detail);
  result.append(summary);

  if (top) {
    const candidatesWrap = document.createElement("div");
    candidatesWrap.className = "recognition-top-grid";
    const topCard = recognitionCandidateCard(top, "Top candidate");
    if (topCard) candidatesWrap.append(topCard);
    if (runner) {
      const runnerCard = recognitionCandidateCard(runner, "Runner-up");
      if (runnerCard) candidatesWrap.append(runnerCard);
    }
    result.append(candidatesWrap);

    const margin = document.createElement("div");
    margin.className = "recognition-margin";
    margin.innerHTML = `<span>Top-vs-runner margin</span><strong>${recognitionPercent(run.score_margin)}</strong>`;
    result.append(margin);
    result.append(renderRecognitionSignals(top));
  }

  const observations = run.ai_observation || {};
  const extracted = document.createElement("div");
  extracted.className = "recognition-observation";
  extracted.innerHTML = `
    <strong>Vision observations</strong>
    <div class="recognition-meta-grid">
      <div><span>Game</span><strong>${observations.game || "Unknown"}</strong></div>
      <div><span>Language</span><strong>${observations.language || "Unknown"}</strong></div>
      <div><span>Name</span><strong>${observations.name_guess || "—"}</strong></div>
      <div><span>Card number</span><strong>${observations.card_number || "—"}</strong></div>
      <div><span>Rarity</span><strong>${observations.rarity_text || "—"}</strong></div>
      <div><span>Card type</span><strong>${observations.card_type_text || "—"}</strong></div>
      <div><span>Art treatment</span><strong>${observations.art_treatment_text || "—"}</strong></div>
      <div><span>Finish</span><strong>${observations.finish_text || "—"}</strong></div>
    </div>`;
  result.append(extracted);

  const reasons = [...(run.decision_reasons || []), ...(run.risk_flags || [])];
  if (reasons.length) {
    const reasonsBox = document.createElement("div");
    reasonsBox.className = "recognition-reasons";
    const heading = document.createElement("strong");
    heading.textContent = "Decision evidence / blockers";
    const list = document.createElement("ul");
    reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      list.append(item);
    });
    reasonsBox.append(heading, list);
    result.append(reasonsBox);
  }

  const safety = document.createElement("p");
  safety.className = "muted recognition-safety";
  safety.textContent = "Recognition Engine v1 never auto-edits inventory identity, pricing or Shopify products.";
  result.append(safety);
}

async function runRecognitionScan() {
  if (!state.recognition.imageDataUrl || state.recognition.busy) return;
  state.recognition.busy = true;
  byId("recognition-scan").disabled = true;
  byId("recognition-clear").disabled = true;
  showMessage(
    "recognition-message",
    "Reading card text, comparing exact printings and checking visual/provider evidence…"
  );
  try {
    const data = await apiRequest("/api/v1/recognition/resolve", {
      method: "POST",
      body: JSON.stringify({
        image_data_url: state.recognition.imageDataUrl,
      }),
    });
    renderRecognitionResult(data);
    showMessage(
      "recognition-message",
      data.run?.decision === "EXACT_CANDIDATE"
        ? "Exact candidate found. No inventory changes were made."
        : "Recognition completed safely and requires review.",
      data.run?.decision === "EXACT_CANDIDATE" ? "success" : "warning"
    );
    await loadRecognitionHistory();
  } catch (error) {
    showMessage("recognition-message", error.message, "error");
  } finally {
    state.recognition.busy = false;
    byId("recognition-clear").disabled = !state.recognition.imageDataUrl;
    byId("recognition-scan").disabled =
      !state.recognition.status?.configured || !state.recognition.imageDataUrl;
  }
}

async function loadRecognitionHistory() {
  const container = byId("recognition-history");
  if (!container || !state.session?.access_token) return;
  try {
    const data = await apiRequest("/api/v1/recognition/runs?limit=15");
    container.replaceChildren();
    (data.items || []).forEach((item) => {
      const row = document.createElement("div");
      row.className = "allocation-row";
      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.top_name || item.inventory_code || "Recognition scan";
      const meta = document.createElement("small");
      meta.textContent = [
        item.top_game,
        item.top_set_name,
        item.top_card_number,
        item.top_variant,
        item.top_language,
        item.top_score !== null ? recognitionPercent(item.top_score) : null,
      ].filter(Boolean).join(" · ");
      info.append(title, meta);
      const badge = document.createElement("span");
      badge.className = item.decision === "EXACT_CANDIDATE" ? "pill approved" : "pill inspection";
      badge.textContent = recognitionDecisionLabel(item.decision || item.status);
      row.append(info, badge);
      row.addEventListener("click", async () => {
        const run = await apiRequest(`/api/v1/recognition/runs/${item.id}`);
        renderRecognitionResult(run);
      });
      container.append(row);
    });
    if (!(data.items || []).length) {
      container.innerHTML = '<p class="muted">No recognition runs yet.</p>';
    }
  } catch (error) {
    container.innerHTML = `<p class="muted">${error.message}</p>`;
  }
}

ensureRecognitionScannerUI();

const baseActivateSellerViewRecognition = activateSellerView;
activateSellerView = function activateSellerViewWithRecognition(name, updateHash = false) {
  const result = baseActivateSellerViewRecognition(name, updateHash);
  if (name === "verification") {
    loadRecognitionStatus();
    loadRecognitionHistory();
  }
  return result;
};

if (recognitionView() && !recognitionView().classList.contains("hidden")) {
  loadRecognitionStatus();
  loadRecognitionHistory();
}
