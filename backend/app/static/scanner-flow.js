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
  const sealed = item => [snapshot(selected(item)).product_type,
    snapshot(selected(item)).collectible_type].includes("SEALED");
  const name = item => snapshot(selected(item)).name || item.guess || "Check this match";
  const meta = item => {
    const card = snapshot(selected(item));
    return [card.game, card.set_name, card.product_code || card.card_number || card.base_card_id,
      card.language, card.variant || card.art_treatment].filter(Boolean).join(" · ");
  };
  const conditions = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
  const graded = item => item.mode === "GRADED";
  const graders = ["PSA", "ACE", "CGC", "BGS", "BVG", "BCCG"];
  const gradeValid = item => graders.includes(item.grading_company) && /^(?:10(?:\s*BLACK\s*LABEL)?|BL10|[1-9](?:\.5)?)$/i.test(item.grade || "")
    && (item.grading_company === "PSA" ? /^\d{7,10}$/ : /^\d{4,14}$/).test(item.certificate_number || "")
    && !item.slab?.conflicts?.length;
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

  class Scanner {
    constructor(options) {
      this.options = options;
      this.owner = sessionId(options.session());
      this.items = [];
      this.epoch = 0;
      this.cameraRevision = 0;
      this.searchRevision = 0;
      this.mode = ["RAW", "GRADED", "SEALED"].includes(options.mode) ? options.mode : "RAW";
      this.auto = true;
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
      this.dialog.setAttribute("aria-label", "Drop Rate card scanner");
      this.dialog.innerHTML = '<section class="dr-scan-camera">' +
        '<video autoplay muted playsinline aria-label="Live camera"></video>' +
        '<header class="dr-scan-topbar"><button type="button" data-action="close" aria-label="Close scanner">←</button>' +
        '<strong>Trading Card Games</strong><button type="button" data-action="settings" aria-label="Scanner settings">⚙</button></header>' +
        '<nav class="dr-scan-modes" aria-label="Scan type">' +
        ['RAW', 'GRADED', 'SEALED'].map(mode => '<button type="button" data-mode="' + mode + '" aria-pressed="false">' + mode + '</button>').join('') + '</nav>' +
        '<button type="button" class="dr-scan-certificate" data-action="certificate" hidden>Enter certificate</button>' +
        '<div class="dr-scan-guide" aria-hidden="true"></div><p class="dr-scan-status" role="status">Place a card inside the guide</p>' +
        '<button type="button" class="dr-scan-camera-resume" data-action="resume">Start camera</button>' +
        '<div class="dr-scan-settings" hidden><label><input type="checkbox" checked> Auto-scan</label>' +
        '<button type="button" data-action="switch">Switch camera</button><button type="button" data-action="torch" hidden>Torch off</button></div>' +
        '<div class="dr-scan-tray"><div class="dr-scan-strip" aria-label="Scanned cards"></div>' +
        '<p class="dr-scan-total"></p><div class="dr-scan-controls">' +
        '<button type="button" data-action="gallery" class="dr-scan-gallery" aria-label="Choose a card photo">▧</button>' +
        '<button type="button" data-action="capture" class="dr-scan-shutter" aria-label="Scan this card"></button>' +
        '<button type="button" data-action="next" class="dr-scan-next">Next →</button></div></div>' +
        '<input type="file" class="dr-scan-file" accept="image/jpeg,image/png,image/webp" hidden></section>' +
        '<section class="dr-scan-review" hidden aria-labelledby="dr-scan-review-title">' +
        '<header class="dr-scan-review-header"><button type="button" data-action="back" aria-label="Resume scanning">←</button>' +
        '<h2 id="dr-scan-review-title">Review Your Matches</h2><button type="button" data-action="close" aria-label="Close review">×</button></header>' +
        '<p class="dr-scan-destination">Adding to: <strong>Your inventory</strong></p>' +
        '<div class="dr-scan-review-list"></div><footer class="dr-scan-review-footer">' +
        '<strong class="dr-scan-review-total"></strong><span class="dr-scan-review-count"></span>' +
        '<p class="dr-scan-save-message" role="status"></p><button type="button" data-action="save" class="dr-scan-primary">Add to Inventory</button>' +
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

    guideMessage() {
      return this.mode === "GRADED" ? "Show the full slab · keep the label and QR readable"
        : this.mode === "SEALED" ? "Frame the whole pack, box or sealed set" : "Place a card inside the guide";
    }

    setMode(mode) {
      if (!["RAW", "GRADED", "SEALED"].includes(mode) || this.processing || this.edit || this.saving) return;
      this.mode = mode; this.dialog.dataset.mode = mode;
      this.dialog.querySelectorAll("[data-mode]").forEach(control => control.setAttribute("aria-pressed", String(control.dataset.mode === mode)));
      this.find('[data-action="certificate"]').hidden = mode !== "GRADED";
      this.find('[data-action="capture"]').setAttribute("aria-label", "Scan " + (mode === "GRADED" ? "graded slab" : mode === "SEALED" ? "sealed product" : "raw card"));
      this.find('[data-action="gallery"]').setAttribute("aria-label", "Choose an item photo");
      this.previous = null; this.stableFrames = 0; this.presenceFrames = 0;
      this.status(this.guideMessage());
    }

    async captureSlabQr() {
      if (this.qrBusy || this.processing || this.awaitingRemoval) return;
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
      this.processing = true; this.render();
      try {
        const parsed = await this.request("/api/v1/grading-certificates/qr/resolve", {method: "POST",
          body: JSON.stringify({qr_value: raw, grader_hint: /^https?:\/\//i.test(raw) ? null : "PSA"})});
        if (revision !== this.cameraRevision || this.mode !== "GRADED") return;
        this.lastQr = raw; this.awaitingRemoval = true;
        this.processing = false;
        this.manualSlab(parsed);
        await this.lookupSlab();
      } catch (_) {
        if (this.active() && revision === this.cameraRevision) { this.processing = false; this.capture(); }
      } finally { if (this.active() && !this.items.some(item => item.status === "processing")) { this.processing = false; this.render(); } }
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
      item.grading_company = data.normalized_provider || provider.provider || observation.grader || item.grading_company || "PSA";
      item.certificate_number = data.normalized_certificate || provider.certificate_number || observation.certificate_number || item.certificate_number || "";
      item.grade = provider.grade || observation.grade || item.grade || "";
      item.guess = provider.subject || observation.card_name || "Choose the graded card";
      item.searchSeed = data.catalogue_search_seed || provider.card_number || observation.card_number || provider.subject || observation.card_name || "";
      item.error = data.conflicts?.length ? "Certificate and label disagree. Resolve this before adding the slab." : null;
    }

    async slabCandidates(item) {
      if (!item.searchSeed || item.searchSeed.length < 2) return;
      const params = new URLSearchParams({q: item.searchSeed.slice(0, 80), limit: "20"});
      const data = await this.request((this.options.role === "seller" ? "/api/v1/owner/catalogue-search?" : "/api/v1/catalogue/search?") + params);
      item.candidates = (data.items || []).filter(row => row.product_type !== "SEALED")
        .map(row => ({...row, catalogue_id: row.id, candidate_snapshot: row, market_value_minor: null}));
      item.suggested = item.candidates[0] || null;
    }

    async recogniseSlab(photo, item, isNew) {
      const epoch = this.epoch;
      item.status = "processing"; item.guess = "Reading slab…"; item.error = null;
      if (isNew) this.items.push(item);
      this.processing = true; this.status("Reading slab label and certificate…"); this.render();
      const controller = new AbortController(); this.controllers.add(controller);
      const timeout = setTimeout(() => controller.abort(), 70000);
      try {
        const data = await this.request("/api/v1/grading-certificates/scan", {method: "POST", signal: controller.signal,
          body: JSON.stringify({image_data_url: photo})});
        this.applySlabEvidence(item, data);
        await this.slabCandidates(item);
        item.selected = null;
        this.status("Slab read · tap its thumbnail to confirm the card and grade");
      } catch (error) {
        if (!this.active(epoch)) return;
        item.error = error.name === "AbortError" ? "Slab reading timed out. Retry the photo or enter the certificate." : error.message;
        this.status("Check slab details · certificate entry is available");
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller);
        if (this.active(epoch)) { item.status = "unresolved"; this.processing = false; this.render(); }
      }
    }

    async lookupSlab() {
      const edit = this.edit; if (!edit || this.editBusy || !graded(edit.item)) return;
      this.editBusy = true;
      this.details.querySelectorAll("button,input,select").forEach(control => { control.disabled = true; });
      try {
        const data = await this.request("/api/v1/grading-certificates/lookup", {method: "POST",
          body: JSON.stringify({grader: edit.grading_company, certificate_number: edit.certificate_number})});
        // A manual lookup cannot erase a conflict observed in the original slab photo.
        const conflicts = edit.item.slab?.conflicts || [];
        Object.assign(edit.item, {grading_company: edit.grading_company, certificate_number: edit.certificate_number});
        this.applySlabEvidence(edit.item, {...data, conflicts});
        await this.slabCandidates(edit.item);
        Object.assign(edit, {grading_company: edit.item.grading_company, certificate_number: edit.item.certificate_number,
          grade: edit.item.grade, selected: edit.item.suggested || edit.selected});
      } catch (error) { if (this.active()) edit.item.lookupMessage = error.message + " You can read the label and confirm the card manually."; }
      finally { if (this.active()) { this.editBusy = false; this.renderSlabDetails(); } }
    }

    renderSlabDetails() {
      const edit = this.edit, item = edit.item;
      this.details.replaceChildren(node("div", "dr-scan-drag-handle"));
      const header = node("header", "dr-scan-details-header"), title = node("h2", "", "Graded Slab Details");
      title.id = "dr-scan-details-title";
      header.append(title, button("×", () => this.closeDetails())); this.details.append(header);
      const content = node("div", "dr-scan-details-content");
      if (item.photo) content.append(this.thumb(item, "dr-scan-slab-photo", null, true));
      const fields = node("div", "dr-scan-detail-fields");
      for (const [key, label] of [["grading_company", "Grader"], ["grade", "Grade"], ["certificate_number", "Certificate number"]]) {
        const wrap = node("label", "", label), input = node(key === "grading_company" ? "select" : "input");
        if (key === "grading_company") graders.forEach(value => { const option = node("option", "", value); option.value = value; input.append(option); });
        else { input.maxLength = key === "grade" ? 40 : 14; if (key === "certificate_number") input.inputMode = "numeric"; }
        input.value = edit[key]; input.setAttribute("aria-label", label);
        input.addEventListener("input", () => { edit[key] = input.value.trim(); this.updateDetailsSave(); });
        wrap.append(input); fields.append(wrap);
      }
      content.append(fields, button("Lookup certificate", () => this.lookupSlab()));
      const evidence = item.slab?.provider_result || item.slab || {};
      content.append(node("p", "dr-scan-review-note", item.lookupMessage || (evidence.verified
        ? "Provider evidence found. Confirm that the card, grade and certificate match your slab."
        : "Confirm the slab label. Certificate verification and Drop Rate identity review may still be required.")));
      if (item.error) content.append(node("p", "dr-scan-item-error", item.error));
      if (item.photo) content.append(button("Read slab photo again", () => { this.closeDetails(); this.recognise(item.photo, item); }));
      content.append(node("p", "dr-scan-results-label", "Choose the exact card:"));
      const candidates = node("div", "dr-scan-alternatives");
      for (const candidate of item.candidates || []) {
        const choice = button("", () => { edit.selected = candidate; this.renderSlabDetails(); }, "dr-scan-alternative");
        choice.setAttribute("aria-pressed", String(edit.selected?.catalogue_id === candidate.catalogue_id));
        choice.setAttribute("aria-label", name({selected:candidate}) + " · " + meta({selected:candidate}));
        choice.append(this.thumb(item, "dr-scan-alternative-thumb", candidate)); candidates.append(choice);
      }
      content.append(candidates, button("Search for the exact card", () => this.openSearch()));
      if (edit.selected) content.append(node("h3", "", name({selected: edit.selected})), node("p", "dr-scan-card-meta", meta({selected: edit.selected})));
      content.append(node("p", "dr-scan-review-note", "One slab per certificate. Grade-specific value is calculated after saving."), node("p", "dr-scan-detail-message"));
      this.details.append(content);
      const footer = node("footer", "dr-scan-details-footer"), save = button("Looks Good", () => this.confirmDetails(), "dr-scan-primary");
      save.dataset.detailsSave = "true";
      footer.append(button("Remove", () => this.remove(item), "dr-scan-delete"), save); this.details.append(footer);
      this.updateDetailsSave();
    }

    async open(mode) {
      if (mode) this.setMode(mode);
      if (!this.active()) throw new Error("Please sign in again before scanning.");
      this.returnFocus = document.activeElement;
      this.dialog.showModal();
      document.body.classList.add("dr-scanner-open");
      if (this.items.some(item => item.requests)) this.showReview();
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
        this.find('[data-action="capture"]').disabled = this.processing;
        this.previous = null;
        this.stableFrames = 0;
        this.presenceFrames = 0;
        this.absenceFrames = 0;
        // Preserve the removal gate when returning from details/review.
        this.status(this.awaitingRemoval ? "Remove the scanned card before continuing" : this.guideMessage());
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
      canvas.width = 20; canvas.height = 28;
      const context = canvas.getContext("2d", {willReadFrequently: true});
      if (!context) return null;
      context.drawImage(this.video, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, 20, 28);
      const pixels = context.getImageData(0, 0, 20, 28).data;
      const fingerprint = new Uint8Array(560);
      let total = 0, squared = 0, edges = 0, edgeCount = 0, border = 0, borderCount = 0, inner = 0, innerCount = 0;
      for (let index = 0; index < 560; index += 1) {
        const pixel = index * 4;
        const gray = Math.round(pixels[pixel] * 0.299 + pixels[pixel + 1] * 0.587 + pixels[pixel + 2] * 0.114);
        fingerprint[index] = gray; total += gray; squared += gray * gray;
        const x = index % 20, y = Math.floor(index / 20);
        if (x < 2 || x >= 18 || y < 2 || y >= 26) { border += gray; borderCount += 1; }
        else { inner += gray; innerCount += 1; }
        if (x > 0) { edges += Math.abs(gray - fingerprint[index - 1]); edgeCount += 1; }
        if (y > 0) { edges += Math.abs(gray - fingerprint[index - 20]); edgeCount += 1; }
      }
      const mean = total / 560;
      const deviation = Math.sqrt(Math.max(0, squared / 560 - mean * mean)) / 255;
      const edge = edges / edgeCount / 255;
      const borderContrast = Math.abs(inner / innerCount - border / borderCount) / 255;
      const present = (borderContrast >= 0.035 && deviation >= 0.055)
        || (edge >= 0.065 && deviation >= 0.10) || deviation >= 0.18;
      return {fingerprint, present};
    }

    tick() {
      if (!this.auto || this.processing || this.edit || this.view !== "camera" || !this.stream || !this.video.videoWidth) return;
      const analysis = this.frame();
      if (!analysis) return;
      if (!analysis.present) {
        this.presenceFrames = 0; this.stableFrames = 0; this.absenceFrames += 1;
        this.previous = analysis.fingerprint;
        if (this.absenceFrames >= 2) this.awaitingRemoval = false;
        this.status(this.awaitingRemoval ? "Remove the scanned card to continue" : this.guideMessage());
        return;
      }
      this.absenceFrames = 0; this.presenceFrames += 1;
      if (this.awaitingRemoval) { this.status("Card scanned · show the next card after removing this one"); return; }
      const movement = fingerprintDelta(analysis.fingerprint, this.previous);
      this.previous = analysis.fingerprint;
      this.stableFrames = movement <= 0.028 ? this.stableFrames + 1 : 0;
      if (this.presenceFrames < 2 || this.stableFrames < 3) { this.status("Hold the item steady"); return; }
      if (this.mode === "GRADED" && !this.qrBusy) this.captureSlabQr();
      else if (this.mode !== "GRADED") this.capture();
    }

    capture() {
      if (this.processing || this.edit || !this.stream || !this.video.videoWidth) return;
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

    async upload(event) {
      const file = event.target.files?.[0]; event.target.value = "";
      if (!file || this.processing || this.editBusy) return;
      const epoch = this.epoch;
      let url;
      this.processing = true; this.render();
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
        this.processing = false;
        await this.recognise(canvas.toDataURL("image/jpeg", 0.88));
      } catch (error) { if (this.active(epoch)) this.status(error.message); }
      finally {
        if (url) URL.revokeObjectURL(url);
        if (this.active(epoch)) { this.processing = false; this.render(); }
      }
    }

    async recognise(photo, retryItem = null) {
      if (this.processing || !this.active()) return;
      const epoch = this.epoch;
      const item = retryItem || {id: crypto.randomUUID(), photo, mode: this.mode, quantity: 1, condition: "", selected: null};
      if (graded(item)) { await this.recogniseSlab(photo, item, !retryItem); return; }
      item.status = "processing"; item.error = null; item.guess = "Loading…";
      if (!retryItem) this.items.push(item);
      this.processing = true;
      this.status("Recognising…"); this.render();
      const controller = new AbortController(); this.controllers.add(controller);
      const timeout = setTimeout(() => controller.abort(), 70000);
      try {
        const data = await this.request("/api/v1/recognition/resolve", {method: "POST", signal: controller.signal,
          body: JSON.stringify({image_data_url: photo, force_refresh: true})});
        item.run = data.run || {};
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
        if (!this.active(epoch)) return;
        item.status = "unresolved"; item.guess = "Recognition failed";
        item.error = error.name === "AbortError" ? "Recognition timed out. Retry this photo." : error.message;
        this.status("Couldn’t recognise this card · tap its thumbnail to retry");
      } finally {
        clearTimeout(timeout); this.controllers.delete(controller);
        if (this.active(epoch)) { this.processing = false; this.render(); }
      }
    }

    async artwork(image, item, candidate = selected(item)) {
      if (candidate?.image_url) { image.src = candidate.image_url; return; }
      if (!item.run?.id || !candidate?.id) { image.hidden = true; return; }
      const key = item.run.id + "/" + candidate.id;
      const epoch = this.epoch;
      if (!this.images.has(key)) {
        const controller = new AbortController(); this.controllers.add(controller);
        this.images.set(key, (async () => {
          try {
            const response = await fetch("/api/v1/recognition/runs/" + item.run.id + "/candidates/" + candidate.id + "/image", {
              headers: {Authorization: "Bearer " + this.options.session()?.access_token}, cache: "no-store", signal: controller.signal,
            });
            if (!response.ok) return null;
            const blob = await response.blob();
            if (!this.active(epoch)) return null;
            const url = URL.createObjectURL(blob); this.objectUrls.add(url); return url;
          } catch (_) { return null; }
          finally { this.controllers.delete(controller); }
        })());
      }
      const url = await this.images.get(key);
      if (!this.active(epoch)) return;
      if (url) image.src = url; else image.hidden = true;
    }

    thumb(item, className = "dr-scan-thumb", candidate = selected(item), captured = false) {
      const wrap = node("div", className);
      const image = node("img"); image.alt = captured ? "Your scanned photo" : name({...item, selected: candidate});
      image.addEventListener("error", () => { image.hidden = true; });
      wrap.append(node("span", "dr-scan-image-placeholder", captured ? "Photo cleared" : "No image"), image);
      if (captured || item.status === "processing") { if (item.photo) image.src = item.photo; else image.hidden = true; }
      else this.artwork(image, item, candidate);
      return wrap;
    }

    totals() {
      let value = 0, unknown = 0, copies = 0;
      for (const item of this.items) {
        copies += item.quantity;
        if (item.selected?.market_value_minor == null) unknown += item.quantity;
        else value += Number(item.selected.market_value_minor) * item.quantity;
      }
      return {value: unknown === copies && copies > 0 ? null : value, unknown, copies};
    }

    editable(item) { return !this.saving && !this.editBusy && !item.requests && item.status !== "processing"; }
    ready(item) { return Boolean(item.requests || (item.selected?.catalogue_id && item.status === "matched"
      && (graded(item) ? gradeValid(item) && item.quantity === 1 : usableRun(item) && (sealed(item) || conditions.includes(item.condition))))); }

    render() {
      const totals = this.totals();
      const strip = this.find(".dr-scan-strip"); strip.replaceChildren();
      if (!this.items.length) strip.append(node("p", "dr-scan-strip-empty", "Your scans will appear here"));
      for (const item of [...this.items].reverse()) {
        const tile = button("", () => this.openDetails(item), "dr-scan-tile " + item.status);
        tile.disabled = item.status === "processing" || this.saving;
        tile.setAttribute("aria-label", (item.status === "processing" ? "Recognising card" : "Review " + name(item)));
        tile.append(this.thumb(item));
        const copy = node("span", "dr-scan-tile-copy");
        copy.append(node("strong", "", item.status === "processing" ? "Loading…" : name(item)));
        const card = snapshot(selected(item));
        if (item.status !== "processing") copy.append(node("span", "", card.card_number || card.product_code || ""),
          node("span", "", item.status === "unresolved" ? "Check match" : money(item.selected?.market_value_minor)));
        tile.append(copy); strip.append(tile);
      }
      this.find(".dr-scan-total").textContent = "Total: " + money(totals.value) + (totals.unknown ? " · " + totals.unknown + " pending" : "");
      this.find('[data-action="next"]').disabled = !this.items.length;
      this.find('[data-action="capture"]').disabled = this.processing || !this.stream;
      this.find('[data-action="gallery"]').disabled = this.processing;
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
        row.append(node("h3", "", item.status === "processing" ? "Recognising…" : name(item)), node("p", "dr-scan-card-meta", meta(item)));
        const body = node("div", "dr-scan-review-body"); body.append(this.thumb(item, "dr-scan-review-thumb"));
        const copy = node("div", "dr-scan-review-copy");
        copy.append(node("strong", "dr-scan-card-value", item.selected?.market_value_minor == null ? "Market value unavailable" : money(item.selected.market_value_minor)));
        const fields = node("dl");
        const card = snapshot(selected(item));
        for (const [label, value] of [["Variant", card.variant || card.art_treatment || card.sealed_product_type || "—"],
          ["Type", graded(item) ? item.grading_company + " " + item.grade : sealed(item) ? "Sealed product" : "Raw card"],
          [graded(item) ? "Certificate" : "Condition", graded(item) ? item.certificate_number : sealed(item) ? "Sealed" : item.condition || "Choose condition"], ["Quantity", item.quantity]]) {
          fields.append(node("dt", "", label), node("dd", "", value));
        }
        copy.append(fields);
        const edit = button(!graded(item) && !sealed(item) && !item.condition ? "Choose condition & confirm" : item.status === "unresolved" ? "Confirm match" : "Edit details", () => this.openDetails(item));
        edit.disabled = !this.editable(item); copy.append(edit);
        if (item.status === "added") copy.append(node("span", "dr-scan-added", "Added to inventory"));
        if (item.error) copy.append(node("p", "dr-scan-item-error", item.error));
        body.append(copy); row.append(body); list.append(row);
      }
      const totals = this.totals();
      this.find(".dr-scan-review-total").textContent = "Total: " + money(totals.value);
      const unresolved = this.items.filter(item => !item.selected).length;
      const missingCondition = this.items.filter(item => item.selected && !graded(item) && !sealed(item) && !item.condition).length;
      const matched = this.items.length - unresolved;
      this.find(".dr-scan-review-count").textContent = matched + " matched " + (matched === 1 ? "scan" : "scans") +
        (unresolved ? " · " + unresolved + " to review" : "") + (missingCondition ? " · check conditions" : "") +
        (totals.unknown ? " · " + totals.unknown + " without a market value" : "") + ".";
      const done = this.items.length && this.items.every(item => item.status === "added");
      const retry = this.items.some(item => item.requests && item.status !== "added");
      const save = this.find('[data-action="save"]');
      save.textContent = this.saving ? "Adding…" : done ? "View inventory" : retry ? "Retry remaining saves" : "Add to Inventory";
      save.disabled = this.saving || !this.items.length || (!done && this.items.some(item => !this.ready(item)));
      this.find('[data-action="back"]').disabled = this.saving;
      this.review.querySelector('[data-action="close"]').disabled = this.saving;
    }

    openDetails(item) {
      if (!this.editable(item)) return;
      this.edit = {item, selected: item.selected || item.suggested, condition: item.condition,
        quantity: item.quantity, searchSelected: item.searchSelected || false,
        grading_company: item.grading_company || "PSA", grade: item.grade || "", certificate_number: item.certificate_number || ""};
      this.sheet.hidden = false; this.camera.inert = true; this.review.inert = true;
      this.renderDetails();
    }

    closeDetails() {
      if (this.editBusy) return;
      this.edit = null; this.searchRevision += 1; clearTimeout(this.searchTimer);
      this.sheet.hidden = true; this.camera.inert = false; this.review.inert = false;
      this.previous = null; this.stableFrames = 0;
      (this.view === "review" ? this.find('[data-action="back"]') : this.find('[data-action="next"]')).focus();
    }

    renderDetails() {
      const edit = this.edit; if (!edit) return;
      const item = edit.item;
      if (graded(item)) { this.renderSlabDetails(); return; }
      this.details.replaceChildren();
      this.details.append(node("div", "dr-scan-drag-handle"));
      const heading = node("header", "dr-scan-details-header");
      const title = node("h2", "", "Scan Details"); title.id = "dr-scan-details-title";
      const close = button("×", () => this.closeDetails()); close.setAttribute("aria-label", "Close scan details");
      heading.append(title, close); this.details.append(heading);
      const content = node("div", "dr-scan-details-content");
      const pair = node("div", "dr-scan-photo-pair");
      for (const [label, captured] of [["Your Picture", true], ["Your Match", false]]) {
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
        choice.append(this.thumb(item, "dr-scan-alternative-thumb", candidate)); matches.append(choice);
      }
      content.append(matches);
      if (allCandidates.length > shortlist.length) content.append(button(edit.showAllCandidates ? "Show closest matches" : "Show other suggestions", () => {
        edit.showAllCandidates = !edit.showAllCandidates; this.renderDetails();
      }));
      const candidateItem = {...item, selected: edit.selected};
      const info = node("div", "dr-scan-detail-identity");
      info.append(node("h3", "", name(candidateItem)), node("strong", "", edit.selected?.market_value_minor == null ? "Market value unavailable" : money(edit.selected.market_value_minor)),
        node("p", "", meta(candidateItem)));
      content.append(info);
      if (edit.selected?.market_value_minor == null) content.append(node("p", "dr-scan-review-note",
        "No verified market valuation is stored for this printing yet. You can still confirm it and add it to inventory."));
      else if (edit.selected.recommended_retail_minor != null) content.append(node("p", "dr-scan-review-note",
        "Suggested retail: " + money(edit.selected.recommended_retail_minor) + " · reference value, not a live quote"));
      if (item.error) content.append(node("p", "dr-scan-item-error", item.error));
      if (!usableRun(item)) {
        const retry = button("Retry this photo", () => { this.closeDetails(); this.recognise(item.photo, item); });
        retry.disabled = this.processing; content.append(retry);
      }
      const isSealed = sealed(candidateItem);
      content.append(node("span", "dr-scan-type-chip", isSealed ? "Sealed product" : "Ungraded"));
      const fields = node("div", "dr-scan-detail-fields");
      const conditionLabel = node("label", "", "Condition");
      const condition = node("select"); condition.setAttribute("aria-label", "Condition");
      (isSealed ? ["Sealed"] : ["Choose condition", ...conditions]).forEach((value, index) => {
        const option = node("option", "", value); option.value = !isSealed && index === 0 ? "" : value; condition.append(option);
      });
      condition.value = isSealed ? "Sealed" : edit.condition;
      condition.disabled = isSealed;
      condition.addEventListener("change", () => { edit.condition = condition.value; this.updateDetailsSave(); });
      conditionLabel.append(condition);
      const variant = node("label", "", "Variant");
      variant.append(node("span", "dr-scan-readonly-field", snapshot(edit.selected).variant || snapshot(edit.selected).art_treatment || snapshot(edit.selected).sealed_product_type || "—"));
      const quantityLabel = node("label", "", "Quantity");
      const quantity = node("input"); quantity.type = "number"; quantity.min = "1"; quantity.max = "50"; quantity.step = "1";
      quantity.value = edit.quantity; quantity.inputMode = "numeric"; quantity.setAttribute("aria-label", "Quantity");
      quantity.addEventListener("input", () => { edit.quantity = Number(quantity.value); this.updateDetailsSave(); });
      quantityLabel.append(quantity); fields.append(conditionLabel, variant, quantityLabel); content.append(fields);
      if (edit.selected && !edit.selected.catalogue_id) content.append(node("p", "dr-scan-review-note",
        isSealed ? "This sealed product needs Drop Rate identity review before inventory." : "This printing will be linked to Drop Rate for review when you confirm it."));
      content.append(node("p", "dr-scan-detail-message"));
      this.details.append(content);
      const footer = node("footer", "dr-scan-details-footer");
      const remove = button("⌫", () => this.remove(item), "dr-scan-delete"); remove.setAttribute("aria-label", "Remove this scan");
      remove.innerHTML = icons.trash;
      const save = button("Looks Good", () => {
        if (!isSealed && !conditions.includes(edit.condition)) {
          condition.focus();
          try { condition.showPicker?.(); } catch (_) { /* Focus still exposes the required field. */ }
          return;
        }
        this.confirmDetails();
      }, "dr-scan-primary"); save.dataset.detailsSave = "true";
      footer.append(remove, save); this.details.append(footer); this.updateDetailsSave();
      close.focus();
    }

    updateDetailsSave() {
      const edit = this.edit; if (!edit) return;
      if (graded(edit.item)) {
        this.details.querySelector('[data-details-save]').disabled = this.editBusy || !edit.selected?.catalogue_id
          || !gradeValid({...edit.item, ...edit}) || edit.quantity !== 1;
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
      save.textContent = missingCondition ? "Choose condition to continue" : "Looks Good";
      this.details.querySelector(".dr-scan-detail-message").textContent = !usableRun(edit.item)
        ? "Retry this photo before confirming a match." : !allowedSealed ? "This sealed product needs identity review."
        : !edit.selected ? "Choose a match or search for the correct card."
        : !valid ? "Quantity must be a whole number from 1 to 50."
        : missingCondition ? "Select the card’s condition above, then confirm the match." : "";
    }

    async confirmDetails() {
      const edit = this.edit; if (!edit || this.editBusy || this.details.querySelector("[data-details-save]").disabled) return;
      if (!graded(edit.item) && !sealed({...edit.item, selected: edit.selected}) && !conditions.includes(edit.condition)) return;
      this.editBusy = true;
      this.details.querySelectorAll("button, input, select").forEach(control => { control.disabled = true; });
      try {
        if (!edit.selected.catalogue_id && edit.selected.reference_selection) {
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
        Object.assign(edit.item, {selected: edit.selected, quantity: edit.quantity, condition: edit.condition,
          searchSelected: edit.searchSelected, status: "matched", error: null,
          ...(graded(edit.item) ? {grading_company: edit.grading_company, grade: edit.grade, certificate_number: edit.certificate_number} : {})});
        this.editBusy = false; this.closeDetails(); this.render();
      } catch (error) {
        if (!this.active()) return;
        this.editBusy = false; this.renderDetails();
        this.details.querySelector(".dr-scan-detail-message").textContent = error.message;
      } finally { this.editBusy = false; }
    }

    remove(item) {
      if (!this.editable(item)) return;
      this.items = this.items.filter(row => row !== item);
      item.photo = null;
      this.closeDetails(); this.render();
    }

    openSearch() {
      if (!this.edit || this.editBusy) return;
      this.searchRevision += 1;
      this.details.replaceChildren();
      const header = node("header", "dr-scan-details-header");
      const title = node("h2", "", "Find your card"); title.id = "dr-scan-details-title";
      header.append(title, button("Back", () => { this.searchRevision += 1; clearTimeout(this.searchTimer); this.renderDetails(); }));
      const input = node("input", "dr-scan-search-input"); input.type = "search"; input.placeholder = "Card name or number";
      input.setAttribute("aria-label", "Search card name or number"); input.maxLength = 160;
      input.addEventListener("input", () => {
        clearTimeout(this.searchTimer); this.searchRevision += 1;
        const revision = this.searchRevision, query = input.value.trim();
        this.details.querySelector(".dr-scan-search-results").replaceChildren();
        this.details.querySelector(".dr-scan-search-message").textContent = query.length >= 2 ? "Searching…" : "Enter at least two characters.";
        if (query.length >= 2) this.searchTimer = setTimeout(() => this.search(query, revision), 260);
      });
      this.details.append(header, input, node("p", "dr-scan-search-message", "Search the exact card number to compare printings."), node("div", "dr-scan-search-results"));
      input.focus();
    }

    async search(query, revision) {
      const edit = this.edit;
      if (!edit || (!graded(edit.item) && !usableRun(edit.item))) { this.details.querySelector(".dr-scan-search-message").textContent = "Retry the scan first so the correction has completed recognition evidence."; return; }
      try {
        const params = new URLSearchParams({q: query, limit: "20"});
        if (this.options.role === "seller" && !graded(edit.item)) { params.set("include_reference", "true"); params.set("run_id", edit.item.run.id); }
        const data = await this.request((this.options.role === "seller" ? "/api/v1/owner/catalogue-search?" : "/api/v1/catalogue/search?") + params);
        if (this.edit !== edit || revision !== this.searchRevision) return;
        const results = this.details.querySelector(".dr-scan-search-results"); results.replaceChildren();
        const rows = (data.items || []).filter(row => row.product_type !== "SEALED");
        this.details.querySelector(".dr-scan-search-message").textContent = rows.length ? "" : "No results. Try the exact card number.";
        for (const row of rows) {
          const choice = button("", () => this.chooseSearch(row), "dr-scan-search-result");
          choice.append(this.thumb({selected: row}, "dr-scan-thumb", row));
          const copy = node("span"); copy.append(node("strong", "", row.name), node("small", "", meta({selected: row})));
          choice.append(copy); results.append(choice);
        }
      } catch (error) {
        if (this.active() && this.edit === edit && revision === this.searchRevision) this.details.querySelector(".dr-scan-search-message").textContent = error.message;
      }
    }

    async chooseSearch(row) {
      const edit = this.edit; if (!edit || this.editBusy) return;
      this.editBusy = true;
      this.details.querySelectorAll("button, input").forEach(control => { control.disabled = true; });
      try {
        let catalogueId = row.id;
        if (row.requires_materialization) {
          const data = await this.request("/api/v1/recognition/runs/" + edit.item.run.id + "/references/select", {
            method: "POST", body: JSON.stringify({provider: row.provider, system_code: row.system_code,
              language: row.language, provider_id: row.provider_id}),
          });
          catalogueId = data.catalogue_id;
        }
        if (!catalogueId) throw new Error("That reference could not be linked. Please choose another match.");
        if (!this.active()) return;
        edit.selected = {...row, catalogue_id: catalogueId, candidate_snapshot: {...row}, id: null,
          ...(graded(edit.item) ? {market_value_minor: null} : {})};
        edit.searchSelected = true; this.searchRevision += 1; this.editBusy = false; this.renderDetails();
      } catch (error) {
        if (!this.active()) return;
        this.editBusy = false; this.openSearch(); this.details.querySelector(".dr-scan-search-message").textContent = error.message;
      } finally { this.editBusy = false; }
    }

    freeze(item) {
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
      const physical = {condition: isSealed ? null : item.condition, seal_status: isSealed ? "SEALED" : null,
        grading_company: null, grade: null, certificate_number: null, language: card.language || null};
      const payload = this.options.role === "seller"
        ? {...physical, recognition_run_id: item.run.id, selected_catalogue_id: item.selected.catalogue_id}
        : {...physical, catalogue_id: item.selected.catalogue_id, identity_confirmed: false,
          notes: "Recognition run " + item.run.id + " · confirmed in scanner review"};
      item.requests = Array.from({length: item.quantity}, () => ({key: crypto.randomUUID(), body: JSON.stringify(payload), result: null}));
    }

    async saveAll() {
      if (this.saving || !this.active() || !this.items.length) return;
      if (this.items.every(item => item.status === "added")) { this.close(); this.options.viewInventory(); return; }
      if (this.items.some(item => !this.ready(item))) return;
      this.saving = true; this.items.forEach(item => this.freeze(item)); this.renderReview();
      const epoch = this.epoch;
      const message = this.find(".dr-scan-save-message");
      let added = 0, failed = 0, marketPending = 0;
      for (const item of this.items) {
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
            if (!data.inventory?.inventory_code) throw new Error("Save confirmation was incomplete. Retry to check this same request.");
            pending.result = data; added += 1;
            if (this.options.role === "seller" && sealed(item) && data.inventory.identity_confirmed && data.inventory.market_value_minor == null) {
              try {
                const market = await this.request("/api/v1/owner/inventory/" + encodeURIComponent(data.inventory.inventory_code) + "/refresh-market", {method: "POST", body: "{}"});
                if (market.valuation?.market_value_minor == null) marketPending += 1;
                else item.selected.market_value_minor = market.valuation.market_value_minor;
              } catch (_) { marketPending += 1; }
            }
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
        : added + " added to your inventory. " + (this.options.role === "founder" || this.items.some(item => item.requests.some(request => !request.result.inventory.identity_confirmed))
          ? "Identity review is still required before approval." : "Saved with verified identity.");
      if (marketPending) message.textContent += " Some market values are still pending.";
      try { await this.options.afterSave(); }
      catch (_) { if (this.active(epoch)) message.textContent += " Refresh inventory to see the latest totals."; }
    }
  }

  return {Scanner, isMobile: () => window.matchMedia("(max-width: 900px)").matches};
})();
