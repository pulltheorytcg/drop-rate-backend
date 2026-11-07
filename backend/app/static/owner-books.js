"use strict";
(() => {
  const conditions = ["Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor"];
  let dialog, requestKey, submittedPayload, actorId, saving = false, pending = false, saved = false;
  let photos = [], scanRevision = 0, scanning = false, scanController = null, priceRevision = 0;
  let photoDrafts = [], photoSaving = false, photoResult = null, openRevision = 0;
  let marketTimer = null;
  let reviewContext = null;
  let savedReceipt = null;
  let identityEdited = false;
  let research = null, researchRunId = null, selectedResearch = null, coverRevision = 0, choosingCover = false;
  const coverUrls = new Set(), coverControllers = new Set(), coverCleanups = new Set();
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
          <button type="button" id="owner-book-recognize" class="owner-primary-action" disabled>Identify my book</button>
          <p id="owner-book-scan-message" role="status" aria-live="polite">Up to 3 photos of the same book. You confirm the details before saving.</p>
        </details>
        <section id="owner-book-research" class="owner-book-research" aria-label="Book identification" hidden>
          <div class="owner-book-research-heading"><h3 id="owner-book-research-title">Book reference</h3><button type="button" id="owner-book-change-cover" class="owner-secondary-action" aria-expanded="false" aria-controls="owner-book-candidates" hidden>Change cover</button></div>
          <p id="owner-book-research-message" role="status" aria-live="polite"></p>
          <div id="owner-book-candidates" class="owner-book-candidates"></div>
          <button type="button" id="owner-book-another-photo" class="owner-secondary-action" hidden>Try another photo</button>
          <p id="owner-book-photo-help" class="owner-book-photo-help"></p>
        </section>
        <section id="owner-book-selected" class="owner-book-selected" hidden></section>
        <section id="owner-book-photo-save" class="owner-book-photo-save" aria-label="Your copy photos" hidden>
          <h3>Your copy photos</h3>
          <p id="owner-book-photo-message" role="status" aria-live="polite"></p>
          <button type="button" id="owner-book-photo-retry" class="owner-secondary-action" hidden>Retry photo save</button>
          <p id="owner-book-photo-permission" class="dr-scan-photo-note">Adding this book also saves the selected photos of your own copy. You confirm you have permission to use them. Photos marked “Identification only” are not saved to your collection. Selling photos still need review.</p>
          <div id="owner-book-photos" class="owner-book-photos"></div>
          <div id="owner-book-photo-choices"></div>
        </section>
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
          <a id="owner-book-sold-search" class="owner-secondary-action" target="_blank" rel="noopener noreferrer" hidden>Compare sold listings</a>
        </section>
        <p class="owner-book-explanation">Add confirms this is your book. You can add condition and cost later.</p>
        <p id="owner-book-message" role="status" aria-live="polite"></p>
        <div class="owner-book-actions" id="owner-book-actions"><button type="button" id="owner-book-remove" class="owner-secondary-action" hidden>Remove scan</button><button type="button" id="owner-book-cancel" class="owner-secondary-action">Cancel</button><button type="submit" id="owner-book-save" class="owner-primary-action">Add to collection</button></div>
        <div class="owner-book-actions" id="owner-book-success" hidden><button type="button" id="owner-book-view-item" class="owner-primary-action">View item</button><button type="button" id="owner-book-add-another" class="owner-secondary-action">Add another</button></div>
      </form>
      <datalist id="owner-book-languages"><option value="English"><option value="Japanese"><option value="French"><option value="German"><option value="Spanish"><option value="Italian"></datalist>`;
    document.body.append(dialog);
    node("form").insertBefore(node("research"), node("form").firstElementChild);
    for (const id of ["category", "state"]) node(id).addEventListener("change", update);
    node("grader").addEventListener("change", clearGradingDetails);
    for (const id of ["close", "cancel"]) node(id).addEventListener("click", () => { if (!saving && !photoSaving) { cancelScan(); dialog.close(); } });
    node("view-item").addEventListener("click",()=>{
      if(!saved||saving||photoSaving||actorId!==state.session?.user?.id)return;
      const item=savedReceipt?.inventory||{};
      if(reviewContext)reviewContext.onClose=null;
      dialog.close();
      if(typeof activateOwnerView==="function")activateOwnerView("inventory");
      document.dispatchEvent(new CustomEvent("hub:inventory-open",{detail:{inventoryId:item.id||item.inventory_id,inventoryCode:item.inventory_code}}));
    });
    node("add-another").addEventListener("click",()=>{
      if(!saved||saving||photoSaving||actorId!==state.session?.user?.id)return;
      const next=reviewContext?.onAddAnother,scannerReturn=reviewContext?.onClose,category=value("category")==="MANGA"?"MANGA":"COMICS";
      dialog.close();if(next)next();else if(!scannerReturn)open({category});
    });
    node("remove").addEventListener("click", () => {
      if (saving || pending || saved || actorId !== state.session?.user?.id || !reviewContext?.onRemove) return;
      const remove = reviewContext.onRemove;
      cancelScan(); photos = []; remove(); dialog.close();
    });
    dialog.addEventListener("cancel", event => { if (saving || photoSaving) event.preventDefault(); });
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
    node("photo-retry").addEventListener("click", () => {
      if (!saved || saving || photoSaving || actorId !== state.session?.user?.id) return;
      void attachSavedPhotos(actorId, openRevision, true);
    });
    node("change-cover").addEventListener("click", () => {
      if (scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
      choosingCover = !choosingCover; renderResearch();
    });
    node("another-photo").addEventListener("click", () => {
      if (scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
      node("photo-details").open = true; node("camera").focus();
      node("scan-message").textContent = "Replace or add a photo, then identify your book again.";
    });
    node("market-check").addEventListener("click", () => checkMarket());
    node("fields").addEventListener("input", scheduleMarket);
    node("fields").addEventListener("change", scheduleMarket);
    node("form").addEventListener("submit", save);
    node("identity").addEventListener("input", () => { node("selected").hidden = true; });
    node("identity").addEventListener("change", () => { node("selected").hidden = true; });
    node("form").addEventListener("invalid", event => {
      if (node("identity").contains(event.target)) node("details").open = true;
      if (node("copy-details").contains(event.target)) node("copy-details").open = true;
      node("message").textContent = event.target === node("number")
        ? "Confirm the issue or volume number. You can choose the matching book details above, or enter it below."
        : "Check the highlighted detail before adding your book.";
    }, true);
    for (const type of ["input", "change"]) node("identity").addEventListener(type, () => {
      identityEdited = true;
      const hadSelection = !!selectedResearch;
      selectedResearch = null;
      choosingCover = true;
      if (hadSelection) renderResearch();
      node("research-message").textContent = "Details changed. Pick a matching cover below, or add with your edited details.";
    });
  }

  function clearCoverLoads() {
    coverRevision++;
    coverCleanups.forEach(cleanup => cleanup()); coverCleanups.clear();
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
      if (url.protocol === "https:" && url.host === "prhcomics.com" && url.pathname === "/book/"
          && !url.username && !url.password && !url.hash && /^\?isbn=(?:\d{13}|\d{17})$/.test(url.search)) return url.href;
      const paths = {"www.marvel.com":["/comics/issue/"],"www.dc.com":["/comics/","/graphic-novels/"],"www.dcuniverseinfinite.com":["/comics/book/"],
        "www.viz.com":["/manga-books/manga/"],"kodansha.us":["/product/"],"sevenseasentertainment.com":["/books/"],
        "yenpress.com":["/titles/"],"imagecomics.com":["/comics/releases/"],"www.darkhorse.com":["/Comics/","/Books/"]};
      return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash
        && paths[url.host]?.some(path => url.pathname.startsWith(path)) ? url.href : null;
    } catch (_) { return null; }
  }

  async function loadCover(image, placeholder, path, revision, actor, fallback) {
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
      image.onerror = () => { if (active()) { image.hidden = true; placeholder.textContent = "Publisher cover could not load"; fallback?.(); } };
      image.src = url;
    } catch (_) { if (active()) {placeholder.textContent = "Publisher cover unavailable · open the source below";fallback?.();} }
    finally { coverControllers.delete(controller); }
  }

  function renderResearch() {
    clearCoverLoads(); node("candidates").replaceChildren();
    node("research").hidden = !research;
    if (!research) return;
    const selected = (research.candidates || []).find(candidate => candidate.id === selectedResearch);
    node("research-title").textContent = selected ? "Selected book reference"
      : research.candidates?.length ? "Possible book matches" : "Publisher lookup";
    node("change-cover").hidden = !selected;
    node("change-cover").disabled = pending || saved || saving;
    node("change-cover").textContent = choosingCover ? "Keep selected cover" : "Change cover";
    node("change-cover").setAttribute("aria-expanded", String(choosingCover));
    node("another-photo").hidden = !choosingCover;
    node("another-photo").disabled = pending || saved || saving;
    node("research-message").textContent = selected && !choosingCover
      ? "Check this reference against your copy. You can change it if needed."
      : research.message || "Choose the cover that matches your book.";
    const revision = coverRevision, actor = actorId;
    const candidates = selected && !choosingCover ? [selected] : (research.candidates || []).slice(0, 4);
    for (const candidate of candidates) {
      if (!/^[a-f0-9]{24}$/.test(candidate.id || "") || !candidate.fields) continue;
      const source = publisherLink(candidate.source_url); if (!source) continue;
      const card = document.createElement("article"); card.className = "owner-book-candidate";
      card.classList.toggle("is-selected", candidate.id === selectedResearch);
      const art = document.createElement("div"); art.className = "owner-book-cover";
      const placeholder = document.createElement("span"); placeholder.textContent = "Publisher cover unavailable";
      const image = document.createElement("img"); image.hidden = true; image.alt = `${candidate.fields.series_title} publisher cover`;
      art.append(placeholder, image);
      const expected = `/api/v1/owner/books/research/${researchRunId}/cover/${candidate.id}`;
      if (/^[0-9a-f-]{36}$/i.test(researchRunId || "") && candidate.image_path === expected) {
        placeholder.textContent = "Loading publisher cover…";
        queueMicrotask(() => loadCover(image, placeholder, expected, revision, actor, () => {
          if (candidate.id === selectedResearch) renderReadSummary(candidate.fields, true);
        }));
      }
      const details = document.createElement("div"); details.className = "owner-book-candidate-copy";
      const title = document.createElement("h4");
      const fields = candidate.fields;
      title.textContent = `${fields.series_title} ${fields.system_code === "MANGA" ? "Vol. " : "#"}${fields.issue_number}`;
      const meta = document.createElement("p"); meta.textContent = [fields.publisher,fields.release_year,fields.language].filter(Boolean).join(" · ");
      const edition = document.createElement("p"); edition.textContent = [fields.volume_identifier,fields.cover_code,
        fields.cover_artist,fields.printing_number ? `Printing ${fields.printing_number}` : ""].filter(Boolean).join(" · ");
      edition.hidden = !edition.textContent;
      const why = document.createElement("p"); why.textContent = candidate.explanation || "Check that the cover matches your copy.";
      why.hidden = !!selected && !choosingCover;
      const link = document.createElement("a"); link.href = source; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = "Publisher record";
      const choose = document.createElement("button"); choose.type = "button"; choose.className = "owner-secondary-action";
      choose.textContent = selectedResearch === candidate.id ? "Keep this cover" : candidate.image_path ? "Use this cover" : "Use these book details";
      choose.hidden = !!selected && !choosingCover;
      choose.setAttribute("aria-pressed", String(selectedResearch === candidate.id));
      choose.disabled = pending || saved || saving;
      choose.addEventListener("click", () => {
        if (scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
        fillBookFields(candidate.fields); selectedResearch = candidate.id; choosingCover = false; identityEdited = true;
        node("details").open = !bookDetailsComplete(); node("message").textContent = "";
        node("photo-details").open = false;
        scheduleMarket();
        renderResearch();
        renderReadSummary(candidate.fields);
      });
      details.append(title,meta,edition,why,link,choose); card.append(art,details); node("candidates").append(card);
    }
    node("photo-help").textContent = value("printing") ? "Check the cover, then add your copy below."
      : "Not sure which printing? Add a photo of the small copyright text inside the cover. You can also save it as unknown for now.";
    node("photo-help").hidden = !!selected && !choosingCover;
  }

  function cancelScan() {
    scanRevision++; priceRevision++; scanning = false;
    scanController?.abort(); scanController = null;
    clearCoverLoads();
    if (dialog && !saving) { node("fields").disabled = pending || saved; node("save").disabled = saved || photoSaving; }
  }

  function scanActive(actor, revision) { return dialog.open && actorId === actor && state.session?.user?.id === actor && scanRevision === revision; }

  function clearIdentification() {
    // A new photo set or failed reread cannot keep the previous book's match.
    research = null; researchRunId = null; selectedResearch = null; choosingCover = false;
    renderResearch();
    node("selected").hidden = true; node("selected").replaceChildren();
    fillBookFields({});
    clearGradingDetails(); node("state").value = "RAW"; update();
    node("details").open = true; node("photo-details").open = true;
    node("title").textContent = "Identify your book";
    priceRevision++;
    clearTimeout(marketTimer); node("sold-search").hidden = true; node("sold-search").removeAttribute("href");
    node("market-result").textContent = "Identify this book to check its market value.";
  }

  function renderPhotos() {
    node("photos").replaceChildren();
    node("photo-choices").replaceChildren();
    node("photo-save").hidden = !photos.length;
    if (window.DropRateScanPhotos) photoDrafts = window.DropRateScanPhotos.sync(photos, photoDrafts);
    photos.forEach((photo, index) => {
      const figure = document.createElement("figure"), image = document.createElement("img"), remove = document.createElement("button");
      image.src = photo; image.alt = `Book photo ${index + 1}`;
      remove.className = "owner-secondary-action";
      remove.type = "button"; remove.textContent = "Remove"; remove.disabled = scanning || saving || photoSaving || pending || saved;
      remove.setAttribute("aria-label", `Remove book photo ${index + 1}`);
      remove.addEventListener("click", () => {
        if (scanning || saving || pending || saved) return;
        cancelScan(); photos.splice(index, 1); clearIdentification(); renderPhotos();
        node("scan-message").textContent = photos.length ? "Photos changed. Identify your book again." : "Add a cover photo to identify your book.";
      });
      figure.append(image, remove); node("photos").append(figure);
      if (photoDrafts[index] && window.DropRateScanPhotos) {
        node("photo-choices").append(window.DropRateScanPhotos.choice(photoDrafts[index], {
          number: index + 1, disabled: scanning || saving || photoSaving || pending || saved,
          onChange: () => { node("photo-message").textContent = ""; },
        }));
      }
    });
    node("recognize").disabled = !photos.length || scanning || saving || pending || saved;
    for (const id of ["camera", "gallery"]) node(id).disabled = photos.length >= 3 || scanning || saving || pending || saved;
    node("remove").hidden = !reviewContext?.onRemove || saved;
    node("remove").disabled = saving || pending;
    renderSaveControls();
  }

  function renderSaveControls() {
    const busy = saving || photoSaving;
    for (const id of ["close", "cancel", "view-item", "add-another", "photo-retry"]) node(id).disabled = busy;
    node("save").disabled = busy || scanning || saved;
    node("photo-retry").hidden = !saved || !photoResult || photoResult.complete;
  }

  function currentOpen(actor, revision) {
    return dialog.open && actor === actorId && actor === state.session?.user?.id && revision === openRevision;
  }

  async function attachSavedPhotos(actor, revision, retry = false) {
    if (!currentOpen(actor, revision)) return;
    const helper = window.DropRateScanPhotos;
    if (!helper?.selected(photoDrafts).length) return;
    photoSaving = true;
    node("message").textContent = "Book added. Saving your photos…";
    node("photo-message").textContent = "Saving the selected photos to this copy…";
    renderPhotos();
    try {
      // A retry reads the current version in case this copy was edited in the
      // meantime, keeping the original photograph and request key for an
      // uncertain upload receipt.
      const inventory = retry ? {...savedReceipt.inventory, version: undefined} : savedReceipt.inventory;
      const result = await helper.attach({request: apiRequest, inventory, drafts: photoDrafts,
        active: () => currentOpen(actor, revision)});
      if (!currentOpen(actor, revision)) return;
      photoResult = result;
    } catch (error) {
      if (!currentOpen(actor, revision)) return;
      photoResult = {complete: false, failed: [{message: error.message || "Photo save interrupted. Retry your photo."}]};
    } finally {
      if (currentOpen(actor, revision)) {
        photoSaving = false;
        if (photoResult?.complete) {
          node("message").textContent = `${savedReceipt.catalogue.name} added to your collection.`;
          node("photo-message").textContent = "Your selected photos are saved to this copy. Selling photos still need review.";
        } else {
          node("message").textContent = "Book added. Photo needs retry.";
          node("photo-message").textContent = "Book added. Photo needs retry. "
            + ((photoResult?.failed || []).map(failure => failure.message).join(" ")
              || "Your book is safely in your collection. Retry the photo save below.");
        }
        renderPhotos();
      }
    }
  }

  function renderReadSummary(fields, coverUnavailable = false) {
    const preview = node("selected"); preview.replaceChildren();
    const selected = research?.candidates?.find(candidate => candidate.id === selectedResearch);
    preview.hidden = !fields.series_title || (!coverUnavailable && !!selected?.image_path);
    if (preview.hidden) return;
    const art = document.createElement("div"); art.className = "owner-book-cover";
    if (photos[0]) {
      const img = document.createElement("img"); img.src = photos[0]; img.alt = "Your scanned cover"; art.append(img);
    }
    const title = document.createElement("h3");
    title.textContent = [fields.series_title, fields.issue_number ? (fields.system_code === "MANGA" ? "Vol. " : "#") + fields.issue_number : ""].filter(Boolean).join(" ");
    const caption = document.createElement("p");
    caption.textContent = [fields.publisher,fields.language,fields.release_year].filter(Boolean).join(" · ")
      + (photos[0] ? " · Your photo" : "")
      + (coverUnavailable ? " · Publisher cover unavailable" : "");
    preview.append(art,title,caption);
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
    cancelScan();
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
    identityEdited = false;
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
    choosingCover = false;
    node("title").textContent = "Add to collection";
    node("scan-message").textContent = research ? "Cover read. Publisher research is shown above."
      : "Book details read — confirm them below." + (missing.length ? " Check: " + missing.join(", ") + "." : "") + " " + (result.warnings || []).join(" ");
    node("details").open = !bookDetailsComplete();
    node("photo-details").open = !bookDetailsComplete() && !research?.candidates?.length;
    renderResearch();
    renderReadSummary(fields);
    scheduleMarket();
  }

  async function recognize() {
    if (!photos.length || scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
    cancelScan();
    const actor = actorId, revision = ++scanRevision;
    clearIdentification();
    scanning = true; scanController = new AbortController(); renderPhotos();
    node("fields").disabled = true; node("save").disabled = true;
    node("scan-message").textContent = "Reading your cover…";
    const controller = scanController, images = [...photos];
    const timeout = setTimeout(() => controller.abort(), 100000);
    try {
      const result = await apiRequest("/api/v1/owner/books/recognize", {method:"POST", signal:controller.signal, body:JSON.stringify({images, defer_research:true})}, false);
      if (!scanActive(actor, revision)) return;
      applySuggestion(result);
      scanning = false; node("fields").disabled = false; node("save").disabled = false; renderPhotos();
      if (["PENDING", "RUNNING"].includes(result.research?.status)) {
        const completed = await window.DropRateScanner.researchBook((url, options) => apiRequest(url, options, false), result, images, controller.signal);
        if (scanActive(actor, revision)) applyResearch(completed);
      }
    } catch (error) { if (scanActive(actor, revision) && !saving && !pending && !saved) {
      node("scan-message").textContent = error.message || "Book scanning failed. Your photos are kept for another attempt.";
      if (["PENDING", "RUNNING"].includes(research?.status)) {
        research = {status:"UNAVAILABLE", candidates:[], message:"Publisher lookup did not finish. Your book details are ready to review."};
        renderResearch();
      }
    } }
    finally { clearTimeout(timeout); if (scanActive(actor, revision)) { scanning = false; scanController = null;
      if (!saving && !pending && !saved) { node("fields").disabled = false; node("save").disabled = false; }
      renderPhotos(); } }
  }

  function applyResearch(result) {
    if (saving || pending || saved || researchRunId !== result.run_id) return;
    // Background metadata can fill identity blanks, but never undo the user's
    // edits, condition, quantity, notes, costs or an in-flight save payload.
    research = result.research || null;
    if (!identityEdited) {
      fillBookFields(result.fields || {}); selectedResearch = research?.selected_candidate_id || null;
      node("details").open = !bookDetailsComplete();
      renderReadSummary(result.fields || {});
    }
    renderResearch();
    node("scan-message").textContent = "Book details ready. Check the cover and add your copy below.";
    if (identityEdited) node("research-message").textContent = "Your edited details are kept. Choose a publisher cover to use its details.";
    scheduleMarket();
  }

  function scheduleMarket() {
    priceRevision++; clearTimeout(marketTimer);
    const link = node("sold-search");
    link.hidden = !value("series") || !value("number");
    if (!link.hidden) {
      const query = [value("series"), value("category") === "MANGA" ? "Vol" : "Issue", value("number"),
        value("publisher"), value("language"), value("year"), value("cover"),
        value("printing") ? `printing ${value("printing")}` : "", value("condition"),
        value("state") === "GRADED" ? `${value("grader")} ${value("grade")}` : ""].filter(Boolean).join(" ");
      link.href = "https://www.ebay.co.uk/sch/i.html?" + new URLSearchParams({_nkw:query,LH_Sold:"1",LH_Complete:"1"});
    } else link.removeAttribute("href");
    node("market-result").textContent = bookDetailsComplete()
      ? "Checking available market value…" : "Identify the book to check its market value.";
    if (bookDetailsComplete()) marketTimer = setTimeout(() => checkMarket(true), 350);
  }

  async function checkMarket(automatic = false) {
    clearTimeout(marketTimer);
    if (!dialog.open || scanning || saving || pending || saved || actorId !== state.session?.user?.id) return;
    if (!(automatic ? node("form").checkValidity() : node("form").reportValidity())) return;
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
    if (saving || photoSaving || scanning || saved || !node("form").reportValidity()) return;
    try {
      if (photos.length && !window.DropRateScanPhotos) throw new Error("Refresh the app before saving this book with photos. Your book has not been added yet.");
      window.DropRateScanPhotos?.validate(photoDrafts);
    } catch (error) {
      node("message").textContent = error.message;
      node("photo-message").textContent = error.message;
      return;
    }
    const savingActor = actorId, revision = openRevision;
    const body = pending ? submittedPayload : JSON.stringify(payload());
    if (submittedPayload && body !== submittedPayload) requestKey = crypto.randomUUID();
    submittedPayload = body; saving = true;
    node("research").querySelectorAll("button").forEach(button => { button.disabled = true; });
    reviewContext?.onSaveState?.(true);
    node("remove").disabled = true;
    node("fields").disabled = true; node("save").disabled = true;
    node("message").textContent = "Saving your book…";
    renderPhotos();
    try {
      let result;
      try {
        result = await apiRequest("/api/v1/owner/books/intake", {method: "POST", headers: {"Idempotency-Key": requestKey}, body});
      } catch (error) {
        if (!currentOpen(savingActor, revision)) return;
        pending = ![400, 401, 403, 404, 409, 422].includes(error.status);
        node("message").textContent = pending
          ? "We couldn't confirm the save. Retry this same book to check it safely. Your details have been kept."
          : error.message || "Unable to save. Check your details and try again.";
        node("fields").disabled = pending;
        node("save").textContent = pending ? "Retry this book" : "Add to collection";
        return;
      }
      if (!currentOpen(savingActor, revision)) return;
      // Intake is committed. All later photo work is a separate, recoverable
      // operation and must never re-enable or repeat this book's intake.
      pending = false; saved = true;
      savedReceipt=result;
      node("message").textContent = `${result.catalogue.name} added to your collection.`;
      node("save").textContent = "Added to collection";
      node("cancel").textContent = "Done";
      node("title").textContent="Added to your collection";
      node("details").open=false;node("copy-details").open=false;node("photo-details").open=false;
      node("actions").hidden=true;node("success").hidden=false;
      renderPhotos();
      await attachSavedPhotos(savingActor, revision);
      if (!currentOpen(savingActor, revision)) return;
      // The scanner only receives a receipt after explicit, successful book intake.
      // A presentation callback must never turn a committed save into a retry.
      const onSaved = reviewContext?.onSaved;
      if (reviewContext) reviewContext.onSaved = null;
      try { onSaved?.(result, JSON.parse(body), {run_id:researchRunId,research,photos:[...photos],photoResult}); } catch (_) { /* Inventory already saved. */ }
      // A failed refresh must not turn a successful save into a second intake.
      await Promise.allSettled([Promise.resolve().then(() => loadOwnerInventory()), Promise.resolve().then(() => loadOwnerOverview())]);
    } finally {
      if (currentOpen(savingActor, revision)) {
        saving = false;
        node("research").querySelectorAll("button").forEach(button => { button.disabled = pending || saved; });
        reviewContext?.onSaveState?.(pending);
        node("remove").disabled = pending || saved;
        renderPhotos();
      }
    }
  }

  function open(options = {}) {
    ensureDialog();
    if (saving || photoSaving) return false;
    if (pending && actorId === state.session?.user?.id) {
      // Preserve the original payload, key and receipt callback even when a
      // different queued scan tries to open while the earlier save is uncertain.
      if (options.scanItemId && options.scanItemId !== reviewContext?.scanItemId)
        node("message").textContent = "Finish checking the previous book save before reviewing another book. Retry this same book safely.";
      reviewContext = {...reviewContext, onClose: options.onClose};
      dialog.showModal(); renderResearch(); return true;
    }
    openRevision++;
    actorId = state.session?.user?.id; pending = false; saved = false;savedReceipt=null;
    photoDrafts = []; photoResult = null; photoSaving = false;
    identityEdited = false;
    reviewContext = {...options};
    cancelScan(); photos = [];
    research = null; researchRunId = null; selectedResearch = null; choosingCover = false; renderResearch(); node("details").open = true; node("photo-details").open = true;
    node("form").reset(); node("selected").hidden = true; node("selected").replaceChildren(); node("copy-details").open = false; requestKey = crypto.randomUUID(); submittedPayload = null;
    // A category-only entry is navigation context, not an identified book.
    // Keep exact catalogue/recognition fields authoritative when supplied.
    if (!options.book && options.category === "MANGA") node("category").value = "MANGA";
    else if (!options.book && options.category === "COMICS") node("category").value = "";
    if(!options.book&&typeof options.query==="string")node("series").value=options.query.slice(0,140);
    node("actions").hidden=false;node("success").hidden=true;
    node("fields").disabled = false; node("save").disabled = false;
    node("save").textContent = "Add to collection"; node("cancel").textContent = "Cancel";
    node("message").textContent = "";
    node("photo-message").textContent = "";
    node("scan-message").textContent = "Up to 3 photos of the same book. You confirm the details before saving.";
    node("market-result").textContent = "Complete the book and copy details to check matching sold evidence.";
    node("title").textContent = options.recognition ? "Confirm your book" : options.category === "MANGA" ? "Add manga" : options.category === "COMICS" ? "Add a comic" : "Add a comic or manga";
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
        // Reuse only the fresh authenticated catalogue context already shown.
        // Selecting a book never starts another listing lookup or copies the
        // seller's condition, binding, asking price or printing into this form.
        const revision = coverRevision, actor = actorId;
        const active = () => revision === coverRevision && actor === actorId && actor === state.session?.user?.id
          && dialog.open && preview.isConnected && !preview.hidden && !identityEdited;
        const listingContext = window.DropRateBookEbay?.context(row), tried = new Set();
        let listingImage = null, listingNote = null, communityNote = null, expiryTimer = null;
        const clearListing = () => { listingImage?.remove(); listingImage = null; listingNote?.remove(); listingNote = null; clearTimeout(expiryTimer); };
        coverCleanups.add(clearListing);
        const listingFallback = () => {
          if (!active()) return;
          const item = window.DropRateBookEbay?.photos(row, listingContext).find(item => !tried.has(item.item_id));
          if (!item) return;
          tried.add(item.item_id); clearListing(); img.remove();
          const photo = document.createElement("img"); listingImage = photo;
          photo.alt = title.textContent + " eBay listing photo; copy may vary";
          photo.loading = "lazy"; photo.decoding = "async"; photo.referrerPolicy = "no-referrer"; photo.crossOrigin = "anonymous";
          photo.addEventListener("load", () => {
            if (!active() || listingImage !== photo || !window.DropRateBookEbay?.validate(row, listingContext)) { photo.remove(); return; }
            placeholder.hidden = true; if (communityNote) communityNote.hidden = true;
            listingNote = window.DropRateBookEbay.photoCredit(item); preview.append(listingNote);
          });
          photo.addEventListener("error", () => { if (active() && listingImage === photo) {clearListing();placeholder.hidden = false;listingFallback();} });
          placeholder.hidden = false; art.append(photo); photo.src = item.image_url;
          expiryTimer = setTimeout(() => {clearListing();if (active()) {placeholder.hidden = false;placeholder.textContent = "Cover unavailable";}},
            Math.max(1, Date.parse(listingContext.expires_at) - Date.now()));
        };
        const path = "/api/v1/catalogue-browser/reference-image?" + new URLSearchParams({provider:"Official Publisher",
          system_code:value("category"),language:value("language"),provider_id:row.catalogue_id,reference_kind:"book"});
        if (/^[0-9a-f-]{36}$/i.test(row.catalogue_id || "") && row.reference_image_path === path) {
          queueMicrotask(() => loadCover(img,placeholder,path,revision,actor,listingFallback));
        } else {
          const community = window.DropRateBookArtwork?.reference(row, true);
          if (community) {
            img.alt = title.textContent + " community cover reference; cover may vary";
            img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
            img.addEventListener("load", () => {img.hidden = false; placeholder.hidden = true;}, {once:true});
            img.addEventListener("error", () => {img.remove(); placeholder.hidden = false;listingFallback();}, {once:true});
            img.hidden = false; img.src = community.image_url;
            communityNote = window.DropRateBookArtwork.credit(community); preview.append(communityNote);
          } else queueMicrotask(listingFallback);
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
    update(); renderPhotos(); dialog.showModal(); scheduleMarket();
    (options.scan ? node("camera") : node("details").open ? node("category") : node("save")).focus({preventScroll:true});
    node("form").scrollTop = 0;
    return true;
  }
  window.DropRateBooks = {open, updateScan(id, result) {
    if (dialog?.open && reviewContext?.scanItemId === id && actorId === state.session?.user?.id) applyResearch(result);
  }, reset() {
    openRevision++; reviewContext = null; saving = false; pending = false; saved = false; savedReceipt = null;
    photoSaving = false; photoResult = null; photoDrafts = []; actorId = null;
    cancelScan(); photos = []; if (dialog) { dialog.close(); renderPhotos(); }
  }};
  document.querySelectorAll("[data-owner-add-book]").forEach(button => button.addEventListener("click", open));
})();
