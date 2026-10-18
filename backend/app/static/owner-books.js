"use strict";
(() => {
  const conditions = ["Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor"];
  let dialog, requestKey, submittedPayload, actorId, saving = false, pending = false, saved = false;
  let photos = [], scanRevision = 0, scanning = false, scanController = null, priceRevision = 0;
  let reviewContext = null;
  let research = null, researchRunId = null, selectedResearch = null, coverRevision = 0;
  const coverUrls = new Set(), coverControllers = new Set();
  const bookMapping = {system_code:"category", series_title:"series", issue_number:"number", volume_identifier:"volume",
    publisher:"publisher", language:"language", release_year:"year", printing_number:"printing", cover_code:"cover",
    cover_artist:"artist", barcode_gtin:"barcode"};
  const node = id => document.getElementById(`owner-book-${id}`);
  const value = id => node(id).value.trim();
  const optional = id => value(id) || null;
  const integer = id => value(id) ? Number(value(id)) : null;

  function clearGradingDetails() {
    node("grade").value = "";
    node("certificate").value = "";
  }

  function update() {
    const manga = value("category") === "MANGA", graded = value("state") === "GRADED";
    const companies = manga ? ["CGC", "BGS"] : ["CGC"], grader = node("grader");
    if (Array.from(grader.options, option => option.value).join(",") !== companies.join(",")) {
      const previous = grader.value;
      grader.replaceChildren(...companies.map(company => new Option(company, company)));
      if (companies.includes(previous)) grader.value = previous;
      else clearGradingDetails();
    }
    const customPublisher = ["MANGA", "OTHER_COMICS"].includes(value("category"));
    node("number-text").textContent = manga ? "Volume number" : "Issue / book number";
    node("series").placeholder = manga ? "e.g. One Piece" : "e.g. The Amazing Spider-Man";
    node("publisher-label").hidden = !customPublisher;
    node("publisher").required = customPublisher;
    node("format-label").hidden = manga;
    node("format").required = !manga;
    node("condition-label").hidden = graded;
    node("grading-fields").hidden = !graded;
    if (graded) node("copy-details").open = true;
    for (const id of ["grader", "grade", "certificate"]) node(id).required = graded;
  }

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.id = "owner-book-dialog";
    dialog.className = "owner-import-dialog owner-book-dialog";
    dialog.setAttribute("aria-labelledby", "owner-book-title");
    dialog.innerHTML = `
      <div class="owner-import-dialog-header">
        <div><h2 id="owner-book-title">Add a comic or manga</h2><p>Scan the cover. We'll look up the details for you.</p></div>
        <button type="button" class="owner-import-close" id="owner-book-close" aria-label="Close add book">×</button>
      </div>
      <form id="owner-book-form" class="owner-import-dialog-body">
        <details id="owner-book-photo-details" class="owner-book-scanner" open>
          <summary>Add a cover, barcode or inside-page photo</summary>
          <h3>Scan your comic or manga</h3>
          <p>Start with the front cover. If we need another clue, add the barcode or the small copyright text inside. For graded books, include the label.</p>
          <div class="owner-book-photo-actions">
            <button type="button" id="owner-book-camera" class="owner-secondary-action">Take a photo</button>
            <button type="button" id="owner-book-gallery" class="owner-secondary-action">Choose photos</button>
          </div>
          <input type="file" id="owner-book-camera-file" accept="image/*" capture="environment" hidden>
          <input type="file" id="owner-book-gallery-file" accept="image/*" multiple hidden>
          <div id="owner-book-photos" class="owner-book-photos"></div>
          <button type="button" id="owner-book-recognize" class="owner-primary-action" disabled>Identify my book</button>
          <p id="owner-book-scan-message" role="status" aria-live="polite">Up to 3 photos of the same book. You confirm the details before saving.</p>
        </details>
        <section id="owner-book-research" class="owner-book-research" aria-label="Book identification" hidden>
          <h3>Is this your book?</h3>
          <p id="owner-book-research-message" role="status" aria-live="polite"></p>
          <div id="owner-book-candidates" class="owner-book-candidates"></div>
          <p id="owner-book-photo-help" class="owner-book-photo-help"></p>
        </section>
        <section id="owner-book-selected" class="owner-book-selected" hidden></section>
        <fieldset id="owner-book-fields">
          <legend class="owner-book-sr-only">Book and copy details</legend>
          <details id="owner-book-details" open><summary>Book details · edit if needed</summary>
          <div id="owner-book-identity" class="owner-import-fields">
            <label>Category<select id="owner-book-category" required><option value="">Choose category</option><option value="MARVEL_COMICS" selected>Marvel Comics</option><option value="DC_COMICS">DC Comics</option><option value="OTHER_COMICS">Other comics</option><option value="MANGA">Manga</option></select></label>
            <label>Series title<input id="owner-book-series" maxlength="140" required></label>
            <label><span id="owner-book-number-text">Issue / book number</span><input id="owner-book-number" maxlength="40" placeholder="e.g. 1, Annual 1 or Omnibus 1" required></label>
            <label>Series volume / edition <span>(optional)</span><input id="owner-book-volume" maxlength="40" placeholder="e.g. Vol. 2 or Deluxe edition"></label>
            <label id="owner-book-publisher-label" hidden>Publisher<input id="owner-book-publisher" maxlength="100" placeholder="e.g. VIZ Media, Kodansha or Image"></label>
            <label id="owner-book-format-label">Format<select id="owner-book-format"><option value="SINGLE_ISSUE">Single issue</option><option value="TRADE_PAPERBACK">Trade paperback / collection</option><option value="HARDCOVER">Hardcover / omnibus</option></select></label>
            <label>Language<input id="owner-book-language" maxlength="80" value="English" required list="owner-book-languages"></label>
            <label>Publication year <span>(optional)</span><input id="owner-book-year" type="number" min="1930" max="2200" step="1" inputmode="numeric"></label>
            <label>Printing number <span>(optional)</span><input id="owner-book-printing" type="number" min="1" max="999" step="1" inputmode="numeric" placeholder="Enter only if known"></label>
            <label>Cover / variant <span>(optional)</span><input id="owner-book-cover" maxlength="100" placeholder="e.g. Cover A, newsstand or virgin variant"></label>
            <label>Cover artist <span>(optional)</span><input id="owner-book-artist" maxlength="100"></label>
            <label>ISBN / barcode <span>(optional)</span><input id="owner-book-barcode" maxlength="40"></label>
          </div></details>
          <details id="owner-book-copy-details"><summary>Your copy (optional)</summary>
          <div class="owner-import-fields">
            <label>State<select id="owner-book-state"><option value="RAW">Ungraded</option><option value="GRADED">Graded</option></select></label>
            <label id="owner-book-condition-label">Condition<select id="owner-book-condition"><option value="">Not assessed yet</option>${conditions.map(c => `<option>${c}</option>`).join("")}</select></label>
          </div>
          <div id="owner-book-grading-fields" class="owner-import-fields" hidden>
            <label>Grading company<select id="owner-book-grader"><option value="CGC">CGC</option></select></label>
            <label>Grade<input id="owner-book-grade" type="number" min="0.5" max="10" step="0.1" inputmode="decimal" placeholder="e.g. 9.8"></label>
            <label>Certificate number<input id="owner-book-certificate" maxlength="120" autocomplete="off"></label>
          </div>
          <div class="owner-import-fields owner-book-costs">
            <label>Cost paid (£) <span>(optional)</span><input id="owner-book-cost" type="number" min="0" step="0.01" inputmode="decimal"></label>
            <input id="owner-book-price" type="hidden" value="">
          </div>
          <label class="owner-book-notes">Notes <span>(optional — signatures, label type, restoration or damage)</span><textarea id="owner-book-notes" rows="3" maxlength="2000"></textarea></label>
          </details>
        </fieldset>
        <section class="owner-book-market" aria-label="Book market value">
          <strong>Market value</strong><p id="owner-book-market-result" role="status">Complete the book and copy details to check matching sold evidence.</p>
          <button type="button" id="owner-book-market-check" class="owner-secondary-action">Check market value</button>
        </section>
        <p class="owner-book-explanation">Add confirms this is your book. You can add condition and cost later.</p>
        <p id="owner-book-message" role="status" aria-live="polite"></p>
        <div class="owner-book-actions"><button type="button" id="owner-book-cancel" class="owner-secondary-action">Cancel</button><button type="submit" id="owner-book-save" class="owner-primary-action">Add to collection</button></div>
      </form>
      <datalist id="owner-book-languages"><option value="English"><option value="Japanese"><option value="French"><option value="German"><option value="Spanish"><option value="Italian"></datalist>`;
    document.body.append(dialog);
    node("form").insertBefore(node("research"), node("form").firstElementChild);
    for (const id of ["category", "state"]) node(id).addEventListener("change", update);
    node("grader").addEventListener("change", clearGradingDetails);
    for (const id of ["close", "cancel"]) node(id).addEventListener("click", () => { if (!saving) { cancelScan(); dialog.close(); } });
    dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
    dialog.addEventListener("close", () => {
      if (dialog.open) return;
      cancelScan();
      const resume = reviewContext?.onClose;
      if (reviewContext) reviewContext.onClose = null;
      resume?.();
    });
    node("camera").addEventListener("click", () => node("camera-file").click());
    node("gallery").addEventListener("click", () => node("gallery-file").click());
    for (const id of ["camera-file", "gallery-file"]) node(id).addEventListener("change", addPhotos);
    node("recognize").addEventListener("click", recognize);
    node("market-check").addEventListener("click", checkMarket);
    node("fields").addEventListener("input", () => { priceRevision++; node("market-result").textContent = "Details changed. Check the value for this exact copy again."; });
    node("fields").addEventListener("change", () => { priceRevision++; node("market-result").textContent = "Details changed. Check the value for this exact copy again."; });
    node("form").addEventListener("submit", save);
    node("identity").addEventListener("input", () => { node("selected").hidden = true; });
    node("identity").addEventListener("change", () => { node("selected").hidden = true; });
    node("form").addEventListener("invalid", event => {
      if (node("identity").contains(event.target)) node("details").open = true;
      if (node("copy-details").contains(event.target)) node("copy-details").open = true;
    }, true);
    for (const type of ["input", "change"]) node("identity").addEventListener(type, () => {
      selectedResearch = null;
      node("candidates").querySelectorAll("[aria-pressed]").forEach(button => button.setAttribute("aria-pressed", "false"));
      node("research-message").textContent = "Details edited. Choose a cover again to keep its publisher artwork, or save your own details.";
    });
  }

  function clearCoverLoads() {
    coverRevision++;
    coverControllers.forEach(controller => controller.abort()); coverControllers.clear();
    coverUrls.forEach(url => URL.revokeObjectURL(url)); coverUrls.clear();
  }

  function fillBookFields(fields) {
    for (const [field, id] of Object.entries(bookMapping)) node(id).value = fields[field] ?? "";
    node("format").value = fields.book_format === "MANGA" ? "SINGLE_ISSUE" : fields.book_format || "";
    update();
  }

  function bookDetailsComplete() {
    return ["category", "series", "number", "language"].every(id => value(id))
      && (!["MANGA", "OTHER_COMICS"].includes(value("category")) || !!value("publisher"))
      && (value("category") === "MANGA" || !!value("format"));
  }

  function publisherLink(value) {
    try {
      const url = new URL(value);
      const paths = {"www.marvel.com":["/comics/issue/"],"www.dc.com":["/comics/","/graphic-novels/"],
        "www.viz.com":["/manga-books/manga/"],"kodansha.us":["/product/"],"sevenseasentertainment.com":["/books/"],
        "yenpress.com":["/titles/"],"imagecomics.com":["/comics/releases/"],"www.darkhorse.com":["/Comics/","/Books/"]};
      return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash
        && paths[url.host]?.some(path => url.pathname.startsWith(path)) ? url.href : null;
    } catch (_) { return null; }
  }

  async function loadCover(image, placeholder, path, revision, actor) {
    const controller = new AbortController(); coverControllers.add(controller);
    const active = () => revision === coverRevision && actor === actorId && actor === state.session?.user?.id && dialog.open && image.isConnected;
    try {
      if (!active()) return;
      const get = token => fetch(path, {headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
      let response = await get(state.session.access_token);
      if (response.status === 401 && active() && typeof refreshSession === "function") {
        const token = await refreshSession(); if (!active()) return; response = await get(token);
      }
      if (!response.ok) throw new Error("Cover unavailable");
      const blob = await response.blob();
      if (!active()) return;
      if (!/^image\/(png|jpeg|webp)$/.test(blob.type) || blob.size > 2_000_000) throw new Error("Invalid cover");
      const url = URL.createObjectURL(blob); coverUrls.add(url);
      image.onload = () => { if (active()) { image.hidden = false; placeholder.hidden = true; } };
      image.onerror = () => { if (active()) { image.hidden = true; placeholder.textContent = "Publisher cover could not load"; } };
      image.src = url;
    } catch (_) { if (active()) placeholder.textContent = "Publisher cover unavailable · open the source below"; }
    finally { coverControllers.delete(controller); }
  }

  function renderResearch() {
    clearCoverLoads(); node("candidates").replaceChildren();
    node("research").hidden = !research;
    if (!research) return;
    node("research-message").textContent = research.message || "Compare these publisher covers with your book.";
    const revision = coverRevision, actor = actorId;
    for (const candidate of (research.candidates || []).slice(0, 4)) {
      if (!/^[a-f0-9]{24}$/.test(candidate.id || "") || !candidate.fields) continue;
      const source = publisherLink(candidate.source_url); if (!source) continue;
      const card = document.createElement("article"); card.className = "owner-book-candidate";
      const art = document.createElement("div"); art.className = "owner-book-cover";
      const placeholder = document.createElement("span"); placeholder.textContent = "Publisher cover unavailable";
      const image = document.createElement("img"); image.hidden = true; image.alt = `${candidate.fields.series_title} publisher cover`;
      art.append(placeholder, image);
      const expected = `/api/v1/owner/books/research/${researchRunId}/cover/${candidate.id}`;
      if (/^[0-9a-f-]{36}$/i.test(researchRunId || "") && candidate.image_path === expected) {
        placeholder.textContent = "Loading publisher cover…";
        queueMicrotask(() => loadCover(image, placeholder, expected, revision, actor));
      }
      const details = document.createElement("div"); details.className = "owner-book-candidate-copy";
      const title = document.createElement("h4");
      const fields = candidate.fields;
      title.textContent = `${fields.series_title} ${fields.system_code === "MANGA" ? "Vol. " : "#"}${fields.issue_number}`;
      const meta = document.createElement("p"); meta.textContent = [fields.publisher,fields.release_year,fields.language].filter(Boolean).join(" · ");
      const edition = document.createElement("p"); edition.textContent = [fields.volume_identifier,fields.cover_code,
        fields.cover_artist,fields.printing_number ? `Printing ${fields.printing_number}` : "Printing not confirmed"].filter(Boolean).join(" · ");
      const why = document.createElement("p"); why.textContent = candidate.explanation || "Check that the cover matches your copy.";
      const link = document.createElement("a"); link.href = source; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = "Publisher record";
      const choose = document.createElement("button"); choose.type = "button"; choose.className = "owner-secondary-action";
      choose.textContent = selectedResearch === candidate.id ? "Selected cover" : candidate.image_path ? "This is my cover" : "Use these book details";
      choose.setAttribute("aria-pressed", String(selectedResearch === candidate.id));
      choose.disabled = pending || saved || saving;
      choose.addEventListener("click", () => {
        if (scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
        fillBookFields(candidate.fields); selectedResearch = candidate.id; node("details").open = !bookDetailsComplete();
        priceRevision++; node("market-result").textContent = "Book identified. Add your copy's condition or grade to check matching sales.";
        renderResearch();
      });
      details.append(title,meta,edition,why,link,choose); card.append(art,details); node("candidates").append(card);
    }
    node("photo-help").textContent = value("printing") ? "Check the cover, then add your copy below."
      : "Not sure which printing? Add a photo of the small copyright text inside the cover. You can also save it as unknown for now.";
  }

  function cancelScan() {
    scanRevision++; priceRevision++; scanning = false;
    scanController?.abort(); scanController = null;
    clearCoverLoads();
    if (dialog && !saving) { node("fields").disabled = pending; node("save").disabled = false; }
  }

  function scanActive(actor, revision) { return dialog.open && actorId === actor && state.session?.user?.id === actor && scanRevision === revision; }

  function clearIdentification() {
    // A new photo set or failed reread cannot keep the previous book's match.
    research = null; researchRunId = null; selectedResearch = null;
    renderResearch();
    node("selected").hidden = true; node("selected").replaceChildren();
    fillBookFields({});
    clearGradingDetails(); node("state").value = "RAW"; update();
    node("details").open = true; node("photo-details").open = true;
    node("title").textContent = "Identify your book";
    priceRevision++;
    node("market-result").textContent = "Identify this book to check its market value.";
  }

  function renderPhotos() {
    node("photos").replaceChildren();
    photos.forEach((photo, index) => {
      const figure = document.createElement("figure"), image = document.createElement("img"), remove = document.createElement("button");
      image.src = photo; image.alt = `Book photo ${index + 1}`;
      remove.type = "button"; remove.textContent = "Remove"; remove.disabled = scanning || pending || saved;
      remove.setAttribute("aria-label", `Remove book photo ${index + 1}`);
      remove.addEventListener("click", () => {
        if (scanning || saving || pending || saved) return;
        photos.splice(index, 1); scanRevision++; clearIdentification(); renderPhotos();
        node("scan-message").textContent = photos.length ? "Photos changed. Identify your book again." : "Add a cover photo to identify your book.";
      });
      figure.append(image, remove); node("photos").append(figure);
    });
    node("recognize").disabled = !photos.length || scanning || saving || pending || saved;
    for (const id of ["camera", "gallery"]) node(id).disabled = photos.length >= 3 || scanning || saving || pending || saved;
  }

  async function imageData(file) {
    if (!file.type.startsWith("image/") || file.size > 20_000_000) throw new Error("Choose an image smaller than 20 MB.");
    const url = URL.createObjectURL(file), image = new Image();
    try {
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error("This photo could not be opened. Try a JPEG or a new camera photo.")); image.src = url; });
      if (!image.naturalWidth || !image.naturalHeight) throw new Error("This photo could not be read.");
      const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL("image/jpeg", .86);
      if (data.length > 4_000_000) throw new Error("The photo is too large. Try a closer photo of the book.");
      return data;
    } finally { URL.revokeObjectURL(url); }
  }

  async function addPhotos(event) {
    const files = [...(event.target.files || [])]; event.target.value = "";
    if (scanning || saving || pending || saved) return;
    const actor = actorId, revision = ++scanRevision;
    try {
      for (const file of files.slice(0, 3 - photos.length)) {
        const data = await imageData(file);
        if (!scanActive(actor, revision)) return;
        photos.push(data);
        clearIdentification();
      }
      node("scan-message").textContent = "Photos ready. Identify my book will research the edition and matching artwork.";
    } catch (error) { if (scanActive(actor, revision)) node("scan-message").textContent = error.message; }
    if (scanActive(actor, revision)) renderPhotos();
  }

  function applySuggestion(result) {
    if (result.status !== "NEEDS_REVIEW") { clearIdentification(); node("scan-message").textContent = (result.warnings || ["No book could be read. Try a clearer photo."]).join(" "); return; }
    const fields = result.fields || {};
    fillBookFields(fields);
    const graded = !!fields.grading_company;
    node("state").value = graded ? "GRADED" : "RAW"; node("condition").value = ""; clearGradingDetails(); update();
    if (graded && [...node("grader").options].some(option => option.value === fields.grading_company.toUpperCase())) {
      node("grader").value = fields.grading_company.toUpperCase(); node("grade").value = fields.grade || ""; node("certificate").value = fields.certificate_number || "";
    }
    node("notes").value = fields.label_notes || "";
    node("cost").value = ""; node("price").value = "";
    const missing = (result.uncertain_fields || []).filter(field => ["system_code", "series_title", "issue_number", "language", "publisher", "printing_number"].includes(field)).map(field => field.replaceAll("_", " "));
    research = result.research || null; researchRunId = result.run_id || null;
    selectedResearch = research?.selected_candidate_id || null;
    node("title").textContent = "Is this your book?";
    node("scan-message").textContent = research ? "Cover read. Publisher research is shown above."
      : "Book details read — confirm them below." + (missing.length ? " Check: " + missing.join(", ") + "." : "") + " " + (result.warnings || []).join(" ");
    node("details").open = !research || !bookDetailsComplete();
    node("photo-details").open = !research?.candidates?.length;
    renderResearch();
    priceRevision++; node("market-result").textContent = "Confirm the printing and copy condition or grade, then check its market value.";
  }

  async function recognize() {
    if (!photos.length || scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
    const actor = actorId, revision = ++scanRevision;
    clearIdentification();
    scanning = true; scanController = new AbortController(); renderPhotos();
    node("fields").disabled = true; node("save").disabled = true;
    node("scan-message").textContent = "Reading your cover and researching its edition and artwork…";
    try {
      const result = await apiRequest("/api/v1/owner/books/recognize", {method:"POST", signal:scanController.signal, body:JSON.stringify({images:[...photos]})}, false);
      if (scanActive(actor, revision)) applySuggestion(result);
    } catch (error) { if (scanActive(actor, revision)) node("scan-message").textContent = error.message || "Book scanning failed. Your photos are kept for another attempt."; }
    finally { if (scanActive(actor, revision)) { scanning = false; scanController = null; node("fields").disabled = false; node("save").disabled = false; renderPhotos(); } }
  }

  async function checkMarket() {
    if (scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
    if (!node("form").reportValidity()) return;
    const actor = actorId, revision = ++priceRevision, body = JSON.stringify(payload());
    node("market-result").textContent = "Checking stored sales for this printing and condition…";
    try {
      const result = await apiRequest("/api/v1/owner/books/market-value", {method:"POST", body}, false);
      if (!dialog.open || actor !== actorId || actor !== state.session?.user?.id || revision !== priceRevision) return;
      node("market-result").textContent = result.market_value_minor == null
        ? result.reason || "No matching market value is available yet."
        : new Intl.NumberFormat("en-GB", {style:"currency",currency:"GBP"}).format(result.market_value_minor/100) + " · " + result.basis + " · UK sold reference";
    } catch (error) {
      if (dialog.open && actor === actorId && actor === state.session?.user?.id && revision === priceRevision) node("market-result").textContent = error.message || "Market value could not be checked.";
    }
  }

  function payload() {
    const graded = value("state") === "GRADED";
    return {
      ...(selectedResearch && researchRunId ? {research_run_id:researchRunId,research_candidate_id:selectedResearch} : {}),
      new_catalogue: {
        product_type: "COMIC", game: "Books", name: value("series"), set_name: value("series"), language: value("language"),
        comic_printing: {
          system_code: value("category"), series_title: value("series"), issue_number: value("number"),
          volume_identifier: optional("volume"), printing_number: integer("printing"), release_year: integer("year"),
          cover_code: optional("cover"), cover_artist: optional("artist"), barcode_gtin: optional("barcode"),
          publisher: optional("publisher"), book_format: value("category") === "MANGA" ? "MANGA" : value("format")
        }
      },
      condition: graded ? null : optional("condition"),
      grading_company: graded ? value("grader") : null,
      grade: graded ? value("grade") : null, certificate_number: graded ? value("certificate") : null,
      acquisition_cost_minor: value("cost") ? Math.round(Number(value("cost")) * 100) : null,
      store_price_minor: value("price") ? Math.round(Number(value("price")) * 100) : null,
      notes: value("notes"), language: value("language")
    };
  }

  async function save(event) {
    event.preventDefault();
    if (!actorId || state.session?.user?.id !== actorId) { dialog.close(); return; }
    if (saving || scanning || saved || !node("form").reportValidity()) return;
    const savingActor = actorId;
    const body = pending ? submittedPayload : JSON.stringify(payload());
    if (submittedPayload && body !== submittedPayload) requestKey = crypto.randomUUID();
    submittedPayload = body; saving = true;
    node("fields").disabled = true; node("save").disabled = true;
    node("message").textContent = "Saving your book…";
    try {
      const result = await apiRequest("/api/v1/owner/books/intake", {method: "POST", headers: {"Idempotency-Key": requestKey}, body});
      if (state.session?.user?.id !== savingActor) { dialog.close(); return; }
      pending = false; saved = true; renderPhotos();
      node("message").textContent = `${result.catalogue.name} added to your collection.`;
      node("save").textContent = "Added to collection";
      node("cancel").textContent = "Done";
      // The scanner only receives a receipt after explicit, successful book intake.
      // A presentation callback must never turn a committed save into a retry.
      try { reviewContext?.onSaved?.(result, JSON.parse(body)); } catch (_) { /* Inventory already saved. */ }
      if (reviewContext) reviewContext.onSaved = null;
      // A failed refresh must not turn a successful save into a second intake.
      await Promise.allSettled([loadOwnerInventory(), loadOwnerOverview()]);
    } catch (error) {
      if (state.session?.user?.id !== savingActor) { dialog.close(); return; }
      pending = ![400, 401, 403, 404, 409, 422].includes(error.status);
      node("message").textContent = pending
        ? "We couldn't confirm the save. Retry this same book to check it safely. Your details have been kept."
        : error.message || "Unable to save. Check your details and try again.";
      node("fields").disabled = pending; node("save").disabled = false;
      node("save").textContent = pending ? "Retry this book" : "Add to collection";
    } finally { saving = false; }
  }

  function open(options = {}) {
    ensureDialog();
    if (saving) return false;
    if (pending && actorId === state.session?.user?.id) {
      // Preserve the original payload, key and receipt callback even when a
      // different queued scan tries to open while the earlier save is uncertain.
      if (options.scanItemId && options.scanItemId !== reviewContext?.scanItemId)
        node("message").textContent = "Finish checking the previous book save before reviewing another book. Retry this same book safely.";
      reviewContext = {...reviewContext, onClose: options.onClose};
      dialog.showModal(); renderResearch(); return true;
    }
    actorId = state.session?.user?.id; pending = false; saved = false;
    reviewContext = {...options};
    cancelScan(); photos = [];
    research = null; researchRunId = null; selectedResearch = null; renderResearch(); node("details").open = true; node("photo-details").open = true;
    node("form").reset(); node("selected").hidden = true; node("selected").replaceChildren(); node("copy-details").open = false; requestKey = crypto.randomUUID(); submittedPayload = null;
    node("fields").disabled = false; node("save").disabled = false;
    node("save").textContent = "Add to collection"; node("cancel").textContent = "Cancel";
    node("message").textContent = "";
    node("scan-message").textContent = "Up to 3 photos of the same book. You confirm the details before saving.";
    node("market-result").textContent = "Complete the book and copy details to check matching sold evidence.";
    node("title").textContent = options.recognition ? "Confirm your book" : "Add a comic or manga";
    if (options.book) {
      const fields = options.book;
      const mapping = {system_code:"category", series_title:"series", issue_number:"number", volume_identifier:"volume",
        publisher:"publisher", language:"language", release_year:"year", printing_number:"printing", cover_code:"cover",
        cover_artist:"artist", barcode_gtin:"barcode"};
      for (const [field,id] of Object.entries(mapping)) node(id).value = fields[field] ?? "";
      node("format").value = fields.book_format === "MANGA" ? "SINGLE_ISSUE" : fields.book_format || "";
      node("condition").value = "";
      node("scan-message").textContent = "Check the cover and edition against your book.";
      if (options.catalogue) {
        const row = options.catalogue, preview = node("selected"); preview.hidden = false;
        const title = document.createElement("h3"); title.textContent = row.name || value("series");
        const caption = document.createElement("p"); caption.textContent = [value("language"),value("cover"),value("barcode")].filter(Boolean).join(" · ");
        const art = document.createElement("div"); art.className = "owner-book-cover";
        const placeholder = document.createElement("span"); placeholder.textContent = "Cover unavailable";
        const img = document.createElement("img"); img.hidden = true; img.alt = title.textContent + " reference cover";
        art.append(placeholder,img); preview.append(art,title,caption);
        const path = "/api/v1/catalogue-browser/reference-image?" + new URLSearchParams({provider:"Official Publisher",
          system_code:value("category"),language:value("language"),provider_id:row.catalogue_id,reference_kind:"book"});
        if (/^[0-9a-f-]{36}$/i.test(row.catalogue_id || "") && row.reference_image_path === path) {
          const revision = coverRevision, actor = actorId;
          queueMicrotask(() => loadCover(img,placeholder,path,revision,actor));
        }
        node("details").open = !bookDetailsComplete(); node("photo-details").open = false;
        node("title").textContent = "Is this your book?";
      }
    }
    if (options.recognition) {
      photos = (options.photos || []).slice(0, 3);
      // A failed read cannot silently inherit the manual form's defaults.
      for (const id of ["category", "language", "format"]) node(id).value = "";
      applySuggestion(options.recognition);
    }
    update(); renderPhotos(); dialog.showModal();
    (options.scan ? node("camera") : node("details").open ? node("category") : node("save")).focus({preventScroll:true});
    node("form").scrollTop = 0;
    return true;
  }
  window.DropRateBooks = {open, reset() { reviewContext = null; cancelScan(); photos = []; if (dialog) { dialog.close(); renderPhotos(); } }};
  document.querySelectorAll("[data-owner-add-book]").forEach(button => button.addEventListener("click", open));
})();
