"use strict";
(() => {
  const conditions = ["Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor"];
  let dialog, requestKey, submittedPayload, actorId, saving = false, pending = false;
  const node = id => document.getElementById(`owner-book-${id}`);
  const value = id => node(id).value.trim();
  const optional = id => value(id) || null;
  const integer = id => value(id) ? Number(value(id)) : null;

  function update() {
    const manga = value("category") === "MANGA", graded = value("state") === "GRADED";
    const customPublisher = ["MANGA", "OTHER_COMICS"].includes(value("category"));
    node("number-text").textContent = manga ? "Volume number" : "Issue / book number";
    node("series").placeholder = manga ? "e.g. One Piece" : "e.g. The Amazing Spider-Man";
    node("publisher-label").hidden = !customPublisher;
    node("publisher").required = customPublisher;
    node("format-label").hidden = manga;
    node("condition-label").hidden = graded;
    node("grading-fields").hidden = !graded;
    for (const id of ["grader", "grade", "certificate"]) node(id).required = graded;
    node("other-grader-label").hidden = !graded || value("grader") !== "OTHER";
    node("other-grader").required = graded && value("grader") === "OTHER";
  }

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.id = "owner-book-dialog";
    dialog.className = "owner-import-dialog owner-book-dialog";
    dialog.setAttribute("aria-labelledby", "owner-book-title");
    dialog.innerHTML = `
      <div class="owner-import-dialog-header">
        <div><h2 id="owner-book-title">Add a comic or manga</h2><p>Record the edition and the details of your copy.</p></div>
        <button type="button" class="owner-import-close" id="owner-book-close" aria-label="Close add book">×</button>
      </div>
      <form id="owner-book-form" class="owner-import-dialog-body">
        <fieldset id="owner-book-fields">
          <legend>Book details</legend>
          <div class="owner-import-fields">
            <label>Category<select id="owner-book-category"><option value="MARVEL_COMICS">Marvel Comics</option><option value="DC_COMICS">DC Comics</option><option value="OTHER_COMICS">Other comics</option><option value="MANGA">Manga</option></select></label>
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
          </div>
          <h3>Your copy</h3>
          <div class="owner-import-fields">
            <label>State<select id="owner-book-state"><option value="RAW">Ungraded</option><option value="GRADED">Graded</option></select></label>
            <label id="owner-book-condition-label">Condition<select id="owner-book-condition"><option value="">Not assessed yet</option>${conditions.map(c => `<option>${c}</option>`).join("")}</select></label>
          </div>
          <div id="owner-book-grading-fields" class="owner-import-fields" hidden>
            <label>Grading company<select id="owner-book-grader"><option value="CGC">CGC</option><option value="CBCS">CBCS</option><option value="PGX">PGX</option><option value="OTHER">Other grading company</option></select></label>
            <label id="owner-book-other-grader-label" hidden>Company name<input id="owner-book-other-grader" maxlength="40"></label>
            <label>Grade<input id="owner-book-grade" type="number" min="0.5" max="10" step="0.1" inputmode="decimal" placeholder="e.g. 9.8"></label>
            <label>Certificate number<input id="owner-book-certificate" maxlength="120" autocomplete="off"></label>
          </div>
          <div class="owner-import-fields owner-book-costs">
            <label>Cost paid (£) <span>(optional)</span><input id="owner-book-cost" type="number" min="0" step="0.01" inputmode="decimal"></label>
            <label>Your selling price (£) <span>(optional)</span><input id="owner-book-price" type="number" min="1" step="0.01" inputmode="decimal"></label>
          </div>
          <label class="owner-book-notes">Notes <span>(optional — signatures, label type, restoration or damage)</span><textarea id="owner-book-notes" rows="3" maxlength="2000"></textarea></label>
        </fieldset>
        <p class="owner-book-explanation">Saved to your collection as a draft. Selling is a separate step. Market value appears only when matching evidence is available; certificate details are recorded for review.</p>
        <p id="owner-book-message" role="status" aria-live="polite"></p>
        <div class="owner-book-actions"><button type="button" id="owner-book-cancel" class="owner-secondary-action">Cancel</button><button type="submit" id="owner-book-save" class="owner-primary-action">Add to my inventory</button></div>
      </form>
      <datalist id="owner-book-languages"><option value="English"><option value="Japanese"><option value="French"><option value="German"><option value="Spanish"><option value="Italian"></datalist>`;
    document.body.append(dialog);
    for (const id of ["category", "state", "grader"]) node(id).addEventListener("change", update);
    for (const id of ["close", "cancel"]) node(id).addEventListener("click", () => { if (!saving) dialog.close(); });
    dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
    node("form").addEventListener("submit", save);
  }

  function payload() {
    const graded = value("state") === "GRADED";
    return {
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
      grading_company: graded ? (value("grader") === "OTHER" ? value("other-grader") : value("grader")) : null,
      grade: graded ? value("grade") : null, certificate_number: graded ? value("certificate") : null,
      acquisition_cost_minor: value("cost") ? Math.round(Number(value("cost")) * 100) : null,
      store_price_minor: value("price") ? Math.round(Number(value("price")) * 100) : null,
      notes: value("notes"), language: value("language")
    };
  }

  async function save(event) {
    event.preventDefault();
    if (!actorId || state.session?.user?.id !== actorId) { dialog.close(); return; }
    if (saving || !node("form").reportValidity()) return;
    const savingActor = actorId;
    const body = pending ? submittedPayload : JSON.stringify(payload());
    if (submittedPayload && body !== submittedPayload) requestKey = crypto.randomUUID();
    submittedPayload = body; saving = true;
    node("fields").disabled = true; node("save").disabled = true;
    node("message").textContent = "Saving your book…";
    try {
      const result = await apiRequest("/api/v1/owner/books/intake", {method: "POST", headers: {"Idempotency-Key": requestKey}, body});
      if (state.session?.user?.id !== savingActor) { dialog.close(); return; }
      pending = false;
      node("message").textContent = `${result.catalogue.name} added to your collection as a draft.`;
      node("save").textContent = "Added to inventory";
      node("cancel").textContent = "Done";
      // A failed refresh must not turn a successful save into a second intake.
      await Promise.allSettled([loadOwnerInventory(), loadOwnerOverview()]);
    } catch (error) {
      if (state.session?.user?.id !== savingActor) { dialog.close(); return; }
      pending = ![400, 401, 403, 404, 409, 422].includes(error.status);
      node("message").textContent = pending
        ? "We couldn't confirm the save. Retry this same book to check it safely. Your details have been kept."
        : error.message || "Unable to save. Check your details and try again.";
      node("fields").disabled = pending; node("save").disabled = false;
      node("save").textContent = pending ? "Retry this book" : "Add to my inventory";
    } finally { saving = false; }
  }

  function open() {
    ensureDialog();
    if (pending && actorId === state.session?.user?.id) { dialog.showModal(); return; }
    actorId = state.session?.user?.id; pending = false;
    node("form").reset(); requestKey = crypto.randomUUID(); submittedPayload = null;
    node("fields").disabled = false; node("save").disabled = false;
    node("save").textContent = "Add to my inventory"; node("cancel").textContent = "Cancel";
    node("message").textContent = ""; update(); dialog.showModal(); node("category").focus();
  }
  window.DropRateBooks = {reset() { if (dialog) dialog.close(); }};
  document.querySelectorAll("[data-owner-add-book]").forEach(button => button.addEventListener("click", open));
})();
