"use strict";

window.DropRateInventory = (() => {
  const el = (tag, cls = "", text = "") => { const n = document.createElement(tag); n.className = cls; n.textContent = text; return n; };
  const button = (label, action, cls = "") => { const n = el("button", cls, label); n.type = "button"; n.addEventListener("click", action); return n; };
  const account = () => state.session?.user?.id || state.session?.access_token;
  let dialog, content, message, selected, revision = 0, busy = false, returnFocus, channels = [];
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

  function image(item, cls) {
    const wrap = el("div", cls), placeholder = el("span", "owner-image-placeholder", "Loading image…");
    const img = el("img");
    img.alt = `${item.name || "Inventory item"} reference image`;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    wrap.append(placeholder, img);
    const owner = account(), attempts = [];
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
    const direct = directUrl(item.image_url);
    if (direct) attempts.push({url: direct});
    if (validId) attempts.push({path: `/api/v1/inventory/${inventoryId}/image`});
    const reference = directUrl(item.reference_image_url);
    if (reference && reference !== direct) attempts.push({url: reference});
    const referencePath = `/api/v1/owner/inventory/${inventoryId}/reference-image`;
    if (validId && item.reference_image_path === referencePath) attempts.push({path: referencePath});
    let index = 0, objectUrl = null, loading = false, started = false;
    const current = () => owner === account() && wrap.isConnected;
    const release = () => {if (objectUrl) {URL.revokeObjectURL(objectUrl); objectUrl = null;}};
    const unavailable = () => {release(); img.remove(); placeholder.textContent = "Image unavailable"; placeholder.hidden = false;};
    async function next() {
      if (loading || !current()) return;
      release();
      while (index < attempts.length && current()) {
        const attempt = attempts[index++];
        if (attempt.url) {img.src = attempt.url; return;}
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
    revision++; busy = false; selected = null; channels = [];
    if (dialog?.open) dialog.close();
    content?.replaceChildren(); returnFocus?.focus();
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

  async function open(item) {
    if (!item?.id || busy) return;
    ensureDialog(); returnFocus = document.activeElement;
    if (!dialog.open) dialog.showModal();
    const rev = ++revision, owner = account(); selected = item;
    content.replaceChildren(); status("Loading item details…");
    try {
      const data = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(item.id)}`);
      if (!alive(rev, owner)) return;
      // Reuse the owner-scoped channel dashboard snapshot; never block item
      // details on an unrelated provider connection or a slow external API.
      channels=state.ownerChannelAccount===owner && Array.isArray(state.ownerChannelSummaries)
        ?state.ownerChannelSummaries:[];
      selected = data.item; render(data); status("");
    } catch (error) { if (alive(rev, owner)) status(error.message, true); }
  }

  async function run(action) {
    if (busy || !selected) return;
    busy = true;
    const rev = revision, owner = account(), id = selected.id;
    dialog.querySelectorAll("button,input,select").forEach(n => { n.disabled = true; });
    status("Saving…");
    let result, failure;
    try { result = await action(); } catch (error) { failure = error; }
    if (!alive(rev, owner)) return;
    // Re-read even after a partial remote failure: local sale protection may
    // already have committed. Never keep acting on the previous version.
    try {
      const data = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(id)}`);
      if (!alive(rev, owner)) return;
      selected = data.item; busy = false; render(data);
    } catch (_) {
      busy = false; content.replaceChildren(button("Reload item", () => open({id})));
    }
    if (alive(rev, owner)) {
      dialog.querySelector("header button").disabled = false;
      status(failure ? failure.message : result?.message || "Saved.", Boolean(failure));
      await Promise.allSettled([loadOwnerInventory(), loadOwnerOverview(), loadOwnerChannels(), loadOwnerInsights()]);
    }
  }

  function render(data) {
    const item = data.item, copies = data.copies || [];
    const sellingOpen = content.querySelector(".owner-item-selling")?.open === true;
    content.replaceChildren();
    const hero = el("section", "owner-item-hero"), figure = el("figure");
    figure.append(image(item, "owner-item-art"), el("figcaption", "", item.image_url ? "Item image" : "Reference image · not a photo of your copy"));
    const identity = el("div");
    identity.append(el("h3", "", item.name), el("p", "", inventoryCardSubtitle(item)),
      el("span", `owner-status-pill ${statusClass(item.status)}`, collectionStatus(item)));
    hero.append(figure, identity); content.append(hero);

    // The inventory grid shows only essentials. Exact copy metadata remains
    // available here, including untruncated IDs and grading certificates.
    const facts = el("details", "owner-item-facts owner-item-section");
    facts.append(el("summary", "", "Item details"));
    const list = el("dl", "owner-item-facts-grid");
    const rows = [
      [item.product_type === "COMIC" ? "Category" : "Game", item.game],
      [item.product_type === "COMIC" ? "Series / edition" : "Set", item.set_name],
      [item.product_type === "COMIC" ? (item.game === "Manga" ? "Volume" : "Issue / book number") : "Card number", item.card_number],
      ["Language", item.language],
      [item.product_type === "SEALED" ? "Seal" : "Condition", conditionLabel(item)],
      ["Type", inventoryTypeLabel(item)],
      ["Grading company", item.grading_company],
      ["Grade", item.grade],
      ["Certificate", item.certificate_number],
      ["Inventory ID", item.inventory_code],
    ];
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
    values.append(el("div", "", "Market value"), el("strong", "", item.reference_value ? window.DropRateReferenceValue.text(item, formatMoney) : price(item.market_value_minor)));
    if (item.reference_value) values.append(el("small", "", window.DropRateReferenceValue.description(item)));
    if (!item.reference_value && item.pricing_method === "CARDMARKET_GUIDE_V1") values.append(el("small", "", "Cardmarket guide estimate"));
    if (item.pricing_updated_at) values.append(el("small", "", `Updated ${new Date(item.pricing_updated_at).toLocaleDateString("en-GB")}`));
    content.append(values);
    const recommended = window.DropRateReferenceValue?.recommendedMinor(item) ?? null;
    const recommendationNote = el("p", "owner-item-note",
      "Recommended retail: " + (window.DropRateReferenceValue?.recommendationText(item, formatMoney) || "Recommendation unavailable"));
    recommendationNote.dataset.recommendedRetail = "true";


    const publishedOnShopify=item.shopify_state==="PUBLISHED";
    const approvedForSale=item.status==="APPROVED" && item.sale_intent==="FOR_SALE";
    const sale = el("details", "owner-item-section owner-item-selling");
    sale.open = sellingOpen;
    sale.append(el("summary", "", publishedOnShopify ? "Manage listing" : "Sell this item"));
    sale.append(el("p", "owner-item-note", "Choose a price and condition when you’re ready to sell."));
    sale.append(recommendationNote);
    let saleCondition;
    if (["CARD", "COMIC"].includes(item.product_type) && !item.grading_company && ["DRAFT", "INSPECTION"].includes(item.status)) {
      const label = el("label", "", "Condition when selling"); saleCondition = el("select");
      saleCondition.setAttribute("aria-label", "Condition when selling");
      const conditions = item.product_type === "COMIC" ? ["", "Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor"] : ["", "Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
      for (const value of conditions) {
        const option = el("option", "", value || "Choose condition"); option.value = value; saleCondition.append(option);
      }
      saleCondition.value = item.condition || ""; label.append(saleCondition); sale.append(label);
    }
    const priceLabel = el("label", "", "Your selling price (£)"), priceInput = el("input");
    priceInput.type = "number"; priceInput.min = "1"; priceInput.step = "0.01"; priceInput.inputMode = "decimal";
    const initialPrice = item.store_price_minor ?? recommended;
    priceInput.value = initialPrice == null ? "" : (initialPrice / 100).toFixed(2);
    let suggestionPrefilled = item.store_price_minor == null && recommended != null;
    let priceEdited = false;
    const recommendationText = recommendationNote.textContent;
    priceInput.addEventListener("input", () => { suggestionPrefilled = false; priceEdited = true; });
    if (saleCondition) saleCondition.addEventListener("change", () => {
      const guide = item.reference_value?.status === "REFERENCE_ESTIMATE";
      const sameBasis = guide ? ["", "Near Mint"].includes(saleCondition.value)
        : saleCondition.value === (item.condition || "");
      if (!sameBasis && suggestionPrefilled) { priceInput.value = ""; suggestionPrefilled = false; }
      recommendationNote.textContent = sameBasis ? recommendationText
        : "Recorded-condition recommendation does not apply to the newly selected condition.";
      if (sameBasis && !priceEdited && item.store_price_minor == null && recommended != null) {
        priceInput.value = (recommended / 100).toFixed(2);
        suggestionPrefilled = true;
      }
    });
    priceInput.setAttribute("aria-label", "Your selling price in pounds"); priceInput.disabled = !active(item);
    priceLabel.append(priceInput); sale.append(priceLabel);
    if (recommended != null) sale.append(el("p", "owner-item-note",
      item.store_price_minor == null
        ? "Suggested automatically from current shared evidence. Nothing is saved or listed until you choose a selling action."
        : "Your saved asking price is retained. The automatic recommendation does not overwrite it."));
    const value = () => {
      if (!/^\d+(\.\d{1,2})?$/.test(priceInput.value) || Number(priceInput.value) < 1 || Number(priceInput.value) > 1_000_000) {
        throw new Error("Enter a selling price of at least £1, with no more than two decimal places.");
      }
      return Math.round(Number(priceInput.value) * 100);
    };
    const priceAction = (path, method) => {
      let minor; try { minor = value(); } catch (error) { status(error.message, true); priceInput.focus(); return; }
      if (path === "approval-request" && saleCondition && !saleCondition.value) {
        status("Choose the condition for your listing. The card is already saved in inventory.", true); saleCondition.focus(); return;
      }
      const body = {version: item.version, store_price_minor: minor};
      if (path === "approval-request" && saleCondition) body.condition = saleCondition.value;
      run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/${path}`, {method, body: JSON.stringify(body)}));
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
      if(item.approval_blockers?.length){
        sale.append(el("p","","Known next steps before selling (channel checks run again before publication):"));
        const list=el("ul");
        const wording={"Drop Rate intake review":"We need to check this item before it can be listed", "An approved listing photo":"Add a clear photo for the listing", "Identity confirmation":"Check that the item details are correct"};
        item.approval_blockers.forEach(reason=>list.append(el("li","",wording[reason] || reason)));
        sale.append(list);
      }
      if(!approvedForSale) {
        sale.append(el("p","owner-item-note",item.seller_approval_available
          ?"List on Shopify confirms that you hold this exact sealed product and want it offered for sale. Your stock stays with you and uses approved catalogue artwork."
          :"This selling request is separate from adding the card. Drop Rate selling review still applies to this item; approval can then trigger Shopify publication."));
      }
      if(!item.shopify_sync_enabled) sale.append(el("p","owner-item-note","Shopify publishing is currently unavailable."));
    }
    content.append(sale);

    const sellerChannels=el("section","owner-item-section owner-channel-section");
    sellerChannels.append(el("h3","","Selling channels"));
    const channelGrid=el("div","owner-item-channels");
    const ebay=channels.find(row=>row.code==="EBAY")||{};
    const ebayEligible=Boolean(ebay.connected && ebay.sync_enabled) &&
      !item.is_consignment && item.product_type==="CARD" && approvedForSale;
    const ebayReason=item.product_type!=="CARD"?(item.product_type === "COMIC" ? "Comics and manga aren't supported here yet" : "Sealed packs aren't supported yet"):
      item.is_consignment?"Consignor sync isn't supported yet":
      !ebay.connected?"eBay account not connected":
      !ebay.sync_enabled?"Seller publishing not enabled":
      !approvedForSale?"Approval required":"Ready to sync";
    const cards=[
      {
        code:"SHOPIFY",label:"Shopify",state:publishedOnShopify?"Published":
          !item.shopify_sync_enabled?"Unavailable":
          !approvedForSale?"Not listed — use List for sale":"Awaiting channel checks",
        action:!publishedOnShopify && item.shopify_sync_enabled && approvedForSale?"Check & sync to Shopify":null,
        click:()=>run(async()=>{
          const result=await apiRequest(`/api/v1/owner/inventory/${item.id}/channels/shopify/sync`,
            {method:"POST",body:JSON.stringify({version:item.version})});
          return {message:"Shopify: "+result.status.replaceAll("_"," ")};
        })
      },
      {
        code:"EBAY",label:"eBay",state:ebayReason,
        action:ebayEligible?"Sync to eBay":null,
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
        const availability=el("span","owner-item-channel-availability",channel.code==="SHOPIFY" && publishedOnShopify
          ?"Already live":"Not available yet");
        availability.setAttribute("aria-label",channel.code==="SHOPIFY" && publishedOnShopify
          ?"Already published on Shopify":"No publishing action available for "+channel.label);
        block.append(availability);
      }
      channelGrid.append(block);
    }
    sellerChannels.append(channelGrid);
    if(!ebayEligible) sellerChannels.append(el("p","owner-item-channel-footnote",
      "eBay: "+ebayReason+". Whatnot is not connected in this workflow. No seller is given access to Shopify Admin."));
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
      select.value = item.id; select.addEventListener("change", () => open({id: select.value})); label.append(select); stock.append(label);
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
        confirmation.append(el("p", "", `Withdraw ${item.inventory_code} from your physical stock and its selling channels? The exact copy's history will be kept.`));
        actions.append(button("Withdraw this copy", () => run(() =>
          apiRequest(`/api/v1/owner/inventory/${item.id}/withdraw`, {
            method: "POST", body: JSON.stringify({version: item.version})
          })), "danger"));
      }
      actions.append(button("Cancel change", resetQuantity));
      confirmation.append(actions);
    };
    add = button("+", () => { if (delta < 1) { delta++; updateQuantity(); } });
    add.setAttribute("aria-label", "Increase quantity by one");
    remove = button("−", () => { if (delta > -1) { delta--; updateQuantity(); } });
    remove.setAttribute("aria-label", "Decrease quantity by withdrawing this copy");
    controls.append(remove, quantity, add);
    stock.append(controls, feedback, confirmation);
    updateQuantity();
    stock.append(el("p", "owner-item-note",
      item.grading_company
        ? (item.product_type === "COMIC" ? "Add each graded book through Comic / manga with its own certificate. Withdrawing a copy keeps its history." : "Add each graded slab through Scan with its own certificate. Withdrawing a copy keeps its history.")
        : "Change the quantity, then confirm to save it."));
    content.insertBefore(values, facts);
    content.insertBefore(stock, facts);
  }
  return {image, open, close, reset: () => close(true)};
})();
