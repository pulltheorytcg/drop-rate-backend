"use strict";

// Shared mobile presentation. API authorization and exact-printing decisions stay on the server.
window.DropRateScanner = (() => {
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  };
  const button = (label, action, className = "dr-scan-text-button") => {
    const element = node("button", className, label);
    element.type = "button";
    element.addEventListener("click", action);
    return element;
  };
  const money = value => value == null ? "—" : new Intl.NumberFormat("en-GB", {
    style: "currency", currency: "GBP",
  }).format(value / 100);
  const snapshot = candidate => candidate?.candidate_snapshot || candidate || {};
  const selected = item => item.selected || item.suggested;
  const book = item => item.mode === "COMIC";
  const researching = result => ["PENDING", "RUNNING"].includes(result?.research?.status);
  async function researchBook(request, result, photos, signal) {
    if (!researching(result) || !/^[0-9a-f-]{36}$/i.test(result.run_id || "")) return result;
    const runId = result.run_id;
    try {
      result = await request(`/api/v1/owner/books/research/${runId}`, {
        method: "POST", signal, body: JSON.stringify({images: photos}),
      });
    } catch (error) {
      if (signal.aborted || [401, 403, 404, 422].includes(error.status)) throw error;
      // A disconnected response may have completed. Read its receipt; never
      // launch another paid lookup just because the transport was interrupted.
      result = await request(`/api/v1/owner/books/recognize/${runId}`, {signal});
    }
    for (let attempt = 0; researching(result) && attempt < 40; attempt++) {
      await new Promise((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
        const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 1500);
        signal.addEventListener("abort", abort, {once:true});
        if (signal.aborted) abort();
      });
      result = await request(`/api/v1/owner/books/recognize/${runId}`, {signal});
    }
    if (researching(result)) throw new Error("Publisher lookup is taking longer. Your book details are ready to review.");
    return result;
  }
  const bookCover = item => {
    const result = item.bookResult, research = result?.research;
    const candidate = research?.candidates?.find(c => c.id === research.selected_candidate_id)
      || (research?.candidates?.length === 1 ? research.candidates[0] : null);
    const path = candidate?.image_path;
    return candidate && /^[0-9a-f-]{36}$/i.test(result.run_id || "") && /^[a-f0-9]{24}$/.test(candidate.id)
      && path === `/api/v1/owner/books/research/${result.run_id}/cover/${candidate.id}` ? path : null;
  };
  const sealed = item => [snapshot(selected(item)).product_type,
    snapshot(selected(item)).collectible_type].includes("SEALED");
  const name = item => snapshot(selected(item)).name || item.guess || "Check this match";
  const meta = item => {
    if (book(item)) {
      const fields = item.bookResult?.fields || {};
      return [fields.publisher, fields.language, fields.volume_identifier].filter(Boolean).join(" · ");
    }
    const card = snapshot(selected(item));
    return [card.game, card.set_name, card.product_code || card.card_number || card.base_card_id,
      card.language, card.variant || card.art_treatment].filter(Boolean).join(" · ");
  };
  const conditions = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
  const graded = item => item.mode === "GRADED";
  const graders = ["PSA", "BGS", "CGC", "TAG", "ACE", "BVG", "BCCG"];
  const gradeOptions = company => {
    const whole = Array.from({length: company === "BCCG" ? 6 : 10}, (_, index) => String(10 - index));
    const values = ["ACE", "TAG", "BCCG"].includes(company) ? whole
      : Array.from({length: 19}, (_, index) => String(10 - index / 2)).filter(value => company !== "PSA" || value !== "9.5");
    if (company === "BGS") values.unshift("10 BLACK LABEL");
    if (["CGC", "TAG"].includes(company)) values.unshift("Pristine 10");
    return values;
  };
  const certificateValid = item => (item.grading_company === "TAG" ? /^[A-Z0-9]{8}$/
    : item.grading_company === "PSA" ? /^\d{7,10}$/ : /^\d{4,14}$/).test(item.certificate_number || "");
  const gradeValid = item => graders.includes(item.grading_company) && gradeOptions(item.grading_company).includes(item.grade)
    && certificateValid(item)
    && !item.slab?.conflicts?.length;
  // A raw reference valuation is never a quote for a different grader/grade.
  const valueOf = item => graded(item) ? item.savedGradedValue ?? null : selected(item)?.market_value_minor ?? null;
  const usableRun = item => item.run?.id && ["EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH"].includes(item.run.decision || item.run.status);
  const icons = {
    photo: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" fill="currentColor"/><circle cx="8" cy="8" r="2" fill="#465050"/><path d="m4 18 5-6 3 3 4-6 5 9" fill="#465050"/></svg>',
    trash: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/></svg>',
  };
  const tokenClaims = session => {
    try { return JSON.parse(atob(session.access_token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); }
    catch (_) { return {}; }
  };
  const sessionId = session => session?.access_token ? session.user?.id || tokenClaims(session).sub : null;
  const fingerprintDelta = (left, right) => {
    if (!left || !right || left.length !== right.length) return 1;
    return left.reduce((total, value, index) => total + Math.abs(value - right[index]), 0) / left.length / 255;
  };

  // Four-sided, straight-edge gate for the live scan guide. Frame variance
  // alone is NOT evidence of a trading card: patterned tables, hands, posters,
  // reflections and empty rooms can be extremely detailed. Fail closed when
  // we cannot establish a centered rectangular object with four visible edges.
  const analyzeCardPresence = (pixels, width, height, mode = "RAW") => {
    const empty = {present: false, box: null, edgeConfidence: 0};
    if (!pixels || width < 32 || height < 44 || pixels.length < width * height * 4) return empty;
    const rgbDifference = (left, right) => (
      Math.abs(pixels[left] - pixels[right])
      + Math.abs(pixels[left + 1] - pixels[right + 1])
      + Math.abs(pixels[left + 2] - pixels[right + 2])
    ) / (3 * 255);
    const edge = (position, scan, vertical) => {
      if (vertical) {
        const a = (scan * width + position - 2) * 4;
        const b = (scan * width + position + 2) * 4;
        return rgbDifference(a, b);
      }
      const a = ((position - 2) * width + scan) * 4;
      const b = ((position + 2) * width + scan) * 4;
      return rgbDifference(a, b);
    };
    const strongestLine = (vertical, from, through, spanStart, spanEnd) => {
      const measures = [];
      for (let position = from; position <= through; position += 1) {
        let total = 0, hits = 0, streak = 0, longest = 0;
        for (let scan = spanStart; scan <= spanEnd; scan += 1) {
          const difference = edge(position, scan, vertical);
          total += difference;
          if (difference >= 0.105) { hits += 1; streak += 1; longest = Math.max(longest, streak); }
          else streak = 0;
        }
        const samples = spanEnd - spanStart + 1;
        measures.push({position, mean: total / samples, support: hits / samples,
          continuity: longest / samples});
      }
      const baseline = measures.reduce((sum, value) => sum + value.mean, 0) / measures.length;
      const peak = measures.reduce((best, line) => line.mean > best.mean ? line : best);
      return {...peak, prominence: peak.mean / Math.max(0.012, baseline)};
    };
    const w = width, h = height, sealed = mode === "SEALED";
    const middleY1 = Math.floor(h * 0.30), middleY2 = Math.ceil(h * 0.70);
    const middleX1 = Math.floor(w * 0.28), middleX2 = Math.ceil(w * 0.72);
    // Sealed booster packs are often taller/narrower than raw cards; keep
    // four-sided evidence mandatory while widening ONLY those guide bands.
    const left = strongestLine(true, Math.ceil(w * 0.07), Math.floor(w * (sealed ? 0.39 : 0.31)), middleY1, middleY2);
    const right = strongestLine(true, Math.ceil(w * (sealed ? 0.61 : 0.69)), Math.floor(w * 0.93), middleY1, middleY2);
    const top = strongestLine(false, Math.ceil(h * 0.06), Math.floor(h * (sealed ? 0.36 : 0.30)), middleX1, middleX2);
    const bottom = strongestLine(false, Math.ceil(h * (sealed ? 0.64 : 0.70)), Math.floor(h * 0.94), middleX1, middleX2);
    const borders = [left, right, top, bottom];
    const widthRatio = (right.position - left.position) / w;
    const heightRatio = (bottom.position - top.position) / h;
    const centered = Math.abs((left.position + right.position) / 2 - w / 2) <= w * 0.12
      && Math.abs((top.position + bottom.position) / 2 - h / 2) <= h * 0.12;
    const rectangular = sealed
      ? (widthRatio >= 0.39 && widthRatio <= 0.92 && heightRatio >= 0.52 && heightRatio <= 0.93
         && Math.abs(widthRatio - heightRatio) <= 0.39)
      : (widthRatio >= 0.56 && widthRatio <= 0.91 && heightRatio >= 0.58 && heightRatio <= 0.92
         && Math.abs(widthRatio - heightRatio) <= 0.16);
    const fourEdges = borders.every(side => side.mean >= 0.105
      && side.support >= 0.54 && side.prominence >= 1.40);
    // Straight lines alone can still mistake an oval hand for a *narrow*
    // sealed pack. A true rectangular item's borders reach toward all four
    // corners; an ellipse's upper/lower outlines exist near the centre only.
    const edgeSpan = (vertical, position, from, through) => {
      let hits = 0;
      const count = Math.max(1, through - from + 1);
      for (let scan = from; scan <= through; scan += 1) {
        if (edge(position, scan, vertical) >= 0.105) hits += 1;
      }
      return hits / count;
    };
    const xSize = right.position - left.position;
    const ySize = bottom.position - top.position;
    const xInset = Math.max(3, Math.round(xSize * 0.12));
    const yInset = Math.max(4, Math.round(ySize * 0.12));
    const xQuarter = Math.max(xInset + 2, Math.round(xSize * 0.34));
    const yQuarter = Math.max(yInset + 3, Math.round(ySize * 0.34));
    const nearCorners = [
      edgeSpan(false, top.position, left.position + xInset, left.position + xQuarter),
      edgeSpan(false, top.position, right.position - xQuarter, right.position - xInset),
      edgeSpan(false, bottom.position, left.position + xInset, left.position + xQuarter),
      edgeSpan(false, bottom.position, right.position - xQuarter, right.position - xInset),
      edgeSpan(true, left.position, top.position + yInset, top.position + yQuarter),
      edgeSpan(true, left.position, bottom.position - yQuarter, bottom.position - yInset),
      edgeSpan(true, right.position, top.position + yInset, top.position + yQuarter),
      edgeSpan(true, right.position, bottom.position - yQuarter, bottom.position - yInset),
    ];
    const cornersSupported = nearCorners.every(support => support >= 0.48);
    // An oval can have high contrast at the four sampled 'corners' if its
    // bounding box was fit to its curved sides. Require that each chosen
    // BORDER actually remains in the SAME place from one end to the other.
    // A hand's curved silhouette drifts several pixels; a card/pack doesn't.
    const longitudinal = [
      edgeSpan(true, left.position, top.position + yInset, bottom.position - yInset),
      edgeSpan(true, right.position, top.position + yInset, bottom.position - yInset),
      edgeSpan(false, top.position, left.position + xInset, right.position - xInset),
      edgeSpan(false, bottom.position, left.position + xInset, right.position - xInset),
    ];
    const straightSides = longitudinal.every(support => support >= 0.72);
    // Hands and blank rectangular objects have smooth interiors. A printed
    // TCG card, graded slab or booster usually contains visible fine artwork
    // inside its outer edge. Confirm local print/detail rather than relying
    // on an isolated silhouette or the camera's overall image variation.
    const innerX1 = Math.ceil(left.position + xSize * 0.24);
    const innerX2 = Math.floor(right.position - xSize * 0.24);
    const innerY1 = Math.ceil(top.position + ySize * 0.20);
    const innerY2 = Math.floor(bottom.position - ySize * 0.20);
    let sum = 0, squared = 0, sampleCount = 0;
    for (let y = innerY1; y <= innerY2; y += 1) {
      for (let x = innerX1; x <= innerX2; x += 1) {
        const pixel = (y * w + x) * 4;
        const gray = pixels[pixel] * 0.299 + pixels[pixel + 1] * 0.587 + pixels[pixel + 2] * 0.114;
        sum += gray; squared += gray * gray; sampleCount += 1;
      }
    }
    const printDeviation = sampleCount
      ? Math.sqrt(Math.max(0, squared / sampleCount - (sum / sampleCount) ** 2)) / 255
      : 0;
    const printed = printDeviation >= 0.055;
    return {
      present: centered && rectangular && fourEdges && cornersSupported && straightSides && printed,
      box: {left: left.position, right: right.position, top: top.position, bottom: bottom.position},
      edgeConfidence: Math.min(...borders.map(side => side.support * side.prominence)),
    };
  };

  class Scanner {
    constructor(options) {
      this.options = options;
      this.owner = sessionId(options.session());
      this.items = [];
      this.inFlight = 0;
      this.recognitionQueue = [];
      this.bookResearchQueue = [];
      this.researchInFlight = 0;
      this.captureBusy = false;
      this.epoch = 0;
      this.cameraRevision = 0;
      this.searchRevision = 0;
      this.mode = ["RAW", "GRADED", "SEALED", ...(options.openBooks ? ["COMIC"] : [])].includes(options.mode) ? options.mode : "RAW";
      this.auto = true;
      // Auto capture requires an observed EMPTY guide before it can arm.
      // This prevents a static textured desk/background from triggering on
      // startup, even if camera exposure briefly resembles a card.
      this.autoArmed = false;
      this.facing = "environment";
      this.controllers = new Set();
      this.images = new Map();
      this.objectUrls = new Set();
      this.build();
      this.setMode(this.mode);
      this.onVisibility = () => {
        if (document.visibilityState === "hidden") this.stopCamera();
      };
      this.onPageHide = () => this.destroy();
      document.addEventListener("visibilitychange", this.onVisibility);
      window.addEventListener("pagehide", this.onPageHide);
    }

    active(epoch = this.epoch) {
      return !this.destroyed && epoch === this.epoch && this.owner && this.owner === sessionId(this.options.session());
    }

    async request(path, options = {}) {
      const epoch = this.epoch;
      if (!this.active(epoch)) throw new Error("Your account changed. Please reopen the scanner.");
      await this.ensureSession(epoch);
      if (!this.active(epoch)) throw new Error("Your account changed. Please reopen the scanner.");
      const result = await this.options.request(path, {...options, headers: {...options.headers,
        Authorization: "Bearer " + this.options.session().access_token}});
      if (!this.active(epoch)) throw new Error("Your account changed. Please reopen the scanner.");
      return result;
    }

    async requestImage(path, {signal} = {}) {
      const epoch = this.epoch;
      if (!this.active(epoch)) throw new Error("Your account changed.");
      // Image transport stays on our authenticated API, never an arbitrary URL.
      if (!path.startsWith('/api/v1/catalogue-browser/reference-image?')
          && !/^\/api\/v1\/owner\/books\/research\/[0-9a-f-]{36}\/cover\/[a-f0-9]{24}$/i.test(path)) throw new Error("Invalid artwork request.");
      await this.ensureSession(epoch);
      if (!this.active(epoch)) throw new Error("Your account changed.");
      const response = await fetch(path, {signal, cache:"no-store",
        headers:{Authorization:"Bearer " + this.options.session().access_token}});
      if (!response.ok) throw new Error("Image unavailable.");
      const blob = await response.blob();
      if (!this.active(epoch)) throw new Error("Your account changed.");
      if (!/^image\/(png|jpeg|webp|avif)$/.test(blob.type) || blob.size > 2000000) throw new Error("Invalid artwork response.");
      return blob;
    }

    async ensureSession(epoch) {
      const session = this.options.session();
      const expires = tokenClaims(session).exp;
      if (!this.options.refreshSession || !expires || expires > Date.now() / 1000 + 60) return;
      if (!this.refreshing) {
        this.refreshing = (async () => {
          if (!session.refresh_token) throw new Error("Your session has expired. Sign in again.");
          const refreshed = await this.options.refreshSession(session.refresh_token);
          if (!this.active(epoch)) throw new Error("Your account changed. Please reopen the scanner.");
          if (sessionId(refreshed) !== this.owner) throw new Error("Session refresh did not match this account.");
          // A newer same-account refresh wins; never restore an older or different login.
          if (this.options.session().access_token === session.access_token) this.options.saveSession(refreshed);
        })().finally(() => { this.refreshing = null; });
      }
      await this.refreshing;
    }

    build() {
      this.dialog = node("dialog", "dr-scanner");
      this.dialog.setAttribute("aria-label", "Drop Rate scanner");
      this.dialog.innerHTML = '<section class="dr-scan-camera">' +
        '<video autoplay muted playsinline aria-label="Live camera"></video>' +
        '<header class="dr-scan-topbar"><button type="button" data-action="close" aria-label="Close scanner">←</button>' +
        '<strong>Scan your collection</strong><button type="button" data-action="settings" aria-label="Scanner settings">⚙</button></header>' +
        '<nav class="dr-scan-modes' + (this.options.openBooks ? ' dr-scan-modes-books' : '') + '" aria-label="Scan type">' +
        ['RAW', 'GRADED', 'SEALED'].map(mode => '<button type="button" data-mode="' + mode + '" aria-pressed="false">' + ({RAW:'Auto',GRADED:'Graded',SEALED:'Sealed'})[mode] + '</button>').join('') +
        (this.options.openBooks ? '<button type="button" data-mode="COMIC" aria-pressed="false">COMICS / MANGA</button>' : '') + '</nav>' +
        '<button type="button" class="dr-scan-certificate" data-action="certificate" hidden>Enter certificate</button>' +
        '<div class="dr-scan-guide" aria-hidden="true"></div><p class="dr-scan-status" role="status">Place a card or book inside the guide</p>' +
        '<button type="button" class="dr-scan-camera-resume" data-action="resume">Start camera</button>' +
        '<div class="dr-scan-settings" hidden><label><input type="checkbox" checked> Auto-scan</label>' +
        '<button type="button" data-action="switch">Switch camera</button><button type="button" data-action="torch" hidden>Torch off</button></div>' +
        '<div class="dr-scan-tray"><div class="dr-scan-strip" aria-label="Scanned items"></div>' +
        '<p class="dr-scan-total"></p><div class="dr-scan-controls">' +
        '<button type="button" data-action="gallery" class="dr-scan-gallery" aria-label="Choose a card photo">▧</button>' +
        '<button type="button" data-action="capture" class="dr-scan-shutter" aria-label="Scan this card"></button>' +
        '<button type="button" data-action="next" class="dr-scan-next">Next →</button></div></div>' +
        '<input type="file" class="dr-scan-file" accept="image/jpeg,image/png,image/webp" hidden></section>' +
        '<section class="dr-scan-review" hidden aria-labelledby="dr-scan-review-title">' +
        '<header class="dr-scan-review-header"><button type="button" data-action="back" aria-label="Resume scanning">←</button>' +
        '<h2 id="dr-scan-review-title">Is this your item?</h2><button type="button" data-action="close" aria-label="Close review">×</button></header>' +
        '<p class="dr-scan-destination">Adding to: <strong>Your inventory</strong></p>' +
        '<div class="dr-scan-review-list"></div><footer class="dr-scan-review-footer">' +
        '<strong class="dr-scan-review-total"></strong><span class="dr-scan-review-count"></span>' +
        '<p class="dr-scan-save-message" role="status"></p><button type="button" data-action="save" class="dr-scan-primary">Add to collection</button>' +
        '</footer></section><div class="dr-scan-sheet-backdrop" hidden><section class="dr-scan-details" aria-labelledby="dr-scan-details-title"></section></div>';
      document.body.append(this.dialog);
      this.camera = this.find(".dr-scan-camera");
      this.video = this.find("video");
      this.review = this.find(".dr-scan-review");
      this.sheet = this.find(".dr-scan-sheet-backdrop");
      this.details = this.find(".dr-scan-details");
      this.find('[data-action="gallery"]').innerHTML = icons.photo;
      this.dialog.querySelectorAll("[data-action]").forEach(control => control.addEventListener("click", () => {
        const actions = {
          close: () => this.close(), settings: () => { this.find(".dr-scan-settings").hidden = !this.find(".dr-scan-settings").hidden; },
          resume: () => this.startCamera(), switch: () => { this.facing = this.facing === "environment" ? "user" : "environment"; this.startCamera(); },
          torch: () => this.toggleTorch(), certificate: () => this.manualSlab(),
          gallery: () => this.find(".dr-scan-file").click(), capture: () => this.capture(),
          next: () => this.showReview(), back: () => this.startCamera(), save: () => this.saveAll(),
        };
        actions[control.dataset.action]();
      }));
      this.dialog.querySelectorAll("[data-mode]").forEach(control => control.addEventListener("click", () => this.setMode(control.dataset.mode)));
      this.find(".dr-scan-settings input").addEventListener("change", event => { this.auto = event.target.checked; });
      this.find(".dr-scan-file").addEventListener("change", event => this.upload(event));
      this.dialog.addEventListener("cancel", event => {
        event.preventDefault();
        if (!this.sheet.hidden) this.closeDetails(); else this.close();
      });
      this.dialog.addEventListener("keydown", event => {
        if (event.key !== "Tab" || this.sheet.hidden) return;
        const controls = [...this.details.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')]
          .filter(control => !control.closest("[hidden]"));
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      });
    }

    find(selector) { return this.dialog.querySelector(selector); }
    status(text) { this.find(".dr-scan-status").textContent = text; }
    get processing() { return this.captureBusy || this.inFlight > 0 || this.recognitionQueue.length > 0; }
    atCapacity() { return this.captureBusy || this.recognitionQueue.length >= 50; }

    guideMessage() {
      return this.mode === "GRADED" ? "Show the full slab · keep the label and QR readable"
        : this.mode === "COMIC" ? "Frame the whole book cover · include the label if graded"
        : this.mode === "SEALED" ? "Frame the whole pack, box or sealed set" : "Place a card or book inside the guide";
    }

    setMode(mode) {
      if (!["RAW", "GRADED", "SEALED", ...(this.options.openBooks ? ["COMIC"] : [])].includes(mode) || this.processing || this.edit || this.saving) return;
      this.mode = mode; this.dialog.dataset.mode = mode;
      this.find(".dr-scan-topbar strong").textContent = mode === "COMIC" ? "Comics & Manga" : "Scan your collection";
      this.dialog.querySelectorAll("[data-mode]").forEach(control => control.setAttribute("aria-pressed", String(control.dataset.mode === mode)));
      this.find('[data-action="certificate"]').hidden = mode !== "GRADED";
      this.find('[data-action="capture"]').setAttribute("aria-label", "Scan " + (mode === "COMIC" ? "comic or manga" : mode === "GRADED" ? "graded slab" : mode === "SEALED" ? "sealed product" : "card or book"));
      this.find('[data-action="gallery"]').setAttribute("aria-label", "Choose an item photo");
      this.previous = null; this.stableFrames = 0; this.presenceFrames = 0;
      this.status(this.guideMessage());
    }

    async captureSlabQr() {
      if (this.qrBusy || this.atCapacity() || this.awaitingRemoval) return;
      if (this.inFlight) { this.capture(); return; }
      this.qrBusy = true;
      const revision = this.cameraRevision;
      let raw;
      try {
        if (!this.qrDetector && "BarcodeDetector" in globalThis) {
          const formats = await BarcodeDetector.getSupportedFormats();
          if (formats.includes("qr_code")) this.qrDetector = new BarcodeDetector({formats: ["qr_code"]});
        }
        if (this.qrDetector) raw = (await this.qrDetector.detect(this.video)).find(code => code.rawValue)?.rawValue;
      } catch (_) { /* Label capture remains available when QR is unsupported. */ }
      finally { this.qrBusy = false; }
      if (revision !== this.cameraRevision || !this.active() || this.mode !== "GRADED" || this.processing || this.edit) return;
      if (!raw || raw === this.lastQr) { this.capture(); return; }
      this.captureBusy = true; this.render();
      try {
        const parsed = await this.request("/api/v1/grading-certificates/qr/resolve", {method: "POST",
          body: JSON.stringify({qr_value: raw, grader_hint: /^https?:\/\//i.test(raw) ? null : "PSA"})});
        if (revision !== this.cameraRevision || this.mode !== "GRADED") return;
        this.lastQr = raw; this.awaitingRemoval = true;
        this.captureBusy = false;
        this.manualSlab(parsed);
        await this.lookupSlab();
      } catch (_) {
        if (this.active() && revision === this.cameraRevision) { this.captureBusy = false; this.capture(); }
      } finally { this.captureBusy = false; if (this.active()) this.render(); }
    }

    manualSlab(parsed = {}) {
      if (this.processing || this.saving) return;
      const item = {id: crypto.randomUUID(), mode: "GRADED", quantity: 1, photo: null,
        grading_company: parsed.provider || "PSA", certificate_number: parsed.certificate_number || "",
        grade: "", condition: "", selected: null, candidates: [], status: "unresolved", guess: "Choose the graded card"};
      this.items.push(item); this.openDetails(item); this.render();
    }

    applySlabEvidence(item, data) {
      const provider = data.provider_result || data, observation = data.observation || {};
      item.slab = data;
      const company = data.normalized_provider || provider.provider || observation.grader || item.grading_company;
      item.grading_company = graders.includes(company) ? company : "";
      item.certificate_number = data.normalized_certificate || provider.certificate_number || observation.certificate_number || item.certificate_number || "";
      const displayedGrade = Object.prototype.hasOwnProperty.call(data, "normalized_grade") ? data.normalized_grade
        : provider.display_grade ?? provider.grade ?? observation.grade ?? item.grade;
      item.grade = gradeOptions(item.grading_company).includes(displayedGrade) ? displayedGrade : "";
      item.guess = provider.subject || observation.card_name || "Choose the graded card";
      item.searchSeed = data.catalogue_search_seed || provider.card_number || observation.card_number || provider.subject || observation.card_name || "";
      item.label = data.catalogue_label || {card_name: provider.subject || observation.card_name || "",
        card_number: provider.card_number || observation.card_number || "", set_name: provider.set_brand || observation.set_name || "",
        language: provider.language_printing || observation.language || ""};
      item.error = data.conflicts?.length ? "Certificate and label disagree. Resolve this before adding the slab." : null;
    }

    async slabCandidates(item, signal) {
      item.candidates = []; item.suggested = null;
      if (!item.searchSeed || item.searchSeed.length < 2 || item.slab?.conflicts?.length) return;
      const label = item.label || {};
      if (!label.card_number || (!label.card_name && !label.set_name)) return;
      const params = new URLSearchParams({q: item.searchSeed.slice(0, 160), limit: "80", product_type: "CARD", owned: "all",
        slab_number: label.card_number.slice(0, 80), slab_name: (label.card_name || "").slice(0, 160),
        slab_set: (label.set_name || "").slice(0, 200)});
      if (["English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish"].includes(label.language)) params.set("language", label.language);
      const data = await this.request("/api/v1/catalogue-browser/products?" + params, {signal});
      item.candidates = (data.items || []).filter(row => row.product_type !== "SEALED")
        .map(row => this.searchCandidate(row));
      item.suggested = item.candidates[0] || null;
    }

    async recogniseSlab(photo, item, isNew) {
      const epoch = this.epoch;
      item.selected = null; item.suggested = null; item.candidates = []; item.slab = null;
      item.grading_company = ""; item.grade = ""; item.certificate_number = ""; item.label = null;
      item.status = "processing"; item.guess = "Reading slab label…"; item.error = null;
      if (isNew) this.items.push(item);
      this.inFlight += 1; this.status("Reading slab · you can capture the next item"); this.render();
      const controller = new AbortController(); this.controllers.add(controller);
      item.recognitionController = controller;
      const timeout = setTimeout(() => controller.abort(), 70000);
      try {
        const data = await this.request("/api/v1/grading-certificates/scan", {method: "POST", signal: controller.signal,
          body: JSON.stringify({image_data_url: photo})});
        if (!this.active(epoch) || !this.items.includes(item)) return;
        this.applySlabEvidence(item, data);
        item.guess = "Checking label against catalogue…"; this.render();
        await this.slabCandidates(item, controller.signal);
        if (!this.active(epoch) || !this.items.includes(item)) return;
        item.selected = null;
        item.guess = data.observation?.card_name || "Slab needs review";
        if (!item.suggested && !item.error) item.error = "No catalogue suggestion agrees with the label. Search for the exact printing; a shared number is not enough.";
        this.status("Slab read · tap its thumbnail to confirm the card and grade");
      } catch (error) {
        if (!this.active(epoch) || !this.items.includes(item)) return;
        item.error = error.name === "AbortError" ? "Slab reading timed out. Retry the photo or enter the certificate." : error.message;
        this.status("Check slab details · certificate entry is available");
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller);
        this.releaseRecognition(item, controller);
        if (this.active(epoch) && this.items.includes(item)) { item.status = "unresolved"; this.render(); }
      }
    }

    async lookupSlab() {
      const edit = this.edit; if (!edit || this.editBusy || !graded(edit)) return;
      this.editBusy = true;
      this.details.querySelectorAll("button,input,select").forEach(control => { control.disabled = true; });
      try {
        const data = await this.request("/api/v1/grading-certificates/lookup", {method: "POST",
          body: JSON.stringify({grader: edit.grading_company, certificate_number: edit.certificate_number})});
        // A manual lookup cannot erase a conflict observed in the original slab photo.
        const conflicts = edit.slab?.conflicts || edit.item.slab?.conflicts || [];
        const draft = {...edit.item, grading_company: edit.grading_company, certificate_number: edit.certificate_number, grade: edit.grade};
        this.applySlabEvidence(draft, {...data, conflicts,
          normalized_provider: data.provider, normalized_certificate: data.certificate_number,
          provider_error: data.warnings?.includes("PROVIDER_NOT_CONFIGURED") ? "PROVIDER_NOT_CONFIGURED" : null});
        await this.slabCandidates(draft);
        Object.assign(edit, {grading_company: draft.grading_company, certificate_number: draft.certificate_number,
          grade: draft.grade, slab: draft.slab, selected: edit.selected || draft.suggested});
        edit.item.candidates = draft.candidates;
        edit.lookupMessage = data.verified || data.provider_result?.verified
          ? "Certificate evidence found. Check the printing and label before confirming."
          : data.warnings?.includes("PROVIDER_NOT_CONFIGURED")
            ? "Automatic lookup is unavailable. Open the official record, then confirm the label manually."
            : "Confirm the label manually. Certificate verification is still required.";
      } catch (error) { if (this.active()) edit.lookupMessage = error.message + " You can read the label and confirm the card manually."; }
      finally { if (this.active()) { this.editBusy = false; this.renderDetails(); } }
    }

    async open(mode, {preferCamera = false, review = false} = {}) {
      if (mode) this.setMode(mode);
      if (!this.active()) throw new Error("Please sign in again before scanning.");
      // Repeated navigation cannot create a second dialog or camera stream.
      if (this.dialog.open) {
        if (review) this.showReview();
        else if (preferCamera && this.view !== "camera") await this.startCamera();
        return;
      }
      this.returnFocus = document.activeElement;
      this.dialog.showModal();
      document.body.classList.add("dr-scanner-open");
      if (review || (!preferCamera && this.items.some(item => item.requests))) this.showReview();
      else await this.startCamera();
    }

    close() {
      if (this.saving || this.editBusy) return;
      this.closeDetails();
      this.stopCamera();
      this.dialog.close();
      document.body.classList.remove("dr-scanner-open");
      this.returnFocus?.focus();
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.epoch += 1;
      this.searchRevision += 1;
      clearTimeout(this.searchTimer);
      this.controllers.forEach(controller => controller.abort());
      this.recognitionQueue.splice(0).forEach(job => job.resolve());
      this.bookResearchQueue = [];
      this.stopCamera();
      this.objectUrls.forEach(url => URL.revokeObjectURL(url));
      this.objectUrls.clear();
      this.images.clear();
      this.items = [];
      this.dialog.close();
      this.dialog.remove();
      document.body.classList.remove("dr-scanner-open");
      document.removeEventListener("visibilitychange", this.onVisibility);
      window.removeEventListener("pagehide", this.onPageHide);
    }

    stopCamera() {
      this.cameraRevision += 1;
      clearInterval(this.timer);
      this.stream?.getTracks().forEach(track => track.stop());
      this.stream = null;
      this.torchTrack = null; this.torchOn = false;
      this.find('[data-action="torch"]').hidden = true;
      this.video.srcObject = null;
      this.autoArmed = false;
      this.absenceFrames = 0; this.presenceFrames = 0; this.stableFrames = 0;
      this.previous = null; this.previousBox = null;
      this.find(".dr-scan-camera-resume").hidden = false;
      this.find('[data-action="capture"]').disabled = true;
    }

    async startCamera() {
      if (!this.active() || this.saving || this.editBusy) return;
      this.stopCamera();
      this.closeDetails();
      this.camera.hidden = false;
      this.review.hidden = true;
      this.camera.inert = false;
      this.view = "camera";
      this.render();
      const revision = this.cameraRevision;
      this.status("Opening camera…");
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera unavailable. Choose a photo below.");
        const stream = await navigator.mediaDevices.getUserMedia({audio: false, video: {
          facingMode: {ideal: this.facing}, width: {ideal: 1920}, height: {ideal: 1080},
        }});
        if (!this.active() || revision !== this.cameraRevision || !this.dialog.open) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
        this.stream = stream;
        this.video.srcObject = stream;
        await this.video.play();
        if (revision !== this.cameraRevision) return;
        this.torchTrack = stream.getVideoTracks?.()[0] || null;
        let supportsTorch = false;
        try { supportsTorch = Boolean(this.torchTrack?.getCapabilities?.().torch); } catch (_) { /* Optional hardware capability. */ }
        this.find('[data-action="torch"]').hidden = !supportsTorch;
        this.find('[data-action="torch"]').textContent = "Torch off";
        this.find(".dr-scan-camera-resume").hidden = true;
        this.find('[data-action="capture"]').disabled = this.atCapacity();
        this.previous = null;
        this.previousBox = null;
        this.autoArmed = false;
        this.stableFrames = 0;
        this.presenceFrames = 0;
        this.absenceFrames = 0;
        // Preserve the removal gate when returning from details/review.
        this.status(this.awaitingRemoval ? "Remove the scanned item before continuing" : this.guideMessage());
        this.timer = setInterval(() => this.tick(), 420);
      } catch (error) {
        if (revision !== this.cameraRevision || !this.active()) return;
        this.stopCamera();
        this.status(error.name === "NotAllowedError"
          ? "Allow camera access, or choose a photo below."
          : error.message || "Camera unavailable. Choose a photo below.");
      }
    }

    async toggleTorch() {
      if (!this.torchTrack?.applyConstraints) return;
      const revision = this.cameraRevision, control = this.find('[data-action="torch"]');
      control.disabled = true;
      try {
        const enabled = !this.torchOn;
        await this.torchTrack.applyConstraints({advanced: [{torch: enabled}]});
        if (revision !== this.cameraRevision) return;
        this.torchOn = enabled; control.textContent = enabled ? "Torch on" : "Torch off";
      } catch (_) { if (revision === this.cameraRevision) this.status("This camera could not change its torch setting."); }
      finally { control.disabled = false; }
    }

    crop() {
      // Capture exactly the visible guide, accounting for object-fit: cover.
      const viewport = this.video.getBoundingClientRect();
      const guide = this.find(".dr-scan-guide").getBoundingClientRect();
      const scale = Math.max(viewport.width / this.video.videoWidth, viewport.height / this.video.videoHeight);
      return {
        sx: (guide.left - viewport.left + (this.video.videoWidth * scale - viewport.width) / 2) / scale,
        sy: (guide.top - viewport.top + (this.video.videoHeight * scale - viewport.height) / 2) / scale,
        sw: guide.width / scale, sh: guide.height / scale,
      };
    }

    frame() {
      const crop = this.crop(), canvas = document.createElement("canvas");
      const width = 48, height = 68;
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d", {willReadFrequently: true});
      if (!context) return null;
      // Include a narrow margin outside the visible guide so an actual
      // card's FOUR outer edges can be distinguished from a textured surface.
      const xMargin = crop.sw * 0.11, yMargin = crop.sh * 0.11;
      const sx = Math.max(0, crop.sx - xMargin), sy = Math.max(0, crop.sy - yMargin);
      const sw = Math.min(this.video.videoWidth - sx, crop.sw + 2 * xMargin);
      const sh = Math.min(this.video.videoHeight - sy, crop.sh + 2 * yMargin);
      if (!(sw > 0 && sh > 0)) return null;
      context.drawImage(this.video, sx, sy, sw, sh, 0, 0, width, height);
      const pixels = context.getImageData(0, 0, width, height).data;
      const detected = analyzeCardPresence(pixels, width, height, this.mode);
      const fingerprint = new Uint8Array(width * height);
      for (let index = 0; index < fingerprint.length; index += 1) {
        const pixel = index * 4;
        fingerprint[index] = Math.round(
          pixels[pixel] * 0.299 + pixels[pixel + 1] * 0.587 + pixels[pixel + 2] * 0.114);
      }
      return {...detected, fingerprint};
    }

    tick() {
      if (this.edit || this.view !== "camera" || !this.stream || !this.video.videoWidth) return;
      const analysis = this.frame();
      if (!analysis) return;
      if (!analysis.present) {
        this.presenceFrames = 0; this.stableFrames = 0; this.absenceFrames += 1;
        this.previous = analysis.fingerprint;
        this.previousBox = null;
        if (this.absenceFrames >= 3) {
          this.autoArmed = true;
          this.awaitingRemoval = false;
        }
        this.status(this.awaitingRemoval ? "Remove the scanned item to continue" : this.guideMessage());
        return;
      }
      this.absenceFrames = 0;
      if (!this.auto) return; // Removal detection still re-arms deliberate manual captures.
      if (this.awaitingRemoval) {
        this.status("Photo captured · remove this item before scanning another copy");
        return;
      }
      if (!this.autoArmed) {
        // Most users show the card *after* opening the camera. If a card was
        // already there on the very first frame, permit an EXTRA-CONFIDENT,
        // long-stable rectangle to scan too; don't force a pointless
        // remove-and-represent gesture like a broken camera app.
        const strong = analysis.edgeConfidence >= 1.35 && Boolean(analysis.box);
        const previousBox = this.previousBox, box = analysis.box;
        const aligned = !previousBox || (
          Math.abs(previousBox.left - box.left) <= 2
          && Math.abs(previousBox.right - box.right) <= 2
          && Math.abs(previousBox.top - box.top) <= 2
          && Math.abs(previousBox.bottom - box.bottom) <= 2);
        const movement = fingerprintDelta(analysis.fingerprint, this.previous);
        this.previous = analysis.fingerprint; this.previousBox = box;
        this.presenceFrames = strong ? this.presenceFrames + 1 : 0;
        this.stableFrames = strong && movement <= 0.018 && aligned
          ? this.stableFrames + 1 : 0;
        if (this.presenceFrames < 5 || this.stableFrames < 4) {
          this.status(strong ? "Item detected · hold steady inside the guide"
            : "Clear the guide briefly, then place your item inside");
          return;
        }
        this.autoArmed = true;
        if (this.mode === "GRADED" && !this.qrBusy) this.captureSlabQr();
        else if (this.mode !== "GRADED") this.capture();
        return;
      }
      this.presenceFrames += 1;
      if (this.atCapacity()) { this.status("Your scan queue is full · review a few items before continuing"); return; }
      const movement = fingerprintDelta(analysis.fingerprint, this.previous);
      const previousBox = this.previousBox, box = analysis.box;
      const aligned = !previousBox || !box || (
        Math.abs(previousBox.left - box.left) <= 2
        && Math.abs(previousBox.right - box.right) <= 2
        && Math.abs(previousBox.top - box.top) <= 2
        && Math.abs(previousBox.bottom - box.bottom) <= 2);
      this.previous = analysis.fingerprint;
      this.previousBox = box;
      this.stableFrames = movement <= 0.022 && aligned ? this.stableFrames + 1 : 0;
      if (this.presenceFrames < 3 || this.stableFrames < 3) {
        this.status("Item detected · hold steady inside the guide");
        return;
      }
      if (this.mode === "GRADED" && !this.qrBusy) this.captureSlabQr();
      else if (this.mode !== "GRADED") this.capture();
    }

    capture() {
      if (this.atCapacity() || this.edit || !this.stream || !this.video.videoWidth) return;
      if (this.awaitingRemoval) { this.status("Photo captured · remove this item before scanning another copy"); return; }
      try {
        const crop = this.crop(), canvas = document.createElement("canvas");
        const scale = Math.min(1, 1500 / Math.max(crop.sw, crop.sh));
        canvas.width = Math.round(crop.sw * scale); canvas.height = Math.round(crop.sh * scale);
        const context = canvas.getContext("2d", {alpha: false});
        if (!context) throw new Error("Capture unavailable. Choose a photo below.");
        context.drawImage(this.video, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, canvas.width, canvas.height);
        this.awaitingRemoval = true; this.stableFrames = 0;
        this.recognise(canvas.toDataURL("image/jpeg", 0.88));
      } catch (error) { this.status(error.message); }
    }

    async upload(event, retryItem = null) {
      const file = event.target.files?.[0]; event.target.value = "";
      if (!file || this.atCapacity() || this.editBusy || (retryItem && !this.editable(retryItem))) return;
      const epoch = this.epoch;
      let url, prepared;
      this.captureBusy = true; this.render();
      try {
        if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size > 20 * 1024 * 1024) {
          throw new Error("Choose a JPEG, PNG or WebP photo under 20 MB.");
        }
        url = URL.createObjectURL(file);
        const image = new Image(); image.src = url; await image.decode();
        if (!this.active(epoch)) return;
        const scale = Math.min(1, 1500 / Math.max(image.width, image.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
        canvas.getContext("2d", {alpha: false}).drawImage(image, 0, 0, canvas.width, canvas.height);
        prepared = canvas.toDataURL("image/jpeg", 0.88);
      } catch (error) { if (this.active(epoch)) this.status(error.message); }
      finally {
        if (url) URL.revokeObjectURL(url);
        this.captureBusy = false;
        if (this.active(epoch)) this.render();
      }
      if (prepared && this.active(epoch)) {
        if (retryItem && (!this.items.includes(retryItem) || !this.editable(retryItem))) return;
        if (retryItem) { retryItem.photo = prepared; this.closeDetails(); }
        await this.recognise(prepared, retryItem);
      }
    }

    async recognise(photo, retryItem = null) {
      if (this.atCapacity() || !this.active() || ["processing", "queued"].includes(retryItem?.status) || retryItem?.requests || this.saving) return;
      const item = retryItem || {id: crypto.randomUUID(), photo, mode: this.mode, quantity: 1, condition: "", selected: null};
      if (!retryItem) this.items.push(item);
      item.photo = photo; item.status = "queued"; item.error = null; item.guess = "Queued · waiting to read";
      item.researchController?.abort();
      this.bookResearchQueue = this.bookResearchQueue.filter(job => job.item !== item);
      item.run = null; item.bookResult = null; item.selected = null; item.suggested = null; item.candidates = [];
      return new Promise(resolve => {
        this.recognitionQueue.push({item, photo, resolve, epoch:this.epoch});
        this.drainRecognition(); this.render();
        if (item.status === "queued") this.status("Photo queued · keep scanning while we identify your items");
      });
    }

    drainRecognition() {
      if (!this.active()) return;
      while (this.inFlight < 2 && this.recognitionQueue.length) {
        const job = this.recognitionQueue.shift();
        if (!this.active(job.epoch) || !this.items.includes(job.item)) { job.resolve(); continue; }
        this.runRecognition(job.photo, job.item).finally(() => { job.resolve(); this.drainRecognition(); });
      }
    }

    async runRecognition(photo, item) {
      const epoch = this.epoch;
      if (book(item)) { await this.recogniseBook(photo, item, false); return; }
      if (graded(item)) { await this.recogniseSlab(photo, item, false); return; }
      item.run = null; item.selected = null; item.suggested = null; item.candidates = [];
      item.status = "processing"; item.error = null; item.guess = "Photo captured · identifying…";
      this.inFlight += 1;
      this.status("Identifying your items · keep scanning"); this.render();
      const controller = new AbortController(); this.controllers.add(controller);
      item.recognitionController = controller;
      const timeout = setTimeout(() => controller.abort(), 70000);
      try {
        const data = await this.request("/api/v1/recognition/resolve", {method: "POST", signal: controller.signal,
          body: JSON.stringify({image_data_url: photo, force_refresh: true})});
        if (!this.active(epoch) || !this.items.includes(item)) return;
        item.run = data.run || {};
        if (data.book_result) {
          item.mode = "COMIC";
          this.acceptBookResult(item, data.book_result, photo, epoch);
          return;
        }
        item.candidates = (data.candidates || []).filter(candidate => !candidate.hard_rejected
          && (candidate.catalogue_id || candidate.source_kind === "PROVIDER"))
          .sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999));
        item.candidates = item.candidates.filter(candidate => item.mode === "SEALED"
          ? sealed({selected: candidate}) : !sealed({selected: candidate}));
        const top = item.candidates[0] || null;
        item.suggested = top;
        item.selected = item.run.decision === "EXACT_CANDIDATE" && top?.catalogue_id === item.run.top_catalogue_id
          && top?.catalogue_id ? top : null;
        item.status = item.selected ? "matched" : "unresolved";
        item.guess = item.run.ai_observation?.name_guess || "No match found";
        if (!top && data.candidates?.length) item.error = "This item does not match " + item.mode + ". Choose the correct scan type and scan it again.";
        if (!usableRun(item)) item.error = "Recognition could not complete. Retry this photo before choosing a match.";
        this.status(item.selected ? "Match found · tap its thumbnail to check details" : "Check the match · tap its thumbnail");
      } catch (error) {
        if (!this.active(epoch) || !this.items.includes(item)) return;
        item.status = "unresolved"; item.guess = "Recognition failed";
        item.error = error.name === "AbortError" ? "Recognition timed out. Retry this photo." : error.message;
        this.status("Couldn’t recognise this item · tap its thumbnail to retry");
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller);
        this.releaseRecognition(item, controller);
        if (this.active(epoch)) this.render();
      }
    }

    async recogniseBook(photo, item, addItem) {
      const epoch = this.epoch;
      item.bookResult = null; item.status = "processing"; item.error = null;
      item.guess = "Photo captured · identifying book…";
      if (addItem) this.items.push(item);
      this.inFlight += 1; this.status("Reading the book cover · you can capture the next book"); this.render();
      const controller = new AbortController(); this.controllers.add(controller);
      item.recognitionController = controller;
      const timeout = setTimeout(() => controller.abort(), 100000);
      try {
        const result = await this.request("/api/v1/owner/books/recognize", {method: "POST", signal: controller.signal,
          body: JSON.stringify({images: [photo], defer_research: true})});
        if (!this.active(epoch) || !this.items.includes(item)) return;
        this.acceptBookResult(item, result, photo, epoch);
      } catch (error) {
        if (!this.active(epoch) || !this.items.includes(item)) return;
        item.status = "unresolved"; item.guess = "Book scan needs another look";
        item.error = error.name === "AbortError" ? "Book recognition timed out. Retry the photo in review." : error.message;
        this.status("Couldn’t read this book · tap its thumbnail to retry");
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller); this.releaseRecognition(item, controller);
        if (this.active(epoch)) this.render();
      }
    }

    acceptBookResult(item, result, photo, epoch) {
      item.bookResult = result; item.status = "unresolved"; item.error = null;
      item.selected = null; item.suggested = null; item.candidates = [];
      const fields = result.fields || {};
      item.guess = result.status === "NEEDS_REVIEW" ? [fields.series_title || "Book details read",
        fields.issue_number ? (fields.system_code === "MANGA" ? "Vol. " : "#") + fields.issue_number : ""].filter(Boolean).join(" ") : "Book not recognised";
      if (result.status !== "NEEDS_REVIEW") item.error = (result.warnings || []).join(" ") || "Try a clearer cover or barcode photo.";
      this.status(result.status === "NEEDS_REVIEW" ? "Book recognised · review the cover and add your copy"
        : "Couldn’t read this book · tap its thumbnail to retry");
      if (researching(result)) {
        this.bookResearchQueue.push({item, result, photo, epoch}); this.drainBookResearch();
      }
    }

    drainBookResearch() {
      while (this.active() && this.researchInFlight < 2 && this.bookResearchQueue.length) {
        const job = this.bookResearchQueue.shift();
        if (!this.items.includes(job.item) || job.item.bookResult !== job.result || job.item.status === "added") continue;
        this.finishBookResearch(job);
      }
    }

    async finishBookResearch({item, result, photo, epoch}) {
      const controller = new AbortController(); this.controllers.add(controller);
      item.researchController = controller; this.researchInFlight++;
      const timeout = setTimeout(() => controller.abort(), 75000);
      const active = () => this.active(epoch) && this.items.includes(item) && item.bookResult === result
        && item.status !== "added" && !item.bookSavePending;
      try {
        const completed = await researchBook(this.request.bind(this), result, [photo], controller.signal);
        if (!active()) return;
        item.bookResult = completed;
        const fields = completed.fields || {};
        item.guess = [fields.series_title || "Book details read", fields.issue_number ?
          (fields.system_code === "MANGA" ? "Vol. " : "#") + fields.issue_number : ""].filter(Boolean).join(" ");
        window.DropRateBooks?.updateScan?.(item.id, completed);
      } catch (_) {
        if (!active()) return;
        item.bookResult = {...result, research:{status:"UNAVAILABLE", candidates:[],
          message:"Publisher cover lookup did not finish. Your book details are ready to review."}};
        window.DropRateBooks?.updateScan?.(item.id, item.bookResult);
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller);
        if (item.researchController === controller) item.researchController = null;
        this.researchInFlight = Math.max(0, this.researchInFlight - 1);
        this.drainBookResearch(); if (this.active(epoch)) this.render();
      }
    }

    async artwork(image, item, candidate = selected(item)) {
      if (!this.active()) { image.hidden = true; return; }
      const card = snapshot(candidate);
      const path = candidate?.reference_image_path || card.reference_image_path;
      const direct = candidate?.image_url || card.display_image_url || card.image_url;
      const runPath = item.run?.id && candidate?.id
        ? "/api/v1/recognition/runs/" + encodeURIComponent(item.run.id) + "/candidates/" + encodeURIComponent(candidate.id) + "/image" : null;
      const local = path?.startsWith("/api/v1/catalogue-browser/reference-image?") || (book(item) && path === bookCover(item)) ? path : runPath;
      const placeholder = image.parentElement?.querySelector(".dr-scan-image-placeholder");
      const missing = text => { image.hidden = true; if (placeholder) placeholder.textContent = text; };
      if (!local) {
        if (direct && /^https:\/\//i.test(direct)) {
          image.addEventListener("error", () => missing("Image could not load"), {once: true});
          image.src = direct;
        } else missing("Reference image unavailable");
        return;
      }
      // Approved direct/CDN images keep their fast path. Only use the
      // authenticated run image on failure; provider reference paths use our
      // existing proxy first to avoid hotlink-denial and external credentials.
      if (direct && !path && /^https:\/\//i.test(direct)) {
        image.addEventListener("error", () => {
          const retry = {...candidate, image_url: null, candidate_snapshot: {...card, image_url: null, display_image_url: null}};
          this.artwork(image, item, retry);
        }, {once: true});
        image.src = direct; return;
      }
      const key = local, epoch = this.epoch;
      if (!this.images.has(key)) {
        const controller = new AbortController(); this.controllers.add(controller);
        const timeout = setTimeout(() => controller.abort(), 12000);
        this.images.set(key, (async () => {
          try {
            let blob;
            if (path === local) blob = await this.requestImage(local, {signal: controller.signal});
            else {
              await this.ensureSession(epoch);
              if (!this.active(epoch)) return null;
              const response = await fetch(local, {headers: {Authorization: "Bearer " + this.options.session()?.access_token},
                cache: "no-store", signal: controller.signal});
              if (!response.ok || !/^image\/(jpeg|png|webp)$/i.test(response.headers.get("content-type")?.split(";")[0] || "")) return null;
              blob = await response.blob();
              if (blob.size > 8 * 1024 * 1024) return null;
            }
            if (!blob || !this.active(epoch)) return null;
            const url = URL.createObjectURL(blob); this.objectUrls.add(url); return url;
          } catch (_) { return null; }
          finally { clearTimeout(timeout); this.controllers.delete(controller); }
        })());
      }
      const url = await this.images.get(key);
      if (!this.active(epoch)) return;
      if (url) { image.hidden = false; image.src = url; }
      else { this.images.delete(key); missing("Image could not load · reopen to retry"); }
    }

    thumb(item, className = "dr-scan-thumb", candidate = selected(item), captured = false) {
      const cover = book(item) && bookCover(item);
      if (cover) candidate = {reference_image_path: cover};
      captured = captured || (book(item) && !cover);
      const wrap = node("div", className);
      const image = node("img"); image.alt = captured ? "Your scanned photo" : name({...item, selected: candidate});
      image.addEventListener("error", () => { image.hidden = true; });
      wrap.append(node("span", "dr-scan-image-placeholder", captured ? "Photo cleared" : "Loading reference image…"), image);
      if (captured || item.status === "processing") { if (item.photo) image.src = item.photo; else image.hidden = true; }
      else this.artwork(image, item, candidate);
      return wrap;
    }

    totals() {
      let value = 0, unknown = 0, copies = 0;
      for (const item of this.items) {
        copies += item.quantity;
        if (!item.selected || valueOf(item) == null) unknown += item.quantity;
        else value += Number(valueOf(item)) * item.quantity;
      }
      return {value: unknown === copies && copies > 0 ? null : value, unknown, copies};
    }

    editable(item) { return !this.saving && !this.editBusy && !item.requests && !["processing", "queued"].includes(item.status) && !(book(item) && item.status === "added"); }
    removable(item) { return !this.saving && !this.editBusy && !item.bookSavePending
      && (!item.requests || item.status === "added") && this.items.includes(item); }
    releaseRecognition(item, controller) {
      if (item.recognitionController === controller) {
        item.recognitionController = null; this.inFlight = Math.max(0, this.inFlight - 1);
        queueMicrotask(() => this.drainRecognition());
      }
    }
    removeControl(item, className = "dr-scan-text-button") {
      const control = button(item.status === "added" ? "Dismiss scan" : "Remove scan", () => this.remove(item), className);
      control.disabled = !this.removable(item);
      control.setAttribute("aria-label", (item.status === "added" ? "Dismiss saved scan: " : "Remove scan: ") + name(item));
      control.title = item.bookSavePending || (item.requests && item.status !== "added")
        ? "Check the pending save before removing this scan" : item.status === "added" ? "Remove from this queue; your collection copy stays saved" : "Remove from scan queue";
      return control;
    }
    ready(item) { return !book(item) && Boolean(item.requests || (item.selected?.catalogue_id && item.status === "matched"
      && (graded(item) ? gradeValid(item) && item.quantity === 1 : usableRun(item) && (!item.condition || conditions.includes(item.condition))))); }

    render() {
      const totals = this.totals();
      const strip = this.find(".dr-scan-strip"); strip.replaceChildren();
      if (!this.items.length) strip.append(node("p", "dr-scan-strip-empty", "Your scans will appear here"));
      for (const item of [...this.items].reverse()) {
        const tile = button("", () => this.openDetails(item), "dr-scan-tile " + item.status);
        tile.disabled = !this.editable(item);
        tile.setAttribute("aria-label", (item.status === "queued" ? "Photo queued" : item.status === "processing" ? "Recognising item" : "Review " + name(item)));
        tile.append(this.thumb(item));
        const copy = node("span", "dr-scan-tile-copy");
        copy.append(node("strong", "", item.status === "processing" ? item.guess : name(item)));
        const card = snapshot(selected(item));
        if (!["processing", "queued"].includes(item.status)) copy.append(node("span", "", card.card_number || card.product_code || ""),
          node("span", "", book(item) ? (item.status === "added" ? "Added to collection" : researching(item.bookResult) ? "Finding publisher cover…" : item.bookResult?.research?.selected_candidate_id ? "Ready to add" : "Review book") : item.status === "unresolved" ? "Check match" : money(valueOf(item))));
        tile.append(copy);
        const queued = node("div", "dr-scan-queued"), remove = this.removeControl(item, "dr-scan-remove-queued");
        remove.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/></svg>';
        queued.append(tile, remove); strip.append(queued);
      }
      this.find(".dr-scan-total").textContent = this.mode === "COMIC"
        ? this.items.length + (this.items.length === 1 ? " scan" : " scans")
          + (this.inFlight ? " · " + this.inFlight + " reading" : "")
          + (this.recognitionQueue.length ? " · " + this.recognitionQueue.length + " queued" : "")
          + (this.researchInFlight ? " · finding covers" : "")
        : "Total: " + money(totals.value) + (totals.unknown ? " · " + totals.unknown + " pending" : "");
      this.find('[data-action="next"]').disabled = !this.items.length;
      this.find('[data-action="capture"]').disabled = this.atCapacity() || !this.stream;
      this.find('[data-action="gallery"]').disabled = this.atCapacity();
      this.dialog.querySelectorAll('[data-mode]').forEach(control => { control.disabled = this.processing || this.saving; });
      this.find('[data-action="certificate"]').disabled = this.processing || this.saving;
      if (this.view === "review") this.renderReview();
    }

    showReview() {
      if (this.editBusy || this.saving) return;
      this.closeDetails(); this.stopCamera();
      this.view = "review"; this.camera.hidden = true; this.review.hidden = false;
      this.review.inert = false;
      this.renderReview();
      this.find('[data-action="back"]').focus();
    }

    renderReview() {
      const list = this.find(".dr-scan-review-list"); list.replaceChildren();
      for (const item of [...this.items].reverse()) {
        const row = node("article", "dr-scan-review-item " + item.status);
        row.append(node("h3", "", item.status === "queued" ? "Photo queued" : item.status === "processing" ? "Recognising…" : name(item)), node("p", "dr-scan-card-meta", meta(item)));
        const body = node("div", "dr-scan-review-body"); body.append(this.thumb(item, "dr-scan-review-thumb"));
        const copy = node("div", "dr-scan-review-copy");
        copy.append(node("strong", "dr-scan-card-value", valueOf(item) == null ? "Market value unavailable" : money(valueOf(item))));
        const fields = node("dl");
        const card = snapshot(selected(item));
        const bookFields = item.bookResult?.fields || {};
        const details = book(item) ? [["Type", bookFields.system_code === "MANGA" ? "Manga" : "Comic / book"],
          ["Printing", bookFields.printing_number || "Check your copy"],
          ["Copy details", item.status === "added" ? "Confirmed in book review" : "Review edition, condition and any grading label"], ["Quantity", 1]] : [["Variant", card.variant || card.art_treatment || card.sealed_product_type || "—"],
          ["Type", graded(item) ? item.grading_company + " " + item.grade : sealed(item) ? "Sealed product" : "Ungraded card"],
          [graded(item) ? "Certificate" : "Condition", graded(item) ? item.certificate_number : sealed(item) ? "Sealed" : item.condition || "Not recorded — needed when selling"], ["Quantity", item.quantity]];
        for (const [label, value] of details) {
          fields.append(node("dt", "", label), node("dd", "", value));
        }
        copy.append(fields);
        const edit = button(book(item) ? "Review book details" : item.status === "unresolved" ? "Confirm match" : "Add to collection", () => this.openDetails(item));
        edit.disabled = !this.editable(item); copy.append(edit);
        copy.append(this.removeControl(item));
        if (item.status === "added") copy.append(node("span", "dr-scan-added", "Added to collection"));
        if (item.error) copy.append(node("p", "dr-scan-item-error", item.error));
        body.append(copy); row.append(body); list.append(row);
      }
      const totals = this.totals();
      this.find(".dr-scan-review-total").textContent = totals.unknown === this.items.length ? "Market value unavailable" : (totals.unknown ? "Known value: " : "Total value: ") + money(totals.value);
      const unresolved = this.items.filter(item => !item.selected && item.status !== "added"
        && !(book(item) && item.bookResult?.status === "NEEDS_REVIEW"
          && item.bookResult.fields?.series_title && item.bookResult.fields?.issue_number)).length;
      const missingCondition = this.items.filter(item => item.selected && !graded(item) && !sealed(item) && !item.condition).length;
      const matched = this.items.length - unresolved;
      this.find(".dr-scan-review-count").textContent = matched + " identified " + (matched === 1 ? "scan" : "scans") +
        (unresolved ? " · " + unresolved + " to review" : "") + (missingCondition ? " · condition can be added later" : "") +
        (totals.unknown ? " · " + totals.unknown + " without a market value" : "") + ".";
      const done = this.items.length && this.items.every(item => item.status === "added");
      const retry = this.items.some(item => item.requests && item.status !== "added");
      const save = this.find('[data-action="save"]');
      const reviewBook = this.items.find(item => book(item) && this.editable(item));
      const ready = this.items.some(item => item.status !== "added" && this.ready(item));
      save.textContent = this.saving ? "Adding…" : done ? "View collection" : retry ? "Retry remaining saves" : !ready && reviewBook ? "Review book details" : "Add to collection";
      save.disabled = this.saving || !this.items.length || (!done && !ready && !reviewBook);
      this.find('[data-action="back"]').disabled = this.saving;
      this.review.querySelector('[data-action="close"]').disabled = this.saving;
    }

    openDetails(item) {
      if (!this.editable(item)) return;
      if (book(item)) { this.openBookDetails(item); return; }
      this.edit = {item, mode: item.mode, selected: item.selected || item.suggested, condition: item.condition,
        quantity: item.quantity, searchSelected: item.searchSelected || false,
        grading_company: item.grading_company ?? "PSA", grade: item.grade || "", certificate_number: item.certificate_number || "",
        slab: item.slab};
      this.sheet.hidden = false; this.camera.inert = true; this.review.inert = true;
      this.renderDetails();
    }

    openBookDetails(item) {
      if (!this.active() || !this.options.openBooks || !this.items.includes(item)) return;
      const epoch = this.epoch;
      this.close();
      const resume = () => { if (this.active(epoch)) this.open(null, {review: true}); };
      const opened = this.options.openBooks({scanItemId: item.id, photos: item.photo ? [item.photo] : [],
        recognition: item.bookResult || {status: "NO_MATCH", warnings: [item.error || "Read the photo again or enter the book details."]},
        onSaved: (result, copy, recognition) => {
          if (!this.active(epoch) || !this.items.includes(item)) return;
          item.status = "added"; item.error = null; item.photo = null; item.guess = result.catalogue.name;
          const receipt = recognition || item.bookResult;
          if (copy?.new_catalogue) item.bookResult = {...receipt, fields: {...copy.new_catalogue.comic_printing, language: copy.language},
            research: {...receipt?.research, selected_candidate_id: copy.research_candidate_id || null}};
          this.render();
        }, onSaveState: pending => { if (this.active(epoch) && this.items.includes(item)) item.bookSavePending = pending; },
        onRemove: () => { if (this.active(epoch)) this.remove(item); }, onClose: resume});
      if (opened === false) resume();
    }

    closeDetails() {
      if (this.editBusy) return;
      this.edit = null; this.searchRevision += 1; clearTimeout(this.searchTimer);
      this.searchController?.abort();
      this.sheet.hidden = true; this.camera.inert = false; this.review.inert = false;
      this.previous = null; this.stableFrames = 0;
      (this.view === "review" ? this.find('[data-action="back"]') : this.find('[data-action="next"]')).focus();
    }

    chooseGrader(company) {
      const edit = this.edit;
      if (!edit || this.editBusy || sealed({selected: edit.selected}) || edit.item.mode === "SEALED") return;
      if (!company) {
        if (!usableRun(edit.item)) return;
        edit.mode = "RAW"; edit.quantity = edit.rawQuantity || edit.item.quantity;
      } else {
        if (!graders.includes(company)) return;
        if (!graded(edit)) edit.rawQuantity = edit.quantity;
        if (company !== edit.grading_company) { edit.grade = ""; edit.certificate_number = ""; edit.lookupMessage = ""; }
        edit.mode = "GRADED"; edit.grading_company = company; edit.quantity = 1;
      }
      this.renderDetails();
      this.details.querySelector('[data-grader][aria-pressed="true"]')?.focus();
    }

    graderChoices() {
      const edit = this.edit, list = node("nav", "dr-scan-graders");
      list.setAttribute("aria-label", "Grading system");
      for (const company of ["", ...graders]) {
        const choice = button(company === "BGS" ? "Beckett" : company || "Ungraded", () => this.chooseGrader(company));
        choice.dataset.grader = company;
        choice.setAttribute("aria-pressed", String(company ? graded(edit) && edit.grading_company === company : !graded(edit)));
        choice.disabled = !company && !usableRun(edit.item);
        if (choice.disabled) choice.title = "Choose Auto to scan an ungraded card";
        list.append(choice);
      }
      return list;
    }

    renderDetails() {
      const edit = this.edit; if (!edit) return;
      edit.detailScroll = this.details.querySelector('.dr-scan-details-content')?.scrollTop ?? edit.detailScroll ?? 0;
      this.details.classList.remove("is-search");
      const item = edit.item;
      this.details.replaceChildren();
      this.details.append(node("div", "dr-scan-drag-handle"));
      const heading = node("header", "dr-scan-details-header");
      const title = node("h2", "", "Scan Details"); title.id = "dr-scan-details-title";
      const close = button("×", () => this.closeDetails()); close.setAttribute("aria-label", "Close scan details");
      heading.append(title, close); this.details.append(heading);
      const content = node("div", "dr-scan-details-content");
      const pair = node("div", "dr-scan-photo-pair");
      for (const [label, captured] of [["Your Picture", true], [item.status === "matched" ? "Selected match" : "Suggested match", false]]) {
        const figure = node("figure"); figure.append(this.thumb(item, "dr-scan-detail-thumb", edit.selected, captured), node("figcaption", "", label)); pair.append(figure);
      }
      content.append(pair, node("p", "dr-scan-results-label", "Suggested matches · check the artwork"));
      const matches = node("div", "dr-scan-alternatives");
      const search = button("⌕", () => this.openSearch(), "dr-scan-search-tile");
      search.setAttribute("aria-label", "Search manually for the correct card");
      search.append(node("small", "", "Not quite right? Search manually.")); matches.append(search);
      const allCandidates = item.candidates || [];
      const bestScore = Number(allCandidates[0]?.score || 0);
      const shortlist = allCandidates.filter(candidate => candidate === edit.selected || Number(candidate.score || 0) >= bestScore - 0.10).slice(0, 5);
      for (const candidate of edit.showAllCandidates ? allCandidates : shortlist) {
        const choice = button("", () => {
          edit.selected = candidate; edit.searchSelected = false; this.renderDetails();
        }, "dr-scan-alternative");
        choice.setAttribute("aria-label", name({selected: candidate}) + " · " + meta({selected: candidate}));
        choice.setAttribute("aria-pressed", String(edit.selected === candidate));
        choice.append(this.thumb(item, "dr-scan-alternative-thumb", candidate),
          node("small", "dr-scan-candidate-meta", meta({selected: candidate}))); matches.append(choice);
      }
      content.append(matches);
      if (allCandidates.length > shortlist.length) content.append(button(edit.showAllCandidates ? "Show closest matches" : "Show other suggestions", () => {
        edit.showAllCandidates = !edit.showAllCandidates; this.renderDetails();
      }));
      if (item.photo && this.editable(item)) {
        const replacement = node("input"); replacement.type = "file"; replacement.hidden = true;
        replacement.accept = "image/jpeg,image/png,image/webp"; replacement.setAttribute("capture", "environment");
        replacement.addEventListener("change", event => this.upload(event, item));
        const retake = button("Replace photo of this item", () => replacement.click());
        retake.disabled = this.atCapacity(); content.append(retake, replacement);
      }
      const isGraded = graded(edit);
      const candidateItem = {...item, ...edit, selected: edit.selected, savedGradedValue: null};
      const marketValue = valueOf(candidateItem);
      const info = node("div", "dr-scan-detail-identity");
      info.append(node("h3", "", name(candidateItem)), node("strong", "", marketValue == null ? "Market value unavailable" : money(marketValue)),
        node("p", "", meta(candidateItem)));
      content.append(info);
      if (marketValue == null) content.append(node("p", "dr-scan-review-note", isGraded
        ? "No verified value is available here for this grader and grade. You can still add the slab."
        : "A market value isn’t available yet. You can still add this item."));
      else if (edit.selected.recommended_retail_minor != null) content.append(node("p", "dr-scan-review-note",
        "Suggested retail: " + money(edit.selected.recommended_retail_minor) + " · reference value, not a live quote"));
      if (item.error) content.append(node("p", "dr-scan-item-error", item.error));
      if (!usableRun(item) && !isGraded) {
        const retry = button("Retry this photo", () => { this.closeDetails(); this.recognise(item.photo, item); });
        retry.disabled = this.atCapacity(); content.append(retry);
      }
      const isSealed = sealed(candidateItem);
      content.append(isSealed ? node("span", "dr-scan-type-chip", "Sealed product") : this.graderChoices());
      const optional = node("details", "dr-scan-optional");optional.open = isGraded;
      optional.append(node("summary", "", isGraded ? "Grading details" : "Quantity & condition (optional)"));
      const fields = node("div", "dr-scan-detail-fields");
      const conditionLabel = node("label", "", isGraded ? "Grade" : "Condition (optional)");
      const condition = node("select"); condition.setAttribute("aria-label", isGraded ? "Grade" : "Condition");
      (isSealed ? ["Sealed"] : isGraded ? ["Choose grade", ...gradeOptions(edit.grading_company)] : ["Not recorded", ...conditions]).forEach((value, index) => {
        const label = isGraded && value === "10" ? (edit.grading_company === "BGS" ? "Pristine · 10" : "10") : value;
        const option = node("option", "", label); option.value = !isSealed && index === 0 ? "" : value; condition.append(option);
      });
      condition.value = isSealed ? "Sealed" : isGraded ? edit.grade : edit.condition;
      condition.disabled = isSealed;
      condition.addEventListener("change", () => { edit[isGraded ? "grade" : "condition"] = condition.value; this.updateDetailsSave(); });
      conditionLabel.append(condition);
      const variant = node("label", "", "Variant");
      variant.append(node("span", "dr-scan-readonly-field", snapshot(edit.selected).variant || snapshot(edit.selected).art_treatment || snapshot(edit.selected).sealed_product_type || "—"));
      const quantityLabel = node("label", "", "Quantity");
      const quantity = node("input"); quantity.type = "number"; quantity.min = "1"; quantity.max = "50"; quantity.step = "1";
      quantity.value = edit.quantity; quantity.inputMode = "numeric"; quantity.setAttribute("aria-label", "Quantity");
      quantity.disabled = isGraded;
      quantity.addEventListener("input", () => { edit.quantity = Number(quantity.value); this.updateDetailsSave(); });
      quantityLabel.append(quantity); fields.append(conditionLabel, variant, quantityLabel); optional.append(fields); content.append(optional);
      if (isGraded) {
        const certificateLabel = node("label", "", "Certificate number"), certificate = node("input");
        certificate.value = edit.certificate_number; certificate.maxLength = edit.grading_company === "TAG" ? 8 : 14;
        certificate.inputMode = edit.grading_company === "TAG" ? "text" : "numeric";
        certificate.autocomplete = "off"; certificate.setAttribute("aria-label", "Certificate number");
        certificate.addEventListener("input", () => { edit.certificate_number = certificate.value.trim().toUpperCase(); this.updateDetailsSave(); });
        certificateLabel.append(certificate); fields.append(certificateLabel);
        const unconfigured = (edit.slab || item.slab)?.provider_error === "PROVIDER_NOT_CONFIGURED"
          && edit.grading_company === (edit.slab || item.slab)?.normalized_provider;
        if (!unconfigured) content.append(button("Lookup certificate", () => this.lookupSlab()));
        else content.append(node("p", "dr-scan-review-note", "Automatic certificate lookup is not configured. Check the official record and confirm the label manually."));
        const verification = (edit.slab || item.slab)?.verification_url;
        // Only server-generated supported official URLs; never a scanned arbitrary link.
        if (verification && /^https:\/\/(?:www\.)?(?:psacard\.com|acegrading\.com|cgccards\.com|taggrading\.com)\//.test(verification)
            && edit.grading_company === (edit.slab || item.slab)?.normalized_provider
            && edit.certificate_number === (edit.slab || item.slab)?.normalized_certificate) {
          const link = node("a", "dr-scan-text-button", "Open official certificate record");
          link.href = verification; link.target = "_blank"; link.rel = "noopener noreferrer"; content.append(link);
        }
        content.append(node("p", "dr-scan-review-note", edit.lookupMessage || "Confirm every certificate digit against the slab. A read label is not a verified certificate. One certificate adds one slab; Drop Rate review still applies."));
        if (item.photo && item.mode === "GRADED") content.append(button("Read slab photo again", () => { this.closeDetails(); this.recognise(item.photo, item); }));
      }
      if (edit.selected && !edit.selected.catalogue_id) content.append(node("p", "dr-scan-review-note",
        isSealed ? "This sealed product needs Drop Rate identity review before inventory." : "Check that the artwork, edition and language match your card."));
      content.append(node("p", "dr-scan-detail-message"));
      this.details.append(content);
      const footer = node("footer", "dr-scan-details-footer");
      const remove = button("⌫", () => this.remove(item), "dr-scan-delete"); remove.setAttribute("aria-label", "Remove this scan");
      remove.innerHTML = icons.trash;
      content.append(node("p", "dr-scan-review-note", "Add confirms this is your item. You can set up selling later."));
      const save = button("Add to collection", () => this.confirmDetails(), "dr-scan-primary"); save.dataset.detailsSave = "true";
      footer.append(remove, save); this.details.append(footer); this.updateDetailsSave();
      content.scrollTop = edit.detailScroll;
      close.focus();
    }

    updateDetailsSave() {
      const edit = this.edit; if (!edit) return;
      if (graded(edit)) {
        const canLink = edit.selected?.catalogue_id || edit.selected?.browser_key
          || (usableRun(edit.item) && edit.selected?.reference_selection);
        this.details.querySelector('[data-details-save]').disabled = this.editBusy || !canLink
          || !gradeValid({...edit.item, ...edit}) || edit.quantity !== 1;
        this.details.querySelector('.dr-scan-detail-message').textContent = (edit.slab || edit.item.slab)?.conflicts?.length
          ? "The certificate and label disagree. Resolve this before adding the slab."
          : !graders.includes(edit.grading_company) ? "Choose the grading company printed on the slab."
          : !canLink ? "Choose the exact card or search for its printing."
          : !gradeOptions(edit.grading_company).includes(edit.grade) ? "Choose the grade printed on the slab."
          : !certificateValid(edit) ? "Enter a valid certificate number for " + edit.grading_company + "." : "";
        return;
      }
      const isSealed = sealed({...edit.item, selected: edit.selected});
      const allowedSealed = !isSealed || (edit.item.run?.decision === "EXACT_CANDIDATE"
        && edit.selected?.catalogue_id === edit.item.run?.top_catalogue_id);
      const valid = usableRun(edit.item) && edit.selected && allowedSealed
        && Number.isInteger(edit.quantity) && edit.quantity >= 1 && edit.quantity <= 50;
      const missingCondition = !isSealed && !conditions.includes(edit.condition);
      const save = this.details.querySelector("[data-details-save]");
      save.disabled = this.editBusy || !valid;
      save.textContent = "Add to collection";
      this.details.querySelector(".dr-scan-detail-message").textContent = !usableRun(edit.item)
        ? "Retry this photo before confirming a match." : !allowedSealed ? "This sealed product needs identity review."
        : !edit.selected ? "Choose a match or search for the correct card."
        : !valid ? "Quantity must be a whole number from 1 to 50."
        : missingCondition ? "Condition is optional for your collection. Confirm it when listing for sale." : "";
    }

    async confirmDetails() {
      const edit = this.edit; if (!edit || this.editBusy || this.details.querySelector("[data-details-save]").disabled) return;
      this.editBusy = true;
      this.details.querySelectorAll("button, input, select").forEach(control => { control.disabled = true; });
      try {
        if (!edit.selected.catalogue_id && graded(edit) && !usableRun(edit.item) && edit.selected.browser_key) {
          const data = await this.request("/api/v1/catalogue-browser/select", {method: "POST",
            body: JSON.stringify({key: edit.selected.browser_key, confirmed: true})});
          if (!data.catalogue_id) throw new Error("This printing could not be confirmed. Please retry.");
          edit.selected = {...edit.selected, catalogue_id: data.catalogue_id};
        } else if (!edit.selected.catalogue_id && edit.selected.reference_selection) {
          const data = await this.request("/api/v1/recognition/runs/" + edit.item.run.id + "/references/select", {
            method: "POST", body: JSON.stringify(edit.selected.reference_selection),
          });
          if (!data.catalogue_id) throw new Error("This reference could not be confirmed. Please retry.");
          edit.selected = {...edit.selected, catalogue_id: data.catalogue_id,
            candidate_snapshot: {...snapshot(edit.selected), ...data.selected}};
          edit.searchSelected = true;
        } else if (!edit.selected.catalogue_id) {
          const data = await this.request("/api/v1/recognition/runs/" + edit.item.run.id + "/candidates/" + edit.selected.id + "/materialize", {method: "POST"});
          const candidate = (data.candidates || []).find(row => row.id === edit.selected.id);
          if (!candidate?.catalogue_id) throw new Error("This printing still needs Drop Rate review. Choose a catalogue match or search manually.");
          edit.selected = candidate; edit.item.candidates = data.candidates; edit.item.run = data.run || edit.item.run;
        }
        if (!this.active()) return;
        Object.assign(edit.item, {selected: edit.selected, mode: edit.mode, quantity: edit.quantity, condition: graded(edit) ? null : edit.condition,
          searchSelected: edit.searchSelected, status: "matched", error: null,
          grading_company: graded(edit) ? edit.grading_company : null, grade: graded(edit) ? edit.grade : null,
          certificate_number: graded(edit) ? edit.certificate_number : null, slab: edit.slab, savedGradedValue: null});
        this.editBusy = false; this.closeDetails(); this.render();
        await this.saveAll([edit.item]);
      } catch (error) {
        if (!this.active()) return;
        this.editBusy = false; this.renderDetails();
        this.details.querySelector(".dr-scan-detail-message").textContent = error.message;
      } finally { this.editBusy = false; }
    }

    remove(item) {
      if (!this.active() || !this.removable(item)) return;
      this.items = this.items.filter(row => row !== item);
      item.researchController?.abort();
      this.bookResearchQueue = this.bookResearchQueue.filter(job => job.item !== item);
      this.recognitionQueue = this.recognitionQueue.filter(job => {
        if (job.item !== item) return true;
        job.resolve(); return false;
      });
      if (item.recognitionController) {
        const controller = item.recognitionController; controller.abort(); this.releaseRecognition(item, controller);
      }
      item.photo = null;
      this.closeDetails(); this.render();
      this.status("Scan removed");
    }

    searchCandidate(row) {
      const reference = row.source_kind === "REFERENCE" || row.requires_materialization;
      return {...row, id: null, catalogue_id: row.catalogue_id || row.id || null,
        image_url: row.display_image_url || row.image_url, candidate_snapshot: {...row}, browser_key: row.key,
        ...(reference ? {reference_selection: {provider: row.provider, system_code: row.system_code,
          language: row.language, provider_id: row.provider_id}} : {})};
    }

    openSearch() {
      if (!this.edit || this.editBusy) return;
      this.searchRevision += 1; this.searchController?.abort(); clearTimeout(this.searchTimer);
      const edit = this.edit;
      edit.detailScroll = this.details.querySelector('.dr-scan-details-content')?.scrollTop ?? edit.detailScroll ?? 0;
      edit.searchState ||= {query: "", system: "", language: "", sort: "newest", rows: [], cache: new Map()};
      const state = edit.searchState;
      this.details.replaceChildren(); this.details.classList.add("is-search");
      const header = node("header", "dr-scan-details-header");
      const title = node("h2", "", "Search"); title.id = "dr-scan-details-title";
      header.append(title, button("Back", () => { this.searchRevision += 1; this.searchController?.abort(); clearTimeout(this.searchTimer); this.renderDetails(); }));
      const bar = node("div", "dr-scan-searchbar"), input = node("input", "dr-scan-search-input");
      input.type = "search"; input.placeholder = "Search by card name or number"; input.value = state.query;
      input.setAttribute("aria-label", "Search card name or number"); input.maxLength = 160;
      const refresh = (immediate = false) => {
        clearTimeout(this.searchTimer); this.searchRevision += 1; this.searchController?.abort();
        state.query = input.value.trim(); state.rows = [];
        const revision = this.searchRevision;
        this.searchFilters();
        this.details.querySelector(".dr-scan-search-results").replaceChildren();
        if (state.query.length < 2 && !state.system) {
          this.details.querySelector(".dr-scan-search-message").textContent = state.query ? "Enter at least two characters." : "Quick Filters · browse every card, including cards you don’t own";
          return;
        }
        this.details.querySelector(".dr-scan-search-message").textContent = "Searching…";
        if (immediate) this.search(state.query, revision);
        else this.searchTimer = setTimeout(() => this.search(state.query, revision), 180);
      };
      input.addEventListener("input", () => refresh());
      input.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); refresh(true); input.blur(); } });
      const clear = button("×", () => { input.value = ""; refresh(true); input.focus(); }); clear.setAttribute("aria-label", "Clear search");
      bar.append(input, clear);
      const scroll = node("div", "dr-scan-search-scroll");
      scroll.append(node("div", "dr-scan-search-filters"), node("p", "dr-scan-search-message"), node("div", "dr-scan-search-games"), node("div", "dr-scan-search-results"));
      this.details.append(header, bar, scroll);
      this.refreshSearch = refresh;
      this.searchFilters(); refresh(true); input.focus();
      if (!this.searchGames) {
        this.request("/api/v1/catalogue-browser/games").then(data => {
          if (!this.active()) return;
          this.searchGames = data.items || [];
          if (this.edit === edit && this.details.classList.contains("is-search")) this.searchFilters();
        }).catch(() => { /* Name/number search remains usable when quick filters are unavailable. */ });
      }
    }

    searchFilters() {
      const edit = this.edit, state = edit?.searchState;
      if (!state || !this.details.classList.contains("is-search")) return;
      const filters = this.details.querySelector(".dr-scan-search-filters"); filters.replaceChildren();
      const rank = game => ({POKEMON_TCG: 0, ONE_PIECE_CARD_GAME: 1}[game.system_code] ?? 2);
      const games = [...(this.searchGames || [])].sort((a, b) => rank(a) - rank(b) || a.game.localeCompare(b.game));
      const select = (label, values, value, onChange) => {
        const wrap = node("label", "", label), control = node("select"); control.setAttribute("aria-label", label);
        values.forEach(([id, text]) => { const option = node("option", "", text); option.value = id; control.append(option); });
        control.value = value; control.addEventListener("change", () => { onChange(control.value); this.refreshSearch(true); });
        wrap.append(control); filters.append(wrap);
      };
      select("Game", [["", "All games"], ...games.map(game => [game.system_code, game.game])], state.system, value => { state.system = value; state.language = ""; });
      const languages = [...new Set(games.filter(game => !state.system || game.system_code === state.system).flatMap(game => game.languages || []))].sort();
      select("Language", [["", "All languages"], ...languages.map(language => [language, language])], state.language, value => { state.language = value; });
      select("Sort", [["newest", "Newest first"], ["name", "Name A–Z"], ["number", "Card number"]], state.sort, value => { state.sort = value; });
      if (state.system || state.language) filters.append(button("Clear filters", () => { state.system = ""; state.language = ""; this.refreshSearch(true); }));
      const quick = this.details.querySelector(".dr-scan-search-games"); quick.replaceChildren(); quick.hidden = Boolean(state.query || state.system);
      for (const game of games) {
        const tile = button("", () => { state.system = game.system_code; state.language = ""; this.refreshSearch(true); }, "dr-scan-game");
        tile.setAttribute("aria-label", "Browse " + game.game);
        tile.append(node("span", "", game.game));
        const art = window.DropRateTitleArt?.game(game.system_code);
        if (art) {
          const logo = node("img"); logo.alt = ""; logo.src = art.url || "/assets/title-art/" + art.file;
          logo.addEventListener("load", () => tile.classList.add("has-logo")); logo.addEventListener("error", () => logo.remove()); tile.append(logo);
        }
        quick.append(tile);
      }
    }

    async search(query, revision, more = false) {
      const edit = this.edit, state = edit?.searchState;
      if (!edit || !state || (!graded(edit) && !usableRun(edit.item))) {
        const message = this.details.querySelector(".dr-scan-search-message");
        if (message) message.textContent = "Retry the scan first so the correction has completed recognition evidence.";
        return;
      }
      this.searchController?.abort();
      const controller = new AbortController(); this.searchController = controller; this.controllers.add(controller);
      const params = new URLSearchParams({q: query, limit: "30", offset: String(more ? state.rows.length : 0),
        product_type: "CARD", owned: "all", sort: state.sort});
      if (state.system) params.set("system_code", state.system);
      if (state.language) params.set("language", state.language);
      const results = this.details.querySelector(".dr-scan-search-results");
      if (!more) {
        results.replaceChildren();
        for (let index = 0; index < 4; index += 1) results.append(node("div", "dr-scan-search-skeleton"));
      }
      const message = this.details.querySelector(".dr-scan-search-message"); message.textContent = "Searching…";
      try {
        const cached = state.cache.get(params.toString());
        const data = cached && Date.now() - cached.time < 60000 ? cached.data
          : await this.request("/api/v1/catalogue-browser/products?" + params, {signal: controller.signal});
        if (!this.active() || this.edit !== edit || revision !== this.searchRevision) return;
        if (state.cache.size >= 20) state.cache.delete(state.cache.keys().next().value);
        state.cache.set(params.toString(), {data, time: Date.now()});
        const rows = (data.items || []).filter(row => row.product_type !== "SEALED");
        state.rows = more ? state.rows.concat(rows) : rows;
        results.replaceChildren();
        message.textContent = state.rows.length ? state.rows.length + " matches · compare artwork, number and language" : "No results. Try the exact card number or clear filters.";
        for (const row of state.rows) {
          const candidate = this.searchCandidate(row), choice = button("", () => this.chooseSearch(row), "dr-scan-search-result");
          choice.append(this.thumb({selected: candidate}, "dr-scan-search-art", candidate));
          const copy = node("span"); copy.append(node("strong", "", row.name), node("small", "", meta({selected: candidate})),
            node("small", "", graded(edit) ? "Choose grader in details" : row.market_value_minor == null ? "Market value unavailable" : money(row.market_value_minor)));
          choice.append(copy); results.append(choice);
        }
        if (data.has_more) {
          const load = button("Load more", () => { load.disabled = true; this.search(query, revision, true); }, "dr-scan-search-more");
          results.append(load);
        }
      } catch (error) {
        if (error.name !== "AbortError" && this.active() && this.edit === edit && revision === this.searchRevision) {
          message.textContent = error.message;
          results.querySelectorAll(".dr-scan-search-skeleton").forEach(element => element.remove());
          results.querySelectorAll("button").forEach(element => { element.disabled = false; });
        }
      } finally { this.controllers.delete(controller); }
    }

    async chooseSearch(row) {
      const edit = this.edit; if (!edit || this.editBusy) return;
      const candidate = this.searchCandidate(row);
      if (!candidate.catalogue_id && !candidate.reference_selection) return;
      // Selection remains a local draft; the explicit confirmation links the reference.
      edit.selected = candidate; edit.searchSelected = true;
      this.searchRevision += 1; this.searchController?.abort(); clearTimeout(this.searchTimer);
      document.activeElement?.blur(); this.renderDetails();
    }

    freeze(item) {
      if (book(item)) throw new Error("Review and save books through book intake.");
      if (item.requests) return;
      const isSealed = sealed(item), card = snapshot(item.selected);
      if (graded(item)) {
        item.feedbackSaved = true;
        item.requests = [{key: crypto.randomUUID(), body: JSON.stringify({selected_catalogue_id: item.selected.catalogue_id,
          grading_company: item.grading_company, grade: item.grade, certificate_number: item.certificate_number,
          language: card.language || null}), result: null}];
        return;
      }
      item.feedback = JSON.stringify({outcome: item.searchSelected ? "CORRECTED_BY_SEARCH"
        : item.selected.catalogue_id === item.run.top_catalogue_id ? "CONFIRMED_TOP" : "CORRECTED_TO_CANDIDATE",
      selected_catalogue_id: item.selected.catalogue_id, notes: "Confirmed in Drop Rate scanner review"});
      const physical = {condition: isSealed ? null : item.condition || null, seal_status: isSealed ? "SEALED" : null,
        grading_company: null, grade: null, certificate_number: null, language: card.language || null};
      const payload = this.options.role === "seller"
        ? {...physical, recognition_run_id: item.run.id, selected_catalogue_id: item.selected.catalogue_id}
        : {...physical, catalogue_id: item.selected.catalogue_id, identity_confirmed: false,
          notes: "Recognition run " + item.run.id + " · confirmed in scanner review"};
      item.requests = Array.from({length: item.quantity}, () => ({key: crypto.randomUUID(), body: JSON.stringify(payload), result: null}));
    }

    async saveAll(onlyItems = null) {
      if (this.saving || !this.active() || !this.items.length) return;
      if (this.items.every(item => item.status === "added")) { this.close(); this.options.viewInventory(); return; }
      const targets = (onlyItems || this.items).filter(item => this.items.includes(item)
        && item.status !== "added" && this.ready(item));
      if (!targets.length) {
        const nextBook = (onlyItems || this.items).find(item => book(item) && this.editable(item));
        if (nextBook) this.openDetails(nextBook);
        return;
      }
      this.saving = true; targets.forEach(item => this.freeze(item)); this.renderReview();
      const epoch = this.epoch;
      const message = this.find(".dr-scan-save-message");
      let added = 0, failed = 0;
      for (const item of targets) {
        if (!this.active(epoch)) return;
        if (item.status === "added") continue;
        try {
          message.textContent = "Adding " + name(item) + "…";
          if (!item.feedbackSaved) {
            await this.request("/api/v1/recognition/runs/" + item.run.id + "/feedback", {method: "POST", body: item.feedback});
            item.feedbackSaved = true;
          }
          for (const pending of item.requests) {
            if (pending.result) continue;
            const data = await this.request(graded(item) ? (this.options.role === "seller" ? "/api/v1/owner/graded-certificate-intake" : "/api/v1/inventory/graded-intake")
              : this.options.role === "seller" ? "/api/v1/owner/recognition-intake" : "/api/v1/inventory/intake", {
              method: "POST", headers: {"Idempotency-Key": pending.key}, body: pending.body,
            });
            if (!this.active(epoch)) return;
            if (!data.inventory?.inventory_code) throw new Error("Save confirmation was incomplete. Retry to check this same request.");
            pending.result = data; added += 1;
            if (graded(item)) item.savedGradedValue = data.valuation?.market_value_minor ?? data.inventory.market_value_minor ?? null;
          }
          item.status = "added"; item.error = null; item.photo = null;
        } catch (error) {
          if (!this.active(epoch)) return;
          item.status = "save-error"; item.error = error.message; failed += 1;
        }
        this.renderReview();
      }
      if (!this.active(epoch)) return;
      this.saving = false; this.render();
      message.textContent = failed ? added + " added. Retry the remaining saves; their details are locked to prevent duplicate copies."
        : added + " added to your collection. Listing for sale is a separate action.";
      if (this.items.some(item => !item.requests && !this.ready(item))) message.textContent += " Uncertain matches remain for confirmation.";
      this.status(message.textContent);
      try { await this.options.afterSave(); }
      catch (_) { if (this.active(epoch)) message.textContent += " Refresh your collection to see the latest totals."; }
    }
  }

  return {Scanner, researchBook, analyzeCardPresence, isMobile: () => window.matchMedia("(max-width: 900px)").matches};
})();
