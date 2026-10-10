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
  const price = minor => minor == null ? "Value pending" : formatMoney(minor);

  function image(item, cls) {
    const wrap = el("div", cls), placeholder = el("span", "owner-image-placeholder", "Image unavailable");
    wrap.append(placeholder);
    const urls = [...new Set([item.image_url, item.reference_image_url].filter(Boolean))];
    if (!urls.length) return wrap;
    const img = el("img"); img.alt = `${item.name || "Inventory item"} ${item.image_url ? "image" : "catalogue reference"}`;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    const owner = account(); let proxied = false, objectUrl;
    img.addEventListener("load", () => { placeholder.hidden = true; if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; } });
    img.addEventListener("error", async () => {
      if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
      if (urls.length) { img.src = urls.shift(); return; }
      const path = item.reference_image_path;
      if (!proxied && /^\/api\/v1\/owner\/inventory\/[0-9a-f-]+\/reference-image$/.test(path || "")) {
        proxied = true;
        try {
          let response = await fetch(path, {headers: {Authorization: `Bearer ${state.session.access_token}`}});
          if (response.status === 401 && owner === account()) response = await fetch(path, {headers: {Authorization: `Bearer ${await refreshSession()}`}});
          if (!response.ok) throw new Error("Image unavailable");
          const blob = await response.blob();
          if (owner !== account() || !wrap.isConnected) return;
          objectUrl = URL.createObjectURL(blob); img.src = objectUrl; return;
        } catch (_) { /* Keep an explicit placeholder when the provider fails. */ }
      }
      img.remove(); placeholder.hidden = false;
    });
    img.src = urls.shift(); wrap.append(img); return wrap;
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
    content.replaceChildren();
    const hero = el("section", "owner-item-hero"), figure = el("figure");
    figure.append(image(item, "owner-item-art"), el("figcaption", "", item.image_url ? "Inventory / approved catalogue image" : "Catalogue reference · not a photo of your copy"));
    const identity = el("div");
    identity.append(el("h3", "", item.name), el("p", "", inventoryCardSubtitle(item)),
      el("span", `owner-status-pill ${statusClass(item.status)}`, item.status));
    hero.append(figure, identity); content.append(hero);

    // The inventory grid shows only essentials. Exact copy metadata remains
    // available here, including untruncated IDs and grading certificates.
    const facts = el("section", "owner-item-facts");
    facts.append(el("h3", "", "Item information"));
    const list = el("dl", "owner-item-facts-grid");
    const rows = [
      ["Game", item.game],
      ["Set", item.set_name],
      ["Card number", item.card_number],
      ["Language", item.language],
      [item.product_type === "SEALED" ? "Seal" : "Condition", conditionLabel(item)],
      ["Type", inventoryTypeLabel(item)],
      ["Grading company", item.grading_company],
      ["Grade", item.grade],
      ["Certificate", item.certificate_number],
      ["Inventory ID", item.inventory_code],
    ];
    for (const [labelText, valueText] of rows) {
      if (valueText == null || String(valueText).trim() === "") continue;
      const pair = el("div", "owner-item-fact");
      pair.append(el("dt", "", labelText), el("dd", "", String(valueText)));
      list.append(pair);
    }
    facts.append(list); content.append(facts);

    const values = el("section", "owner-item-values");
    values.append(el("div", "", "Market value"), el("strong", "", price(item.market_value_minor)));
    if (item.pricing_method === "CARDMARKET_GUIDE_V1") values.append(el("small", "", "Cardmarket guide estimate"));
    if (item.pricing_updated_at) values.append(el("small", "", `Updated ${new Date(item.pricing_updated_at).toLocaleDateString("en-GB")}`));
    content.append(values);

    const publishedOnShopify=item.shopify_state==="PUBLISHED";
    const approvedForSale=item.status==="APPROVED" && item.sale_intent==="FOR_SALE";
    const sale = el("section", "owner-item-section");
    sale.append(el("h3", "", "Selling price"));
    const priceLabel = el("label", "", "Your selling price (£)"), priceInput = el("input");
    priceInput.type = "number"; priceInput.min = "1"; priceInput.step = "0.01"; priceInput.inputMode = "decimal";
    priceInput.value = item.store_price_minor == null ? "" : (item.store_price_minor / 100).toFixed(2);
    priceInput.setAttribute("aria-label", "Your selling price in pounds"); priceInput.disabled = !active(item);
    priceLabel.append(priceInput); sale.append(priceLabel);
    const value = () => {
      if (!/^\d+(\.\d{1,2})?$/.test(priceInput.value) || Number(priceInput.value) < 1 || Number(priceInput.value) > 1_000_000) {
        throw new Error("Enter a selling price of at least £1, with no more than two decimal places.");
      }
      return Math.round(Number(priceInput.value) * 100);
    };
    const priceAction = (path, method) => {
      let minor; try { minor = value(); } catch (error) { status(error.message, true); priceInput.focus(); return; }
      run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/${path}`, {method, body: JSON.stringify({version: item.version, store_price_minor: minor})}));
    };
    const actions=el("div","owner-item-actions");
    const save=button("Save selling price",()=>priceAction("selling-price","PATCH"));
    save.disabled=!active(item);
    actions.append(save);
    // Approval is only needed before publication. A published pack should
    // never be offered a second "Approve" action.
    if(!publishedOnShopify && !approvedForSale){
      const approve=button(
        item.seller_approval_available?"Approve for Shopify":
        item.status==="INSPECTION"?"Update Shopify approval request":"Approve sale & request review",
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
        sale.append(el("p","","Before this copy can be published:"));
        const list=el("ul");
        item.approval_blockers.forEach(reason=>list.append(el("li","",reason)));
        sale.append(list);
      }
      if(!approvedForSale) {
        sale.append(el("p","owner-item-note",item.seller_approval_available
          ?"Approve to confirm that you hold this exact sealed product and want to sell it. Your stock stays with you and uses the approved catalogue image."
          :"Approval saves your selling price and requests Drop Rate review. Approved For Sale stock can then sync to Shopify."));
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
    const ebayReason=item.product_type!=="CARD"?"Sealed packs aren't supported yet":
      item.is_consignment?"Consignor sync isn't supported yet":
      !ebay.connected?"eBay account not connected":
      !ebay.sync_enabled?"Seller publishing not enabled":
      !approvedForSale?"Approval required":"Ready to sync";
    const cards=[
      {
        code:"SHOPIFY",label:"Shopify",state:publishedOnShopify?"Published":
          !item.shopify_sync_enabled?"Unavailable":
          !approvedForSale?"Awaiting approval":"Ready to sync",
        action:!publishedOnShopify && item.shopify_sync_enabled && approvedForSale?"Sync to Shopify":null,
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
        state:"Personal seller connection awaiting Whatnot API access",
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
      "eBay: "+ebayReason+". Whatnot direct seller-account authorisation is currently unavailable; your account will not be linked to Drop Rate’s Shopify admin."));
    content.append(sellerChannels);

    const stock = el("section", "owner-item-section"); stock.append(el("h3", "", "Quantity"));
    stock.append(el("p", "", `${copies.length} ${copies.length === 1 ? "copy" : "copies"} in your active inventory`));
    if (copies.length > 1) {
      const label = el("label", "", "Choose the copy to manage"), select = el("select");
      select.setAttribute("aria-label", "Choose inventory copy");
      copies.forEach(copy => { const option = el("option", "", `${copy.inventory_code} · ${copy.status}`); option.value = copy.id; select.append(option); });
      select.value = item.id; select.addEventListener("change", () => open({id: select.value})); label.append(select); stock.append(label);
    }
    const controls = el("div", "owner-item-quantity"), confirmation = el("div", "owner-item-confirmation");
    const add = button("+", () => {
      confirmation.replaceChildren(el("p", "", `Add one more ${item.language} copy in the same condition?`),
        button("Confirm additional copy", () => {
          const storageKey = `drop_rate_copy:${account()}:${item.id}`;
          let pending; try { pending = JSON.parse(sessionStorage.getItem(storageKey)); } catch (_) { /* replace corrupt pending data */ }
          pending ||= {key: crypto.randomUUID(), version: item.version};
          sessionStorage.setItem(storageKey, JSON.stringify(pending));
          run(async () => {
            const result = await apiRequest(`/api/v1/owner/inventory/${item.id}/copies`, {method: "POST", headers: {"Idempotency-Key": pending.key}, body: JSON.stringify({version: pending.version, confirmed: true})});
            sessionStorage.removeItem(storageKey); return result;
          });
        }, "primary"));
    });
    add.setAttribute("aria-label", "Increase quantity by one");
    add.disabled = !active(item) || Boolean(item.grading_company || item.grade || item.certificate_number);
    const remove = button("−", () => {
      confirmation.replaceChildren(el("p", "", `Withdraw ${item.inventory_code} from active inventory and any sales channels?`),
        button("Withdraw this copy", () => run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/withdraw`, {method: "POST", body: JSON.stringify({version: item.version})})), "danger"));
    });
    remove.setAttribute("aria-label", "Decrease quantity by withdrawing this copy"); remove.disabled = !active(item);
    controls.append(remove, el("strong", "", String(copies.length)), add); stock.append(controls, confirmation);
    stock.append(el("p", "owner-item-note", item.grading_company ? "Add graded slabs through Scan using each slab’s own certificate." : "Additional copies need their own sale approval. Withdrawing a copy keeps its history."));
    content.append(stock);
  }
  return {image, open, close, reset: () => close(true)};
})();
