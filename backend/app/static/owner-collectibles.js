"use strict";
(() => {
  const sportsFields = [
    ["sport", "Sport", 60, true, "e.g. Basketball"],
    ["release_year", "Release year", 4, true, "e.g. 2024", "number"],
    ["manufacturer", "Manufacturer", 80, true, "e.g. Topps or Panini"],
    ["set_name", "Set", 100, true, "Name printed on the card or packaging"],
    ["subject_name", "Player / subject", 140, true, "Name on the card"],
    ["card_number", "Card number", 80, true, "e.g. 23 or RC-12"],
    ["parallel", "Parallel / variation", 100, true, "Enter Base only if it is the base card"],
    ["language", "Language", 80, true, "e.g. English"],
  ];
  const sportsOptional = [
    ["league", "League", 80], ["season", "Season", 30, false, "e.g. 2023–24"],
    ["team", "Team", 80], ["print_run", "Number produced", 7, false, "For /99, enter 99", "number"],
  ];
  const figureFields = [
    ["manufacturer", "Manufacturer", 80, true, "Name on the figure or packaging"],
    ["franchise", "Franchise", 120, true, "e.g. Star Wars"],
    ["character", "Character / figure name", 140, true, "Exact figure name"],
    ["product_line", "Product line", 100, true, "e.g. Black Series"],
    ["edition", "Edition / variant", 100, true, "Colour, version or exclusive edition"],
  ];
  const figureOptional = [
    ["scale", "Scale / size", 30, false, "e.g. 1:6 or 6 inch"],
    ["release_year", "Release year", 4, false, "Enter only if known", "number"],
    ["manufacturer_sku", "Manufacturer product code", 80],
    ["barcode_gtin", "Barcode / GTIN", 40, false, "8, 12, 13 or 14 digits"],
  ];
  const cardConditions = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
  const figureConditions = ["New", "Like New", "Very Good", "Good", "Fair", "Damaged"];
  let dialog, actor, category = "sports", catalogue = null, reference = null, options = {}, requestKey, submittedBody;
  let saving = false, pending = false, saved = false, receipt = null, generation = 0;
  const node = id => document.getElementById(`owner-collectible-${id}`);
  const value = id => node(id).value.trim();
  const currentActor = () => typeof state !== "undefined" ? state.session?.user?.id : null;
  const seller = () => Boolean(document.getElementById("owner-view-scan"));
  const optional = id => value(id) || null;
  const labels = () => category === "sports" ? {one: "sports card", title: "Add a sports card"} : {one: "figure", title: "Add a figure"};
  const canonicalId = row => {
    if(!row||typeof row!=="object"||row.metadata_only===true||row.source_kind==="REFERENCE")return null;
    const id=Object.hasOwn(row,"catalogue_id")?row.catalogue_id:row.id;
    return typeof id==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)?id:null;
  };
  const sourceLink = value => {
    if(typeof value!=="string"||value.length>2048||/[\s\\\u0000-\u001f\u007f]/.test(value))return null;
    try {
      const url=new URL(value),host=url.hostname.toLowerCase().replace(/\.$/,"");
      if(url.protocol!=="https:"||url.username||url.password||url.port||!host.includes(".")||host.includes(":")||
        /^[0-9.]+$/.test(host)||host.endsWith(".localhost")||host.endsWith(".local")||host.endsWith(".internal")||host.endsWith(".home.arpa"))return null;
      return url.href;
    }catch(_){return null;}
  };

  function showProvenance(row) {
    const target=node("reference-provenance"),source=row?.source_attribution;
    target.replaceChildren();
    if(!source||typeof source!=="object"||Array.isArray(source))return;
    const label=typeof source.label==="string"?source.label.trim().slice(0,160):"";
    const href=sourceLink(source.url);
    if(label){
      const credit=document.createElement("p");credit.textContent="Metadata source: ";
      if(href){const link=document.createElement("a");link.textContent=label;link.href=href;link.target="_blank";link.rel="noopener noreferrer";credit.append(link);}
      else credit.append(document.createTextNode(label));
      target.append(credit);
    }
    if(typeof source.coverage==="string"&&source.coverage.trim()){
      const coverage=document.createElement("p");coverage.textContent=source.coverage.trim().slice(0,1000);target.append(coverage);
    }
    if(source.notice_url==="/assets/catalogue-source-notices.txt"){
      const notice=document.createElement("a");notice.textContent="Source notices and coverage";notice.href=source.notice_url;
      notice.target="_blank";notice.rel="noopener noreferrer";target.append(notice);
    }
  }

  function prefillReference(row) {
    const details=category==="sports"?row.sports_card:row.figure_details;
    if(!details||typeof details!=="object"||Array.isArray(details)||
      (details.system_code&&details.system_code!==(category==="sports"?"SPORTS_CARDS":"FIGURES")))return;
    const definitions=category==="sports"?[...sportsFields,...sportsOptional]:[...figureFields,...figureOptional];
    // Field definitions are the only accepted input keys; never copy ownership,
    // value, condition or arbitrary source fields into the physical-item form.
    for(const [key,,max,,,type] of definitions){
      const supplied=details[key];
      if(type==="number"){
        const minimum=key==="print_run"?1:1800,maximum=key==="print_run"?1000000:2200;
        if(Number.isSafeInteger(supplied)&&supplied>=minimum&&supplied<=maximum)node(`${category}-${key}`).value=String(supplied);
      }else if(typeof supplied==="string"&&supplied.trim()&&supplied.trim().length<=max&&
        !/[\u0000-\u001f\u007f]/.test(supplied)&&!["unknown","not stated","n/a"].includes(supplied.trim().toLowerCase())){
        node(`${category}-${key}`).value=supplied.trim();
      }
    }
  }

  function fields(kind, definitions) {
    return definitions.map(([key, label, max, required, placeholder, type = "text"]) => {
      const range = type === "number" ? ` min="${key === "print_run" ? 1 : 1800}" max="${key === "print_run" ? 1000000 : 2200}" step="1" inputmode="numeric"` : ` maxlength="${max}"`;
      return `<label>${label}${required ? "" : " <span>(optional)</span>"}<input id="owner-collectible-${kind}-${key}" type="${type}"${range}${required ? " required" : ""}${placeholder ? ` placeholder="${placeholder}"` : ""}></label>`;
    }).join("");
  }

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.id = "owner-collectible-dialog";
    dialog.className = "owner-collectible-dialog";
    dialog.setAttribute("aria-labelledby", "owner-collectible-title");
    dialog.innerHTML = `
      <header class="owner-collectible-header"><div><p class="owner-collectible-eyebrow">Your collection</p><h2 id="owner-collectible-title">Add a collectible</h2><p id="owner-collectible-intro">Enter the exact details from your item.</p></div><button id="owner-collectible-close" class="owner-collectible-close" type="button" aria-label="Close add collectible">×</button></header>
      <form id="owner-collectible-form">
        <fieldset id="owner-collectible-fields">
          <legend class="owner-collectible-sr-only">Collectible and copy details</legend>
          <label class="owner-collectible-category" id="owner-collectible-category-label">Category<select id="owner-collectible-category"><option value="sports">Sports Cards</option><option value="figures">Figures</option></select></label>
          <section id="owner-collectible-reference" class="owner-collectible-reference" hidden><p class="owner-collectible-eyebrow">Selected reference</p><h3 id="owner-collectible-reference-name"></h3><p id="owner-collectible-reference-details"></p><p id="owner-collectible-reference-review">Check the edition against your item before adding it.</p><div id="owner-collectible-reference-provenance"></div></section>
          <fieldset id="owner-collectible-sports"><legend>Card details</legend><div class="owner-collectible-grid">${fields("sports", sportsFields)}</div><details class="owner-collectible-details"><summary>More printing details <span>(optional)</span></summary><div class="owner-collectible-grid">${fields("sports", sportsOptional)}</div><p class="owner-collectible-hint">The numbered print run describes the edition. Add your copy’s individual serial number below.</p></details></fieldset>
          <fieldset id="owner-collectible-figures" hidden disabled><legend>Figure details</legend><div class="owner-collectible-grid">${fields("figures", figureFields)}</div><details class="owner-collectible-details"><summary>More edition details <span>(optional)</span></summary><div class="owner-collectible-grid">${fields("figures", figureOptional)}</div></details></fieldset>
          <details id="owner-collectible-copy" class="owner-collectible-details"><summary>Your copy <span>(optional)</span></summary><div class="owner-collectible-grid">
            <label id="owner-collectible-state-label">State<select id="owner-collectible-state"><option value="RAW">Ungraded</option><option value="GRADED">Graded</option></select></label>
            <label id="owner-collectible-condition-label">Condition<select id="owner-collectible-condition"></select></label>
            <label id="owner-collectible-seal-label" hidden>Packaging<select id="owner-collectible-seal"><option value="">Not assessed yet</option><option value="SEALED">Factory sealed</option><option value="UNSEALED">Opened / unboxed</option></select></label>
          </div><fieldset id="owner-collectible-grading" hidden disabled><legend class="owner-collectible-sr-only">Grading details</legend><div class="owner-collectible-grid">
            <label>Grading company<input id="owner-collectible-grader" maxlength="40" placeholder="Name on the label" required></label><label>Grade<input id="owner-collectible-grade" maxlength="40" placeholder="Grade on the label" required></label><label>Certificate number<input id="owner-collectible-certificate" maxlength="120" autocomplete="off" required></label>
          </div></fieldset><div class="owner-collectible-grid">
            <label>Serial number on this copy <span>(optional)</span><input id="owner-collectible-serial" maxlength="80" placeholder="e.g. 12/99"></label><label>Cost paid (£) <span>(optional)</span><input id="owner-collectible-cost" type="number" min="0" step="0.01" inputmode="decimal"></label><label>Date acquired <span>(optional)</span><input id="owner-collectible-date" type="date"></label>
          </div><label class="owner-collectible-notes">Copy notes <span>(optional — packaging, accessories or damage)</span><textarea id="owner-collectible-notes" rows="3" maxlength="1900"></textarea></label></details>
        </fieldset>
        <p id="owner-collectible-explanation" class="owner-collectible-hint">This adds your item to your collection. You can add photos, assess its condition and choose to sell later.</p>
        <p id="owner-collectible-message" role="status" aria-live="polite" tabindex="-1"></p>
        <footer class="owner-collectible-actions" id="owner-collectible-actions"><button id="owner-collectible-cancel" type="button" class="owner-secondary-action">Cancel</button><button id="owner-collectible-save" type="submit" class="owner-primary-action">Add to collection</button></footer>
        <footer class="owner-collectible-actions" id="owner-collectible-success" hidden><button id="owner-collectible-add-another" type="button" class="owner-secondary-action">Add another</button><button id="owner-collectible-view" type="button" class="owner-primary-action">View item</button></footer>
      </form>`;
    document.body.append(dialog);
    node("category").addEventListener("change", () => { category = value("category"); updateCategory(); });
    node("state").addEventListener("change", updateCopy);
    node("figures-barcode_gtin").setAttribute("inputmode", "numeric");
    node("figures-barcode_gtin").addEventListener("input", validateBarcode);
    node("form").addEventListener("submit", save);
    node("form").addEventListener("invalid", event => {
      for (let parent = event.target.parentElement; parent && parent !== dialog; parent = parent.parentElement) {
        if (parent.tagName === "DETAILS") parent.open = true;
      }
    }, true);
    for (const id of ["cancel", "close"]) node(id).addEventListener("click", () => { if (!saving) dialog.close(); });
    dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
    node("add-another").addEventListener("click", () => {
      if (!saved || actor !== currentActor()) return;
      const callback = options.onAddAnother, nextCategory = category;
      dialog.close();
      if (typeof callback === "function") callback(); else open({category: nextCategory});
    });
    node("view").addEventListener("click", () => {
      if (!saved || actor !== currentActor()) return;
      const item = receipt?.inventory || {};
      dialog.close();
      if (seller() && typeof activateOwnerView === "function") activateOwnerView("inventory");
      else if (typeof activateSellerView === "function") activateSellerView("inventory", true);
      document.dispatchEvent(new CustomEvent("hub:inventory-open", {detail: {inventoryId: item.id || item.inventory_id, inventoryCode: item.inventory_code}}));
    });
    dialog.addEventListener("close", () => {
      if (dialog.open) return;
      const callback = options.onClose;
      options.onClose = null;
      if (typeof callback === "function") callback();
    });
  }

  function updateCopy() {
    const sports = category === "sports", graded = sports && value("state") === "GRADED";
    node("state-label").hidden = !sports;
    node("state").disabled = !sports;
    node("condition-label").hidden = graded;
    node("condition").disabled = graded;
    node("seal-label").hidden = sports;
    node("seal").disabled = sports;
    node("grading").hidden = !graded;
    node("grading").disabled = !graded;
  }

  function validateBarcode() {
    const input = node("figures-barcode_gtin"), barcode = input.value.replace(/[\s-]/g, "");
    const valid = !input.value.trim() || /^(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})$/.test(barcode);
    input.setCustomValidity(valid ? "" : "Enter an 8, 12, 13 or 14 digit barcode, or leave this optional field blank.");
  }

  function updateCategory() {
    const sports = category === "sports";
    for (const kind of ["sports", "figures"]) {
      node(kind).hidden = !!catalogue || kind !== category;
      node(kind).disabled = !!catalogue || kind !== category;
    }
    const condition = node("condition"), previous = condition.value;
    condition.replaceChildren(new Option("Not assessed yet", ""), ...(sports ? cardConditions : figureConditions).map(text => new Option(text, text)));
    if ((sports ? cardConditions : figureConditions).includes(previous)) condition.value = previous;
    node("title").textContent = catalogue ? `Add this ${labels().one}` : labels().title;
    node("intro").textContent = catalogue ? "Add a copy of the selected edition to your collection." : reference
      ? "Check the prefilled details against your item, then complete anything missing. This reference has not verified your physical copy."
      : "Enter the exact details from your item. Leave optional details blank if you’re unsure.";
    updateCopy();
  }

  function readIdentity(kind, definitions) {
    return Object.fromEntries(definitions.map(([key, , , , , type]) => [key, optional(`${kind}-${key}`) === null ? null : type === "number" ? Number(value(`${kind}-${key}`)) : value(`${kind}-${key}`)]));
  }

  function payload() {
    const sports = category === "sports", graded = sports && value("state") === "GRADED";
    const result = {category: sports ? "SPORTS" : "FIGURES", acquisition_cost_minor: value("cost") === "" ? null : Math.round(Number(value("cost")) * 100),
      acquisition_date: optional("date"), condition: graded ? null : optional("condition"), seal_status: sports ? null : optional("seal"),
      grading_company: graded ? optional("grader") : null, grade: graded ? optional("grade") : null,
      certificate_number: graded ? optional("certificate") : null, copy_serial_number: optional("serial"), notes: value("notes")};
    if (catalogue) result.catalogue_id = canonicalId(catalogue);
    else if (sports) {
      const identity = readIdentity("sports", [...sportsFields, ...sportsOptional]), language = identity.language;
      delete identity.language;
      result.new_catalogue = {product_type: "CARD", game: "Sports Cards", name: identity.subject_name,
        set_name: identity.set_name, language, sports_card: {system_code: "SPORTS_CARDS", ...identity}};
    } else {
      const identity = readIdentity("figures", [...figureFields, ...figureOptional]);
      result.new_catalogue = {product_type: "FIGURE", game: "Figures", name: identity.character,
        set_name: identity.product_line, figure_details: {system_code: "FIGURES", ...identity}};
    }
    return result;
  }

  async function save(event) {
    event.preventDefault();
    if (!actor || actor !== currentActor()) { clearSession(); return; }
    if (!pending) validateBarcode();
    if (saving || saved || (!pending && !node("form").reportValidity())) return;
    const body = pending ? submittedBody : JSON.stringify(payload());
    if (submittedBody && body !== submittedBody) requestKey = crypto.randomUUID();
    submittedBody = body; saving = true;
    const savingActor = actor, revision = generation;
    node("fields").disabled = true; node("save").disabled = true; node("cancel").disabled = true; node("close").disabled = true;
    node("message").textContent = `Adding your ${labels().one}…`;
    try {
      const result = await apiRequest(seller() ? "/api/v1/owner/collectibles/intake" : "/api/v1/inventory/collectibles/intake",
        {method: "POST", headers: {"Idempotency-Key": requestKey}, body});
      if (revision !== generation || savingActor !== currentActor()) return;
      receipt = result; pending = false; saved = true;
      node("title").textContent = "Added to your collection";
      node("message").textContent = `${result.catalogue?.name || "Your item"} is now in your collection.`;
      node("fields").hidden = true; node("explanation").hidden = true;
      node("actions").hidden = true; node("success").hidden = false;
      node("view").focus();
      document.dispatchEvent(new CustomEvent("owner-inventory-changed", {detail: {inventoryId: result.inventory?.id, actorId: actor}}));
      try { options.onSaved?.(result); } catch (_) { /* A presentation callback cannot undo a committed save. */ }
      if (!seller() && typeof reloadDashboard === "function") await Promise.allSettled([Promise.resolve().then(() => reloadDashboard())]);
    } catch (error) {
      if (revision !== generation || savingActor !== currentActor()) return;
      pending = ![400, 401, 403, 404, 409, 422].includes(error.status);
      node("message").textContent = pending
        ? "We couldn’t confirm the save. Your details are kept. Retry this same item to check safely."
        : error.message || "Unable to add this item. Check its details and try again.";
      node("fields").disabled = pending;
      node("save").disabled = false;
      node("save").textContent = pending ? "Retry this item" : "Add to collection";
      node("message").focus();
    } finally {
      if (revision === generation && savingActor === currentActor()) {
        saving = false; node("cancel").disabled = false; node("close").disabled = false;
      }
    }
  }

  function open(next = {}) {
    if (!currentActor()) return false;
    ensureDialog();
    if (actor && actor !== currentActor()) clearSession();
    if (saving) return false;
    if (pending && actor === currentActor()) {
      node("message").textContent = "Finish checking the previous save before adding another item. Retry this same item safely.";
      if (!dialog.open) dialog.showModal();
      node("save").focus(); return true;
    }
    generation++; actor = currentActor(); options = {...next};
    category = String(next.category || "sports").toLowerCase() === "figures" ? "figures" : "sports";
    const selected=next.catalogue || next.item;
    reference=selected&&typeof selected==="object"&&!Array.isArray(selected)?selected:null;
    catalogue=canonicalId(reference)?reference:null;
    requestKey = crypto.randomUUID(); submittedBody = null; pending = saved = saving = false; receipt = null;
    node("form").reset(); node("category").value = category;
    validateBarcode();
    node("fields").disabled = false; node("fields").hidden = false; node("explanation").hidden = false;
    node("category-label").hidden = !!reference; node("reference").hidden = !reference;
    showProvenance(reference);
    if (reference) {
      node("reference-name").textContent = reference.name || reference.display_name || "Selected collectible";
      node("reference-details").textContent = [reference.set_name, reference.card_number, reference.metadata_only?null:reference.variant,
        category==="sports"&&!reference.metadata_only?reference.language:null].filter(Boolean).join(" · ");
      node("reference-review").textContent=catalogue?"Check the edition against your item before adding it."
        : "Metadata reference only. Confirm the exact parallel or edition and language where applicable. Artwork, condition and market value are not verified.";
      if(!catalogue)prefillReference(reference);
    } else if (typeof next.query === "string") node(category === "sports" ? "sports-subject_name" : "figures-character").value = next.query.slice(0, 140);
    node("form").querySelectorAll("details").forEach(detail => { detail.open = false; });
    node("actions").hidden = false; node("success").hidden = true; node("message").textContent = "";
    node("save").disabled = false; node("save").textContent = "Add to collection";
    node("cancel").disabled = false; node("close").disabled = false;
    updateCategory();
    if (!dialog.open) dialog.showModal();
    node(catalogue ? "save" : category === "sports" ? "sports-sport" : "figures-manufacturer").focus();
    return true;
  }

  function clearSession() {
    generation++; actor = null; options = {}; receipt = catalogue = reference = null;
    submittedBody = requestKey = null; saving = pending = saved = false;
    if (dialog) {
      node("form").reset(); node("reference-name").textContent = "";
      node("reference-details").textContent = "";node("reference-provenance").replaceChildren(); node("message").textContent = "";
      if (dialog.open) dialog.close();
    }
  }
  window.addEventListener("hub-session-cleared", clearSession);
  window.DropRateOwnerCollectibles = window.DropRateCollectibles = {open};
})();
