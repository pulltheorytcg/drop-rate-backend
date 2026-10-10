"use strict";

/* Seller Hub Sales → To ship. Every row is a physical owner allocation, not
   the entire Shopify order. Never fetch buyer addresses or imply that a
   carrier label or tracking has been created. */
(() => {
  const ids = {
    panel: "owner-dispatch-review",
    total: "owner-dispatch-count",
    list: "owner-dispatch-list",
    status: "owner-dispatch-message",
    previous: "owner-dispatch-prev",
    next: "owner-dispatch-next",
    page: "owner-dispatch-page",
    refresh: "owner-dispatch-refresh",
    verifyShopify: "owner-dispatch-shopify-check",
    shopifyStatus: "owner-dispatch-shopify-status",
  };
  const reasonLabels = {
    ORDER_REFUND_REVIEW_REQUIRED: "Refund review needed",
    PHYSICAL_INVENTORY_STATE_MISMATCH: "Physical inventory requires review",
    SHOPIFY_ALLOCATION_INCOMPLETE: "Shopify item allocation requires review",
    PHYSICAL_SHIPPER_UNVERIFIED: "Sender / custody not verified",
    CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED: "Label and tracking connection pending",
    SHOPIFY_ORDER_CANCELLED: "Shopify cancelled this order",
    SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED: "Shopify payment is not verified",
    SHOPIFY_ORDER_ALREADY_FULFILLED: "Already fulfilled on Shopify",
    SHOPIFY_LINE_ITEMS_TRUNCATED: "Shopify order details require further review",
    SHOPIFY_FULFILMENT_ORDERS_TRUNCATED: "Shopify fulfilment list requires review",
    LOCAL_OWNER_ALLOCATION_MISMATCH: "Owner's physical allocation mismatch",
    FULFILMENT_ORDER_NOT_UNIQUE: "Shopify fulfilment needs manual review",
    FULFILMENT_ORDER_WRONG_ORDER: "Shopify order reference mismatch",
    FULFILMENT_ORDER_NOT_OPEN: "Shopify fulfilment no longer open",
    FULFILMENT_SHIPPING_ORIGIN_OR_DESTINATION_MISSING: "Shipping origin or destination incomplete",
    FULFILMENT_LINES_TRUNCATED: "Shopify fulfilment line count requires review",
    FULFILMENT_NON_SHIPPING_OR_INVALID_QUANTITY: "Fulfilment quantities require review",
    FULFILMENT_ALREADY_DISPATCHED_OR_RESERVED: "Already dispatched or reserved on Shopify",
    FULFILMENT_MIXED_OWNER_OR_QUANTITY_SPLIT_REQUIRED: "Separate seller parcels need a Shopify fulfilment split",
    INTERNATIONAL_CUSTOMS_AND_INSURANCE_REVIEW: "Customs and insurance review required",
    SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING: "Carrier cost approval and duplicate-purchase protection pending",
    LOCAL_PARTIAL_REFUND_REVIEW_REQUIRED: "Refund requires manual review",
  };
  const page = {offset: 0, limit: 25, total: 0};
  let authenticated = false;
  let generation = 0;

  const element = (id) => document.getElementById(id);
  const visible = () => {
    const panel = document.getElementById("owner-view-sales");
    return authenticated && panel && !panel.classList.contains("hidden");
  };
  const clear = (node) => { if (node) node.replaceChildren(); };
  const itemText = (node, value) => { node.textContent = String(value ?? ""); return node; };
  const tag = (name, className, value) => {
    const node = document.createElement(name);
    if (className) node.className = className;
    return itemText(node, value);
  };
  const currency = (minor) => new Intl.NumberFormat("en-GB", {
    style: "currency", currency: "GBP",
  }).format((Number(minor) || 0) / 100);
  const heading = (entry) => {
    const value = [entry.card_name, entry.card_number ? "#" + entry.card_number : ""]
      .filter(Boolean).join(" ");
    return value || entry.inventory_code || "Physical item";
  };

  function renderPagination() {
    const start = page.total ? page.offset + 1 : 0;
    const end = Math.min(page.offset + page.limit, page.total);
    itemText(element(ids.page), page.total ? `${start}–${end} of ${page.total} items` : "0 items");
    element(ids.previous).disabled = page.offset === 0;
    element(ids.next).disabled = page.offset + page.limit >= page.total;
  }

  function renderResult(result) {
    const rows = Array.isArray(result.items) ? result.items : [];
    const list = element(ids.list);
    clear(list);
    page.total = Math.max(0, Number(result.total || 0));
    const unavailable = [
      result.capabilities?.carrier_label_purchase,
      result.capabilities?.dispatch_confirmation,
      result.capabilities?.shopify_tracking_sync,
    ].some((enabled) => enabled !== false);
    // Never display a fake operational control if the backend contract changed.
    if (unavailable) {
      itemText(element(ids.status), "Shipping capability changed. Contact Drop Rate before dispatch.");
      renderPagination();
      return;
    }
    itemText(element(ids.total), String(page.total));
    if (!rows.length) {
      list.append(tag("p", "owner-dispatch-empty",
        "No paid Shopify order items currently require dispatch review."));
      itemText(element(ids.status),
        "When a Shopify purchase is recorded against your physical stock, it will appear here. Carrier labels are not yet connected.");
      renderPagination();
      return;
    }
    itemText(element(ids.status),
      "These are your allocated items only. Shipment labels, buyer addresses and Shopify dispatch confirmation are not yet enabled.");
    for (const entry of rows) {
      const card = document.createElement("article");
      card.className = "owner-dispatch-item";
      const head = document.createElement("div");
      head.className = "owner-dispatch-item-head";
      head.append(
        tag("strong", "", entry.order_number || "Shopify order"),
        tag("span", "owner-dispatch-pill", "Requires review")
      );
      card.append(head);
      card.append(tag("div", "owner-dispatch-product", heading(entry)));
      card.append(tag("div", "owner-dispatch-meta",
        [entry.inventory_code, entry.set_name, currency(entry.net_sale_minor)]
          .filter(Boolean).join(" · ")));
      const reasons = Array.isArray(entry.blockers) ? entry.blockers : [];
      const detail = document.createElement("ul");
      detail.className = "owner-dispatch-blockers";
      for (const reason of reasons) {
        detail.append(tag("li", "", reasonLabels[reason] || "Dispatch verification required"));
      }
      card.append(detail);

      // This is a real Shopify read-only check. No "Buy" or "Dispatch"
      // affordance may be shown before a separately approved cost-backed
      // purchase journal and physical-custody verification exist.
      if (/^[0-9a-f-]{36}$/i.test(String(entry.order_item_id || ""))) {
        const button = tag("button", "owner-dispatch-remote-check", "Check Shopify");
        button.type = "button";
        const remote = tag("p", "owner-dispatch-remote-status", "");
        button.addEventListener("click", async () => {
          if (!visible()) return;
          const sequence = generation;
          button.disabled = true;
          itemText(remote, "Checking this exact order and remaining Shopify fulfilment quantity…");
          try {
            const data = await apiRequest(
              `/api/v1/fulfilment/to-ship/${encodeURIComponent(entry.order_item_id)}/shopify`
            );
            if (sequence !== generation || !visible() || !card.isConnected) return;
            const detailReasons = Array.isArray(data.blockers) ? data.blockers : [];
            const summaries = detailReasons.map((reason) =>
              reasonLabels[reason] || "Dispatch verification required"
            );
            itemText(remote,
              data.shopify_connected === true
                ? `Shopify checked · ${summaries.join(" · ") || "Review required"} · No label purchased`
                : "Shopify could not be verified. No label purchased."
            );
          } catch (_error) {
            if (sequence !== generation || !visible() || !card.isConnected) return;
            itemText(remote, "Shopify verification unavailable. No label purchased.");
          } finally {
            button.disabled = false;
          }
        });
        card.append(button, remote);
      }
      list.append(card);
    }
    renderPagination();
  }

  async function refresh() {
    if (!visible()) return;
    const sequence = ++generation;
    itemText(element(ids.status), "Checking your allocated Shopify orders…");
    try {
      if (typeof apiRequest !== "function") throw new Error("Sign in before loading dispatch");
      const params = new URLSearchParams({
        limit: String(page.limit), offset: String(page.offset),
      });
      const result = await apiRequest(`/api/v1/fulfilment/to-ship?${params}`);
      if (sequence !== generation || !visible()) return;
      renderResult(result);
    } catch (error) {
      if (sequence !== generation || !visible()) return;
      clear(element(ids.list));
      page.total = 0;
      itemText(element(ids.total), "—");
      itemText(element(ids.status), "Unable to verify dispatch. Refresh or try signing in again.");
      renderPagination();
    }
  }

  element(ids.verifyShopify)?.addEventListener("click", async () => {
    if (!visible()) return;
    const sequence = generation;
    const button = element(ids.verifyShopify);
    button.disabled = true;
    itemText(element(ids.shopifyStatus), "Verifying Drop Rate's direct Shopify API connection…");
    try {
      const status = await apiRequest("/api/v1/fulfilment/shopify-status");
      if (sequence !== generation || !visible()) return;
      const isConnected = status.store_connected === true
        && status.shopify_fulfilment_read_access === true;
      itemText(element(ids.shopifyStatus),
        isConnected
          ? `Shopify connected · ${status.shop || "Drop Rate"} · Label purchases still require seller and cost verification.`
          : "Shopify API access is incomplete. Orders remain on hold.");
    } catch (_error) {
      if (sequence !== generation || !visible()) return;
      itemText(element(ids.shopifyStatus), "Shopify connection unavailable. Try again later.");
    } finally {
      button.disabled = false;
    }
  });

  element(ids.refresh)?.addEventListener("click", () => refresh());
  element(ids.previous)?.addEventListener("click", () => {
    page.offset = Math.max(0, page.offset - page.limit);
    refresh();
  });
  element(ids.next)?.addEventListener("click", () => {
    if (page.offset + page.limit >= page.total) return;
    page.offset += page.limit;
    refresh();
  });
  element("owner-logout-button")?.addEventListener("click", () => {
    authenticated = false;
    generation++;
    clear(element(ids.list));
    itemText(element(ids.status), "");
    itemText(element(ids.shopifyStatus), "Shopify verification available after sign-in.");
  }, {capture: true});
  document.addEventListener("hub-ready", () => {
    authenticated = true;
    generation++;
    page.offset = 0;
    if (visible()) refresh();
  });
  document.addEventListener("owner-view-changed", (event) => {
    generation++;
    if (event.detail?.view === "sales" && authenticated) refresh();
  });
})();
