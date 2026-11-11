"use strict";

window.DropRateInventory = (() => {
  const el = (tag, cls = "", text = "") => { const n = document.createElement(tag); n.className = cls; n.textContent = text; return n; };
  const button = (label, action, cls = "") => { const n = el("button", cls, label); n.type = "button"; n.addEventListener("click", action); return n; };
  const account = () => state.session?.user?.id || state.session?.access_token;
  let dialog, content, message, selected, revision = 0, mutationRevision = 0, busy = false, returnFocus, channels = [];
  let listingIntent = false, listingStep = "condition", returnScroll = 0;
  // Files stay only in this open, account-scoped item dialog. A failed upload
  // must not erase the other side or the seller's unsaved preparation fields.
  let comicDraft = null;
  const comicPreviewUrls = new Set();
  function releaseComicPreviews() {
    for (const url of comicPreviewUrls) URL.revokeObjectURL(url);
    comicPreviewUrls.clear();
  }
  function comicDraftFor(item) {
    const identity = JSON.stringify([account(), item.id, item.catalogue_id, item.product_type,
      item.language, item.condition, item.grading_company, item.grade, item.certificate_number,
      item.comic_printing?.printing_number, item.comic_printing?.cover_code, item.comic_printing?.barcode_gtin]);
    if (!comicDraft || comicDraft.identity !== identity) {
      comicDraft = {identity, owner:account(), id:item.id, values:{}, photos:{}};
    }
    return comicDraft;
  }
  const draftKey = id => state.session?.user?.id ? `drop_rate_listing_draft:${state.session.user.id}:${id}` : null;
  function listingDraft(item) {
    const key=draftKey(item.id);if(!key)return null;
    try{
      const value=JSON.parse(sessionStorage.getItem(key));if(!value || value.version!==item.version)return null;
      return {version:item.version,step:["condition","preparation","price","review"].includes(value.step)?value.step:"condition",
        price:typeof value.price==="string" && value.price.length<=20?value.price:"",
        condition:typeof value.condition==="string" && value.condition.length<=80?value.condition:""};
    }catch(_){return null;}
  }
  function saveListingDraft(item, values={}) {
    const key=draftKey(item.id);if(!key)return;
    const next={...listingDraft(item),step:listingStep,...values};
    try{sessionStorage.setItem(key,JSON.stringify({version:item.version,
      step:["condition","preparation","price","review"].includes(next.step)?next.step:"condition",
      price:typeof next.price==="string" && next.price.length<=20?next.price:"",
      condition:typeof next.condition==="string" && next.condition.length<=80?next.condition:""}));}catch(_){/* The current form stays usable without session storage. */}
  }
  function clearListingDraft(item) {const key=draftKey(item?.id);if(key)try{sessionStorage.removeItem(key);}catch(_){} }
  // Transparent original brand wordmarks, not reconstructed symbols or app icons.
  // All three use the same secure image source and visual alignment rules.
  const channelLogos=Object.freeze({
    SHOPIFY:"https://upload.wikimedia.org/wikipedia/commons/0/0e/Shopify_logo_2018.svg",
    EBAY:"https://upload.wikimedia.org/wikipedia/commons/1/1b/EBay_logo.svg",
    WHATNOT:"https://upload.wikimedia.org/wikipedia/commons/9/91/Whatnot_Logo_2025.svg"
  });
  const alive = (rev, owner) => revision === rev && account() === owner && dialog?.open;
  const active = item => ["DRAFT", "INSPECTION", "APPROVED"].includes(item.status);
  const price = minor => minor == null ? "Value unavailable" : formatMoney(minor);

  function slabMediaKind(item) {
    if (item.card_image_scope === "CANONICAL_CARD" || item.card_image_scope === "CANONICAL_PRODUCT") {
      // This is the exact printing's approved artwork, not the owner's slab.
      return item.reference_image_status === "GRADED_CARD_ART_REFERENCE" ? "CARD_ART_REFERENCE" : "";
    }
    if (item.card_image_scope !== "INVENTORY_ITEM") return "";
    if (item.card_image_capture_context === "GRADED_SLAB" &&
        item.card_image_rights_tier === "FIRST_PARTY_CAPTURE" &&
        ["FOUNDER_UPLOAD","CONSIGNOR_UPLOAD"].includes(item.card_image_source_type)) return "PHYSICAL_PHOTO";
    if (["GRADED_SLAB","RAW_UNSLEEVED"].includes(item.card_image_capture_context) &&
        item.card_image_rights_tier === "INTERNAL_REFERENCE_ONLY" &&
        item.card_image_source_type === "OFFICIAL_PROVIDER" &&
        ["PSA","ACE","BGS","CGC"].includes(String(item.card_image_source_provider || "").toUpperCase()) &&
        String(item.card_image_source_provider || "").toUpperCase() === String(item.grading_company || "").toUpperCase())
      return item.card_image_capture_context === "RAW_UNSLEEVED"
        ? "CERTIFICATE_RAW_REFERENCE" : "CERTIFICATE_REFERENCE";
    return "";
  }

  function image(item, cls) {
    const graded = [item.grading_company, item.grade, item.certificate_number].some(value => String(value || "").trim());
    const mediaKind = slabMediaKind(item);
    const wrap = el("div", cls), placeholder = el("span", "owner-image-placeholder", "Loading image…");
    const img = el("img");
    img.alt = `${item.name || "Inventory item"} ${graded
      ? mediaKind === "CERTIFICATE_REFERENCE" ? "grading certificate reference image"
        : mediaKind === "CERTIFICATE_RAW_REFERENCE" ? "grading certificate raw card reference image, not a slab photo"
        : mediaKind === "CARD_ART_REFERENCE" ? "matching card artwork, not a slab photo"
        : "slab photo"
      : "reference image"}`;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    wrap.append(placeholder, img);
    const owner = account(), attempts = [];
    const community = !graded && window.DropRateBookArtwork?.reference(item, cls === "owner-item-art");
    const inventoryId = item.inventory_id || item.id;
    const validId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(inventoryId || "");
    const directUrl = (value) => {
      try {
        const url = new URL(value);
        if (url.protocol !== "https:" || url.username || url.password || url.hash || (url.port && url.port !== "443")) return null;
        const host = url.hostname.toLowerCase();
        return host === "cdn.shopify.com" || host === "assets.tcgdex.net" || host.endsWith(".shopifycdn.com") || host.endsWith(".shopifycdn.net") ? url.href : null;
      } catch (_) { return null; }
    };
    // Same delivery route as Founder HQ; a provider's public URL need not work
    // in a browser. Send credentials ONLY to our owned-item API, never a CDN.
    const direct = (!graded || Boolean(mediaKind)) && directUrl(item.image_url);
    if (direct) attempts.push({url: direct});
    // The shared proxy is for assigned physical/canonical media only. If a
    // copy has no assigned asset, calling it for every card repeats ownership
    // and exact-reference lookups (often ending in a legitimate 404). Prefer
    // the already-resolved exact reference below, without guessing artwork.
    if (validId && (item.image_url || graded)) attempts.push({path: `/api/v1/inventory/${inventoryId}/image`});
    const reference = !graded && directUrl(item.reference_image_url);
    if (reference && reference !== direct) attempts.push({url: reference});
    const referencePath = `/api/v1/owner/inventory/${inventoryId}/reference-image`;
    if (!graded && validId && item.reference_image_path === referencePath) attempts.push({path: referencePath});
    if (community) {
      attempts.push({url: community.image_url});
      if (!item.image_url && !item.reference_image_path && cls !== "owner-item-art") {
        wrap.title = "Open Library cover reference · Cover may vary";
      }
    }
    let index = 0, objectUrl = null, loading = false, started = false;
    const current = () => owner === account() && wrap.isConnected;
    const release = () => {if (objectUrl) {URL.revokeObjectURL(objectUrl); objectUrl = null;}};
    const unavailable = () => {release(); img.remove(); placeholder.textContent = graded
      ? mediaKind === "CERTIFICATE_REFERENCE" ? "Certificate image unavailable"
        : mediaKind === "CERTIFICATE_RAW_REFERENCE" ? "Certificate card image unavailable"
        : mediaKind === "CARD_ART_REFERENCE" ? "Card artwork unavailable"
        : mediaKind === "PHYSICAL_PHOTO" ? "Slab photo unavailable" : "Slab photo required"
      : "Image unavailable"; placeholder.hidden = false;};
    async function next() {
      if (loading || !current()) return;
      release();
      while (index < attempts.length && current()) {
        const attempt = attempts[index++];
        if (attempt.url) {
          if (community && attempt.url === community.image_url) img.alt = `${item.name || "Book"} community cover reference; cover may vary`;
          img.src = attempt.url; return;
        }
        loading = true;
        try {
          const get = token => fetch(attempt.path, {headers: {Authorization: `Bearer ${token}`}, cache: "no-store"});
          let response = await get(state.session.access_token);
          if (response.status === 401 && current()) {
            const token = await refreshSession();
            if (!current()) return;
            response = await get(token);
          }
          if (!response.ok) throw new Error("Image unavailable");
          const blob = await response.blob();
          if (!current()) return;
          if (!/^image\/(png|jpeg|webp)$/.test(blob.type) || blob.size > 12 * 1024 * 1024) throw new Error("Invalid image response");
          objectUrl = URL.createObjectURL(blob); img.src = objectUrl; return;
        } catch (_) { /* Try only the next bounded, authenticated source. */ }
        finally {loading = false;}
      }
      if (current()) unavailable();
    }
    img.addEventListener("load", () => {release(); if (current()) placeholder.hidden = true; else img.remove();});
    img.addEventListener("error", next);
    const start = () => {if (!started) {started = true; next();}};
    if (!attempts.length) unavailable();
    else if (typeof window.IntersectionObserver === "function") {
      const observer = new window.IntersectionObserver(entries => {
        if (!current()) {observer.disconnect(); return;}
        if (entries.some(entry => entry.isIntersecting)) {observer.disconnect(); start();}
      }, {rootMargin: "320px 0px"});
      observer.observe(wrap);
    } else {
      // Queue after the caller inserts the returned element in the document.
      queueMicrotask(start);
    }
    return wrap;
  }

  function close(force = false) {
    if (busy && !force) return;
    revision++; busy = false; selected = null; channels = [];listingIntent=false;
    comicDraft = null; releaseComicPreviews();
    if (dialog?.open) dialog.close();
    content?.replaceChildren();
    const visibleTarget=node=>node?.isConnected && !node.disabled
      && node.matches("button,input,select,textarea,a[href],[tabindex]")
      && !node.closest('[hidden],.hidden,[aria-hidden="true"],dialog:not([open])');
    [returnFocus,document.querySelector("#owner-inventory-search"),document.querySelector(".owner-nav-item.active")]
      .find(visibleTarget)?.focus({preventScroll:true});
    window.scrollTo({top:returnScroll,behavior:"instant"});
  }

  function ensureDialog() {
    if (dialog) return;
    dialog = el("dialog", "owner-item-dialog"); dialog.setAttribute("aria-labelledby", "owner-item-title");
    const header = el("header");
    const title = el("h2", "", "Item details"); title.id = "owner-item-title";
    const dismiss = button("×", () => close()); dismiss.setAttribute("aria-label", "Close item details");
    header.append(title, dismiss); content = el("div", "owner-item-content");
    message = el("p", "owner-item-message"); message.setAttribute("role", "status");
    dialog.append(header, message, content); document.body.append(dialog);
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  }

  function status(text, error = false) { message.textContent = text; message.classList.toggle("error", error); }

  async function open(item, options = {}) {
    if (!item?.id || busy) return;
    ensureDialog();
    if(!dialog.open){returnFocus=document.activeElement;returnScroll=window.scrollY || 0;}
    listingIntent=options.selling===true || options.prepareEbay===true;
    listingStep=["condition","preparation","price","review"].includes(options.step)?options.step:options.prepareEbay?"preparation":"condition";
    if (!dialog.open) dialog.showModal();
    const rev = ++revision, owner = account(); selected = item;
    if (comicDraft?.owner !== owner || comicDraft?.id !== item.id) comicDraft = null;
    releaseComicPreviews();
    content.replaceChildren(); status("Loading item details…");
    try {
      const data = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(item.id)}`);
      if (!alive(rev, owner)) return;
      // Reuse the owner-scoped channel dashboard snapshot; never block item
      // details on an unrelated provider connection or a slow external API.
      channels=state.ownerChannelAccount===owner && Array.isArray(state.ownerChannelSummaries)
        ?state.ownerChannelSummaries:[];
      selected = data.item;
      const saved=listingDraft(selected);
      if(!options.step && !options.prepareEbay && saved?.step && ["condition","preparation","price","review"].includes(saved.step))listingStep=saved.step;
      render(data);status(saved && listingIntent ? "Your listing draft is ready to continue. Nothing has been published." : "");
      if (window.DropRateScanPhotos && selected.product_type === "COMIC"
          && (selected.comic_photos || []).some(photo => photo.approval_status === "PENDING"
            && ["NOT_UPLOADED", "UPLOADED", "PROCESSING"].includes(photo.shopify_file_status))) {
        // Finish a received file without blocking the item form or approving it.
        // Old interrupted transfers can resume; never ask for the same photo twice.
        refreshReceivedPhotos(selected.id, rev, owner);
      }
      if (options.prepareEbay) {
        const selling = content.querySelector(".owner-item-selling");
        if (selling) selling.open = true;
        const preparation = content.querySelector(".owner-ebay-preparation");
        if (preparation) { preparation.open = true; preparation.focus(); }
      }
    } catch (error) { if (alive(rev, owner)) status(error.message, true); }
  }

  async function refreshReceivedPhotos(id, rev, owner) {
    const mutation = mutationRevision;
    const current = () => alive(rev, owner) && !busy && selected?.id === id && mutation === mutationRevision;
    try {
      await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(id)}/photos/refresh`, {method:"POST",body:"{}"});
      if (!current()) return;
      const data = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(id)}`);
      if (!current()) return;
      const scrollTop = dialog.scrollTop;
      selected = data.item; render(data); dialog.scrollTop = scrollTop;
    } catch (_) { /* The received photo stays visible with its processing retry. */ }
  }

  async function run(action, options = {}) {
    if (busy || !selected) return;
    // A background photo read may finish after this mutation is no longer
    // busy. Its earlier snapshot must not replace the mutation's readback.
    mutationRevision++;
    busy = true;
    const rev = revision, owner = account(), id = selected.id;
    const previous=selected,draft=listingDraft(selected);
    const scrollTop = dialog.scrollTop;
    dialog.querySelectorAll("button,input,select,textarea").forEach(n => { n.disabled = true; });
    status(options.pendingMessage || "Saving…");
    let result, failure;
    try { result = await action(); } catch (error) { failure = error; }
    if (!alive(rev, owner)) return;
    // Re-read even after a partial remote failure: local sale protection may
    // already have committed. Never keep acting on the previous version.
    try {
      const data = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(id)}`);
      if (!alive(rev, owner)) return;
      const recovered = failure && options.recoveredMessage?.(data.item);
      if (recovered) {failure = null;result = {message:recovered};}
      if(!failure && options.clearPricingDraft)clearListingDraft(selected);
      else if(!failure && draft && active(data.item) && ["catalogue_id","product_type","condition","seal_status","language","grading_company","grade"].every(key=>previous[key]===data.item[key])){
        saveListingDraft(data.item,{step:draft.step,price:draft.price,condition:draft.condition});
      }
      selected = data.item; busy = false; render(data);
      if (options.preserveScroll) dialog.scrollTop = scrollTop;
      if (failure && options.focusSelector) content.querySelector(options.focusSelector)?.focus({preventScroll:true});
    } catch (_) {
      busy = false; content.replaceChildren(button("Reload item", () => open({id})));
    }
    if (alive(rev, owner)) {
      dialog.querySelector("header button").disabled = false;
      status(failure ? failure.message : result?.message || "Saved.", Boolean(failure));
      if(!failure)document.dispatchEvent(new CustomEvent("hub:inventory-saved",{detail:{inventoryId:id,message:result?.message||"Saved."}}));
      state.inventory.facets = null;
      await Promise.allSettled([loadOwnerInventory(), loadOwnerOverview(), loadOwnerChannels(), loadOwnerInsights()]);
      if (alive(rev, owner) && !failure && options.closeAfterRemoval && selected?.status === "WITHDRAWN") {
        clearListingDraft(selected);
        close();
        showPortalMessage("Copy removed from your collection.", "success");
      }
    }
  }

  async function chooseBookCover(item, target, trigger) {
    const rev = revision, owner = account();
    trigger.disabled = true; target.textContent = "Finding publisher covers…";
    try {
      const choices = await apiRequest(`/api/v1/owner/books/inventory/${item.id}/covers`);
      if (!alive(rev, owner) || !target.isConnected) return;
      target.replaceChildren();
      target.append(el("p", "owner-item-note", choices.candidates.length
        ? "Choose the cover that matches your copy. This saves reference artwork; your book details stay as entered."
        : "No matching publisher cover is in the catalogue yet. Keep this item; you don’t need to add it again."));
      for (const candidate of choices.candidates.slice(0, 4)) {
        if (!/^[a-f0-9]{24}$/.test(candidate.id || "") || !Number.isInteger(choices.version)) continue;
        const expected = `/api/v1/owner/books/inventory/${item.id}/covers/${candidate.id}?version=${choices.version}`;
        if (candidate.image_path !== expected) continue;
        const card = el("article", "owner-book-candidate"), art = el("div", "owner-book-cover");
        const picture = el("img"), placeholder = el("span", "", "Loading cover…");
        picture.alt = candidate.source_title || "Publisher cover"; picture.hidden = true;
        art.append(placeholder, picture);
        const copy = el("div", "owner-book-candidate-copy"), fields = candidate.fields || {};
        copy.append(el("strong", "", candidate.source_title || fields.series_title),
          el("p", "", [fields.language, fields.printing_number ? `Printing ${fields.printing_number}` : "", fields.cover_artist, fields.cover_code].filter(Boolean).join(" · ")));
        const save = button("Use this cover", () => run(() => apiRequest(`/api/v1/owner/books/inventory/${item.id}/cover`, {
          method: "POST", body: JSON.stringify({version: choices.version, identity_digest: choices.identity_digest,
            candidate_id: candidate.id, confirmed: true})
        })), "owner-primary-action");
        save.disabled = true; copy.append(save); card.append(art, copy); target.append(card);
        (async () => {
          const current = () => alive(rev, owner) && picture.isConnected;
          try {
            let response = await fetch(expected, {headers: {Authorization: `Bearer ${state.session.access_token}`}, cache: "no-store"});
            if (response.status === 401 && current()) {
              const token = await refreshSession();
              if (!current()) return;
              response = await fetch(expected, {headers: {Authorization: `Bearer ${token}`}, cache: "no-store"});
            }
            if (!response.ok) throw new Error("Cover unavailable");
            const blob = await response.blob();
            if (!current()) return;
            if (!/^image\/(png|jpeg|webp)$/.test(blob.type) || blob.size > 2_000_000) throw new Error("Invalid cover");
            const url = URL.createObjectURL(blob);
            picture.onload = () => { URL.revokeObjectURL(url); if (current()) { picture.hidden = false; placeholder.hidden = true; save.disabled = busy; } };
            picture.onerror = () => { URL.revokeObjectURL(url); if (current()) placeholder.textContent = "Publisher cover temporarily unavailable"; };
            picture.src = url;
          } catch (_) { if (current()) placeholder.textContent = "Publisher cover temporarily unavailable"; }
        })();
      }
    } catch (error) { if (alive(rev, owner)) target.textContent = error.message; }
    finally { if (alive(rev, owner)) trigger.disabled = false; }
  }

  function renderComicPreparation(item) {
    const draft = comicDraftFor(item);
    const section = el("section", "owner-comic-preparation owner-item-section");
    section.dataset.comicPreparation = "true";
    section.append(el("h3", "", "Prepare your comic for Shopify"),
      el("p", "owner-item-note", "Tell Drop Rate where this exact copy is held and the measured parcel size. You can add what you paid for profit tracking. Staff must verify the details and approve the photos before anything is listed."));
    const prep = item.comic_listing_preparation || {};
    const fields = el("div", "owner-comic-preparation-fields");
    const field = (caption, type, key, options = {}) => {
      const label = el("label", "", caption), input = el(type === "textarea" ? "textarea" : "input");
      if (type !== "textarea") input.type = type;
      input.dataset.comicField = key;
      input.dataset.comicSavedValue = String(options.value ?? "");
      if (options.min != null) input.min = String(options.min);
      if (options.max != null) input.max = String(options.max);
      if (options.step != null) input.step = String(options.step);
      if (options.placeholder) input.placeholder = options.placeholder;
      if (type === "textarea") input.rows = 2;
      input.value = draft.values[key] ?? options.value ?? "";
      input.addEventListener("input", () => {draft.values[key] = input.value;});
      label.append(input); fields.append(label);
      return input;
    };
    const locationLabel = el("label", "", "Where is this copy held?"), location = el("select");
    location.dataset.comicField = "holding";
    location.dataset.comicSavedValue = prep.holding || "";
    [["", "Choose where it is held"], ["SELLER_HELD", "With me — I will dispatch it"],
      ["DROP_RATE_HELD", "Already with Drop Rate — staff to verify"]].forEach(([value, title]) => {
      const option = el("option", "", title); option.value = value; location.append(option);
    });
    location.value = draft.values.holding ?? prep.holding ?? "";
    location.addEventListener("change", () => {draft.values.holding = location.value;});
    locationLabel.append(location); fields.append(locationLabel);
    const dispatch = field("Dispatch / holding notes", "textarea", "dispatch_note",
      {value:prep.dispatch_note || "", placeholder:"e.g. London, ready to dispatch — no full home address needed"});
    dispatch.maxLength = 200;
    const reportedCost = prep.acquisition_cost_minor ?? item.comic_acquisition_cost_minor;
    const cost = field("What you paid (£) — optional", "number", "cost", {min:0,max:1000000,step:0.01,
      value:reportedCost == null ? "" : (reportedCost / 100).toFixed(2)});
    const weight = field("Packed weight (g)", "number", "weight", {min:1,max:100000,step:1,
      value:prep.parcel_weight_grams ?? ""});
    const length = field("Parcel length (mm)", "number", "length", {min:1,max:10000,step:1,
      value:prep.parcel_length_mm ?? ""});
    const width = field("Parcel width (mm)", "number", "width", {min:1,max:10000,step:1,
      value:prep.parcel_width_mm ?? ""});
    const height = field("Parcel height (mm)", "number", "height", {min:1,max:10000,step:1,
      value:prep.parcel_height_mm ?? ""});
    const rememberFields = () => fields.querySelectorAll("[data-comic-field]").forEach(input => {
      draft.values[input.dataset.comicField] = input.value;
    });
    section.append(fields);
    const save = button("Save preparation details", () => {
      rememberFields();
      if (!location.value) {status("Choose where this physical comic is held.", true);location.focus();return;}
      const number = (input, scale = 1) => {
        if (!input.value.trim()) return null;
        const numeric = Number(input.value);
        if (!input.checkValidity() || !Number.isFinite(numeric) || numeric <= (scale === 100 ? -1 : 0))
          throw new Error("Check the cost and parcel measurements before saving.");
        return Math.round(numeric * scale);
      };
      let values;
      try {
        values = {version:item.version,holding:location.value,dispatch_note:dispatch.value.trim(),
          acquisition_cost_minor:number(cost,100),parcel_weight_grams:number(weight),
          parcel_length_mm:number(length),parcel_width_mm:number(width),parcel_height_mm:number(height)};
      } catch (error) {status(error.message,true);return;}
      run(async () => {
        const result = await apiRequest(`/api/v1/owner/inventory/${item.id}/comic-preparation`,
          {method:"PATCH",body:JSON.stringify(values)});
        draft.values = {};
        return result;
      }, {preserveScroll:true});
    }, "owner-primary-action");
    save.disabled = !active(item);
    section.append(save, el("p", "owner-item-note", "Parcel measurements are for review, not an approved shipping rate. Drop Rate will confirm the COMIC_BOOK or MANGA_BOOK shipping profile."));

    const photos = el("div", "owner-comic-photo-section");
    photos.append(el("h4", "", "Photographs of your exact copy"),
      el("p", "owner-item-note", "A saved scan of your exact copy counts as a photo for selling. Use a clear front cover and include the back for a graded comic; an ungraded back is helpful too."));
    const graded = Boolean(item.grading_company && item.grade);
    for (const side of ["FRONT", "BACK"]) {
      const assets = (item.comic_photos || []).filter(asset => asset.side === side);
      const latest = assets[assets.length - 1], row = el("div", "owner-comic-photo-row");
      const processingFailed = latest?.shopify_file_status === "FAILED";
      row.dataset.comicSide = side;
      const label = el("strong", "", `${side === "FRONT" ? "Front cover" : "Back cover"}${side === "BACK" && !graded ? " (recommended)" : " (required)"}`);
      row.append(label);
      if (latest?.approval_status === "APPROVED" && !processingFailed) {
        delete draft.photos[side];
        row.append(el("p", "owner-item-note", "Approved by Drop Rate for this exact copy."));
      } else if (latest?.approval_status === "PENDING" && !processingFailed) {
        delete draft.photos[side];
        row.append(el("p", "owner-item-note", latest.shopify_file_status === "NOT_UPLOADED"
          ? "Photo received. Image processing needs to finish before review."
          : latest.shopify_file_status === "READY"
          ? "Photo submitted — awaiting staff review."
          : "Photo submitted — processing for staff review."));
        if (["NOT_UPLOADED", "UPLOADED", "PROCESSING"].includes(latest.shopify_file_status)) {
          row.append(button("Check photo processing", () => run(() =>
            apiRequest(`/api/v1/owner/inventory/${item.id}/photos/refresh`, {method:"POST",body:"{}"}),
            {preserveScroll:true,pendingMessage:"Checking your received photos…"}), "owner-secondary-action"));
        }
      } else {
        if (processingFailed) row.append(el("p", "owner-comic-retake-reason",
          "This photo could not be processed. Choose and submit the photo again."));
        if (latest?.approval_status === "REJECTED") row.append(el("p", "owner-comic-retake-reason",
          "Retake requested: " + (latest.retake_reason || "Please submit a clearer photo.")));
        const photo = draft.photos[side] ||= {file:null,rights:false,error:"",requestKey:null};
        const file = el("input"); file.type = "file"; file.accept = "image/jpeg,image/png,image/webp";
        file.setAttribute("aria-label", `Choose ${side.toLowerCase()} comic photo`);
        file.disabled = !active(item);
        const fileLabel = el("label", "owner-comic-file-picker", `Choose ${side.toLowerCase()} photo`); fileLabel.append(file);
        const selection = el("div", "owner-comic-file-selection");
        const feedback = el("p", "owner-comic-upload-error", photo.error); feedback.setAttribute("role", "alert");
        const rightsLabel = el("label", "owner-comic-rights", ""), rights = el("input");
        rights.type = "checkbox"; rights.checked = photo.rights; rights.disabled = !active(item);
        rights.setAttribute("aria-label", `I own or can use this ${side.toLowerCase()} photograph`);
        rights.addEventListener("change", () => {photo.rights = rights.checked;});
        rightsLabel.append(rights, el("span", "", "This is my own photograph, or I am authorised to use it."));
        let previewUrl = null;
        const showSelection = () => {
          if (previewUrl) {URL.revokeObjectURL(previewUrl);comicPreviewUrls.delete(previewUrl);previewUrl = null;}
          selection.replaceChildren();
          if (photo.file && ["image/jpeg","image/png","image/webp"].includes(photo.file.type) && photo.file.size <= 12 * 1024 * 1024) {
            previewUrl = URL.createObjectURL(photo.file);comicPreviewUrls.add(previewUrl);
            const preview = el("img");preview.src = previewUrl;preview.alt = `Selected ${side.toLowerCase()} photo, not yet submitted`;
            selection.append(preview);
          }
          const filename = el("p", "", photo.file ? `${photo.file.name} · Selected, not yet submitted` : "JPG, PNG or WebP · up to 12 MB");
          filename.setAttribute("role", "status");selection.append(filename);
          fileLabel.firstChild.textContent = photo.file ? `Change ${side.toLowerCase()} photo` : `Choose ${side.toLowerCase()} photo`;
        };
        file.addEventListener("change", () => {
          photo.file = file.files?.[0] || null; photo.rights = false;rights.checked = false;
          photo.requestKey = null;photo.error = "";feedback.textContent = "";showSelection();
        });
        showSelection();
        const upload = button(photo.error ? `Retry ${side.toLowerCase()} photo` : latest ? "Resubmit photo" : "Submit photo for review", () => {
          const selectedFile = file.files?.[0] || photo.file;
          if (!selectedFile || !["image/jpeg", "image/png", "image/webp"].includes(selectedFile.type)
              || selectedFile.size < 1 || selectedFile.size > 12 * 1024 * 1024) {
            status("Choose one JPG, PNG or WebP photo up to 12 MB.", true); file.focus(); return;
          }
          if (!rights.checked) {status("Confirm that you own or can use this photograph.",true);rights.focus();return;}
          if (photo.file !== selectedFile) photo.requestKey = null;
          photo.file = selectedFile;photo.rights = true;photo.error = "";
          photo.requestKey ||= crypto.randomUUID();
          rememberFields();
          const owner = account(), rev = revision;
          run(async () => {
            try {
              const query = new URLSearchParams({side,version:String(item.version),filename:selectedFile.name,
                rights_confirmed:"true",request_key:photo.requestKey});
              const result = await apiRequest(`/api/v1/owner/inventory/${item.id}/comic-photo/upload?${query}`,
                {method:"POST",headers:{"Content-Type":selectedFile.type},body:selectedFile});
              if (!alive(rev, owner)) return result;
              delete draft.photos[side];
              return result;
            } catch (error) {
              const transport = error instanceof TypeError || /load failed|failed to fetch|network.*(?:error|fail)/i.test(error.message || "");
              photo.error = transport
                ? "The photo upload was interrupted. Your photo and details are still here. Retry this photo."
                : `${error.message || "The photo could not be uploaded."} Your selected photo is still here; check the message and retry.`;
              throw new Error(photo.error);
            }
          }, {preserveScroll:true,focusSelector:`[data-comic-upload="${side}"]`,
            pendingMessage:`Uploading ${side.toLowerCase()} photo… Keep this window open.`,
            recoveredMessage:updated => {
              const saved = (updated.comic_photos || []).filter(asset => asset.side === side).at(-1);
              if (saved?.shopify_file_status === "FAILED") return null;
              return saved?.approval_status === "PENDING" ? `${side === "FRONT" ? "Front" : "Back"} photo received — awaiting Drop Rate review.`
                : saved?.approval_status === "APPROVED" ? `${side === "FRONT" ? "Front" : "Back"} photo is approved for this copy.` : null;
            }});
        }, "owner-secondary-action");
        upload.dataset.comicUpload = side;
        upload.setAttribute("aria-label", `Submit ${side.toLowerCase()} photo for review`);
        upload.disabled = !active(item);
        row.append(selection,fileLabel,rightsLabel,feedback,upload);
      }
      if (latest?.photo_url) {
        try {
          const url = new URL(latest.photo_url);
          if (url.protocol === "https:" && (url.hostname === "cdn.shopify.com" || url.hostname.endsWith(".shopifycdn.com") || url.hostname.endsWith(".shopifycdn.net"))) {
            const preview = el("img", "owner-comic-photo-preview"); preview.src = url.href;
            preview.alt = `${side.toLowerCase()} submitted comic photograph`; preview.loading = "lazy";
            row.append(preview);
          }
        } catch (_) { /* Never render an arbitrary submitted image URL. */ }
      }
      photos.append(row);
    }
    section.append(photos,el("p", "owner-item-note", "Submitting this evidence cannot approve a comic or publish it. Drop Rate will confirm identity, condition, intake, shipping and photography."));
    return section;
  }

  function comicReviewStatus(item, onPrepare) {
    const section = el("section", "owner-comic-review-status");
    const prep = item.comic_listing_preparation || {}, draft = comicDraftFor(item);
    section.append(el("h4", "", item.status === "INSPECTION" ? "Listing review in progress" : "Before this comic can go live"),
      el("p", "", item.status === "INSPECTION"
        ? "Your listing request is saved. Your remaining steps and Drop Rate's checks are shown below."
        : "Submit the details and photos of this physical copy. Drop Rate then checks them before Shopify publication."));
    const next = [];
    if (!prep.holding && !item.location_recorded) next.push("Save where this copy is held and your dispatch details.");
    const requiredSides = item.grading_company && item.grade ? ["FRONT","BACK"] : ["FRONT"];
    for (const side of ["FRONT","BACK"]) {
      const photo = (item.comic_photos || []).filter(asset => asset.side === side).at(-1);
      if (draft.photos[side]?.file) next.push(`Submit your selected ${side.toLowerCase()} photo.`);
      else if (requiredSides.includes(side) && (photo?.shopify_file_status === "FAILED" || !["PENDING","APPROVED"].includes(photo?.approval_status))) {
        next.push(`${photo?.approval_status === "REJECTED" ? "Retake and submit" : "Upload"} the ${side.toLowerCase()} photo of this copy.`);
      }
    }
    if (next.length) {
      section.append(el("strong", "", "Your next steps"));
      const list = el("ul");next.forEach(text => list.append(el("li", "", text)));
      section.append(list,button("Continue preparation", onPrepare));
    } else section.append(el("p", "", "Your required preparation details and photos are saved for review."));
    const checks = item.approval_blockers || [], staff = [];
    if (checks.some(reason => /exact printing|identity confirmation/i.test(reason))) staff.push("Verify the exact printing and item details.");
    if (checks.some(reason => /storage|dispatch location|intake review/i.test(reason))) staff.push("Confirm where this copy is held and how it will be dispatched.");
    if (checks.some(reason => /Shopify media|approved.*photo|approved.*image/i.test(reason))) staff.push("Review and approve the physical-copy photographs.");
    if (checks.some(reason => /shipping profile/i.test(reason))) staff.push("Confirm the comic shipping profile.");
    if (staff.length) {
      section.append(el("strong", "", "Drop Rate checks"));
      const list = el("ul");staff.forEach(text => list.append(el("li", "", text)));section.append(list);
    }
    return section;
  }

  function collectibleIdentityRows(item) {
    if(item.product_type==="FIGURE" && item.figure_details){
      const figure=item.figure_details;
      return [["Manufacturer",figure.manufacturer],["Franchise",figure.franchise],["Character",figure.character],
        ["Product line",figure.product_line],["Edition",figure.edition],["Scale",figure.scale],
        ["Release year",figure.release_year],["Manufacturer code",figure.manufacturer_sku],["Barcode",figure.barcode_gtin]];
    }
    if(item.product_type==="CARD" && item.sports_card){
      const card=item.sports_card;
      return [["Sport",card.sport],["League",card.league],["Release year",card.release_year],["Season",card.season],
        ["Manufacturer",card.manufacturer],["Set",card.set_name],["Player / subject",card.subject_name],
        ["Team",card.team],["Card number",card.card_number],["Parallel",card.parallel],["Print run",card.print_run]];
    }
    return [];
  }

  function installListingFlow(item, sale, {saleCondition,priceInput,priceLabel,priceBasisNote,save,actions}) {
    const summary=sale.querySelector("summary"), existing=[...sale.children].filter(child=>child!==summary);
    const flow=el("div","owner-listing-flow"),nav=el("nav","owner-listing-steps");nav.setAttribute("aria-label","Listing preparation steps");
    const stages=[["condition","Item"],["preparation","Preparation"],["price","Price"],["review","Review"]];
    const panels=Object.fromEntries(stages.map(([key,label])=>{const panel=el("section","owner-listing-stage");panel.dataset.listingStep=key;panel.setAttribute("aria-label",label);return[key,panel];}));
    panels.review.append(...existing);
    panels.condition.append(el("h3","","Confirm the copy you want to sell"),el("p","owner-item-note",`${item.inventory_code} · ${item.language || "Language not recorded"}`));
    const structuredIdentity=collectibleIdentityRows(item).filter(([,value])=>value!=null && String(value).trim());
    if(structuredIdentity.length){
      const details=el("dl","owner-item-facts-grid");
      for(const [label,value] of structuredIdentity){const pair=el("div","owner-item-fact");pair.append(el("dt","",label),el("dd","",String(value)));details.append(pair);}
      panels.condition.append(details);
    }
    if(saleCondition)panels.condition.append(saleCondition.parentElement);
    else panels.condition.append(el("p","",`${inventoryTypeLabel(item)} · ${conditionLabel(item)}`));
    panels.condition.append(el("p","owner-item-note","Check the item, printing and language above. Selling applies only to the selected physical copy."));
    panels.preparation.append(el("h3","","Photos and preparation"));
    const comic=panels.review.querySelector(".owner-comic-preparation"),ebay=panels.review.querySelector(".owner-ebay-preparation");
    if(comic)panels.preparation.append(comic);
    if(ebay)panels.preparation.append(ebay);
    if(!comic && !ebay)panels.preparation.append(el("p","owner-item-note",item.seller_approval_available
      ?"This sealed product can use its approved catalogue artwork. Confirm that you hold this exact product before listing."
      :"Drop Rate checks the identity, intake details and listing photographs of this exact copy before publication."));
    const remaining=el("div","owner-listing-readiness");
    remaining.append(el("strong","",item.approval_blockers?.length ? `${item.approval_blockers.length} check${item.approval_blockers.length===1?"":"s"} before publication` : "Final channel checks run before publication"));
    if(item.approval_blockers?.length){
      const wording={"Drop Rate intake review":"We need to check this item before it can be listed", "An approved listing photo":"Add a clear photo for the listing", "Identity confirmation":"Check that the item details are correct"};
      const checks=el("ul");for(const reason of item.approval_blockers){const row=el("li");row.append(el("span","",wording[reason]||reason));
        const step=/price/i.test(reason)?"price":/condition|grade|language/i.test(reason)?"condition":null;
        if(step)row.append(button(step==="price"?"Set price":"Review item",()=>showStep(step)));checks.append(row);
      }remaining.append(checks);
    }
    panels.preparation.append(remaining);
    panels.price.append(el("h3","","Set your selling price"),priceBasisNote,priceLabel,save,
      el("p","owner-item-note","Commission is based on the item sale price after discounts. Your purchase cost is optional and only affects profit tracking. Final proceeds also reflect any applicable fees and deductions."));
    const reviewHeading=el("h3","","Review your listing"),reviewFacts=el("dl","owner-listing-review-facts");
    const comicStatus = item.product_type === "COMIC" && item.status !== "APPROVED" ? el("div") : null;
    const updateReview=()=>{
      reviewFacts.replaceChildren();
      for(const [label,value] of [["Physical copy",item.inventory_code],["Language",item.language || "Not recorded"],["Condition / grade",saleCondition?.value || conditionLabel(item)],["Selling price",priceInput.value.trim()?`£${priceInput.value}`:"Not set"]]){
        const pair=el("div");pair.append(el("dt","",label),el("dd","",value));reviewFacts.append(pair);
      }
      if (comicStatus) comicStatus.replaceChildren(comicReviewStatus(item, () => showStep("preparation")));
    };
    panels.review.prepend(reviewHeading,reviewFacts,...(comicStatus ? [comicStatus] : []));
    if(actions.children.length===0)actions.remove();
    const buttons=new Map();for(const [index,[key,label]] of stages.entries()){
      const control=button(`${index+1}. ${label}`,()=>showStep(key));control.setAttribute("aria-controls",`owner-listing-stage-${key}`);buttons.set(key,control);nav.append(control);panels[key].id=`owner-listing-stage-${key}`;
    }
    const footer=el("div","owner-listing-navigation"),back=button("Back",()=>showStep(stages[Math.max(0,stages.findIndex(([key])=>key===listingStep)-1)][0])),next=button("Continue",()=>{
      if(listingStep==="condition" && saleCondition && !saleCondition.value){status("Choose the condition of this copy before continuing.",true);saleCondition.focus();return;}
      if(listingStep==="price" && (!/^\d+(\.\d{1,2})?$/.test(priceInput.value)||Number(priceInput.value)<1||Number(priceInput.value)>1_000_000)){status("Enter a selling price of at least £1, with no more than two decimal places.",true);priceInput.focus();return;}
      const index=stages.findIndex(([key])=>key===listingStep);showStep(stages[Math.min(stages.length-1,index+1)][0]);
    },"primary");
    footer.append(back,next);
    const draftNote=el("p","owner-listing-draft-note",item.product_type === "COMIC"
      ? "Keep this window open until your photos and preparation details are saved. Your price and current step stay in this browser session."
      : "Your progress stays in this browser session. Save your details or submit for review when you’re ready.");
    function showStep(key,{focus=true,persist=true}={}){
      listingStep=stages.some(([name])=>name===key)?key:"condition";updateReview();
      for(const [name,panel]of Object.entries(panels)){panel.hidden=name!==listingStep;buttons.get(name).toggleAttribute("data-active",name===listingStep);if(name===listingStep)buttons.get(name).setAttribute("aria-current","step");else buttons.get(name).removeAttribute("aria-current");}
      const index=stages.findIndex(([name])=>name===listingStep);back.hidden=index===0;next.hidden=index===stages.length-1;next.textContent=index===stages.length-2?"Review listing":"Continue";
      if(persist)saveListingDraft(item,{step:listingStep,price:priceInput.value,condition:saleCondition?.value||""});
      if(focus){
        panels[listingStep].tabIndex=-1;panels[listingStep].focus({preventScroll:true});
        const headerHeight=dialog.querySelector("header").getBoundingClientRect().height;
        const top=dialog.scrollTop+flow.getBoundingClientRect().top-dialog.getBoundingClientRect().top-headerHeight-8;
        dialog.scrollTo?.({top:Math.max(0,top),behavior:"auto"});status("");
      }
    }
    const saveDraft=()=>{saveListingDraft(item,{price:priceInput.value,condition:saleCondition?.value||"",step:listingStep});updateReview();};
    priceInput.addEventListener("input",saveDraft);saleCondition?.addEventListener("change",saveDraft);
    nav.style.top=`${Math.ceil(dialog.querySelector("header").getBoundingClientRect().height)}px`;
    flow.append(nav,...Object.values(panels),footer,draftNote);sale.append(flow);
    sale.showListingStep=showStep;
    showStep(listingStep,{focus:false,persist:false});
    sale.addEventListener("toggle",()=>{if(sale.open){listingIntent=true;dialog.classList.add("is-listing");dialog.querySelector("#owner-item-title").textContent=item.shopify_state==="PUBLISHED"?"Manage listing":"Prepare listing";}});
    const backToItem=button("← Item overview",()=>{listingIntent=false;dialog.classList.remove("is-listing");sale.open=false;dialog.querySelector("#owner-item-title").textContent="Item details";dialog.scrollTop=0;},"owner-listing-back");
    flow.prepend(backToItem);
  }

  function render(data) {
    const item = data.item, copies = data.copies || [];
    const sellingOpen = listingIntent || content.querySelector(".owner-item-selling")?.open === true;
    releaseComicPreviews();
    content.replaceChildren();
    dialog.classList.toggle("is-listing",listingIntent);
    dialog.querySelector("#owner-item-title").textContent=listingIntent?"Prepare listing":"Item details";
    const hero = el("section", "owner-item-hero"), figure = el("figure");
    const gradedImage = [item.grading_company, item.grade, item.certificate_number].some(value => String(value || "").trim());
    const slabKind = slabMediaKind(item);
    figure.append(image(item, "owner-item-art"), el("figcaption", "", gradedImage
      ? (slabKind === "PHYSICAL_PHOTO" ? "Your slab photo" : slabKind === "CERTIFICATE_REFERENCE"
          ? `${safeText(item.card_image_source_provider, "Grading service")} certificate slab image · private reference, not listing media`
          : slabKind === "CERTIFICATE_RAW_REFERENCE"
          ? `${safeText(item.card_image_source_provider, "Grading service")} certificate card image · not a slab photo or listing media`
          : slabKind === "CARD_ART_REFERENCE"
          ? "Matching card artwork · not this slab's photo or listing media"
          : "Add a photo of this slab")
      : item.image_url ? "Item image" : "Reference image · not a photo of your copy"));
    const community = window.DropRateBookArtwork?.reference(item, true);
    if (community && !item.image_url && !item.reference_image_path) figure.append(window.DropRateBookArtwork.credit(community));
    const identity = el("div");
    identity.append(el("h3", "", item.name), el("p", "", inventoryCardSubtitle(item)),
      el("span", `owner-status-pill ${statusClass(item.status)}`, collectionStatus(item)));
    hero.append(figure, identity); content.append(hero);
    if (item.product_type === "COMIC" && active(item) && !item.image_url) {
      const choices = el("div", "owner-book-candidates"), covers = el("section", "owner-item-section");
      const trigger = button(item.reference_image_path ? "Change cover" : "Choose cover", () => chooseBookCover(item, choices, trigger), "owner-secondary-action");
      covers.append(trigger, choices); content.append(covers);
    }

    // The inventory grid shows only essentials. Exact copy metadata remains
    // available here, including untruncated IDs and grading certificates.
    const facts = el("details", "owner-item-facts owner-item-section");
    facts.append(el("summary", "", "Item details"));
    const list = el("dl", "owner-item-facts-grid");
    const rows = [
      [["COMIC","FIGURE"].includes(item.product_type) || item.sports_card ? "Category" : "Game", item.game],
      [item.product_type === "COMIC" ? "Series / edition" : item.product_type==="FIGURE"?"Range / series":"Set", item.set_name],
      [item.product_type === "COMIC" ? (item.game === "Manga" ? "Volume" : "Issue / book number") : item.product_type==="FIGURE"?"Model / product code":"Card number", item.card_number],
      ["Language", item.language],
      [item.product_type === "SEALED" ? "Seal" : "Condition", conditionLabel(item)],
      ["Type", inventoryTypeLabel(item)],
      ["Grading company", item.grading_company],
      ["Grade", item.grade],
      ["Certificate", item.certificate_number],
      ["Inventory ID", item.inventory_code],
    ];
    rows.push(...collectibleIdentityRows(item));
    if(item.identity_source==="SELLER_ENTERED")rows.push(["Identity source","Seller entered"]);
    if (item.comic_printing) {
      const book = item.comic_printing;
      rows.push(["Publisher", book.attributes?.publisher], ["Publication year", book.release_year],
        ["Printing", book.printing_number], ["Cover / variant", book.cover_code],
        ["Cover artist", book.cover_artist], ["ISBN / barcode", book.barcode_gtin], ["Notes", book.notes]);
    }
    for (const [labelText, valueText] of rows) {
      if (valueText == null || String(valueText).trim() === "") continue;
      const pair = el("div", "owner-item-fact");
      pair.append(el("dt", "", labelText), el("dd", "", String(valueText)));
      list.append(pair);
    }
    facts.append(list); content.append(facts);

    const values = el("section", "owner-item-values");
    const displayedValue = (item.reference_value || item.catalogue_reference) ? window.DropRateReferenceValue.text(item, formatMoney)
      : item.market_value_minor == null ? "Value unavailable" : price(item.market_value_minor);
    values.append(el("div", "", window.DropRateReferenceValue?.label(item) || "Market value"),
      el("strong", "", displayedValue.replace(/^(?:Value|Drop Rate UK\/EU estimate):\s*/, "")));
    if (window.DropRateReferenceValue?.isHistorical(item)) {
      const reference = window.DropRateReferenceValue.displayReference(item);
      const checked = new Date(reference.checked_at);
      const history = Number.isNaN(checked.getTime()) ? "Historical value"
        : `Historical value · Last known ${checked.toLocaleDateString("en-GB")}`;
      values.append(el("small", "owner-item-historical-label", history));
    }
    const sourceDescription = item.reference_value || item.catalogue_reference
      ? window.DropRateReferenceValue.description(item)
      : item.pricing_method === "CARDMARKET_GUIDE_V1" ? "Source: Cardmarket market-price guide." : "";
    if (sourceDescription) {
      const source = el("details", "owner-market-source");
      source.append(el("summary", "", "About this value"), el("p", "", sourceDescription));
      values.append(source);
    }
    if (item.pricing_updated_at) values.append(el("small", "", `Updated ${new Date(item.pricing_updated_at).toLocaleDateString("en-GB")}`));
    content.append(values);
    const marketMinor = window.DropRateReferenceValue?.marketMinor(item) ?? null;
    const suggestedPrice = marketMinor != null && marketMinor >= 100 ? marketMinor : null;
    const priceBasisNote = el("p", "owner-item-note",
      item.store_price_minor == null
        ? suggestedPrice == null ? "Enter your selling price." : "Starts from the current market value. Nothing is saved or listed until you choose a selling action."
        : "Your saved selling price is retained.");
    priceBasisNote.dataset.priceBasisNote = "";


    const publishedOnShopify=item.shopify_state==="PUBLISHED";
    const approvedForSale=item.status==="APPROVED" && item.sale_intent==="FOR_SALE";
    const sale = el("details", "owner-item-section owner-item-selling");
    sale.open = sellingOpen || (item.product_type === "COMIC" && item.sale_intent === "FOR_SALE");
    sale.append(el("summary", "", publishedOnShopify ? "Manage listing" : "Sell this item"));
    if (item.product_type === "CARD" && item.ebay_preparation) {
      const preparation = item.ebay_preparation;
      const checklist = el("details", "owner-ebay-preparation");
      checklist.tabIndex = -1;
      checklist.setAttribute("aria-label", "eBay preparation checklist");
      checklist.append(el("summary", "", `Prepare for eBay · ${preparation.completed}/${preparation.checks.length}`),
        el("p", "owner-item-note", `${preparation.completed} of ${preparation.checks.length} preparation steps complete`));
      if (preparation.scope_blocker) checklist.append(el("p", "owner-item-note", preparation.scope_blocker + ". You can prepare the card while publishing is unavailable."));
      const steps = el("ul", "owner-ebay-checklist");
      for (const check of preparation.checks) {
        const step = el("li", check.complete ? "complete" : "pending");
        step.append(el("strong", "", (check.complete ? "✓ " : "○ ") + check.label));
        if (!check.complete) step.append(el("small", "", check.next_step));
        steps.append(step);
      }
      checklist.append(steps, el("p", "owner-item-note", "Final account, delivery and eBay checks run before publication. Preparing a card does not list it."));
      sale.append(checklist);
    }
    sale.append(priceBasisNote);
    if (item.product_type === "COMIC") sale.append(renderComicPreparation(item));
    let saleCondition;
    if (["CARD", "COMIC", "FIGURE"].includes(item.product_type) && !item.grading_company && ["DRAFT", "INSPECTION"].includes(item.status)) {
      const label = el("label", "", "Condition when selling"); saleCondition = el("select");
      saleCondition.setAttribute("aria-label", "Condition when selling");
      const conditions = item.product_type === "FIGURE" ? ["","New","Like New","Very Good","Good","Fair","Damaged"] : item.product_type === "COMIC" ? ["", "Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor"] : ["", "Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
      for (const value of conditions) {
        const option = el("option", "", value || "Choose condition"); option.value = value; saleCondition.append(option);
      }
      const saved=listingDraft(item);
      saleCondition.value = saved?.condition || item.condition || ""; label.append(saleCondition); sale.append(label);
    }
    const priceLabel = el("label", "", "Your selling price (£)"), priceInput = el("input");
    priceInput.type = "number"; priceInput.min = "1"; priceInput.step = "0.01"; priceInput.inputMode = "decimal";
    const initialPrice = item.store_price_minor ?? suggestedPrice;
    const savedDraft=listingDraft(item);
    priceInput.value = typeof savedDraft?.price==="string" && savedDraft.price.length<=20 ? savedDraft.price : initialPrice == null ? "" : (initialPrice / 100).toFixed(2);
    let suggestionPrefilled = item.store_price_minor == null && suggestedPrice != null;
    let priceEdited = false;
    const originalPriceBasisText = priceBasisNote.textContent;
    priceInput.addEventListener("input", () => { suggestionPrefilled = false; priceEdited = true; });
    if (saleCondition) saleCondition.addEventListener("change", () => {
      const guide = item.reference_value?.status === "REFERENCE_ESTIMATE";
      const sameBasis = guide ? ["", "Near Mint"].includes(saleCondition.value)
        : saleCondition.value === (item.condition || "");
      if (!sameBasis && suggestionPrefilled) { priceInput.value = ""; suggestionPrefilled = false; }
      priceBasisNote.textContent = sameBasis ? originalPriceBasisText
        : "The displayed market value does not confirm the newly selected condition. Enter your selling price.";
      if (sameBasis && !priceEdited && item.store_price_minor == null && suggestedPrice != null) {
        priceInput.value = (suggestedPrice / 100).toFixed(2);
        suggestionPrefilled = true;
      }
    });
    priceInput.setAttribute("aria-label", "Your selling price in pounds"); priceInput.disabled = !active(item);
    priceLabel.append(priceInput); sale.append(priceLabel);
    const value = () => {
      if (!/^\d+(\.\d{1,2})?$/.test(priceInput.value) || Number(priceInput.value) < 1 || Number(priceInput.value) > 1_000_000) {
        throw new Error("Enter a selling price of at least £1, with no more than two decimal places.");
      }
      return Math.round(Number(priceInput.value) * 100);
    };
    const priceAction = (path, method) => {
      let minor; try { minor = value(); } catch (error) { sale.showListingStep?.("price");status(error.message, true); priceInput.focus(); return; }
      if (path === "approval-request" && saleCondition && !saleCondition.value) {
        sale.showListingStep?.("condition");status("Choose the condition for your listing. The item is already saved in your collection.", true); saleCondition.focus(); return;
      }
      if (path === "approval-request" && item.product_type === "COMIC" && Object.values(comicDraftFor(item).photos).some(photo => photo.file)) {
        sale.showListingStep?.("preparation");
        status("Submit your selected photos before updating the listing request. Your photos and details are still here.", true);
        return;
      }
      if (path === "approval-request" && item.product_type === "COMIC" && [...content.querySelectorAll("[data-comic-field]")].some(input => input.value !== input.dataset.comicSavedValue)) {
        sale.showListingStep?.("preparation");
        status("Save your preparation details before updating the listing request. Your changes are still here.", true);
        return;
      }
      const body = {version: item.version, store_price_minor: minor};
      if (path === "approval-request" && saleCondition) body.condition = saleCondition.value;
      run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/${path}`, {method, body: JSON.stringify(body)}),{clearPricingDraft:path==="approval-request"});
    };
    const actions=el("div","owner-item-actions");
    const save=button("Save selling price",()=>priceAction("selling-price","PATCH"));
    save.disabled=!active(item);
    actions.append(save);
    // Approval is only needed before publication. A published pack should
    // never be offered a second "Approve" action.
    if(!publishedOnShopify && !approvedForSale){
      const approve=button(
        item.seller_approval_available?"List on Shopify":
        item.status==="INSPECTION"?"Update listing request":"Request listing review",
        ()=>priceAction("approval-request","POST"),"primary"
      );
      approve.disabled=!active(item);
      actions.append(approve);
    }
    sale.append(actions);
    if(publishedOnShopify){
      sale.append(el("p","owner-item-note","This copy is already published on Shopify. You can still update your selling price."));
    }else{
      if(!approvedForSale) {
        sale.append(el("p","owner-item-note",item.seller_approval_available
          ?"List on Shopify confirms that you hold this exact sealed product and want it offered for sale. Your stock stays with you and uses approved catalogue artwork."
          :"Your item is already saved in your collection. This request sends the selected copy for Drop Rate selling review; approval can then trigger Shopify publication."));
      }
      if(!item.shopify_sync_enabled) sale.append(el("p","owner-item-note","Shopify publishing is currently unavailable."));
    }
    content.append(sale);

    const sellerChannels=el("section","owner-item-section owner-channel-section");
    sellerChannels.append(el("h3","","Selling channels"));
    const channelGrid=el("div","owner-item-channels");
    const ebay=channels.find(row=>row.code==="EBAY")||{};
    const ebayScopeBlocker=item.ebay_preparation?.scope_blocker;
    const ebayChecks=item.ebay_preparation?.checks;
    const ebayPrepared=Array.isArray(ebayChecks) && ebayChecks.length>0 &&
      ebayChecks.every(check=>check.complete===true);
    const ebayEligible=Boolean(ebay.connected && ebay.sync_enabled) &&
      !ebayScopeBlocker && item.product_type==="CARD" && approvedForSale;
    const ebayReason=item.product_type!=="CARD"?(item.product_type === "COMIC" ? "Comics and manga aren't supported here yet" : item.product_type==="FIGURE"?"Figure publishing is not available yet":"Sealed packs aren't supported yet"):
      ebayScopeBlocker?ebayScopeBlocker:
      !ebay.connected?"eBay account not connected":
      !ebay.sync_enabled?"Seller publishing not enabled":
      !approvedForSale?"Approval required":
      !ebayPrepared?"Some listing details may need attention":"Ready for final checks";
    const cards=[
      {
        code:"SHOPIFY",label:"Shopify",state:publishedOnShopify?"Published":
          !item.shopify_sync_enabled?"Unavailable":
          !approvedForSale?(item.seller_approval_available?"Not listed — use List on Shopify":
            item.status === "INSPECTION" ? "Awaiting Drop Rate review — not live yet" : "Submit for Drop Rate review above"):"Awaiting channel checks",
        action:!publishedOnShopify && item.shopify_sync_enabled && approvedForSale?"Check & sync to Shopify":null,
        click:()=>run(async()=>{
          const result=await apiRequest(`/api/v1/owner/inventory/${item.id}/channels/shopify/sync`,
            {method:"POST",body:JSON.stringify({version:item.version})});
          return {message:"Shopify: "+result.status.replaceAll("_"," ")};
        })
      },
      {
        code:"EBAY",label:"eBay",state:ebayReason,
        action:ebayEligible?"List on eBay":null,
        click:()=>run(async()=>{
          const result=await apiRequest(`/api/v1/owner/inventory/${item.id}/channels/ebay/sync`,
            {method:"POST",body:JSON.stringify({version:item.version})});
          return {message:"eBay: "+result.status.replaceAll("_"," ")};
        })
      },
      {
        code:"WHATNOT",label:"Whatnot",
        state:"Not connected in Drop Rate — publishing unavailable",
        action:null
      }
    ];
    for(const channel of cards){
      const block=el("div","owner-item-channel owner-item-channel-"+channel.code.toLowerCase());
      const visual=el("span","owner-item-channel-visual");
      const img=el("img","owner-item-channel-logo");
      img.src=channelLogos[channel.code]; img.alt=channel.label+" logo";
      img.loading="lazy";img.decoding="async";img.referrerPolicy="no-referrer";
      img.addEventListener("error",()=>{
        img.remove();visual.append(el("span","owner-item-channel-fallback",channel.label));
      });
      visual.append(img);
      const info=el("small","owner-item-channel-state",channel.state);
      block.append(visual,info);
      if(channel.action){
        const action=button(channel.action,channel.click,"owner-item-channel-action");
        action.setAttribute("aria-label",channel.action==="Set up"?"Set up "+channel.label:channel.action);
        block.append(action);
      }else{
        const availability=el("span","owner-item-channel-availability",channel.code==="SHOPIFY"
          ? publishedOnShopify ? "Already live" : !item.shopify_sync_enabled ? "Publishing paused" : item.status === "INSPECTION" ? "In review" : "Preparation needed"
          : channel.code==="EBAY" ? "Check connection or inventory status" : "Not available yet");
        availability.setAttribute("aria-label",channel.code==="SHOPIFY" && publishedOnShopify
          ?"Already published on Shopify":"No publishing action available for "+channel.label);
        block.append(availability);
      }
      channelGrid.append(block);
    }
    sellerChannels.append(channelGrid);
    // One authenticated owner-scoped media decision feeds all channels. This
    // is a preview, not a listing action; never trust an image URL from the UI.
    const mediaPreview=el("div","owner-channel-media-status");
    mediaPreview.setAttribute("role","status");
    mediaPreview.append(el("p","owner-item-note","Checking approved images for each channel…"));
    sellerChannels.append(mediaPreview);
    const previewRevision=revision,previewOwner=account(),previewItemId=item.id;
    apiRequest(`/api/v1/media/resolve/${encodeURIComponent(previewItemId)}`).then(result=>{
      if(!alive(previewRevision,previewOwner) || selected?.id!==previewItemId
         || !mediaPreview.isConnected || result.inventory_id!==previewItemId)return;
      const list=el("ul","owner-channel-media-list");
      for(const [code,label] of [["DROP_RATE","Drop Rate"],["SHOPIFY","Shopify"],["EBAY","eBay"],["WHATNOT","Whatnot"]]){
        const choice=result.channels?.[code];
        if(!choice)continue;
        const count=Array.isArray(choice.selectedMedia)?choice.selectedMedia.length:0;
        const summary=code==="WHATNOT"?"Not connected — no publishing":
          choice.complete && count?(`Approved ${count===1?"image":"images"}: ${count} selected`):
          code==="EBAY"?"Add a front scan or approved catalogue image":
          choice.blockers?.length?"Approved image still required":"No eligible image selected";
        list.append(el("li","",`${label}: ${summary}`));
      }
      mediaPreview.replaceChildren(el("strong","","Channel image selection"),list,
        el("p","owner-item-note","Image selection is separate from listing approval. Scanned photos remain attached to your exact physical copy."));
    }).catch(()=>{
      if(alive(previewRevision,previewOwner) && selected?.id===previewItemId
         && mediaPreview.isConnected)
        mediaPreview.replaceChildren(el("p","owner-item-note","Image preview unavailable; existing listing checks still apply."));
    });
    if(!ebayEligible) sellerChannels.append(el("p","owner-item-channel-footnote",
      "eBay: "+ebayReason+"."));
    sale.append(sellerChannels);

    const stock = el("section", "owner-item-section"); stock.append(el("h3", "", "Quantity"));
    const savedQuantity = copies.length;
    stock.append(el("p", "", `${savedQuantity} ${savedQuantity === 1 ? "copy" : "copies"} in your collection`));
    const awaitingApproval = copies.filter(copy => ["DRAFT", "INSPECTION"].includes(copy.status)).length;
    const approvedPhysicalCopies = copies.filter(copy => copy.status === "APPROVED" && copy.sale_intent === "FOR_SALE").length;
    if (awaitingApproval) sale.append(el("p", "owner-item-quantity-breakdown",
      `${approvedPhysicalCopies} approved for sale · ${awaitingApproval} awaiting approval. Pending copies are not live on Shopify.`));
    if (copies.length > 1) {
      const label = el("label", "", "Choose the copy to manage"), select = el("select");
      select.setAttribute("aria-label", "Choose inventory copy");
      copies.forEach(copy => { const option = el("option", "", `${copy.inventory_code} · ${collectionStatus(copy)}`); option.value = copy.id; select.append(option); });
      select.value = item.id; select.addEventListener("change", () => open({id: select.value},{selling:listingIntent,step:listingStep})); label.append(select);label.className="owner-exact-copy-picker";content.insertBefore(label,hero.nextSibling);
    }
    // A tap changes the VISIBLE proposed number; only explicit confirmation
    // changes physical inventory. Never display a draft copy as Shopify stock.
    const controls = el("div", "owner-item-quantity"), confirmation = el("div", "owner-item-confirmation");
    const quantity = el("strong", "owner-item-quantity-value", String(savedQuantity));
    quantity.setAttribute("role", "status"); quantity.setAttribute("aria-live", "polite");
    const feedback = el("p", "owner-item-quantity-feedback");
    let delta = 0, add, remove;
    const resetQuantity = () => { delta = 0; updateQuantity(); };
    const updateQuantity = () => {
      const proposed = savedQuantity + delta;
      quantity.textContent = String(proposed);
      quantity.classList.toggle("unsaved", delta !== 0);
      quantity.setAttribute("aria-label", delta
        ? `Proposed quantity ${proposed}, not saved`
        : `Saved quantity ${proposed}`);
      feedback.textContent = delta
        ? `Not saved: ${savedQuantity} → ${proposed}. Confirm or cancel below.`
        : "";
      add.disabled = !active(item) || Boolean(item.grading_company || item.grade || item.certificate_number) || delta === 1;
      remove.disabled = !active(item) || delta === -1;
      confirmation.replaceChildren();
      if (!delta) return;
      const actions = el("div", "owner-item-confirmation-actions");
      if (delta > 0) {
        confirmation.append(el("p", "", `Add one more ${item.language} copy in the same condition? It will be added to your collection.`));
        actions.append(button("Confirm additional copy", () => {
          const storageKey = `drop_rate_copy:${account()}:${item.id}`;
          let pending; try { pending = JSON.parse(sessionStorage.getItem(storageKey)); } catch (_) { /* replace corrupt pending data */ }
          pending ||= {key: crypto.randomUUID(), version: item.version};
          try { sessionStorage.setItem(storageKey, JSON.stringify(pending)); }
          catch (_) { status("Could not save a safe retry token. Please enable session storage before adding stock.", true); return; }
          run(async () => {
            const result = await apiRequest(`/api/v1/owner/inventory/${item.id}/copies`, {
              method: "POST", headers: {"Idempotency-Key": pending.key},
              body: JSON.stringify({version: pending.version, confirmed: true})
            });
            sessionStorage.removeItem(storageKey);
            return {...result, message: "One copy added to your collection."};
          });
        }, "primary"));
      } else {
        confirmation.append(el("p", "", `Remove ${item.inventory_code} from your collection and its selling channels? The exact copy's history will be kept.`));
        actions.append(button("Confirm removal", () => run(() =>
          apiRequest(`/api/v1/owner/inventory/${item.id}/withdraw`, {
            method: "POST", body: JSON.stringify({version: item.version})
          }), {closeAfterRemoval:true,
            recoveredMessage: updated => updated.status === "WITHDRAWN" ? "Copy removed from your collection." : null}), "danger"));
      }
      actions.append(button("Cancel change", resetQuantity));
      confirmation.append(actions);
    };
    add = button("Add another copy", () => { delta=1; updateQuantity(); });
    add.setAttribute("aria-label", "Add another copy");
    remove = button("Remove this copy", () => { delta=-1; updateQuantity(); });
    remove.setAttribute("aria-label", "Remove this copy");
    controls.append(quantity, add, remove);
    stock.append(controls, feedback, confirmation);
    updateQuantity();
    stock.append(el("p", "owner-item-note",
      item.grading_company
        ? (item.product_type === "COMIC" ? "Add each graded book through Comic / manga with its own certificate. Withdrawing a copy keeps its history." : "Add each graded slab through Scan with its own certificate. Withdrawing a copy keeps its history.")
        : "Add another matching copy, or remove the selected copy. Confirm the change before your collection is updated."));
    content.insertBefore(values, facts);
    content.insertBefore(stock, facts);
    stock.classList.add("owner-item-stock");
    installListingFlow(item,sale,{saleCondition,priceInput,priceLabel,priceBasisNote,save,actions});
  }
  return {image, open, close, reset: () => close(true)};
})();


