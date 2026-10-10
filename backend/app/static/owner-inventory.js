"use strict";

window.DropRateInventory = (() => {
  const el = (tag, cls = "", text = "") => { const n = document.createElement(tag); n.className = cls; n.textContent = text; return n; };
  const button = (label, action, cls = "") => { const n = el("button", cls, label); n.type = "button"; n.addEventListener("click", action); return n; };
  const account = () => state.session?.user?.id || state.session?.access_token;
  let dialog, content, message, selected, revision = 0, busy = false, returnFocus;
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
    revision++; busy = false; selected = null;
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
      el("p", "", [item.game, item.language, conditionLabel(item)].filter(Boolean).join(" · ")),
      el("p", "owner-item-code", item.inventory_code),
      el("span", `owner-status-pill ${statusClass(item.status)}`, item.status));
    if (item.certificate_number) identity.append(el("p", "", `Certificate: ${item.certificate_number}`));
    hero.append(figure, identity); content.append(hero);

    const values = el("section", "owner-item-values");
    values.append(el("div", "", "Market value"), el("strong", "", price(item.market_value_minor)));
    if (item.pricing_method === "CARDMARKET_GUIDE_V1") values.append(el("small", "", "Cardmarket guide estimate"));
    if (item.pricing_updated_at) values.append(el("small", "", `Updated ${new Date(item.pricing_updated_at).toLocaleDateString("en-GB")}`));
    content.append(values);

    const sale = el("section", "owner-item-section"); sale.append(el("h3", "", "Sell on Shopify"));
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
    const actions = el("div", "owner-item-actions");
    const save = button("Save selling price", () => priceAction("selling-price", "PATCH")); save.disabled = !active(item);
    const approve = button(item.seller_approval_available ? "Approve for Shopify" : item.status === "INSPECTION" ? "Update Shopify approval request" : "Approve sale & request review",
      () => priceAction("approval-request", "POST"), "primary"); approve.disabled = !active(item);
    actions.append(save, approve); sale.append(actions);
    const stateLabel = item.shopify_state ? `Shopify: ${item.shopify_state.replaceAll("_", " ")}` : "Not yet published to Shopify";
    sale.append(el("p", "", `${stateLabel} · ${item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "For sale"}`));
    if (item.approval_blockers?.length) {
      sale.append(el("p", "", "Before this copy can be published:"));
      const list = el("ul"); item.approval_blockers.forEach(reason => list.append(el("li", "", reason))); sale.append(list);
    }
    sale.append(el("p", "owner-item-note", item.seller_approval_available
      ? "Approve to confirm that you hold this exact sealed product and want to sell it at this price. We use the catalogue image. Your stock stays with you and syncs automatically."
      : "Your approval saves your selling price and requests Drop Rate review. Approved stock marked For sale syncs automatically."));
    const sync = button("Sync to Shopify", () => run(async () => {
      const result = await apiRequest(`/api/v1/owner/inventory/${item.id}/channels/shopify/sync`, {method: "POST", body: JSON.stringify({version: item.version})});
      return {message: `Shopify: ${result.status.replaceAll("_", " ")}`};
    }));
    sync.disabled = !(item.shopify_sync_enabled && item.status === "APPROVED" && item.sale_intent === "FOR_SALE");
    sale.append(sync);
    if (!item.shopify_sync_enabled) sale.append(el("p", "owner-item-note", "Shopify publishing is currently unavailable."));
    content.append(sale);

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
