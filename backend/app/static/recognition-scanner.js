"use strict";

state.recognition = {
  status: null,
  imageDataUrl: null,
  fileName: "",
  busy: false,
  currentResult: null,
  cameraStream: null,
  cameraFacingMode: "environment",
  torchOn: false,
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
        <div class="recognition-camera-launch">
          <button id="recognition-open-camera" class="primary-button recognition-camera-primary" type="button">
            <span aria-hidden="true">◉</span>
            <span><strong>Open live camera</strong><small>Recommended on mobile</small></span>
          </button>
          <p>Use your rear camera, line the card up and scan it immediately.</p>
        </div>
        <div id="recognition-camera-stage" class="recognition-camera-stage hidden">
          <div class="recognition-camera-viewport">
            <video id="recognition-camera-video" autoplay muted playsinline></video>
            <div class="recognition-card-guide" aria-hidden="true">
              <span class="recognition-guide-corner top-left"></span>
              <span class="recognition-guide-corner top-right"></span>
              <span class="recognition-guide-corner bottom-left"></span>
              <span class="recognition-guide-corner bottom-right"></span>
            </div>
            <div class="recognition-camera-tip">Fill the frame · keep the card flat · avoid glare</div>
          </div>
          <div class="recognition-camera-controls">
            <button id="recognition-switch-camera" class="ghost-button compact" type="button">Switch camera</button>
            <button id="recognition-torch" class="ghost-button compact hidden" type="button">Torch</button>
            <button id="recognition-capture-scan" class="primary-button compact" type="button">Capture & recognise</button>
            <button id="recognition-close-camera" class="ghost-button compact" type="button">Close</button>
          </div>
        </div>
        <div class="recognition-upload-divider"><span>or upload a photo</span></div>
        <label class="recognition-dropzone" for="recognition-file">
          <input id="recognition-file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
          <span class="recognition-drop-icon">◎</span>
          <strong>Choose a card photo</strong>
          <small>JPEG, PNG or WebP · the phone camera picker still works as a fallback</small>
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
  byId("recognition-open-camera").addEventListener("click", openRecognitionCamera);
  byId("recognition-switch-camera").addEventListener("click", switchRecognitionCamera);
  byId("recognition-torch").addEventListener("click", toggleRecognitionTorch);
  byId("recognition-capture-scan").addEventListener("click", captureAndRecogniseCard);
  byId("recognition-close-camera").addEventListener("click", () => stopRecognitionCamera());
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

async function loadRecognitionCandidateImage(image, runId, candidateId) {
  if (!image || !runId || !candidateId || !state.session?.access_token) return;
  try {
    const response = await fetch(
      `/api/v1/recognition/runs/${runId}/candidates/${candidateId}/image`,
      {
        headers: { Authorization: `Bearer ${state.session.access_token}` },
        cache: "no-store",
      }
    );
    if (!response.ok) throw new Error("Candidate artwork could not be loaded");
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    image.addEventListener("load", () => URL.revokeObjectURL(objectUrl), { once: true });
    image.src = objectUrl;
  } catch (_error) {
    image.alt = "Card artwork unavailable inline — open the source image";
  }
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
    const cameraSupported = Boolean(
      navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function"
    );
    const cameraButton = byId("recognition-open-camera");
    cameraButton.disabled = !cameraSupported;
    cameraButton.title = cameraSupported
      ? "Open the rear camera"
      : "Live camera is not supported in this browser. Use photo upload instead.";
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

function recognitionCameraErrorMessage(error) {
  if (!error) return "The camera could not be opened.";
  if (error.name === "NotAllowedError" || error.name === "SecurityError") {
    return "Camera permission was blocked. Allow camera access for Drop Rate in your browser settings, then try again.";
  }
  if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
    return "No compatible camera was found. You can upload a photo instead.";
  }
  if (error.name === "NotReadableError" || error.name === "AbortError") {
    return "The camera is busy in another app or tab. Close it there and try again.";
  }
  return "The camera could not be opened. You can upload a photo instead.";
}

function stopRecognitionCamera({ hide = true } = {}) {
  const stream = state.recognition.cameraStream;
  if (stream) {
    stream.getTracks().forEach((track) => {
      try {
        track.stop();
      } catch (_error) {
        // Best-effort hardware shutdown.
      }
    });
  }
  state.recognition.cameraStream = null;
  state.recognition.torchOn = false;

  const video = byId("recognition-camera-video");
  if (video) video.srcObject = null;

  const torch = byId("recognition-torch");
  if (torch) {
    torch.classList.add("hidden");
    torch.textContent = "Torch";
  }
  if (hide) {
    byId("recognition-camera-stage")?.classList.add("hidden");
    byId("recognition-open-camera")?.classList.remove("hidden");
  }
}

async function startRecognitionCamera(facingMode = "environment") {
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    throw new Error("Live camera is not supported in this browser.");
  }

  stopRecognitionCamera({ hide: false });
  const constraints = {
    audio: false,
    video: {
      facingMode: { ideal: facingMode },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
    },
  };
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  state.recognition.cameraStream = stream;
  state.recognition.cameraFacingMode = facingMode;

  const video = byId("recognition-camera-video");
  video.srcObject = stream;
  await video.play();

  byId("recognition-camera-stage").classList.remove("hidden");
  byId("recognition-open-camera").classList.add("hidden");

  const track = stream.getVideoTracks()[0];
  let capabilities = {};
  try {
    capabilities = typeof track?.getCapabilities === "function"
      ? track.getCapabilities()
      : {};
  } catch (_error) {
    capabilities = {};
  }
  const torchButton = byId("recognition-torch");
  torchButton.classList.toggle("hidden", !capabilities.torch);

  showMessage(
    "recognition-message",
    facingMode === "environment"
      ? "Rear camera ready. Line the full card up inside the guide."
      : "Front camera ready. Switch back to the rear camera for the best card scan."
  );
}

async function openRecognitionCamera() {
  const button = byId("recognition-open-camera");
  button.disabled = true;
  showMessage("recognition-message", "Opening camera…");
  try {
    await startRecognitionCamera("environment");
  } catch (error) {
    stopRecognitionCamera();
    showMessage("recognition-message", recognitionCameraErrorMessage(error), "error");
  } finally {
    button.disabled = false;
  }
}

async function switchRecognitionCamera() {
  const next = state.recognition.cameraFacingMode === "environment"
    ? "user"
    : "environment";
  const button = byId("recognition-switch-camera");
  button.disabled = true;
  try {
    await startRecognitionCamera(next);
  } catch (error) {
    showMessage("recognition-message", recognitionCameraErrorMessage(error), "error");
    try {
      await startRecognitionCamera(
        next === "environment" ? "user" : "environment"
      );
    } catch (_restoreError) {
      stopRecognitionCamera();
    }
  } finally {
    button.disabled = false;
  }
}

async function toggleRecognitionTorch() {
  const track = state.recognition.cameraStream?.getVideoTracks?.()[0];
  if (!track || typeof track.applyConstraints !== "function") return;
  const button = byId("recognition-torch");
  const next = !state.recognition.torchOn;
  try {
    await track.applyConstraints({ advanced: [{ torch: next }] });
    state.recognition.torchOn = next;
    button.textContent = next ? "Torch on" : "Torch";
  } catch (_error) {
    button.classList.add("hidden");
    showMessage(
      "recognition-message",
      "Torch control is not available on this camera. The scan can still continue.",
      "warning"
    );
  }
}

function recognitionCardCrop(videoWidth, videoHeight) {
  const cardRatio = 5 / 7;
  let height = videoHeight * 0.88;
  let width = height * cardRatio;
  const maxWidth = videoWidth * 0.88;
  if (width > maxWidth) {
    width = maxWidth;
    height = width / cardRatio;
  }
  return {
    sx: Math.max(0, (videoWidth - width) / 2),
    sy: Math.max(0, (videoHeight - height) / 2),
    sw: Math.max(1, width),
    sh: Math.max(1, height),
  };
}

function setRecognitionCapturedImage(dataUrl, sourceLabel, metaText) {
  state.recognition.imageDataUrl = dataUrl;
  state.recognition.fileName = sourceLabel;
  state.recognition.currentResult = null;
  byId("recognition-preview").src = dataUrl;
  byId("recognition-file-name").textContent = sourceLabel;
  byId("recognition-file-meta").textContent = metaText;
  byId("recognition-preview-wrap").classList.remove("hidden");
  byId("recognition-clear").disabled = false;
  byId("recognition-scan").disabled =
    !state.recognition.status?.configured || state.recognition.busy;
}

function recognitionPromiseTimeout(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => window.clearTimeout(timer));
}

function recognitionCanvasJpegDataUrl(canvas, quality = 0.9) {
  if (typeof canvas.toBlob !== "function") {
    return Promise.resolve(canvas.toDataURL("image/jpeg", quality));
  }
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("The camera photo could not be encoded."));
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("The camera photo could not be read."));
      reader.readAsDataURL(blob);
    }, "image/jpeg", quality);
  });
}

async function captureAndRecogniseCard() {
  if (state.recognition.busy) return;
  const video = byId("recognition-camera-video");
  if (
    !state.recognition.cameraStream
    || !video.videoWidth
    || !video.videoHeight
  ) {
    showMessage("recognition-message", "Camera is not ready yet. Hold for a moment and try again.", "warning");
    return;
  }

  const captureButton = byId("recognition-capture-scan");
  captureButton.disabled = true;
  try {
    const crop = recognitionCardCrop(video.videoWidth, video.videoHeight);
    const maxOutput = 1800;
    const scale = Math.min(1, maxOutput / Math.max(crop.sw, crop.sh));
    const outputWidth = Math.max(400, Math.round(crop.sw * scale));
    const outputHeight = Math.max(560, Math.round(crop.sh * scale));

    const canvas = document.createElement("canvas");
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Camera capture is unavailable in this browser.");
    context.drawImage(
      video,
      crop.sx,
      crop.sy,
      crop.sw,
      crop.sh,
      0,
      0,
      outputWidth,
      outputHeight
    );

    showMessage(
      "recognition-message",
      "Preparing camera photo…"
    );
    const dataUrl = await recognitionPromiseTimeout(
      recognitionCanvasJpegDataUrl(canvas, 0.9),
      12000,
      "Camera photo preparation took too long. Please try again or use photo upload."
    );
    const approxBytes = Math.max(
      0,
      Math.floor((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75)
    );
    setRecognitionCapturedImage(
      dataUrl,
      "Live camera capture",
      `JPEG · ${outputWidth}×${outputHeight} · ~${(approxBytes / 1_000_000).toFixed(2)} MB`
    );
    stopRecognitionCamera();

    if (!state.recognition.status?.configured) {
      showMessage(
        "recognition-message",
        "Photo captured. Recognition is not configured yet, so it was not sent.",
        "warning"
      );
      return;
    }

    showMessage(
      "recognition-message",
      "Photo captured. Starting exact-printing recognition…"
    );
    await runRecognitionScan();
  } catch (error) {
    showMessage("recognition-message", error.message || "Card capture failed.", "error");
  } finally {
    captureButton.disabled = false;
  }
}

function handleRecognitionFile(event) {
  const file = event.target.files?.[0];
  if (!file) {
    clearRecognitionScan();
    return;
  }

  state.recognition.currentResult = null;
  state.recognition.imageDataUrl = null;
  byId("recognition-scan").disabled = true;
  byId("recognition-result").innerHTML = `
    <div class="recognition-empty">
      <strong>New card selected</strong>
      <span>Preparing this image. The previous scan result has been cleared.</span>
    </div>`;

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
  stopRecognitionCamera();
  state.recognition.imageDataUrl = null;
  state.recognition.fileName = "";
  state.recognition.currentResult = null;
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

function recognitionCandidateCard(candidate, label, runId) {
  if (!candidate) return null;
  const snapshot = candidate.candidate_snapshot || {};
  const card = document.createElement("article");
  card.className = "recognition-candidate-card";

  const imageUrl = snapshot.reference_image_url || snapshot.image_url;
  if (imageUrl) {
    const link = document.createElement("a");
    link.href = imageUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "recognition-candidate-image";
    const image = document.createElement("img");
    image.alt = [snapshot.name, snapshot.card_number, snapshot.language].filter(Boolean).join(" · ");
    image.loading = "lazy";
    link.append(image);
    card.append(link);
    loadRecognitionCandidateImage(image, runId, candidate.id);
  } else if (candidate.source_kind === "CATALOGUE") {
    const missingImage = document.createElement("div");
    missingImage.className = "recognition-candidate-image recognition-candidate-image-missing";
    missingImage.textContent = "Exact printing image not verified yet";
    card.append(missingImage);
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
    snapshot.card_number || snapshot.base_card_id || candidate.provider_id,
    snapshot.variant,
    snapshot.rarity,
    snapshot.language,
  ].filter(Boolean).join(" · ");
  const score = document.createElement("div");
  score.className = "recognition-score";
  const identityLabel = document.createElement("span");
  const identityValue = document.createElement("strong");
  identityLabel.textContent = "Identity confidence";
  identityValue.textContent = recognitionPercent(candidate.score);
  score.append(identityLabel, identityValue);

  const printing = document.createElement("div");
  printing.className = "recognition-score recognition-printing-score";
  const printingLabel = document.createElement("span");
  const printingValue = document.createElement("strong");
  printingLabel.textContent = "Printing confidence";
  printingValue.textContent = recognitionPercent(
    candidate?.signals?.printing_confidence?.match
  );
  printing.append(printingLabel, printingValue);

  const marketValue = document.createElement("div");
  marketValue.className = "recognition-score recognition-market-value";
  const marketLabel = document.createElement("span");
  const marketAmount = document.createElement("strong");
  marketLabel.textContent = "Market value";
  marketAmount.textContent = recognitionMoney(candidate.market_value_minor);
  marketValue.append(marketLabel, marketAmount);

  body.append(eyebrow, title, meta, score, printing);
  if (candidate.market_value_minor !== null && candidate.market_value_minor !== undefined) {
    body.append(marketValue);
    const pricingMeta = document.createElement("small");
    pricingMeta.className = "recognition-market-meta";
    const sourceCount = Number(candidate.pricing_source_count || 0);
    const confidence = candidate.pricing_confidence !== null
      && candidate.pricing_confidence !== undefined
      ? recognitionPercent(candidate.pricing_confidence)
      : null;
    const algorithm = String(candidate.pricing_algorithm_version || "").toLowerCase();
    const provisional = algorithm.includes("provisional") ? "Provisional" : "Stored pricing";
    pricingMeta.textContent = [
      provisional,
      confidence ? `${confidence} pricing confidence` : null,
      sourceCount ? `${sourceCount} source${sourceCount === 1 ? "" : "s"}` : null,
    ].filter(Boolean).join(" · ");
    body.append(pricingMeta);
  }
  card.append(body);
  return card;
}

function recognitionSignalSource(signal) {
  const source = String(signal?.source || "").replaceAll("_", " ");
  if (!source) return "";
  const labels = {
    catalogue: "catalogue",
    provider: "provider",
    vision: "vision",
    "catalogue after identity": "resolved",
    "provider after identity": "provider",
    "reference image": "image",
    "provider mapping": "provider",
    "human verified scans": "human verified",
    "provider image": "provider image",
  };
  return labels[source] || source;
}

function renderRecognitionSignals(candidate) {
  const signals = candidate?.signals || {};
  const rows = document.createElement("div");
  rows.className = "recognition-signal-grid";
  [
    ["Identity", signals.identity_confidence],
    ["Printing", signals.printing_confidence],
    ["Promotion", signals.promotion],
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
    ["Verified scans", signals.learning],
    ["Visual", signals.visual],
  ].forEach(([label, signal]) => {
    if (!signal) return;
    const row = document.createElement("div");
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    const sourceNode = document.createElement("small");
    labelNode.textContent = label;
    valueNode.textContent = recognitionPercent(signal.match);
    const source = recognitionSignalSource(signal);
    if (source) {
      sourceNode.textContent = source;
      valueNode.append(document.createTextNode(" · "), sourceNode);
    }
    row.append(labelNode, valueNode);
    rows.append(row);
  });
  return rows;
}

function renderRecognitionResult(data) {
  state.recognition.currentResult = data;
  const result = byId("recognition-result");
  result.replaceChildren();
  const run = data.run || {};
  const candidates = [...(data.candidates || [])]
    .sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999));
  const riskFlags = new Set(run.risk_flags || []);
  const hasUnmappedProviderChallenge =
    riskFlags.has("UNMAPPED_PROVIDER_CHALLENGER")
    || riskFlags.has("UNMAPPED_PROVIDER_CANDIDATE");
  const viableCandidates = candidates.filter((item) => !item.hard_rejected);
  const strongestProvider = viableCandidates.find(
    (item) => item.source_kind === "PROVIDER"
  ) || null;
  const strongestCatalogue = viableCandidates.find(
    (item) => item.source_kind === "CATALOGUE"
  ) || null;

  let top = null;
  if (hasUnmappedProviderChallenge && !run.top_catalogue_id && strongestProvider) {
    top = strongestProvider;
  } else {
    top = candidates.find(
      (item) => run.top_catalogue_id && item.catalogue_id === run.top_catalogue_id
    )
      || strongestCatalogue
      || viableCandidates[0]
      || candidates[0]
      || null;
  }

  const topBaseNumber = String(
    top?.candidate_snapshot?.card_number
    || top?.candidate_snapshot?.base_card_id
    || ""
  ).toUpperCase();
  const runnerPool = candidates.filter(
    (item) => item.id !== top?.id && !item.hard_rejected
  );

  let runner = null;
  if (hasUnmappedProviderChallenge) {
    runner = top?.source_kind === "PROVIDER"
      ? (runnerPool.find((item) => item.source_kind === "CATALOGUE") || runnerPool[0] || null)
      : (runnerPool.find((item) => item.source_kind === "PROVIDER") || runnerPool[0] || null);
  } else {
    runner = runnerPool.find((item) => {
      const number = String(
        item?.candidate_snapshot?.card_number
        || item?.candidate_snapshot?.base_card_id
        || ""
      ).toUpperCase();
      return topBaseNumber && number === topBaseNumber;
    }) || runnerPool[0] || null;
  }

  const summary = document.createElement("div");
  summary.className = `recognition-decision ${String(run.decision || run.status || "").toLowerCase()}`;
  const label = document.createElement("strong");
  label.textContent = recognitionDecisionLabel(run.decision || run.status);
  const detail = document.createElement("span");
  detail.textContent = run.decision === "EXACT_CANDIDATE"
    ? "The evidence supports one exact printing. This is still a candidate — inventory was not changed."
    : run.decision === "NEEDS_REVIEW"
      ? (hasUnmappedProviderChallenge
        ? "A strong external printing candidate is not yet mapped into the Drop Rate catalogue. Compare it with the local candidate; it cannot be confirmed until catalogue mapping is complete."
        : top
          ? "Card identity found, but the exact printing still needs review. Check the recovered ID and artwork evidence below."
          : "The engine refused to choose silently. Review the evidence and competing printing(s).")
      : run.decision === "NO_MATCH"
        ? "No local exact printing passed the hard identity gates."
        : "Recognition could not complete.";
  summary.append(label, detail);
  result.append(summary);

  if (top) {
    const candidatesWrap = document.createElement("div");
    candidatesWrap.className = "recognition-top-grid";
    const topLabel = top.source_kind === "PROVIDER"
      ? "Top evidence candidate · catalogue mapping required"
      : "Top candidate";
    const topCard = recognitionCandidateCard(top, topLabel, run.id);
    if (topCard) candidatesWrap.append(topCard);
    if (runner) {
      const runnerLabel = runner.source_kind === "PROVIDER"
        ? "Unmapped provider challenger"
        : "Runner-up";
      const runnerCard = recognitionCandidateCard(runner, runnerLabel, run.id);
      if (runnerCard) candidatesWrap.append(runnerCard);
    }
    result.append(candidatesWrap);

    const marginValue = run.score_margin !== null && run.score_margin !== undefined
      ? Number(run.score_margin)
      : (runner ? Math.max(0, Number(top.score || 0) - Number(runner.score || 0)) : null);
    const margin = document.createElement("div");
    margin.className = "recognition-margin";
    margin.innerHTML = `<span>Identity margin vs runner-up</span><strong>${recognitionPercent(marginValue)}</strong>`;
    result.append(margin);
    result.append(renderRecognitionSignals(top));
  }

  const observations = run.ai_observation || {};
  const extracted = document.createElement("div");
  extracted.className = "recognition-observation";
  const extractedHeading = document.createElement("strong");
  extractedHeading.textContent = "Vision + recovered identity evidence";
  const metaGrid = document.createElement("div");
  metaGrid.className = "recognition-meta-grid";

  const addMeta = (labelText, valueText) => {
    const row = document.createElement("div");
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    labelNode.textContent = labelText;
    valueNode.textContent = valueText === null || valueText === undefined || valueText === ""
      ? "—"
      : String(valueText);
    row.append(labelNode, valueNode);
    metaGrid.append(row);
  };

  const recoveredNumber = top?.signals?.card_number?.recovered;
  const numberSource = top?.signals?.card_number?.source;
  addMeta("Game", observations.game || "Unknown");
  addMeta("Language", observations.language || "Unknown");
  addMeta("Name", observations.name_guess);
  addMeta(
    "Card number",
    numberSource === "provider_override" && recoveredNumber
      ? `${recoveredNumber} · provider override (OCR read ${observations.card_number || "uncertain"})`
      : observations.card_number
        || (recoveredNumber
          ? `${recoveredNumber} · recovered via provider fingerprint`
          : "—")
  );
  addMeta("Cost", observations.cost);
  addMeta("Power", observations.power);
  addMeta("Colours", (observations.colors || []).join(", "));
  addMeta("Attributes", (observations.attributes || []).join(", "));
  addMeta("Traits", (observations.traits || []).join(", "));
  addMeta("Rarity", observations.rarity_text);
  addMeta("Card type", observations.card_type_text);
  addMeta("Art treatment", observations.art_treatment_text);
  addMeta("Finish", observations.finish_text);
  if (numberSource === "provider_fingerprint" || numberSource === "provider_override") {
    addMeta(
      "ID recovery confidence",
      recognitionPercent(top?.signals?.card_number?.confidence)
    );
  }
  extracted.append(extractedHeading, metaGrid);

  if (observations.effect_text) {
    const effect = document.createElement("div");
    effect.className = "recognition-effect-text";
    const effectLabel = document.createElement("span");
    const effectValue = document.createElement("p");
    effectLabel.textContent = "Visible effect text";
    effectValue.textContent = observations.effect_text;
    effect.append(effectLabel, effectValue);
    extracted.append(effect);
  }
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

  if (
    run.id
    && ["EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH"].includes(run.decision || run.status)
  ) {
    const feedback = document.createElement("div");
    feedback.className = "recognition-feedback";
    const heading = document.createElement("strong");
    heading.textContent = "Teach the recognition system";
    const note = document.createElement("small");
    note.textContent = "Confirmed/corrected labels become verified learning data. They never edit inventory or publish anything.";
    feedback.append(heading, note);

    const actions = document.createElement("div");
    actions.className = "toolbar";
    if (top?.catalogue_id) {
      const confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = "primary-button compact";
      confirm.textContent = "Confirm top candidate";
      confirm.addEventListener("click", () => submitRecognitionFeedback(
        run.id,
        "CONFIRMED_TOP",
        top.catalogue_id
      ));
      actions.append(confirm);
    }
    if (runner?.catalogue_id) {
      const correct = document.createElement("button");
      correct.type = "button";
      correct.className = "ghost-button compact";
      correct.textContent = "Runner-up is correct";
      correct.addEventListener("click", () => submitRecognitionFeedback(
        run.id,
        "CORRECTED_TO_CANDIDATE",
        runner.catalogue_id
      ));
      actions.append(correct);
    }
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "ghost-button compact danger-button";
    reject.textContent = "Reject all candidates";
    reject.addEventListener("click", () => submitRecognitionFeedback(
      run.id,
      "REJECTED_ALL",
      null
    ));
    actions.append(reject);
    feedback.append(actions);

    const previous = (data.feedback || [])[0];
    if (previous) {
      const latest = document.createElement("small");
      latest.className = "recognition-feedback-latest";
      latest.textContent = `Latest human label: ${previous.outcome.replaceAll("_", " ")}`;
      feedback.append(latest);
    }
    result.append(feedback);
  }

  const safety = document.createElement("p");
  safety.className = "muted recognition-safety";
  safety.textContent = "Recognition Engine v1 never auto-edits inventory identity, pricing or Shopify products.";
  result.append(safety);
}

async function submitRecognitionFeedback(runId, outcome, catalogueId) {
  showMessage("recognition-message", "Saving human recognition label…");
  try {
    const data = await apiRequest(`/api/v1/recognition/runs/${runId}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        outcome,
        selected_catalogue_id: catalogueId,
        notes: "",
      }),
    });
    renderRecognitionResult(data);
    showMessage(
      "recognition-message",
      "Human label saved to the verified learning dataset. Inventory was not changed.",
      "success"
    );
    await loadRecognitionHistory();
  } catch (error) {
    showMessage("recognition-message", error.message, "error");
  }
}

async function runRecognitionScan() {
  if (!state.recognition.imageDataUrl || state.recognition.busy) return;
  state.recognition.busy = true;
  state.recognition.currentResult = null;
  byId("recognition-scan").disabled = true;
  byId("recognition-clear").disabled = true;
  byId("recognition-result").innerHTML = `
    <div class="recognition-empty">
      <strong>Scanning this card…</strong>
      <span>Reading identity, promotion and exact-printing evidence. Previous results are not shown during this scan.</span>
    </div>`;
  showMessage(
    "recognition-message",
    "Reading card text, comparing exact printings and checking visual/provider evidence…"
  );
  try {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 70000);
    let data;
    try {
      data = await apiRequest("/api/v1/recognition/resolve", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          image_data_url: state.recognition.imageDataUrl,
        }),
      });
    } finally {
      window.clearTimeout(timeoutId);
    }
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
    const message = error?.name === "AbortError"
      ? "Recognition exceeded 70 seconds and was stopped. The scan was not left hanging."
      : error.message;
    showMessage("recognition-message", message, "error");
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
  if (name !== "verification") {
    stopRecognitionCamera();
  }
  const result = baseActivateSellerViewRecognition(name, updateHash);
  if (name === "verification") {
    loadRecognitionStatus();
    loadRecognitionHistory();
  }
  return result;
};

document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopRecognitionCamera();
});
window.addEventListener("pagehide", () => stopRecognitionCamera());

if (recognitionView() && !recognitionView().classList.contains("hidden")) {
  loadRecognitionStatus();
  loadRecognitionHistory();
}
