"use strict";

/* Owner-only Seller Hub fulfilment wizard. The packing slip comes from exact
   live Shopify Order line items and is printed locally, without buyer PII.
   The carrier label comes from Shopify Shipping ONLY after purchase, which
   is not enabled in this release. Never invent a label, price or dispatch. */
(() => {
  const el = (id) => document.getElementById(id);
  const template = el("owner-fulfill-template");
  const state = {item: null, revision: 0, packingAllowed: false};
  if (!template) return;
  let dialog = null;
  let summary = null;
  let blockers = null;
  let printPacking = null;
  let printLabel = null;
  let confirm = null;

  function ensureDialog() {
    if (dialog) return dialog;
    // Delayed creation means inventory/scanner dialogs retain their existing
    // DOM order and event handling until a seller explicitly clicks Fulfill.
    dialog = template.content.firstElementChild.cloneNode(true);
    document.body.append(dialog);
    summary = el("owner-fulfill-item-summary");
    blockers = el("owner-fulfill-blockers");
    printPacking = el("owner-fulfill-print-packing");
    printLabel = el("owner-fulfill-print-label");
    confirm = el("owner-fulfill-confirm");
    installDialogHandlers();
    return dialog;
  }

  const text = (id, value) => {el(id).textContent = String(value ?? "");};
  const node = (type, value, className = "") => {
    const result = document.createElement(type);
    if (className) result.className = className;
    result.textContent = String(value ?? "");
    return result;
  };
  const blockerCopy = {
    SHOPIFY_ORDER_CANCELLED: "Shopify cancelled this order.",
    SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED: "Shopify payment is not verified.",
    SHOPIFY_ORDER_ALREADY_FULFILLED: "Shopify already completed the fulfilment.",
    ORDER_REFUND_REVIEW_REQUIRED: "The order was refunded or changed.",
    LOCAL_PARTIAL_REFUND_REVIEW_REQUIRED: "A refund requires manual review.",
    PHYSICAL_INVENTORY_STATE_MISMATCH: "The physical card has a stock-state mismatch.",
    SHOPIFY_ALLOCATION_INCOMPLETE: "Shopify order mapping needs review.",
    LOCAL_OWNER_ALLOCATION_MISMATCH: "Your item allocation does not match Shopify.",
    FULFILMENT_ORDER_NOT_OPEN: "This Shopify fulfilment is not open.",
    FULFILMENT_MIXED_OWNER_OR_QUANTITY_SPLIT_REQUIRED: "This Shopify order needs splitting by dispatching seller.",
    PHYSICAL_SHIPPER_UNVERIFIED: "Your physical shipping location needs verification.",
    CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED: "Carrier label purchase is not enabled.",
    SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING: "The actual carrier cost and purchase record must be verified.",
    INTERNATIONAL_CUSTOMS_AND_INSURANCE_REVIEW: "Customs or insurance verification is required.",
  };
  const fatalForPacking = new Set([
    "SHOPIFY_ORDER_CANCELLED", "SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED",
    "SHOPIFY_ORDER_ALREADY_FULFILLED", "LOCAL_PARTIAL_REFUND_REVIEW_REQUIRED",
    "ORDER_REFUND_REVIEW_REQUIRED", "PHYSICAL_INVENTORY_STATE_MISMATCH",
    "SHOPIFY_ALLOCATION_INCOMPLETE", "LOCAL_OWNER_ALLOCATION_MISMATCH",
    "FULFILMENT_ORDER_NOT_OPEN", "FULFILMENT_ALREADY_DISPATCHED_OR_RESERVED",
  ]);

  function close() {
    state.revision++;
    if (!dialog) return;
    state.item = null;
    state.packingAllowed = false;
    printPacking.disabled = true;
    printLabel.disabled = true;
    confirm.disabled = true;
    summary.replaceChildren();
    blockers.replaceChildren();
    if (dialog.open) dialog.close();
  }

  function markBlockers(codes) {
    blockers.replaceChildren();
    for (const code of codes || []) {
      blockers.append(node("li", blockerCopy[code] || "Shopify verification requires review."));
    }
  }

  async function openFor(item) {
    if (!item || !/^[0-9a-f-]{36}$/i.test(String(item.order_item_id || ""))) return;
    ensureDialog();
    const revision = ++state.revision;
    state.item = item;
    state.packingAllowed = false;
    printPacking.disabled = true;
    printLabel.disabled = true;
    confirm.disabled = true;
    text("owner-fulfill-title", "Fulfill " + (item.order_number || "Shopify order"));
    text("owner-fulfill-caption", "Verify your own stock and prepare printable documents.");
    summary.replaceChildren(
      node("strong", [item.card_name, item.card_number ? "#" + item.card_number : ""].filter(Boolean).join(" ")),
      node("span", item.inventory_code || "Unique physical item"),
    );
    blockers.replaceChildren();
    text("owner-fulfill-status", "Checking the latest payment and fulfilment state directly with Shopify…");
    if (!dialog.open) dialog.showModal();
    try {
      const checked = await apiRequest(
        `/api/v1/fulfilment/to-ship/${encodeURIComponent(item.order_item_id)}/shopify`
      );
      if (revision !== state.revision || !dialog.open) return;
      const reasons = Array.isArray(checked.blockers) ? checked.blockers : [];
      markBlockers(reasons);
      const eligible = checked.shopify_connected === true
        && String(item.order_status).toUpperCase() === "PAID"
        && !reasons.some((reason) => fatalForPacking.has(reason));
      state.packingAllowed = eligible;
      printPacking.disabled = !eligible;
      text("owner-fulfill-status",
        eligible
          ? "Shopify order verified. You can print a seller-only packing slip. Label purchasing and dispatch remain locked."
          : "This order needs verification before anything can be printed or dispatched."
      );
    } catch (_error) {
      if (revision !== state.revision || !dialog.open) return;
      markBlockers(["SHOPIFY_CHECK_UNAVAILABLE"]);
      text("owner-fulfill-status", "Shopify could not verify this order. Nothing has been purchased or fulfilled.");
    }
  }

  function preparePrintableDocument(pop, slip) {
    const d = pop.document;
    d.title = "Drop Rate packing slip - " + slip.order_number;
    d.head.replaceChildren();
    d.body.replaceChildren();
    const style = d.createElement("style");
    style.textContent = `
      @page{size:A4;margin:18mm}
      *{box-sizing:border-box}
      body{margin:0;font:14px/1.5 system-ui,-apple-system,sans-serif;color:#13294a}
      header{display:flex;justify-content:space-between;align-items:end;border-bottom:3px solid #103e80;padding-bottom:14px;margin-bottom:26px}
      h1{margin:0;font-size:26px;letter-spacing:-.04em}
      h2{font-size:16px;margin:0 0 8px}
      small{color:#697a91}
      .pill{font-weight:700;background:#edf4fe;border-radius:8px;padding:7px 10px}
      table{border-collapse:collapse;width:100%;margin-top:12px}
      th,td{padding:11px 9px;text-align:left;border-bottom:1px solid #d7e1ed}
      th{background:#f4f7fc;color:#31547e}
      td:last-child,th:last-child{text-align:right}
      .notice{color:#61738a;margin-top:30px}
      footer{margin-top:70px;padding-top:14px;border-top:1px solid #d7e1ed;font-size:11px;color:#6a7f99}
      @media print{button{display:none}}
    `;
    d.head.append(style);
    const header=d.createElement("header");
    const brand=d.createElement("div");
    brand.append(node("h1", "DROP RATE"), node("small", "Packing slip · Shopify order"));
    header.append(brand,node("div", slip.order_number, "pill"));
    d.body.append(header);
    d.body.append(node("h2","Items in this seller's parcel"));
    const table=d.createElement("table");
    const thead=d.createElement("thead"),row=d.createElement("tr");
    for(const t of ["Shopify product","SKU","Inventory ID","Qty"])row.append(node("th",t));
    thead.append(row);table.append(thead);
    const tbody=d.createElement("tbody");
    for(const item of slip.items){
      const tr=d.createElement("tr");
      for(const k of ["title","sku","inventory_id","quantity"])tr.append(node("td",item[k]||"—"));
      tbody.append(tr);
    }
    table.append(tbody);d.body.append(table);
    d.body.append(node("p",slip.notice || "Pack only the listed items.", "notice"));
    d.body.append(node("footer",
      "Packed by the responsible Drop Rate seller · Destination is printed on the official Shopify Shipping carrier label."
    ));
  }

  function installDialogHandlers() {
    printPacking.addEventListener("click", async () => {
    if (!state.packingAllowed || !state.item || !dialog.open) return;
    const rev = state.revision;
    // Open synchronously in the actual user gesture; avoid popup blocking.
    const pop = window.open("", "_blank");
    if (!pop) {
      text("owner-fulfill-status","Allow pop-ups to print your Shopify packing slip.");
      return;
    }
    try {
      pop.opener = null;
      pop.document.body.textContent = "Checking Shopify and preparing your packing slip…";
      printPacking.disabled = true;
      const slip = await apiRequest(
        `/api/v1/fulfilment/to-ship/${encodeURIComponent(state.item.order_item_id)}/packing-slip`
      );
      if (rev !== state.revision || !dialog.open) { pop.close(); return; }
      if (slip.source !== "SHOPIFY_ADMIN_ORDER" ||
          slip.document_type !== "OWNER_PACKING_SLIP" ||
          slip.customer_personal_data_included !== false ||
          !Array.isArray(slip.items) || !slip.items.length) {
        throw new Error("Shopify packing-slip verification incomplete");
      }
      preparePrintableDocument(pop, slip);
      pop.focus();
      if (typeof pop.print === "function") pop.print();
      text("owner-fulfill-status",
        "Packing slip prepared from your Shopify order. Printing does not purchase postage or mark items fulfilled."
      );
    } catch (_error) {
      pop.close();
      if (rev === state.revision && dialog.open) {
        text("owner-fulfill-status",
          "Shopify couldn't prepare the slip. No label was bought and no order was fulfilled."
        );
      }
    } finally {
      if (rev === state.revision && dialog.open) printPacking.disabled = false;
    }
  });

  el("owner-fulfill-close").addEventListener("click",close);
  dialog.addEventListener("cancel", (event)=>{event.preventDefault();close();});
  }
  document.addEventListener("seller-fulfillment-open", (event) => {
    openFor(event.detail?.item);
  });
  document.addEventListener("owner-view-changed",(event)=>{
    if(event.detail?.view !== "sales")close();
  });
  el("owner-logout-button")?.addEventListener("click",close,{capture:true});
})();
