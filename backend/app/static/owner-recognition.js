"use strict";

state.ownerRecognition = {
  status: null,
  imageDataUrl: null,
  busy: false,
  cameraStream: null,
  cameraFacingMode: "environment",
  result: null,
  selectedCandidate: null,
  intakeKey: null,
  batch: {
    items: [],
    enabled: false,
    processing: false,
    paused: false,
    timer: null,
    previousFingerprint: null,
    lastAcceptedFingerprint: null,
    stableFrames: 0,
    armed: true,
    currentCorrectionId: null,
    searchTimer: null,
    latestResultId: null,
    statusTimer: null,
    flashTimer: null,
    lastAutoCaptureFingerprint: null,
    lastAutoCaptureAt: 0,
  },
};

function ownerScanMessage(text = "", kind = "") {
  const node = byId("owner-scan-message");
  if (!node) return;
  node.textContent = text;
  node.className = `owner-card-message${kind ? ` ${kind}` : ""}`;
}

function ownerScanIntakeMessage(text = "", kind = "") {
  const node = byId("owner-scan-intake-message");
  if (!node) return;
  node.textContent = text;
  node.className = `owner-card-message${kind ? ` ${kind}` : ""}`;
}

function ownerScanPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function ownerScanDecisionLabel(value) {
  return {
    EXACT_CANDIDATE: "Exact candidate",
    NEEDS_REVIEW: "Review required",
    NO_MATCH: "No exact match",
    FAILED: "Recognition failed",
  }[value] || safeText(value, "Pending");
}

async function ownerScanLoadCandidateImage(image, runId, candidateId) {
  if (!image || !runId || !candidateId || !state.session?.access_token) return;
  try {
    let response = await fetch(
      `/api/v1/recognition/runs/${runId}/candidates/${candidateId}/image`,
      {
        headers: {Authorization: `Bearer ${state.session.access_token}`},
        cache: "no-store",
      }
    );
    if (response.status === 401) {
      const token = await refreshSession();
      response = await fetch(
        `/api/v1/recognition/runs/${runId}/candidates/${candidateId}/image`,
        {headers: {Authorization: `Bearer ${token}`}, cache: "no-store"}
      );
    }
    if (!response.ok) throw new Error("image unavailable");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    image.addEventListener("load", () => URL.revokeObjectURL(url), {once: true});
    image.src = url;
  } catch (_error) {
    image.closest(".owner-scan-candidate-image")?.classList.add("image-missing");
  }
}

function ownerScanStopCamera({hide = true} = {}) {
  ownerBatchStopLoop();
  const batch = state.ownerRecognition.batch;
  window.clearTimeout(batch.statusTimer);
  window.clearTimeout(batch.flashTimer);
  document.querySelector(".owner-scan-card-guide")?.classList.remove("scan-ok", "scan-review");
  document.body.classList.remove("owner-batch-camera-open");
  batch.enabled = false;
  if (state.ownerRecognition.cameraStream) {
    state.ownerRecognition.cameraStream.getTracks().forEach((track) => {
      try { track.stop(); } catch (_error) {}
    });
  }
  state.ownerRecognition.cameraStream = null;
  const video = byId("owner-scan-video");
  if (video) video.srcObject = null;
  if (hide) {
    byId("owner-scan-camera-stage")?.classList.add("hidden");
    byId("owner-scan-open-camera")?.classList.remove("hidden");
  }
}

async function ownerScanStartCamera(facingMode = "environment") {
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    throw new Error("Live camera is not supported in this browser. Upload a photo instead.");
  }
  ownerScanStopCamera({hide: false});
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      facingMode: {ideal: facingMode},
      width: {ideal: 1920},
      height: {ideal: 1080},
    },
  });
  state.ownerRecognition.cameraStream = stream;
  state.ownerRecognition.cameraFacingMode = facingMode;
  const video = byId("owner-scan-video");
  video.srcObject = stream;
  await video.play();
  byId("owner-scan-camera-stage").classList.remove("hidden");
  byId("owner-scan-open-camera").classList.add("hidden");
  if (ownerBatchIsMobile()) {
    state.ownerRecognition.batch.enabled = true;
    state.ownerRecognition.batch.paused = false;
    document.body.classList.add("owner-batch-camera-open");
    ownerBatchStartLoop();
    ownerBatchRender();
    ownerBatchSetCameraState("Auto-scan on · tap Capture now any time");
  }
  ownerScanMessage(
    facingMode === "environment"
      ? "Rear camera ready. Fill the guide with the whole card."
      : "Front camera ready. Rear camera usually gives better recognition."
  );
}

function ownerScanCrop(videoWidth, videoHeight) {
  const ratio = 5 / 7;
  let height = videoHeight * 0.88;
  let width = height * ratio;
  const maxWidth = videoWidth * 0.88;
  if (width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }
  return {
    sx: Math.max(0, (videoWidth - width) / 2),
    sy: Math.max(0, (videoHeight - height) / 2),
    sw: Math.max(1, width),
    sh: Math.max(1, height),
  };
}

function ownerScanSetImage(dataUrl, name, meta) {
  state.ownerRecognition.imageDataUrl = dataUrl;
  state.ownerRecognition.result = null;
  state.ownerRecognition.selectedCandidate = null;
  state.ownerRecognition.intakeKey = null;
  byId("owner-scan-preview").src = dataUrl;
  byId("owner-scan-file-name").textContent = name;
  byId("owner-scan-file-meta").textContent = meta;
  byId("owner-scan-preview-wrap").classList.remove("hidden");
  byId("owner-scan-run").disabled = !state.ownerRecognition.status?.configured;
  byId("owner-scan-clear").disabled = false;
  byId("owner-scan-intake-panel").classList.add("hidden");
  byId("owner-scan-success").classList.add("hidden");
}

async function ownerScanCapture() {
  if (state.ownerRecognition.busy) return;
  const video = byId("owner-scan-video");
  if (!state.ownerRecognition.cameraStream || !video.videoWidth || !video.videoHeight) {
    ownerScanMessage("Camera is still starting. Try again in a moment.", "error");
    return;
  }

  try {
    const crop = ownerScanCrop(video.videoWidth, video.videoHeight);
    const maxOutput = 1800;
    const scale = Math.min(1, maxOutput / Math.max(crop.sw, crop.sh));
    const width = Math.max(400, Math.round(crop.sw * scale));
    const height = Math.max(560, Math.round(crop.sh * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", {alpha: false});
    if (!context) throw new Error("Camera capture is unavailable in this browser.");
    context.drawImage(
      video,
      crop.sx,
      crop.sy,
      crop.sw,
      crop.sh,
      0,
      0,
      width,
      height
    );
    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    const approxBytes = Math.max(0, Math.floor((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75));
    ownerScanSetImage(
      dataUrl,
      "Live camera capture",
      `JPEG · ${width}×${height} · ~${(approxBytes / 1_000_000).toFixed(2)} MB`
    );
    ownerScanStopCamera();
    await ownerScanRun();
  } catch (error) {
    ownerScanMessage(error.message || "Card capture failed.", "error");
  }
}

function ownerScanHandleFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const allowed = new Set(["image/jpeg", "image/png", "image/webp"]);
  const maxBytes = Number(state.ownerRecognition.status?.max_image_bytes || 8_000_000);
  if (!allowed.has(file.type)) {
    ownerScanMessage("Use a JPEG, PNG or WebP card photo.", "error");
    event.target.value = "";
    return;
  }
  if (file.size > maxBytes) {
    ownerScanMessage(`Image is too large. Maximum is ${(maxBytes / 1_000_000).toFixed(1)} MB.`, "error");
    event.target.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    ownerScanSetImage(
      String(reader.result || ""),
      file.name || "Card photo",
      `${file.type.replace("image/", "").toUpperCase()} · ${(file.size / 1_000_000).toFixed(2)} MB`
    );
    ownerScanMessage();
  };
  reader.onerror = () => ownerScanMessage("The card photo could not be read.", "error");
  reader.readAsDataURL(file);
}

function ownerScanClear({keepMessage = false} = {}) {
  ownerScanStopCamera();
  state.ownerRecognition.imageDataUrl = null;
  state.ownerRecognition.result = null;
  state.ownerRecognition.selectedCandidate = null;
  state.ownerRecognition.intakeKey = null;
  byId("owner-scan-file").value = "";
  byId("owner-scan-preview").removeAttribute("src");
  byId("owner-scan-preview-wrap").classList.add("hidden");
  byId("owner-scan-run").disabled = true;
  byId("owner-scan-clear").disabled = true;
  byId("owner-scan-intake-panel").classList.add("hidden");
  byId("owner-scan-success").classList.add("hidden");
  ownerScanRenderEmpty();
  if (!keepMessage) ownerScanMessage();
  ownerScanIntakeMessage();
}

function ownerScanRenderEmpty() {
  const result = byId("owner-scan-result");
  if (!result) return;
  const empty = document.createElement("div");
  empty.className = "owner-scan-empty";
  const icon = document.createElement("span");
  icon.textContent = "◎";
  const title = document.createElement("strong");
  title.textContent = "No scan yet";
  const copy = document.createElement("small");
  copy.textContent = "Your recognition result and evidence will appear here.";
  empty.append(icon, title, copy);
  result.replaceChildren(empty);
}

function ownerScanCandidateCard(candidate, run, index) {
  const snapshot = candidate.candidate_snapshot || {};
  const card = document.createElement("article");
  card.className = "owner-scan-candidate";

  const imageWrap = document.createElement("div");
  imageWrap.className = "owner-scan-candidate-image";
  const image = document.createElement("img");
  image.alt = [snapshot.name, snapshot.card_number, snapshot.language].filter(Boolean).join(" · ") || "Candidate card";
  image.loading = "lazy";
  imageWrap.append(image);
  if (candidate.id && run.id) ownerScanLoadCandidateImage(image, run.id, candidate.id);

  const body = document.createElement("div");
  body.className = "owner-scan-candidate-body";
  const rank = document.createElement("span");
  rank.className = "owner-scan-rank";
  rank.textContent = index === 0 ? "Top candidate" : `Candidate ${index + 1}`;
  const title = document.createElement("strong");
  title.textContent = snapshot.name || "Candidate";
  const meta = document.createElement("small");
  meta.textContent = [
    snapshot.game,
    snapshot.set_name,
    snapshot.card_number || snapshot.base_card_id,
    snapshot.variant,
    snapshot.rarity,
    snapshot.language,
  ].filter(Boolean).join(" · ");

  const evidence = document.createElement("div");
  evidence.className = "owner-scan-evidence-grid";
  for (const [labelText, valueText] of [
    ["Identity", ownerScanPercent(candidate.score)],
    ["Printing", ownerScanPercent(candidate?.signals?.printing_confidence?.match)],
    ["Market", candidate.market_value_minor == null ? "—" : formatMoney(candidate.market_value_minor)],
  ]) {
    const box = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = labelText;
    const value = document.createElement("strong");
    value.textContent = valueText;
    box.append(label, value);
    evidence.append(box);
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "owner-scan-confirm-button";
  button.disabled = !candidate.catalogue_id || candidate.hard_rejected;
  button.textContent = candidate.catalogue_id
    ? (candidate.hard_rejected ? "Rejected by evidence" : "This is my card")
    : "Catalogue mapping required";
  if (!button.disabled) {
    button.addEventListener("click", () => ownerScanConfirmCandidate(run, candidate));
  }

  body.append(rank, title, meta, evidence, button);
  card.append(imageWrap, body);
  return card;
}

function ownerScanRenderResult(data) {
  state.ownerRecognition.result = data;
  const result = byId("owner-scan-result");
  result.replaceChildren();

  const run = data.run || {};
  const summary = document.createElement("div");
  summary.className = `owner-scan-decision ${String(run.decision || run.status || "").toLowerCase()}`;
  const label = document.createElement("strong");
  label.textContent = ownerScanDecisionLabel(run.decision || run.status);
  const detail = document.createElement("span");
  detail.textContent = run.decision === "EXACT_CANDIDATE"
    ? "One printing leads the evidence. Check it visually before confirming."
    : "The engine will not choose silently. Compare the candidates and confirm the exact printing yourself.";
  summary.append(label, detail);
  result.append(summary);

  const candidates = (data.candidates || [])
    .filter((candidate) => !candidate.hard_rejected)
    .sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999))
    .filter((candidate) => candidate.catalogue_id)
    .slice(0, 3);

  if (!candidates.length) {
    const empty = document.createElement("div");
    empty.className = "owner-scan-empty";
    const title = document.createElement("strong");
    title.textContent = "No confirmable catalogue match";
    const copy = document.createElement("small");
    copy.textContent = "This scan needs Drop Rate review before it can be added. Try another photo if the card is clear.";
    empty.append(title, copy);
    result.append(empty);
  } else {
    const list = document.createElement("div");
    list.className = "owner-scan-candidates";
    candidates.forEach((candidate, index) => list.append(ownerScanCandidateCard(candidate, run, index)));
    result.append(list);
  }

  const reasons = [...new Set([...(run.decision_reasons || []), ...(run.risk_flags || [])])];
  if (reasons.length) {
    const evidence = document.createElement("details");
    evidence.className = "owner-scan-evidence-details";
    const summaryNode = document.createElement("summary");
    summaryNode.textContent = "Why the engine decided this";
    const list = document.createElement("ul");
    reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = String(reason).replaceAll("_", " ");
      list.append(item);
    });
    evidence.append(summaryNode, list);
    result.append(evidence);
  }
}

async function ownerScanRun() {
  if (!state.ownerRecognition.imageDataUrl || state.ownerRecognition.busy) return;
  state.ownerRecognition.busy = true;
  state.ownerRecognition.selectedCandidate = null;
  state.ownerRecognition.intakeKey = null;
  byId("owner-scan-run").disabled = true;
  byId("owner-scan-clear").disabled = true;
  byId("owner-scan-intake-panel").classList.add("hidden");
  byId("owner-scan-success").classList.add("hidden");

  const result = byId("owner-scan-result");
  const loading = document.createElement("div");
  loading.className = "owner-scan-empty";
  const icon = document.createElement("span");
  icon.textContent = "◌";
  const title = document.createElement("strong");
  title.textContent = "Recognising this card…";
  const copy = document.createElement("small");
  copy.textContent = "Reading text, exact-printing evidence and visual/provider signals.";
  loading.append(icon, title, copy);
  result.replaceChildren(loading);
  ownerScanMessage("Checking exact card identity and runner-up evidence…");

  try {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 70000);
    let data;
    try {
      data = await apiRequest("/api/v1/recognition/resolve", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({image_data_url: state.ownerRecognition.imageDataUrl}),
      });
    } finally {
      window.clearTimeout(timeout);
    }
    ownerScanRenderResult(data);
    ownerScanMessage(
      data.run?.decision === "EXACT_CANDIDATE"
        ? "Match found. Confirm the exact card before adding it."
        : "Recognition completed. Review the candidates before adding anything.",
      data.run?.decision === "EXACT_CANDIDATE" ? "success" : ""
    );
  } catch (error) {
    ownerScanRenderEmpty();
    ownerScanMessage(
      error?.name === "AbortError"
        ? "Recognition took too long and was safely stopped. Try a clearer photo."
        : error.message,
      "error"
    );
  } finally {
    state.ownerRecognition.busy = false;
    byId("owner-scan-clear").disabled = !state.ownerRecognition.imageDataUrl;
    byId("owner-scan-run").disabled =
      !state.ownerRecognition.status?.configured || !state.ownerRecognition.imageDataUrl;
  }
}

function ownerScanRenderSelected(candidate) {
  const snapshot = candidate.candidate_snapshot || {};
  const container = byId("owner-scan-selected-card");
  container.replaceChildren();

  const imageWrap = document.createElement("div");
  imageWrap.className = "owner-scan-selected-image";
  const image = document.createElement("img");
  image.alt = safeText(snapshot.name, "Selected card");
  image.loading = "lazy";
  imageWrap.append(image);
  const runId = state.ownerRecognition.result?.run?.id;
  if (candidate.id && runId) ownerScanLoadCandidateImage(image, runId, candidate.id);

  const copy = document.createElement("div");
  copy.className = "owner-scan-selected-copy";
  const kicker = document.createElement("span");
  kicker.textContent = "Confirmed match";
  const title = document.createElement("strong");
  title.textContent = safeText(snapshot.name, "Card");
  const meta = document.createElement("small");
  meta.textContent = [
    snapshot.game,
    snapshot.set_name,
    snapshot.card_number || snapshot.base_card_id,
    snapshot.variant,
    snapshot.rarity,
    snapshot.language,
  ].filter(Boolean).join(" · ");
  const score = document.createElement("em");
  score.textContent = `${ownerScanPercent(candidate.score)} identity confidence`;
  copy.append(kicker, title, meta, score);
  container.append(imageWrap, copy);
}

async function ownerScanConfirmCandidate(run, candidate) {
  if (!run?.id || !candidate?.catalogue_id) return;
  ownerScanMessage("Saving your confirmed card identity…");
  try {
    const outcome = candidate.catalogue_id === run.top_catalogue_id
      ? "CONFIRMED_TOP"
      : "CORRECTED_TO_CANDIDATE";
    await apiRequest(`/api/v1/recognition/runs/${run.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        outcome,
        selected_catalogue_id: candidate.catalogue_id,
        notes: "Seller-confirmed from owner portal scan intake",
      }),
    });
    state.ownerRecognition.selectedCandidate = candidate;
    state.ownerRecognition.intakeKey = crypto.randomUUID();
    ownerScanRenderSelected(candidate);

    const snapshot = candidate.candidate_snapshot || {};
    byId("owner-scan-language").value =
      snapshot.language || state.ownerRecognition.result?.run?.ai_observation?.language || "";
    byId("owner-scan-condition").value = "";
    byId("owner-scan-grading-company").value = "";
    byId("owner-scan-grade").value = "";
    byId("owner-scan-certificate").value = "";
    document.querySelector('input[name="owner-scan-state"][value="raw"]').checked = true;
    ownerScanUpdatePhysicalState();

    byId("owner-scan-intake-panel").classList.remove("hidden");
    byId("owner-scan-success").classList.add("hidden");
    ownerScanIntakeMessage();
    ownerScanMessage("Match confirmed. Add the physical condition to finish.", "success");
    byId("owner-scan-intake-panel").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    ownerScanMessage(error.message, "error");
  }
}

function ownerScanUpdatePhysicalState() {
  const graded = document.querySelector('input[name="owner-scan-state"]:checked')?.value === "graded";
  byId("owner-scan-condition-wrap").classList.toggle("hidden", graded);
  byId("owner-scan-grade-fields").classList.toggle("hidden", !graded);
  byId("owner-scan-condition").required = !graded;
  byId("owner-scan-grading-company").required = graded;
  byId("owner-scan-grade").required = graded;
}

async function ownerScanSubmitIntake(event) {
  event.preventDefault();
  const candidate = state.ownerRecognition.selectedCandidate;
  const run = state.ownerRecognition.result?.run;
  if (!candidate?.catalogue_id || !run?.id) {
    ownerScanIntakeMessage("Confirm a recognition candidate first.", "error");
    return;
  }

  const graded = document.querySelector('input[name="owner-scan-state"]:checked')?.value === "graded";
  const payload = {
    recognition_run_id: run.id,
    selected_catalogue_id: candidate.catalogue_id,
    condition: graded ? null : byId("owner-scan-condition").value || null,
    grading_company: graded ? byId("owner-scan-grading-company").value.trim() || null : null,
    grade: graded ? byId("owner-scan-grade").value.trim() || null : null,
    certificate_number: graded ? byId("owner-scan-certificate").value.trim() || null : null,
    language: byId("owner-scan-language").value.trim() || null,
  };

  if (!graded && !payload.condition) {
    ownerScanIntakeMessage("Choose the card condition.", "error");
    return;
  }
  if (graded && (!payload.grading_company || !payload.grade)) {
    ownerScanIntakeMessage("Enter both grading company and grade.", "error");
    return;
  }

  const button = byId("owner-scan-add");
  button.disabled = true;
  ownerScanIntakeMessage("Adding your card and calculating valuation…");
  state.ownerRecognition.intakeKey ||= crypto.randomUUID();

  try {
    const data = await apiRequest("/api/v1/owner/recognition-intake", {
      method: "POST",
      headers: {"Idempotency-Key": state.ownerRecognition.intakeKey},
      body: JSON.stringify(payload),
    });
    byId("owner-scan-market-value").textContent =
      data.inventory?.market_value_minor == null ? "—" : formatMoney(data.inventory.market_value_minor);
    byId("owner-scan-store-value").textContent =
      data.inventory?.store_value_minor == null ? "—" : formatMoney(data.inventory.store_value_minor);
    byId("owner-scan-inventory-code").textContent = safeText(data.inventory?.inventory_code);

    const note = byId("owner-scan-valuation-note");
    if (data.valuation?.status === "CALCULATED") {
      note.textContent = "Valuation calculated by the same deterministic Drop Rate pricing engine used in Founder HQ.";
      note.className = "owner-scan-valuation-note success";
    } else {
      note.textContent = data.valuation?.detail
        ? `Valuation is not available yet: ${data.valuation.detail}`
        : "Valuation is not available yet. The card is still safely saved in your inventory.";
      note.className = "owner-scan-valuation-note";
    }

    byId("owner-scan-success").classList.remove("hidden");
    ownerScanIntakeMessage("Card added successfully.", "success");
    await Promise.all([loadOwnerOverview(), loadOwnerInventory()]);
    byId("owner-scan-success").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    ownerScanIntakeMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}


function ownerBatchIsMobile() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function ownerBatchFormatValue(value) {
  return value == null ? "—" : formatMoney(value);
}

function ownerBatchFingerprintDelta(left, right) {
  if (!left || !right || left.length !== right.length || !left.length) return 1;
  let total = 0;
  for (let index = 0; index < left.length; index += 1) {
    total += Math.abs(left[index] - right[index]);
  }
  return total / left.length / 255;
}

function ownerBatchFrameFingerprint(video) {
  if (!video?.videoWidth || !video?.videoHeight) return null;
  const crop = ownerScanCrop(video.videoWidth, video.videoHeight);
  const canvas = document.createElement("canvas");
  canvas.width = 20;
  canvas.height = 28;
  const context = canvas.getContext("2d", {willReadFrequently: true});
  if (!context) return null;
  context.drawImage(
    video,
    crop.sx,
    crop.sy,
    crop.sw,
    crop.sh,
    0,
    0,
    canvas.width,
    canvas.height
  );
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const fingerprint = new Uint8Array(canvas.width * canvas.height);
  for (let pixel = 0, output = 0; pixel < pixels.length; pixel += 4, output += 1) {
    fingerprint[output] = Math.round(
      pixels[pixel] * 0.299 + pixels[pixel + 1] * 0.587 + pixels[pixel + 2] * 0.114
    );
  }
  return fingerprint;
}

function ownerBatchCaptureDataUrl(video) {
  const crop = ownerScanCrop(video.videoWidth, video.videoHeight);
  const maxOutput = 1500;
  const scale = Math.min(1, maxOutput / Math.max(crop.sw, crop.sh));
  const width = Math.max(420, Math.round(crop.sw * scale));
  const height = Math.max(588, Math.round(crop.sh * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", {alpha: false});
  if (!context) throw new Error("Camera capture is unavailable in this browser.");
  context.drawImage(
    video,
    crop.sx,
    crop.sy,
    crop.sw,
    crop.sh,
    0,
    0,
    width,
    height
  );
  return canvas.toDataURL("image/jpeg", 0.88);
}

function ownerBatchStopLoop() {
  if (state.ownerRecognition.batch.timer) {
    window.clearInterval(state.ownerRecognition.batch.timer);
  }
  state.ownerRecognition.batch.timer = null;
  state.ownerRecognition.batch.previousFingerprint = null;
  state.ownerRecognition.batch.stableFrames = 0;
}

function ownerBatchStartLoop() {
  ownerBatchStopLoop();
  if (!state.ownerRecognition.batch.enabled) return;
  state.ownerRecognition.batch.timer = window.setInterval(ownerBatchTick, 420);
}

function ownerBatchSetCameraState(text) {
  const node = byId("owner-batch-camera-state");
  if (node) node.textContent = text;
}

function ownerBatchFlashResult(status) {
  const guide = document.querySelector(".owner-scan-card-guide");
  if (!guide) return;
  window.clearTimeout(state.ownerRecognition.batch.flashTimer);
  guide.classList.remove("scan-ok", "scan-review");
  guide.classList.add(status === "recognised" || status === "corrected" ? "scan-ok" : "scan-review");
  state.ownerRecognition.batch.flashTimer = window.setTimeout(() => {
    guide.classList.remove("scan-ok", "scan-review");
  }, 720);
}

function ownerBatchScheduleReady(itemId) {
  const batch = state.ownerRecognition.batch;
  window.clearTimeout(batch.statusTimer);
  batch.statusTimer = window.setTimeout(() => {
    if (
      batch.enabled
      && !batch.paused
      && !batch.processing
      && batch.latestResultId === itemId
    ) {
      ownerBatchSetCameraState("Move to the next card · auto-scan ready");
    }
  }, 1450);
}

function ownerBatchShouldSuppressAutoCapture(fingerprint) {
  const batch = state.ownerRecognition.batch;
  if (!fingerprint || !batch.lastAutoCaptureFingerprint) return false;
  if (Date.now() - batch.lastAutoCaptureAt > 1800) return false;
  return ownerBatchFingerprintDelta(fingerprint, batch.lastAutoCaptureFingerprint) < 0.012;
}

async function ownerBatchCaptureNow() {
  const batch = state.ownerRecognition.batch;
  const video = byId("owner-scan-video");
  const button = byId("owner-batch-capture-now");

  if (batch.processing) {
    ownerBatchSetCameraState("Already recognising this card…");
    return;
  }
  if (!state.ownerRecognition.cameraStream || !video?.videoWidth || !video?.videoHeight) {
    ownerBatchSetCameraState("Camera is still starting · try again in a moment");
    return;
  }

  if (button) button.disabled = true;
  try {
    const fingerprint = ownerBatchFrameFingerprint(video);
    if (fingerprint) {
      batch.previousFingerprint = fingerprint;
      batch.lastAcceptedFingerprint = fingerprint;
      batch.lastAutoCaptureFingerprint = fingerprint;
      batch.lastAutoCaptureAt = Date.now();
      batch.armed = false;
      batch.stableFrames = 0;
    }
    const dataUrl = ownerBatchCaptureDataUrl(video);
    await ownerBatchRecognise(dataUrl);
  } catch (error) {
    ownerBatchSetCameraState(error.message || "Capture failed · try again");
  } finally {
    if (button) button.disabled = false;
  }
}

async function ownerBatchTick() {
  const batch = state.ownerRecognition.batch;
  const video = byId("owner-scan-video");
  if (
    !batch.enabled
    || batch.paused
    || batch.processing
    || !state.ownerRecognition.cameraStream
    || !video?.videoWidth
  ) {
    return;
  }

  const fingerprint = ownerBatchFrameFingerprint(video);
  if (!fingerprint) return;

  if (batch.lastAcceptedFingerprint) {
    const changed = ownerBatchFingerprintDelta(fingerprint, batch.lastAcceptedFingerprint);
    if (!batch.armed && changed >= 0.11) {
      batch.armed = true;
      batch.stableFrames = 0;
      ownerBatchSetCameraState("New card detected · hold steady");
    }
  }

  const movement = ownerBatchFingerprintDelta(fingerprint, batch.previousFingerprint);
  batch.previousFingerprint = fingerprint;

  if (movement <= 0.028) {
    batch.stableFrames += 1;
  } else {
    batch.stableFrames = 0;
    ownerBatchSetCameraState(batch.armed ? "Hold card steady" : "Move to the next card");
  }

  if (batch.armed && batch.stableFrames >= 3) {
    batch.stableFrames = 0;
    batch.armed = false;
    batch.lastAcceptedFingerprint = fingerprint;
    if (ownerBatchShouldSuppressAutoCapture(fingerprint)) {
      ownerBatchSetCameraState("Same card just scanned · move to the next card");
      return;
    }
    batch.lastAutoCaptureFingerprint = fingerprint;
    batch.lastAutoCaptureAt = Date.now();
    const dataUrl = ownerBatchCaptureDataUrl(video);
    await ownerBatchRecognise(dataUrl);
  }
}

function ownerBatchCandidateSnapshot(candidate) {
  return candidate?.candidate_snapshot || {};
}

function ownerBatchSelectedName(item) {
  const selected = item.selected;
  const snapshot = ownerBatchCandidateSnapshot(selected);
  return snapshot.name || selected?.name || item.guess || "Card needs review";
}

function ownerBatchSelectedMeta(item) {
  const selected = item.selected;
  const snapshot = ownerBatchCandidateSnapshot(selected);
  if (selected?.manual_search) {
    return [
      selected.game,
      selected.set_name,
      selected.card_number,
      selected.variant,
      selected.language,
    ].filter(Boolean).join(" · ");
  }
  return [
    snapshot.game,
    snapshot.set_name,
    snapshot.card_number || snapshot.base_card_id,
    snapshot.variant,
    snapshot.language,
  ].filter(Boolean).join(" · ");
}

function ownerBatchMarketValue(item) {
  return item.selected?.market_value_minor ?? null;
}

function ownerBatchReferenceTotal() {
  return state.ownerRecognition.batch.items.reduce((total, item) => {
    if (!["recognised", "corrected", "added"].includes(item.status)) return total;
    return total + Number(ownerBatchMarketValue(item) || 0);
  }, 0);
}

function ownerBatchUnresolvedCount() {
  return state.ownerRecognition.batch.items.filter(
    (item) => !["recognised", "corrected", "added"].includes(item.status)
  ).length;
}

function ownerBatchCreateThumb(item, className = "owner-batch-thumb") {
  const wrap = document.createElement("div");
  wrap.className = className;
  const image = document.createElement("img");
  image.src = item.captureDataUrl;
  image.alt = ownerBatchSelectedName(item);
  wrap.append(image);
  return wrap;
}

function ownerBatchRenderStrip() {
  const strip = byId("owner-batch-strip");
  if (!strip) return;
  strip.replaceChildren();
  const items = state.ownerRecognition.batch.items;

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-batch-strip-empty";
    empty.textContent = "Recognised cards will appear here automatically.";
    strip.append(empty);
    return;
  }

  for (const item of items.slice().reverse()) {
    const card = document.createElement("article");
    card.className = `owner-batch-strip-card ${item.status}`;
    card.append(ownerBatchCreateThumb(item));

    const copy = document.createElement("div");
    copy.className = "owner-batch-strip-copy";
    const name = document.createElement("strong");
    name.textContent = ownerBatchSelectedName(item);
    const value = document.createElement("span");
    value.textContent = item.status === "unresolved"
      ? "Needs review"
      : ownerBatchFormatValue(ownerBatchMarketValue(item));
    copy.append(name, value);

    const fix = document.createElement("button");
    fix.type = "button";
    fix.textContent = item.status === "unresolved" ? "Fix" : "Change";
    fix.addEventListener("click", () => ownerBatchOpenCorrection(item.id));

    card.append(copy, fix);
    strip.append(card);
  }
  strip.scrollLeft = 0;
}

function ownerBatchLatestItem() {
  const batch = state.ownerRecognition.batch;
  return batch.items.find((item) => item.id === batch.latestResultId)
    || batch.items[batch.items.length - 1]
    || null;
}

function ownerBatchRemoveItem(itemId) {
  const batch = state.ownerRecognition.batch;
  const item = ownerBatchFindItem(itemId);
  if (!item || item.status === "added") return;
  batch.items = batch.items.filter((candidate) => candidate.id !== itemId);
  batch.latestResultId = batch.items[batch.items.length - 1]?.id || null;
  ownerBatchRender();
  if (!byId("owner-batch-review").classList.contains("hidden")) {
    ownerBatchRenderReview();
  }
  ownerBatchSetCameraState(
    batch.items.length ? "Card removed · keep scanning" : "Point at a card"
  );
}

function ownerBatchRenderLatest() {
  const card = byId("owner-batch-latest");
  const item = ownerBatchLatestItem();
  if (!card || !item) {
    if (card) card.classList.add("hidden");
    return;
  }

  state.ownerRecognition.batch.latestResultId = item.id;
  card.dataset.itemId = item.id;
  card.className = `owner-batch-latest ${item.status}`;
  card.classList.remove("hidden");

  const thumb = byId("owner-batch-latest-thumb");
  thumb.replaceChildren();
  const image = document.createElement("img");
  image.src = item.captureDataUrl;
  image.alt = ownerBatchSelectedName(item);
  thumb.append(image);

  byId("owner-batch-latest-name").textContent = ownerBatchSelectedName(item);
  byId("owner-batch-latest-meta").textContent =
    ownerBatchSelectedMeta(item) || item.guess || "Check this match";
  byId("owner-batch-latest-value").textContent =
    item.status === "unresolved" || item.status === "error"
      ? "Value pending until match is confirmed"
      : `Market ${ownerBatchFormatValue(ownerBatchMarketValue(item))}`;

  const status = byId("owner-batch-latest-status");
  const labels = {
    recognised: "Match found",
    corrected: "Corrected",
    unresolved: "Needs review",
    error: "Needs attention",
    added: "Added",
  };
  status.textContent = labels[item.status] || "Scanned";
  status.className = `owner-batch-latest-status ${item.status}`;

  const fix = byId("owner-batch-latest-fix");
  fix.textContent = item.status === "unresolved" || item.status === "error"
    ? "Fix match"
    : "Change";
  fix.disabled = item.status === "added";
  byId("owner-batch-latest-remove").disabled = item.status === "added";
}

function ownerBatchRender() {
  const items = state.ownerRecognition.batch.items;
  const unresolved = ownerBatchUnresolvedCount();
  byId("owner-batch-count").textContent = `${items.length} ${items.length === 1 ? "card" : "cards"}`;
  byId("owner-batch-total").textContent = formatMoney(ownerBatchReferenceTotal());
  byId("owner-batch-unresolved").textContent = String(unresolved);
  byId("owner-batch-unresolved-wrap").classList.toggle("hidden", unresolved === 0);
  byId("owner-batch-review-button").disabled = items.length === 0;
  ownerBatchRenderLatest();
  ownerBatchRenderStrip();
}

async function ownerBatchRecognise(dataUrl) {
  const batch = state.ownerRecognition.batch;
  if (batch.processing) return;
  batch.processing = true;
  byId("owner-batch-scan-pulse").classList.remove("hidden");
  ownerBatchSetCameraState("Captured · recognising…");

  try {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 70000);
    let data;
    try {
      data = await apiRequest("/api/v1/recognition/resolve", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({image_data_url: dataUrl, force_refresh: true}),
      });
    } finally {
      window.clearTimeout(timeout);
    }

    const candidates = (data.candidates || [])
      .filter((candidate) => candidate.catalogue_id && !candidate.hard_rejected)
      .sort((left, right) => Number(left.rank || 9999) - Number(right.rank || 9999));
    const top = candidates[0] || null;
    const autoRecognised =
      data.run?.decision === "EXACT_CANDIDATE"
      && top
      && top.catalogue_id === data.run?.top_catalogue_id;

    const observation = data.run?.ai_observation || {};
    const item = {
      id: crypto.randomUUID(),
      runId: data.run?.id,
      run: data.run,
      result: data,
      captureDataUrl: dataUrl,
      selected: autoRecognised ? top : null,
      suggested: top,
      status: autoRecognised ? "recognised" : "unresolved",
      guess: observation.name_guess || top?.candidate_snapshot?.name || "Unresolved card",
      searchSeed: observation.card_number || top?.candidate_snapshot?.card_number || "",
      feedbackOutcome: null,
      intakeKey: crypto.randomUUID(),
      inventoryCode: null,
      error: null,
    };
    batch.items.push(item);
    batch.latestResultId = item.id;
    ownerBatchRender();
    ownerBatchFlashResult(item.status);

    if (autoRecognised) {
      ownerBatchSetCameraState(
        `${ownerBatchSelectedName(item)} · ${ownerBatchFormatValue(ownerBatchMarketValue(item))}`
      );
    } else {
      ownerBatchSetCameraState("Needs review · keep scanning or tap Fix match");
    }
    ownerBatchScheduleReady(item.id);
  } catch (error) {
    const item = {
      id: crypto.randomUUID(),
      runId: null,
      run: null,
      result: null,
      captureDataUrl: dataUrl,
      selected: null,
      suggested: null,
      status: "unresolved",
      guess: "Recognition failed",
      searchSeed: "",
      feedbackOutcome: null,
      intakeKey: crypto.randomUUID(),
      inventoryCode: null,
      error: error?.name === "AbortError" ? "Recognition timed out" : error.message,
    };
    batch.items.push(item);
    batch.latestResultId = item.id;
    ownerBatchRender();
    ownerBatchFlashResult("unresolved");
    ownerBatchSetCameraState("Couldn’t identify that card · tap Fix match or keep scanning");
    ownerBatchScheduleReady(item.id);
  } finally {
    batch.processing = false;
    byId("owner-batch-scan-pulse").classList.add("hidden");
  }
}

function ownerBatchFindItem(id) {
  return state.ownerRecognition.batch.items.find((item) => item.id === id) || null;
}

function ownerBatchCloseCorrection() {
  const batch = state.ownerRecognition.batch;
  batch.currentCorrectionId = null;
  byId("owner-batch-correction").classList.add("hidden");
  byId("owner-batch-search-results").replaceChildren();
  byId("owner-batch-search-message").textContent = "";
  if (batch.enabled && state.ownerRecognition.cameraStream) {
    batch.paused = false;
    batch.stableFrames = 0;
    batch.previousFingerprint = null;
    ownerBatchSetCameraState("Correction saved · show the next card");
  }
}

function ownerBatchOpenCorrection(itemId) {
  const item = ownerBatchFindItem(itemId);
  if (!item) return;
  const batch = state.ownerRecognition.batch;
  batch.currentCorrectionId = itemId;
  batch.paused = true;
  batch.stableFrames = 0;
  byId("owner-batch-correction").classList.remove("hidden");
  const input = byId("owner-batch-search-input");
  input.value = item.searchSeed || "";
  byId("owner-batch-search-results").replaceChildren();
  byId("owner-batch-search-message").textContent = "";
  input.focus();
  if (input.value.trim().length >= 2) ownerBatchSearchCards(input.value.trim());
}

function ownerBatchSearchResultCard(row) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "owner-batch-search-result";

  const imageWrap = document.createElement("div");
  imageWrap.className = "owner-batch-search-image";
  if (row.image_url) {
    const image = document.createElement("img");
    image.src = row.image_url;
    image.alt = safeText(row.name, "Trading card");
    image.loading = "lazy";
    imageWrap.append(image);
  } else {
    imageWrap.textContent = safeText(row.game, "DR").slice(0, 3).toUpperCase();
  }

  const copy = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = safeText(row.name);
  const meta = document.createElement("span");
  meta.textContent = [
    row.game,row.set_name,row.card_number,row.variant,row.rarity,row.language,
  ].filter(Boolean).join(" · ");
  const value = document.createElement("small");
  value.textContent = row.market_value_minor == null
    ? "Reference value unavailable"
    : `Market ${formatMoney(row.market_value_minor)}`;
  copy.append(name, meta, value);

  const choose = document.createElement("em");
  choose.textContent = "Choose";
  card.append(imageWrap, copy, choose);
  card.addEventListener("click", () => ownerBatchChooseSearchResult(row));
  return card;
}

async function ownerBatchSearchCards(query) {
  const message = byId("owner-batch-search-message");
  const results = byId("owner-batch-search-results");
  message.textContent = "Searching Drop Rate catalogue…";
  results.replaceChildren();
  try {
    const params = new URLSearchParams({q: query, limit: "20"});
    const data = await apiRequest(`/api/v1/owner/catalogue-search?${params.toString()}`);
    const items = data.items || [];
    message.textContent = items.length ? "" : "No matching cards found. Try the exact card number.";
    items.forEach((row) => results.append(ownerBatchSearchResultCard(row)));
  } catch (error) {
    message.textContent = error.message;
    message.className = "owner-card-message error";
  }
}

async function ownerBatchChooseSearchResult(row) {
  const item = ownerBatchFindItem(state.ownerRecognition.batch.currentCorrectionId);
  if (!item) return;

  if (!item.runId) {
    item.error = "Rescan this card first so the correction can be attached to recognition evidence.";
    ownerBatchCloseCorrection();
    ownerBatchRenderReview();
    return;
  }

  byId("owner-batch-search-message").textContent = "Saving correction…";
  try {
    await apiRequest(`/api/v1/recognition/runs/${item.runId}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        outcome: "CORRECTED_BY_SEARCH",
        selected_catalogue_id: row.id,
        notes: "Seller corrected batch scan using catalogue search",
      }),
    });
    item.selected = {
      manual_search: true,
      catalogue_id: row.id,
      game: row.game,
      name: row.name,
      set_name: row.set_name,
      card_number: row.card_number,
      variant: row.variant,
      rarity: row.rarity,
      language: row.language,
      market_value_minor: row.market_value_minor,
      recommended_retail_minor: row.recommended_retail_minor,
      image_url: row.image_url,
    };
    item.status = "corrected";
    item.feedbackOutcome = "CORRECTED_BY_SEARCH";
    item.error = null;
    item.searchSeed = row.card_number || row.name || "";
    state.ownerRecognition.batch.latestResultId = item.id;
    ownerBatchCloseCorrection();
    ownerBatchRender();
    ownerBatchFlashResult("corrected");
    ownerBatchRenderReview();
  } catch (error) {
    byId("owner-batch-search-message").textContent = error.message;
    byId("owner-batch-search-message").className = "owner-card-message error";
  }
}

function ownerBatchRenderReview() {
  const list = byId("owner-batch-review-list");
  if (!list) return;
  list.replaceChildren();
  const items = state.ownerRecognition.batch.items;
  const unresolved = ownerBatchUnresolvedCount();

  byId("owner-batch-review-count").textContent = String(items.length);
  byId("owner-batch-review-total").textContent = formatMoney(ownerBatchReferenceTotal());

  for (const item of items) {
    const row = document.createElement("article");
    row.className = `owner-batch-review-item ${item.status}`;
    row.append(ownerBatchCreateThumb(item, "owner-batch-review-thumb"));

    const copy = document.createElement("div");
    copy.className = "owner-batch-review-copy";
    const name = document.createElement("strong");
    name.textContent = ownerBatchSelectedName(item);
    const meta = document.createElement("span");
    meta.textContent = ownerBatchSelectedMeta(item) || item.error || "Needs a corrected match";
    const value = document.createElement("small");
    value.textContent = item.status === "unresolved"
      ? "Needs review before inventory"
      : `Reference market value ${ownerBatchFormatValue(ownerBatchMarketValue(item))}`;
    copy.append(name, meta, value);

    const actions = document.createElement("div");
    actions.className = "owner-batch-review-item-actions";
    if (item.status !== "added") {
      const fix = document.createElement("button");
      fix.type = "button";
      fix.textContent = item.status === "unresolved" ? "Fix match" : "Change";
      fix.addEventListener("click", () => ownerBatchOpenCorrection(item.id));
      actions.append(fix);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = item.status === "added" ? "Added" : "Remove";
    remove.disabled = item.status === "added";
    remove.addEventListener("click", () => ownerBatchRemoveItem(item.id));
    actions.append(remove);

    row.append(copy, actions);
    list.append(row);
  }

  const condition = byId("owner-batch-condition").value;
  byId("owner-batch-add-all").disabled =
    !items.length
    || unresolved > 0
    || !condition
    || items.every((item) => item.status === "added");
}

function ownerBatchOpenReview() {
  state.ownerRecognition.batch.paused = true;
  ownerScanStopCamera();
  byId("owner-batch-review").classList.remove("hidden");
  ownerBatchRenderReview();
  byId("owner-batch-review").scrollIntoView({behavior: "smooth", block: "start"});
}

async function ownerBatchResume() {
  byId("owner-batch-review").classList.add("hidden");
  try {
    await ownerScanStartCamera(state.ownerRecognition.cameraFacingMode || "environment");
  } catch (error) {
    ownerScanMessage(error.message, "error");
  }
}

async function ownerBatchEnsureFeedback(item) {
  if (item.feedbackOutcome) return;
  if (!item.runId || !item.selected?.catalogue_id) {
    throw new Error("This card still needs a confirmed identity.");
  }
  const topCatalogueId = item.run?.top_catalogue_id;
  const outcome = item.selected.catalogue_id === topCatalogueId
    ? "CONFIRMED_TOP"
    : "CORRECTED_TO_CANDIDATE";
  await apiRequest(`/api/v1/recognition/runs/${item.runId}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      outcome,
      selected_catalogue_id: item.selected.catalogue_id,
      notes: "Seller confirmed during batch scan review",
    }),
  });
  item.feedbackOutcome = outcome;
}

async function ownerBatchAddAll() {
  const condition = byId("owner-batch-condition").value;
  const items = state.ownerRecognition.batch.items;
  const unresolved = ownerBatchUnresolvedCount();
  const message = byId("owner-batch-review-message");
  if (!condition) {
    message.textContent = "Choose the default condition for this batch.";
    message.className = "owner-card-message error";
    return;
  }
  if (unresolved) {
    message.textContent = `Fix ${unresolved} unresolved ${unresolved === 1 ? "card" : "cards"} before adding the batch.`;
    message.className = "owner-card-message error";
    return;
  }

  const button = byId("owner-batch-add-all");
  button.disabled = true;
  let added = 0;
  let failed = 0;

  for (const item of items) {
    if (item.status === "added") continue;
    try {
      message.textContent = `Adding ${ownerBatchSelectedName(item)}…`;
      message.className = "owner-card-message";
      await ownerBatchEnsureFeedback(item);
      const language = item.selected?.manual_search
        ? item.selected.language
        : ownerBatchCandidateSnapshot(item.selected).language;
      const data = await apiRequest("/api/v1/owner/recognition-intake", {
        method: "POST",
        headers: {"Idempotency-Key": item.intakeKey},
        body: JSON.stringify({
          recognition_run_id: item.runId,
          selected_catalogue_id: item.selected.catalogue_id,
          condition,
          grading_company: null,
          grade: null,
          certificate_number: null,
          language: language || null,
        }),
      });
      item.status = "added";
      item.inventoryCode = data.inventory?.inventory_code || null;
      if (data.inventory?.market_value_minor != null) {
        item.selected.market_value_minor = data.inventory.market_value_minor;
      }
      added += 1;
    } catch (error) {
      item.error = error.message;
      item.status = "error";
      failed += 1;
    }
    ownerBatchRenderReview();
  }

  await Promise.all([loadOwnerOverview(), loadOwnerInventory()]);
  ownerBatchRender();
  ownerBatchRenderReview();
  if (failed) {
    message.textContent = `${added} added, ${failed} need attention. Nothing was duplicated on retry.`;
    message.className = "owner-card-message error";
  } else {
    message.textContent = `${added} ${added === 1 ? "card" : "cards"} added to your inventory as DRAFT, pending Drop Rate verification.`;
    message.className = "owner-card-message success";
  }
}

async function ownerRecognitionEnter() {
  if (!state.session?.access_token || state.ownerRecognition.status) return;
  const badge = byId("owner-scan-engine-status");
  try {
    const data = await apiRequest("/api/v1/recognition/status");
    state.ownerRecognition.status = data;
    badge.textContent = data.configured ? `${data.vision_model} · READY` : "UNAVAILABLE";
    badge.className = `owner-status-pill ${data.configured ? "approved" : "inspection"}`;
    byId("owner-scan-open-camera").disabled = !data.configured;
    byId("owner-scan-run").disabled = !data.configured || !state.ownerRecognition.imageDataUrl;
    if (!data.configured) {
      ownerScanMessage("Recognition is temporarily unavailable. Your existing inventory is unaffected.", "error");
    }
  } catch (error) {
    badge.textContent = "UNAVAILABLE";
    badge.className = "owner-status-pill inspection";
    ownerScanMessage(error.message, "error");
  }
}
window.ownerRecognitionEnter = ownerRecognitionEnter;

byId("owner-scan-open-camera").addEventListener("click", async () => {
  try {
    await ownerScanStartCamera("environment");
  } catch (error) {
    ownerScanMessage(
      error?.name === "NotAllowedError"
        ? "Camera permission was blocked. Allow camera access or upload a photo instead."
        : error.message,
      "error"
    );
  }
});
byId("owner-scan-switch-camera").addEventListener("click", async () => {
  try {
    await ownerScanStartCamera(
      state.ownerRecognition.cameraFacingMode === "environment" ? "user" : "environment"
    );
  } catch (error) {
    ownerScanMessage(error.message, "error");
  }
});
byId("owner-scan-close-camera").addEventListener("click", () => ownerScanStopCamera());
byId("owner-batch-close").addEventListener("click", () => ownerScanStopCamera());
byId("owner-batch-switch-camera").addEventListener("click", async () => {
  try {
    await ownerScanStartCamera(
      state.ownerRecognition.cameraFacingMode === "environment" ? "user" : "environment"
    );
  } catch (error) {
    ownerScanMessage(error.message, "error");
  }
});
byId("owner-batch-capture-now").addEventListener("click", ownerBatchCaptureNow);
byId("owner-batch-latest-fix").addEventListener("click", () => {
  const item = ownerBatchLatestItem();
  if (item && item.status !== "added") ownerBatchOpenCorrection(item.id);
});
byId("owner-batch-latest-remove").addEventListener("click", () => {
  const item = ownerBatchLatestItem();
  if (item) ownerBatchRemoveItem(item.id);
});
byId("owner-batch-review-button").addEventListener("click", ownerBatchOpenReview);
byId("owner-batch-resume").addEventListener("click", ownerBatchResume);
byId("owner-batch-correction-close").addEventListener("click", ownerBatchCloseCorrection);
byId("owner-batch-search-input").addEventListener("input", (event) => {
  window.clearTimeout(state.ownerRecognition.batch.searchTimer);
  const query = event.currentTarget.value.trim();
  state.ownerRecognition.batch.searchTimer = window.setTimeout(() => {
    if (query.length >= 2) ownerBatchSearchCards(query);
    else {
      byId("owner-batch-search-results").replaceChildren();
      byId("owner-batch-search-message").textContent = "";
    }
  }, 260);
});
byId("owner-batch-condition").addEventListener("change", ownerBatchRenderReview);
byId("owner-batch-add-all").addEventListener("click", ownerBatchAddAll);
byId("owner-scan-capture").addEventListener("click", ownerScanCapture);
byId("owner-scan-file").addEventListener("change", ownerScanHandleFile);
byId("owner-scan-run").addEventListener("click", ownerScanRun);
byId("owner-scan-clear").addEventListener("click", () => ownerScanClear());
byId("owner-scan-intake-form").addEventListener("submit", ownerScanSubmitIntake);
byId("owner-scan-change-match").addEventListener("click", () => {
  byId("owner-scan-intake-panel").classList.add("hidden");
  state.ownerRecognition.selectedCandidate = null;
  state.ownerRecognition.intakeKey = null;
  byId("owner-scan-result").scrollIntoView({behavior: "smooth", block: "start"});
});
document.querySelectorAll('input[name="owner-scan-state"]').forEach((input) => {
  input.addEventListener("change", ownerScanUpdatePhysicalState);
});
byId("owner-scan-another").addEventListener("click", () => {
  ownerScanClear({keepMessage: true});
  ownerScanMessage("Ready for your next card.");
  byId("owner-scan-open-camera").scrollIntoView({behavior: "smooth", block: "center"});
});
document.querySelectorAll('[data-owner-view="scan"],[data-owner-jump="scan"]').forEach((button) => {
  button.addEventListener("click", () => ownerRecognitionEnter());
});

window.addEventListener("pagehide", () => ownerScanStopCamera());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") ownerScanStopCamera();
});
