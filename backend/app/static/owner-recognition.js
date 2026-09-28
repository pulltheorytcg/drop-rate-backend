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
