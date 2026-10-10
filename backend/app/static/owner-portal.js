"use strict";



const state = {
  config: null,
  session: null,
  providers: {google: false, apple: false},
  inventory: {offset: 0, limit: 50, total: 0, search: "", status: "", layout: "grid"},
  sales: {offset: 0, limit: 50, total: 0},
  settlements: {offset: 0, limit: 50, total: 0},
  channels: {offset: 0, limit: 60, total: 0, search: "", channel: "ALL"},
  payoutPreferenceVersion: 0,
  financeSummary: null,
  payoutPreference: null,
  profile: null,
};

const byId = (id) => document.getElementById(id);

function formatMoney(minor) {
  const value = Number(minor || 0) / 100;
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    maximumFractionDigits: 2,
  }).format(value);
}

function safeText(value, fallback = "—") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function showPortalMessage(text = "", kind = "") {
  const node = byId("owner-portal-message");
  node.textContent = text;
  node.className = `message owner-global-message${kind ? ` ${kind}` : ""}`;
}

function statusClass(value) {
  return String(value || "").trim().toLowerCase();
}

function inventoryCardSubtitle(item) {
  return [
    safeText(item.set_name, ""),
    item.card_number ? `#${item.card_number}` : "",
    safeText(item.variant, ""),
  ].filter(Boolean).join(" · ") || safeText(item.game);
}

function conditionLabel(item) {
  if (String(item.seal_status || "").toUpperCase() === "SEALED") return "Sealed";
  if (String(item.seal_status || "").toUpperCase() === "UNSEALED") return "Unsealed";
  return item.grade
    ? `${safeText(item.grading_company, "Graded")} ${item.grade}`
    : safeText(item.condition);
}

function inventoryTypeLabel(item) {
  if (item.sealed_product_type) {
    return String(item.sealed_product_type)
      .toLowerCase()
      .split("_")
      .map((part) => part ? part[0].toUpperCase() + part.slice(1) : "")
      .join(" ");
  }
  return item.product_type === "SEALED" ? "Sealed product" : "Card";
}

function createCardImage(item, className) {
  if (window.DropRateInventory) return window.DropRateInventory.image(item, className);
  const wrap = document.createElement("div");
  wrap.className = className;
  const url = String(item.image_url || "").trim();
  if (url) {
    const image = document.createElement("img");
    image.src = url;
    image.alt = `${safeText(item.name, "Trading card")} reference image`;
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => {
      wrap.replaceChildren();
      const fallback = document.createElement("span");
      fallback.className = "owner-image-placeholder";
      fallback.textContent = safeText(item.game, "DR").slice(0, 3).toUpperCase();
      wrap.append(fallback);
    }, {once: true});
    wrap.append(image);
    return wrap;
  }
  const fallback = document.createElement("span");
  fallback.className = "owner-image-placeholder";
  fallback.textContent = safeText(item.game, "DR").slice(0, 3).toUpperCase();
  wrap.append(fallback);
  return wrap;
}

// A collection tile represents interchangeable physical copies, not a Shopify
// variant or a change of ownership. Leave identity, prices and reservation
// decisions to PostgreSQL/FastAPI. Never pool graded, non-sealed or mixed stock.
function ownerInventoryDisplayGroups(items) {
  const grouped=new Map(),result=[];
  for(const original of items){
    const item={...original};
    const eligible=Boolean(item.catalogue_id) &&
      ["SEALED","COLLECTION"].includes(item.product_type) &&
      item.seal_status==="SEALED" && item.status==="APPROVED" &&
      item.sale_intent==="FOR_SALE" && !item.grading_company && !item.grade &&
      !item.certificate_number && item.store_price_minor!=null;
    const signature=eligible?JSON.stringify([
      item.catalogue_id,item.product_type,item.sealed_product_type||"",
      item.language||"",item.seal_status,item.condition||"",item.variant||"",
      item.status,item.sale_intent,item.store_price_minor
    ]):"item:"+item.id;
    const previous=grouped.get(signature);
    const valued=Number.isInteger(item.market_value_minor);
    if(!previous){
      item.grouped_quantity=1;
      item.group_valued_count=valued?1:0;
      item.group_member_ids=[item.id];
      item.group_unvalued_code=!valued&&item.can_refresh_market?item.inventory_code:null;
      grouped.set(signature,item);result.push(item);
      continue;
    }
    previous.grouped_quantity++;
    previous.group_member_ids.push(item.id);
    if(valued) {
      previous.group_valued_count++;
      // Show one evidenced physical-copy value, never manufacture a valuation
      // for a second item whose valuation is still pending.
      if(previous.market_value_minor==null){
        previous.market_value_minor=item.market_value_minor;
        previous.pricing_method=item.pricing_method;
      }
    }
    if(!valued&&item.can_refresh_market)previous.group_unvalued_code=item.inventory_code;
    previous.can_refresh_market=Boolean(previous.can_refresh_market||item.can_refresh_market);
  }
  return result;
}

function renderInventoryRows(items) {
  const body = byId("owner-inventory-body");
  body.replaceChildren();

  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "muted";
    cell.textContent = "No inventory matches these filters.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");

    const cardCell = document.createElement("td");
    const cardWrap = document.createElement("div");
    cardWrap.className = "owner-table-card";
    cardWrap.append(createCardImage(item, "owner-table-mini-image"));
    const cardCopy = document.createElement("div");
    cardCopy.className = "owner-table-card-copy";
    const cardName = document.createElement("strong");
    cardName.textContent = safeText(item.name);
    const cardCode = document.createElement("small");
    cardCode.textContent = inventoryCardSubtitle(item);
    if((item.grouped_quantity||1)>1)cardCode.textContent+=" · Qty "+item.grouped_quantity;
    cardCopy.append(cardName, cardCode);
    if (item.id && window.DropRateInventory) {
      const open = document.createElement("button");
      open.type = "button"; open.className = "owner-inventory-open";
      open.setAttribute("aria-label", `View ${item.name}`);
      open.append(...cardCopy.childNodes); cardCopy.append(open);
      open.addEventListener("click", () => window.DropRateInventory.open(item));
    }
    cardWrap.append(cardCopy);
    cardCell.append(cardWrap);

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `owner-status-pill ${statusClass(item.status)}`;
    status.textContent = safeText(item.status);
    statusCell.append(status);

    const marketCell = document.createElement("td");
    marketCell.textContent = item.market_value_minor == null
      ? "Value pending"
      : formatMoney(item.market_value_minor)+(item.pricing_method==="CARDMARKET_GUIDE_V1"?" · Cardmarket estimate":"");
    if((item.grouped_quantity||1)>1 && item.group_valued_count<item.grouped_quantity)
      marketCell.append(document.createTextNode(" · "+item.group_valued_count+"/"+item.grouped_quantity+" copies valued"));
    const storeCell = document.createElement("td");
    const storeValue = item.store_price_minor ?? item.recommended_retail_minor;
    storeCell.textContent = storeValue == null ? "—" : formatMoney(storeValue);

    row.append(cardCell, statusCell, marketCell, storeCell);
    body.append(row);
  }
}

function renderInventoryCards(items) {
  const grid = byId("owner-inventory-grid");
  grid.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-inventory-empty";
    const icon = document.createElement("div");
    icon.className = "owner-inventory-empty-icon";
    icon.textContent = "▣";
    const title = document.createElement("strong");
    title.textContent = state.inventory.search || state.inventory.status
      ? "No inventory items match these filters"
      : "No inventory linked yet";
    const copy = document.createElement("span");
    copy.textContent = state.inventory.search || state.inventory.status
      ? "Try clearing your search or choosing another status."
      : "Once Drop Rate links inventory to your seller account, every item will appear here automatically.";
    empty.append(icon, title, copy);
    grid.append(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "owner-inventory-card";

    const imageWrap = document.createElement("button");
    imageWrap.type = "button";
    imageWrap.setAttribute("aria-label", `View ${item.name}`);
    imageWrap.className = "owner-card-image-wrap";
    imageWrap.append(createCardImage(item, "owner-card-thumb"));
    if((item.grouped_quantity||1)>1){
      const count=document.createElement("span");count.className="owner-card-quantity";
      count.textContent="×"+item.grouped_quantity;
      count.setAttribute("aria-label",item.grouped_quantity+" physical copies");
      imageWrap.append(count);
      imageWrap.setAttribute("aria-label",`View ${item.grouped_quantity} copies of ${item.name}`);
    }
    imageWrap.addEventListener("click", () => window.DropRateInventory?.open(item));

    const body = document.createElement("div");
    body.className = "owner-card-body";

    const heading = document.createElement("div");
    heading.className = "owner-card-title-row";
    const title = document.createElement("div");
    title.className = "owner-card-title";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const subtitle = document.createElement("span");
    subtitle.textContent = inventoryCardSubtitle(item);
    title.append(name, subtitle);
    const status = document.createElement("span");
    status.className = `owner-status-pill ${statusClass(item.status)}`;
    status.textContent = safeText(item.status);
    heading.append(title, status);

    const prices = document.createElement("div");
    prices.className = "owner-card-prices";
    const storeValue = item.store_price_minor ?? item.recommended_retail_minor;
    const storeLabel = item.store_price_minor == null && item.recommended_retail_minor != null
      ? "Recommended retail"
      : "Store price";
    for (const [labelText, valueText] of [
      ["Market value", item.market_value_minor == null ? "Value pending" : formatMoney(item.market_value_minor)+(item.pricing_method==="CARDMARKET_GUIDE_V1"?" · Cardmarket estimate":"")],
      [storeLabel, storeValue == null ? "—" : formatMoney(storeValue)],
    ]) {
      const box = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = labelText;
      const value = document.createElement("strong");
      value.textContent = valueText;
      box.append(label, value);
      if(labelText==="Market value" && (item.grouped_quantity||1)>1){
        const note=document.createElement("small");
        note.className="owner-card-value-coverage";
        note.textContent=item.group_valued_count+"/"+item.grouped_quantity+" copies valued";
        box.append(note);
      }
      prices.append(box);
    }

    body.append(heading, prices);
    const details = document.createElement("button");
    details.type = "button"; details.className = "owner-secondary-button owner-inventory-details";
    details.textContent = "View details & manage";
    details.addEventListener("click", () => window.DropRateInventory?.open(item));
    body.append(details);
    card.addEventListener("click", event => {
      if (!event.target.closest("button,a,input,select")) window.DropRateInventory?.open(item);
    });

    if (item.can_refresh_market) {
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "owner-secondary-button owner-market-refresh";
      refresh.textContent = "Refresh market value";
      refresh.addEventListener("click", async () => {
        refresh.disabled = true;
        refresh.textContent = "Refreshing value…";
        try {
          await apiRequest(
            `/api/v1/owner/inventory/${encodeURIComponent(item.group_unvalued_code||item.inventory_code)}/refresh-market`,
            {method: "POST", body: "{}"}
          );
          showPortalMessage("Market value refreshed from current sealed-product evidence.", "success");
          await Promise.all([loadOwnerOverview(), loadOwnerInventory(), loadOwnerInsights()]);
        } catch (error) {
          showPortalMessage(error.message || "Market value could not be refreshed.", "error");
          refresh.disabled = false;
          refresh.textContent = "Refresh market value";
        }
      });
      body.append(refresh);
    }

    card.append(imageWrap, body);
    grid.append(card);
  }
}

function renderOverviewLatestInventory(items) {
  const container = byId("owner-overview-latest");
  if (!container) return;
  container.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-empty-inline";
    const title = document.createElement("strong");
    title.textContent = "No inventory yet";
    const copy = document.createElement("span");
    copy.textContent = "Your latest cards and sealed products will appear here as soon as inventory is linked to your account.";
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  for (const item of items.slice(0, 4)) {
    const card = document.createElement("article");
    card.className = "owner-latest-card";
    card.append(createCardImage(item, "owner-latest-image"));

    const copy = document.createElement("div");
    copy.className = "owner-latest-copy";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const detail = document.createElement("span");
    detail.textContent = inventoryCardSubtitle(item);
    const status = document.createElement("small");
    status.textContent = safeText(item.status);
    copy.append(name, detail, status);
    card.append(copy);
    container.append(card);
  }
}


function renderOwnerPayoutTracker(data) {
  state.financeSummary = data;
  const payout = data.next_payout || {};
  const status = String(payout.status || "MANUAL").toUpperCase();
  const scheduled = payout.scheduled_for || null;
  const amount = Number(payout.amount_minor || 0);

  byId("owner-next-payout-date").textContent = scheduled
    ? formatDateTime(scheduled)
    : "Manual payout";
  byId("owner-next-payout-amount").textContent =
    (payout.amount_basis === "CURRENT_AVAILABLE_BALANCE" && scheduled ? "~" : "")
    + formatMoney(amount);

  const statusNode = byId("owner-next-payout-status");
  statusNode.textContent =
    status === "ESTIMATED" ? "Estimated" :
    status === "APPROVED" ? "Approved" :
    status === "REQUESTED" ? "Scheduled" :
    "Available now";
  statusNode.className =
    "owner-payout-tracker-status "
    + (status === "APPROVED" ? "approved" : status === "REQUESTED" ? "scheduled" : "");

  byId("owner-next-payout-basis").textContent =
    payout.amount_basis === "SCHEDULED_REQUEST"
      ? "This amount is already reserved in a payout request."
      : scheduled
        ? "Estimate based on your currently cleared, unreserved balance."
        : "Your payout schedule is manual. This is your currently available balance.";
}

function renderOwnerInsightList(containerId, items, mover = false) {
  const container = byId(containerId);
  if (!container) return;
  container.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-empty-inline";
    const title = document.createElement("strong");
    title.textContent = mover ? "Building price history" : "No valuation data yet";
    const copy = document.createElement("span");
    copy.textContent = mover
      ? "Weekly movers appear once a card has enough historical pricing for a real comparison."
      : "Cards appear here after the pricing engine produces a market value.";
    empty.append(title, copy);
    container.append(empty);
    return;
  }

  items.forEach((item, index) => {
    const row = document.createElement("article");
    row.className = "owner-insight-row";
    row.append(createCardImage(item, "owner-insight-thumb"));

    const rank = document.createElement("span");
    rank.className = "owner-insight-rank";
    rank.textContent = String(index + 1);

    const copy = document.createElement("div");
    copy.className = "owner-insight-copy";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const meta = document.createElement("span");
    meta.textContent = inventoryCardSubtitle(item);
    const sub = document.createElement("small");
    sub.textContent = item.grade
      ? safeText(item.grading_company, "Graded") + " " + item.grade
      : safeText(item.condition);
    copy.append(name, meta, sub);

    const value = document.createElement("div");
    value.className = "owner-insight-value";
    const current = document.createElement("strong");
    current.textContent = formatMoney(
      mover ? item.current_value_minor : item.market_value_minor
    );
    value.append(current);

    if (mover) {
      const pct = Number(item.change_pct || 0);
      const movement = document.createElement("span");
      movement.className =
        "owner-movement " + (pct > 0 ? "up" : pct < 0 ? "down" : "flat");
      movement.textContent =
        (pct > 0 ? "↑ " : pct < 0 ? "↓ " : "→ ")
        + Math.abs(pct).toFixed(2).replace(/\.00$/, "")
        + "%";
      const delta = document.createElement("small");
      delta.textContent =
        (Number(item.change_minor || 0) >= 0 ? "+" : "")
        + formatMoney(item.change_minor || 0);
      value.append(movement, delta);
    } else {
      const store = document.createElement("small");
      store.textContent = item.store_value_minor == null
        ? "Store value pending"
        : "Store / recommended " + formatMoney(item.store_value_minor);
      value.append(store);
    }

    row.append(rank, copy, value);
    container.append(row);
  });
}

async function loadOwnerInsights() {
  const data = await apiRequest("/api/v1/owner/insights");
  renderOwnerInsightList("owner-top-valued-cards", data.top_valued || [], false);
  renderOwnerInsightList("owner-weekly-movers", data.weekly_movers || [], true);
}

function ownerChannelCount(channel, stateName) {
  const row = (channel?.states || []).find(
    (entry) => String(entry.state || "").toUpperCase() === stateName
  );
  return Number(row?.count || 0);
}

function ownerChannelStatusClass(value) {
  const stateValue = String(value || "").toUpperCase();
  if (["PUBLISHED", "LIVE", "READY", "CONNECTED", "PLATFORM_MANAGED"].includes(stateValue)) {
    return "approved";
  }
  if (["ERROR", "ACTION_REQUIRED"].includes(stateValue)) return "withdrawn";
  if (["DRAFT", "PUBLISHING"].includes(stateValue)) return "inspection";
  return "";
}

function renderOwnerChannelSummary(data) {
  const channels = data.channels || [];
  const shopify = channels.find((channel) => channel.code === "SHOPIFY") || {};
  const ebay = channels.find((channel) => channel.code === "EBAY") || {};

  const shopifyStatus = byId("owner-channel-shopify-status");
  shopifyStatus.textContent = shopify.connected ? "Connected" : "Not configured";
  shopifyStatus.className =
    "owner-status-pill " + ownerChannelStatusClass(shopify.connection_status);
  byId("owner-channel-shopify-live").textContent =
    ownerChannelCount(shopify, "PUBLISHED").toLocaleString("en-GB");
  byId("owner-channel-shopify-errors").textContent =
    ownerChannelCount(shopify, "ERROR").toLocaleString("en-GB");

  const ebayStatus = byId("owner-channel-ebay-status");
  ebayStatus.textContent = safeText(
    ebay.connection_status,
    ebay.connected ? "Connected" : "Not connected"
  ).replaceAll("_", " ");
  ebayStatus.className =
    "owner-status-pill " + ownerChannelStatusClass(ebay.connection_status);
  byId("owner-channel-ebay-live").textContent =
    ownerChannelCount(ebay, "LIVE").toLocaleString("en-GB");
  byId("owner-channel-ebay-errors").textContent =
    ownerChannelCount(ebay, "ERROR").toLocaleString("en-GB");
}

function renderOwnerChannelsRows(items, channels = []) {
  const body = byId("owner-channels-body");
  body.replaceChildren();

  if (!items.length) {
    renderEmptyRow("owner-channels-body", 6, "No inventory matches these filters.");
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");

    const cardCell = document.createElement("td");
    const cardWrap = document.createElement("div");
    cardWrap.className = "owner-table-card";
    cardWrap.append(createCardImage(item, "owner-table-mini-image"));
    const copy = document.createElement("div");
    copy.className = "owner-table-card-copy";
    const name = document.createElement("strong");
    name.textContent = safeText(item.name);
    const meta = document.createElement("small");
    meta.textContent =
      safeText(item.inventory_code) + " · " + inventoryCardSubtitle(item);
    copy.append(name, meta);
    cardWrap.append(copy);
    cardCell.append(cardWrap);

    const shopifyCell = document.createElement("td");
    const shopify = document.createElement("span");
    shopify.className =
      "owner-status-pill " + ownerChannelStatusClass(item.shopify_state);
    shopify.textContent = safeText(item.shopify_state, "Not linked").replaceAll("_", " ");
    shopifyCell.append(shopify);
    if (item.shopify_price_minor != null) {
      const price = document.createElement("small");
      price.className = "owner-channel-price";
      price.textContent = formatMoney(item.shopify_price_minor);
      shopifyCell.append(price);
    }

    const ebayCell = document.createElement("td");
    const ebay = document.createElement("span");
    ebay.className = "owner-status-pill " + ownerChannelStatusClass(item.ebay_state);
    ebay.textContent = safeText(item.ebay_state, "Not linked").replaceAll("_", " ");
    ebayCell.append(ebay);
    if (item.ebay_price_minor != null) {
      const price = document.createElement("small");
      price.className = "owner-channel-price";
      price.textContent = formatMoney(item.ebay_price_minor);
      ebayCell.append(price);
    }
    if (item.ebay_listing_id && String(item.ebay_state || "").toUpperCase() === "LIVE") {
      const link = document.createElement("a");
      link.className = "owner-channel-link";
      link.href = "https://www.ebay.co.uk/itm/" + encodeURIComponent(item.ebay_listing_id);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View listing ↗";
      ebayCell.append(link);
    }
    if (item.ebay_last_error_code) {
      const error = document.createElement("small");
      error.className = "owner-channel-error";
      error.textContent = String(item.ebay_last_error_code).replaceAll("_", " ");
      ebayCell.append(error);
    }

    for (const [code, cell, linked] of [["SHOPIFY", shopifyCell, item.shopify_state === "PUBLISHED"], ["EBAY", ebayCell, item.ebay_state === "LIVE"]]) {
      if (linked) continue;
      const channel = channels.find(value => value.code === code);
      const eligible = item.inventory_status === "APPROVED" && item.sale_intent === "FOR_SALE";
      if (eligible && channel?.sync_enabled) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost-button compact";
        button.textContent = "Sync to " + channel.label;
        button.addEventListener("click", async () => {
          if (!window.confirm(`List ${item.inventory_code} for sale on ${channel.label}?`)) return;
          button.disabled = true;
          try {
            const result = await apiRequest(`/api/v1/owner/inventory/${encodeURIComponent(item.inventory_id)}/channels/${code.toLowerCase()}/sync`, {method: "POST", body: JSON.stringify({version: item.version})});
            showOwnerChannelsMessage(`${item.inventory_code}: ${result.status.replaceAll("_", " ")}`, "success");
            await loadOwnerChannels();
          } catch (error) { showOwnerChannelsMessage(error.message, "error"); button.disabled = false; }
        });
        cell.append(button);
      } else {
        const note = document.createElement("small");
        note.className = "owner-channel-price";
        note.textContent = !eligible ? (item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "Awaiting approval") : "Seller sync not enabled yet";
        cell.append(note);
      }
    }

    const marketCell = document.createElement("td");
    marketCell.textContent =
      item.market_value_minor == null ? "Value pending" : formatMoney(item.market_value_minor)+(item.pricing_method==="CARDMARKET_GUIDE_V1"?" · Cardmarket estimate":"");

    const storeCell = document.createElement("td");
    storeCell.textContent =
      item.store_value_minor == null ? "—" : formatMoney(item.store_value_minor);

    const checkedCell = document.createElement("td");
    const times = [item.shopify_last_synced_at, item.ebay_last_verified_at]
      .filter(Boolean)
      .map((value) => new Date(value))
      .filter((value) => !Number.isNaN(value.getTime()))
      .sort((left, right) => right.getTime() - left.getTime());
    checkedCell.textContent = times.length ? formatDateTime(times[0].toISOString()) : "—";

    row.append(cardCell, shopifyCell, ebayCell, marketCell, storeCell, checkedCell);
    body.append(row);
  }
}

function renderOwnerChannelsPagination() {
  const {offset, limit, total} = state.channels;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-channels-page").textContent = total
    ? String(start) + "–" + String(end) + " of " + String(total)
    : "0 linked cards";
  byId("owner-channels-prev").disabled = offset <= 0;
  byId("owner-channels-next").disabled = offset + limit >= total;
}

function showOwnerChannelsMessage(text = "", kind = "") {
  const node = byId("owner-channels-message");
  node.textContent = text;
  node.className = "owner-inline-message" + (kind ? " " + kind : "");
}

async function loadOwnerChannels() {
  const params = new URLSearchParams({
    limit: String(state.channels.limit),
    offset: String(state.channels.offset),
    channel: state.channels.channel,
  });
  if (state.channels.search) params.set("search", state.channels.search);

  try {
    const data = await apiRequest("/api/v1/owner/channels?" + params.toString());
    state.ownerChannelAccount = state.session?.user?.id || state.session?.access_token;
    state.ownerChannelSummaries = Array.isArray(data.channels)?data.channels:[];
    state.channels.total = Number(data.total || 0);
    byId("owner-channels-total").textContent =
      state.channels.total.toLocaleString("en-GB");
    renderOwnerChannelSummary(data);
    renderOwnerChannelsRows(data.items || [], data.channels || []);
    renderOwnerChannelsPagination();
    showOwnerChannelsMessage();
  } catch (error) {
    showOwnerChannelsMessage(error.message, "error");
    throw error;
  }
}

function renderInventoryPagination() {
  const {offset, limit, total} = state.inventory;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-inventory-page").textContent = total
    ? `${start}–${end} of ${total}`
    : "0 items";
  byId("owner-inventory-prev").disabled = offset <= 0;
  byId("owner-inventory-next").disabled = offset + limit >= total;
}

async function loadOwnerOverview() {
  const data = await apiRequest("/api/v1/owner/overview");
  const summary = data.summary || {};
  const total = Number(summary.total_inventory_count || 0);
  byId("owner-total-inventory").textContent = total.toLocaleString("en-GB");
  const unvalued = Number(summary.active_unvalued_count || 0);
  const valued = Number(summary.active_valued_count || 0);
  byId("owner-market-value").textContent = unvalued && !valued
    ? "Value pending" : formatMoney(summary.active_market_value_minor);
  byId("owner-market-value-note").textContent = unvalued
    ? `${valued} valued · ${unvalued} awaiting market data`
    : "Latest available market prices";
  if(summary.guide_estimate_count)byId("owner-market-value-note").textContent+=` · ${summary.guide_estimate_count} Cardmarket estimates`;
  byId("owner-store-value").textContent = formatMoney(
    summary.active_store_value_minor ?? summary.active_store_price_minor
  );
  byId("owner-sold-count").textContent = Number(summary.sold_count || 0).toLocaleString("en-GB");

  const stages = {
    draft: Number(summary.draft_count || 0),
    inspection: Number(summary.inspection_count || 0),
    approved: Number(summary.approved_count || 0),
    reserved: Number(summary.reserved_count || 0),
  };
  for (const [stage, count] of Object.entries(stages)) {
    const value = byId(`owner-pipeline-${stage}`);
    const bar = byId(`owner-pipeline-${stage}-bar`);
    if (value) value.textContent = count.toLocaleString("en-GB");
    if (bar) bar.style.width = `${total ? Math.min(100, Math.max(4, (count / total) * 100)) : 0}%`;
  }
}

async function loadOwnerInventory() {
  const revision = state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  const account = state.session?.user?.id || state.session?.access_token;
  const params = new URLSearchParams({
    limit: String(state.inventory.limit),
    offset: String(state.inventory.offset),
  });
  if (state.inventory.search) params.set("search", state.inventory.search);
  if (state.inventory.status) params.set("status", state.inventory.status);

  const data = await apiRequest(`/api/v1/owner/inventory?${params.toString()}`);
  if (revision !== state.inventory.requestRevision || account !== (state.session?.user?.id || state.session?.access_token)) return;
  state.inventory.total = Number(data.total || 0);
  const items = data.items || [];
  const displayGroups=ownerInventoryDisplayGroups(items);
  renderInventoryRows(displayGroups);
  renderInventoryCards(displayGroups);
  renderInventoryPagination();
  const totalLabel = byId("owner-inventory-total-label");
  if (totalLabel) {
    totalLabel.textContent = displayGroups.length.toLocaleString("en-GB");
    const units = state.inventory.total.toLocaleString("en-GB");
    const fullyLoaded = state.inventory.offset===0 && items.length>=state.inventory.total;
    if(totalLabel.nextElementSibling)
      totalLabel.nextElementSibling.textContent =
        (fullyLoaded? (displayGroups.length===1?"product":"products") : "products shown")+
        " · "+units+" "+(state.inventory.total===1?"copy":"copies");
  }
  if (state.inventory.offset === 0 && !state.inventory.search && !state.inventory.status) {
    renderOverviewLatestInventory(displayGroups);
  }
}

async function reloadOwnerDashboard() {
  showPortalMessage("Loading your account…");
  try {
    await Promise.all([
      loadOwnerOverview(),
      loadOwnerInventory(),
      loadOwnerInsights(),
      loadOwnerChannels(),
      loadOwnerFinanceSummary(),
      loadOwnerSales(),
      loadOwnerSettlements(),
      loadOwnerPayouts(),
      loadOwnerPayoutPreference(),
      loadOwnerStripeStatus(),
      loadOwnerProfile(),
    ]);
    showPortalMessage();
  } catch (error) {
    showPortalMessage(error.message, "error");
  }
}

function setProfileMessage(id, text = "", kind = "") {
  const node = byId(id);
  if (!node) return;
  node.textContent = text;
  node.className = `message owner-card-message${kind ? ` ${kind}` : ""}`;
}

function renderOwnerProfile(profile) {
  state.profile = profile || {};
  const displayName = safeText(state.profile.display_name, "");
  byId("owner-profile-display-name").value = displayName;
  byId("owner-profile-username").value = state.profile.username || "";
  byId("owner-profile-owner-type").textContent =
    state.profile.owner_type === "CONSIGNOR" ? "Seller" : safeText(state.profile.owner_type);
  byId("owner-profile-member-since").textContent =
    formatDate(state.profile.membership_created_at || state.profile.created_at);
  byId("owner-profile-commission").textContent =
    `${(Number(state.profile.commission_bps || 0) / 100).toFixed(2).replace(/\.00$/, "")}%`;

  const user = state.session?.user || {};
  byId("owner-profile-current-email").textContent = safeText(user.email, "—");
  const verified = Boolean(user.email_confirmed_at || user.confirmed_at);
  byId("owner-profile-email-status").textContent =
    verified ? "Verified email" : "Email verification pending";
}

async function loadOwnerProfile() {
  const data = await apiRequest("/api/v1/owner/profile");
  renderOwnerProfile(data.profile || {});
}

async function saveOwnerProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = byId("owner-profile-save");
  const displayName = byId("owner-profile-display-name").value.trim();
  const usernameRaw = byId("owner-profile-username").value.trim().toLowerCase();
  if (usernameRaw && !/^[a-z0-9][a-z0-9_]{2,29}$/.test(usernameRaw)) {
    setProfileMessage(
      "owner-profile-message",
      "Username must be 3–30 characters using lowercase letters, numbers and underscores.",
      "error"
    );
    return;
  }

  button.disabled = true;
  setProfileMessage("owner-profile-message", "Saving profile…");
  try {
    const data = await apiRequest("/api/v1/owner/profile", {
      method: "PATCH",
      body: JSON.stringify({
        display_name: displayName,
        username: usernameRaw || null,
      }),
    });
    renderOwnerProfile(data.profile || {});
    const name = data.profile?.display_name || displayName || "Owner";
    byId("owner-portal-name").textContent = name;
    byId("owner-portal-initial").textContent = name.slice(0, 1).toUpperCase();
    byId("owner-overview-name").textContent = name;
    setProfileMessage("owner-profile-message", "Profile saved.", "success");
  } catch (error) {
    setProfileMessage("owner-profile-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function changeOwnerEmail(event) {
  event.preventDefault();
  const button = byId("owner-email-save");
  const newEmail = byId("owner-profile-new-email").value.trim().toLowerCase();
  const currentEmail = String(state.session?.user?.email || "").trim().toLowerCase();

  if (!newEmail || !newEmail.includes("@")) {
    setProfileMessage("owner-email-message", "Enter a valid email address.", "error");
    return;
  }
  if (newEmail === currentEmail) {
    setProfileMessage("owner-email-message", "That is already your current email.", "error");
    return;
  }

  button.disabled = true;
  setProfileMessage("owner-email-message", "Sending email-change verification…");
  try {
    const updatedUser = await authRequest(
      `/user?redirect_to=${encodeURIComponent(`${window.location.origin}/owner`)}`,
      {
        method: "PUT",
        headers: {Authorization: `Bearer ${state.session.access_token}`},
        body: JSON.stringify({email: newEmail}),
      }
    );
    state.session.user = updatedUser;
    saveSession(state.session);
    renderOwnerProfile(state.profile || {});
    byId("owner-profile-new-email").value = "";
    setProfileMessage(
      "owner-email-message",
      "Verification sent. Your login email will change after the required confirmation step completes.",
      "success"
    );
  } catch (error) {
    setProfileMessage("owner-email-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function changeOwnerPassword(event) {
  event.preventDefault();
  const button = byId("owner-password-save");
  const currentPassword = byId("owner-profile-current-password").value;
  const newPassword = byId("owner-profile-new-password").value;
  const confirmation = byId("owner-profile-confirm-password").value;
  const email = String(state.session?.user?.email || "").trim().toLowerCase();

  if (newPassword !== confirmation) {
    setProfileMessage("owner-password-message", "The new passwords do not match.", "error");
    return;
  }
  if (newPassword.length < 12) {
    setProfileMessage("owner-password-message", "Use at least 12 characters for your new password.", "error");
    return;
  }
  if (!email) {
    setProfileMessage("owner-password-message", "No verified email is available for password re-authentication.", "error");
    return;
  }

  button.disabled = true;
  setProfileMessage("owner-password-message", "Verifying your current password…");
  try {
    const freshSession = await authRequest("/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({email, password: currentPassword}),
    });
    saveSession(freshSession);
    await hydrateSessionUser();

    setProfileMessage("owner-password-message", "Updating password…");
    await authRequest("/user", {
      method: "PUT",
      headers: {Authorization: `Bearer ${state.session.access_token}`},
      body: JSON.stringify({password: newPassword}),
    });
    await hydrateSessionUser();
    byId("owner-profile-current-password").value = "";
    byId("owner-profile-new-password").value = "";
    byId("owner-profile-confirm-password").value = "";
    setProfileMessage("owner-password-message", "Password changed successfully.", "success");
  } catch (error) {
    setProfileMessage("owner-password-message", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", {day: "2-digit", month: "short", year: "numeric"});
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function renderEmptyRow(bodyId, colspan, message) {
  const body = typeof bodyId === "string" ? byId(bodyId) : bodyId;
  if (!body) return;
  body.replaceChildren();
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.className = "muted";
  cell.textContent = message;
  row.append(cell);
  body.append(row);
}

async function loadOwnerFinanceSummary() {
  const data = await apiRequest("/api/v1/owner/finance/summary");
  byId("owner-sales-revenue").textContent = formatMoney(data.sales_revenue_minor);
  byId("owner-commission-total").textContent = formatMoney(data.commission_minor);
  byId("owner-commission-rate").textContent =
    `Drop Rate commission: ${(Number(data.commission_bps || 0) / 100).toFixed(2).replace(/\.00$/, "")}%`;
  byId("owner-lifetime-proceeds").textContent = formatMoney(data.lifetime_owner_proceeds_minor);
  byId("owner-financial-completeness").textContent =
    data.financials_complete ? "COMPLETE" : `${Number(data.unreconciled_sales || 0)} PENDING`;
  byId("owner-available-balance").textContent = formatMoney(data.available_to_withdraw_minor);
  byId("owner-pending-balance").textContent = formatMoney(data.pending_minor);
  byId("owner-reserved-payouts").textContent = formatMoney(data.reserved_payout_minor);
  byId("owner-paid-out").textContent = formatMoney(data.paid_out_minor);
  byId("owner-overview-balance").textContent = formatMoney(data.available_to_withdraw_minor);
  byId("owner-overview-proceeds").textContent = formatMoney(data.lifetime_owner_proceeds_minor);
  byId("owner-overview-pending").textContent = formatMoney(data.pending_minor);
  byId("owner-overview-paid").textContent = formatMoney(data.paid_out_minor);
  renderOwnerPayoutTracker(data);
}

function otherDeductions(item) {
  return Number(item.platform_fee_minor || item.platform_fees_minor || 0)
    + Number(item.payment_fee_minor || item.payment_fees_minor || 0)
    + Number(item.shipping_cost_minor || 0)
    + Number(item.fulfilment_material_cost_minor || 0)
    + Number(item.refund_minor || item.refunds_minor || 0)
    + Number(item.shipping_refund_minor || item.shipping_refunds_minor || 0)
    - Number(item.adjustment_minor || item.adjustments_minor || 0);
}

function renderSales(items) {
  const body = byId("owner-sales-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-sales-body", 8, "No sales yet.");
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const cardNumber = item.card_number ? ` #${item.card_number}` : "";
    const variant = item.variant ? ` · ${item.variant}` : "";
    const values = [
      formatDate(item.sold_at),
      `${safeText(item.name)}${cardNumber}${variant}`,
      `${safeText(item.source)} · ${safeText(item.order_number)}`,
      formatMoney(item.net_sale_minor),
      formatMoney(item.commission_minor),
      formatMoney(otherDeductions(item)),
      formatMoney(item.owner_proceeds_minor),
      item.financials_complete ? "Complete" : "Reconciling",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderSalesPagination() {
  const {offset, limit, total} = state.sales;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-sales-page").textContent = total ? `${start}–${end} of ${total}` : "0 sales";
  byId("owner-sales-prev").disabled = offset <= 0;
  byId("owner-sales-next").disabled = offset + limit >= total;
}

async function loadOwnerSales() {
  const params = new URLSearchParams({
    limit: String(state.sales.limit),
    offset: String(state.sales.offset),
  });
  const data = await apiRequest(`/api/v1/owner/finance/sales?${params.toString()}`);
  state.sales.total = Number(data.total || 0);
  renderSales(data.items || []);
  renderSalesPagination();
}

function renderSettlements(items) {
  const body = byId("owner-settlements-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-settlements-body", 8, "No settlements yet.");
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const revenue = Number(item.sales_revenue_minor || 0) + Number(item.shipping_revenue_minor || 0);
    const values = [
      `${safeText(item.source)} · ${safeText(item.order_number)}`,
      formatDate(item.placed_at),
      Number(item.item_count || 0).toLocaleString("en-GB"),
      formatMoney(revenue),
      formatMoney(item.commission_minor),
      formatMoney(otherDeductions(item)),
      formatMoney(item.owner_proceeds_minor),
      item.financials_complete ? "Complete" : "Reconciling",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderSettlementPagination() {
  const {offset, limit, total} = state.settlements;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-settlements-page").textContent =
    total ? `${start}–${end} of ${total}` : "0 settlements";
  byId("owner-settlements-prev").disabled = offset <= 0;
  byId("owner-settlements-next").disabled = offset + limit >= total;
}

async function loadOwnerSettlements() {
  const params = new URLSearchParams({
    limit: String(state.settlements.limit),
    offset: String(state.settlements.offset),
  });
  const data = await apiRequest(`/api/v1/owner/finance/settlements?${params.toString()}`);
  state.settlements.total = Number(data.total || 0);
  renderSettlements(data.items || []);
  renderSettlementPagination();
}

function renderPayouts(items) {
  const body = byId("owner-payouts-body");
  body.replaceChildren();
  if (!items.length) {
    renderEmptyRow("owner-payouts-body", 7, "No payouts yet.");
    return;
  }
  for (const item of items) {
    const row = document.createElement("tr");
    const values = [
      safeText(item.payout_code),
      formatMoney(item.amount_minor),
      item.request_origin === "SCHEDULED" ? "Scheduled" : "Manual",
      safeText(item.status),
      formatDateTime(item.scheduled_for),
      formatDateTime(item.requested_at),
      formatDateTime(item.resolved_at),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

async function loadOwnerPayouts() {
  const data = await apiRequest("/api/v1/owner/finance/payouts");
  renderPayouts(data.items || []);
}

function renderOwnerStripeStatus(data) {
  const account = data.account || null;
  const connected = Boolean(data.connected && account);
  const ready = Boolean(data.ready_for_payouts);
  const transferReady = account?.transfers_capability_status === "ACTIVE";
  const mode = account?.livemode ? "Live" : "Test";

  byId("owner-stripe-account-state").textContent = connected ? "CONNECTED" : "NOT CONNECTED";
  byId("owner-stripe-account-note").textContent = connected
    ? `${mode} · ${safeText(account.account_type, "Express")}`
    : "Set up your payout account";

  byId("owner-stripe-verification-state").textContent = ready ? "READY" : connected ? "PENDING" : "NOT READY";
  byId("owner-stripe-verification-note").textContent = ready
    ? "Identity and payout requirements satisfied"
    : connected
      ? "Complete Stripe verification requirements"
      : "Identity verification required";

  byId("owner-stripe-transfer-state").textContent = transferReady ? "READY" : "LOCKED";

  const button = byId("owner-stripe-onboard");
  button.textContent = ready ? "Payout account ready" : connected ? "Continue Stripe onboarding" : "Set up payouts";
  button.disabled = ready;
}

function showOwnerStripeMessage(text = "", kind = "") {
  const node = byId("owner-stripe-message");
  node.textContent = text;
  node.className = `message owner-card-message${kind ? ` ${kind}` : ""}`;
}

async function loadOwnerStripeStatus() {
  try {
    const data = await apiRequest("/api/v1/stripe/connect/status");
    renderOwnerStripeStatus(data);
    showOwnerStripeMessage();
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
  }
}

async function syncOwnerStripeStatus() {
  const button = byId("owner-stripe-refresh");
  button.disabled = true;
  showOwnerStripeMessage("Refreshing Stripe payout status…");
  try {
    const status = await apiRequest("/api/v1/stripe/connect/status");
    if (status.connected) {
      await apiRequest("/api/v1/stripe/connect/sync", {method: "POST"});
    }
    await loadOwnerStripeStatus();
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function startOwnerStripeOnboarding() {
  const button = byId("owner-stripe-onboard");
  button.disabled = true;
  showOwnerStripeMessage("Preparing secure Stripe onboarding…");
  try {
    let status = await apiRequest("/api/v1/stripe/connect/status");
    if (!status.connected) {
      await apiRequest("/api/v1/stripe/connect/account", {method: "POST"});
      status = await apiRequest("/api/v1/stripe/connect/status");
    }
    if (status.ready_for_payouts) {
      renderOwnerStripeStatus(status);
      showOwnerStripeMessage("Your payout account is ready.", "success");
      return;
    }
    const link = await apiRequest("/api/v1/stripe/connect/onboarding-link", {method: "POST"});
    if (!link.url) throw new Error("Stripe onboarding link was not returned.");
    window.location.assign(link.url);
  } catch (error) {
    showOwnerStripeMessage(error.message, "error");
    button.disabled = false;
  }
}

function updateOwnerPayoutFields() {
  const cadence = byId("owner-payout-cadence").value;
  byId("owner-payout-weekday-wrap").classList.toggle(
    "hidden",
    !["WEEKLY", "FORTNIGHTLY"].includes(cadence)
  );
  byId("owner-payout-monthly-wrap").classList.toggle("hidden", cadence !== "MONTHLY");
}

function renderOwnerPayoutPreference(data) {
  const preference = data.preference || data;
  state.payoutPreference = preference;
  state.payoutPreferenceVersion = Number(preference.version || 0);
  byId("owner-payout-cadence").value = preference.cadence || "MANUAL";
  if (preference.weekday !== null && preference.weekday !== undefined) {
    byId("owner-payout-weekday").value = String(preference.weekday);
  }
  if (preference.monthly_day !== null && preference.monthly_day !== undefined) {
    byId("owner-payout-monthly-day").value = String(preference.monthly_day);
  }
  byId("owner-payout-next").textContent = preference.next_scheduled_at
    ? formatDateTime(preference.next_scheduled_at)
    : "Manual only";
  updateOwnerPayoutFields();
}

async function loadOwnerPayoutPreference() {
  const data = await apiRequest("/api/v1/payout-preferences");
  renderOwnerPayoutPreference(data);
}

async function saveOwnerPayoutPreference() {
  const cadence = byId("owner-payout-cadence").value;
  const payload = {
    cadence,
    weekday: ["WEEKLY", "FORTNIGHTLY"].includes(cadence)
      ? Number(byId("owner-payout-weekday").value)
      : null,
    monthly_day: cadence === "MONTHLY"
      ? Number(byId("owner-payout-monthly-day").value)
      : null,
    version: state.payoutPreferenceVersion,
  };
  const button = byId("owner-payout-save");
  button.disabled = true;
  const message = byId("owner-payout-preference-message");
  message.textContent = "Saving payout schedule…";
  message.className = "message owner-card-message";
  try {
    const data = await apiRequest("/api/v1/payout-preferences", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderOwnerPayoutPreference(data);
    message.textContent = "Payout schedule saved.";
    message.className = "message owner-card-message success";
  } catch (error) {
    message.textContent = error.message;
    message.className = "message owner-card-message error";
  } finally {
    button.disabled = false;
  }
}

function activateOwnerView(view, pushHistory = true, launchCameraFromClick = false) {
  const views = {
    search: ["Search", "Discover cards and sets across the complete catalogue."],
    overview: ["Home", "Everything you need to track your cards, sales and payouts."],
    inventory: ["Inventory", "Browse and search every physical card linked to your seller account."],
    scan: ["Scan cards", "Use Drop Rate recognition to identify a card, confirm it and add it safely to your inventory."],
    sales: ["Sales", "Understand every sale, deduction and penny allocated to you."],
    balance: ["Payouts", "Manage your payout account, balance and preferred payout schedule."],
    channels: ["Channels", "See exactly where your inventory is synced and whether each channel is healthy."],
    settlements: ["Settlements", "Follow order-by-order allocation and reconciliation."],
    more: ["More", "Payouts, channels, settlements and your account."],
    profile: ["Profile", "Manage your Seller Hub identity, login email and password securely."],
    settings: ["Settings", "Make your workspace feel like yours."],
  };
  const target = Object.hasOwn(views, view) ? view : "overview";
  const leavingScan = target !== "scan"
    && !byId("owner-view-scan")?.classList.contains("hidden");

  document.querySelectorAll("[data-owner-view-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.ownerViewPanel !== target);
  });
  document.querySelectorAll(".owner-nav-item[data-owner-view]").forEach((button) => {
    const primary = ["overview", "search", "inventory", "scan", "more"].includes(target) ? target : "more";
    button.classList.toggle("active", button.dataset.ownerView === primary);
    if (button.dataset.ownerView === primary) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  // One heading per section: content-led views already have a local title.
  // Keep the global title for Home, Payouts, Profile, Settings and More only.
  const contentLed = new Set(["search", "inventory", "scan", "sales", "channels", "settlements"]);
  const pageHeader = document.querySelector(".owner-page-header");
  if (pageHeader) pageHeader.hidden = contentLed.has(target);
  document.querySelector(".owner-dashboard-content")?.setAttribute("data-active-owner-view", target);
  byId("owner-page-title").textContent = views[target][0];
  byId("owner-page-subtitle").textContent = views[target][1];
  const destination=target === "overview" ? "/owner" : `/owner#${target}`;
  if(location.pathname+location.hash!==destination) history[pushHistory?"pushState":"replaceState"]({}, document.title, destination);
  document.dispatchEvent(new CustomEvent("owner-view-changed", {detail:{view:target}}));
  window.scrollTo({top: 0, behavior: "instant"});
  if (target === "scan") {
    // Readiness checks must never delay a user-initiated camera permission
    // request: getUserMedia must begin within this original click handler.
    window.ownerRecognitionEnter?.();
    if (launchCameraFromClick) window.ownerRecognitionLaunchCamera?.();
  } else if (leavingScan) {
    // Close the camera on browser navigation as well as the scanner's own Back.
    window.ownerRecognitionLeave?.();
  }
}

function errorMessage(data) {
  const detail = data?.error_description || data?.msg || data?.detail || data?.message;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return "Something went wrong. Please try again.";
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error=new Error(errorMessage(data));error.status=response.status;error.code=data.code||data.error_code;throw error; }
  return data;
}

function showMessage(text = "", kind = "") {
  const node = byId("owner-login-message");
  node.textContent = text;
  node.className = `message${kind ? ` ${kind}` : ""}`;
}

function setBusy(form, busy) {
  const button = form.querySelector('button[type="submit"]');
  if (!button) return;
  button.disabled = busy;
  button.dataset.label ||= button.textContent;
  button.textContent = busy ? "Please wait…" : button.dataset.label;
}

async function authRequest(path, options = {}) {
  return readJson(await fetch(`${state.config.supabase_url}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: state.config.publishable_key,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }));
}

function saveSession(session) {
  state.session = session;
  window.PullTheoryHubSession.save(session);
}

function clearSession() {
  state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  window.DropRateInventory?.reset();
  window.dropRateCatalogue?.destroy();
  window.dropRateCatalogue = null;
  window.dropRateScanner?.destroy();
  window.dropRateScanner = null;
  state.session = null;
  window.PullTheoryHubSession.clear();
}

async function refreshSession() {
  return window.PullTheoryHubSession.refresh(async () => {
    const previous = state.session;
    try {
      if (!previous?.refresh_token) {
        const error = new Error("Your session has expired.");
        error.sessionExpired = true;
        throw error;
      }
      const session = await authRequest("/token?grant_type=refresh_token", {method:"POST", body:JSON.stringify({refresh_token:previous.refresh_token})});
      if (state.session !== previous) throw new Error("Your account changed. Please sign in again.");
      saveSession(session);
      return session.access_token;
    } catch (error) {
      error.refreshSession = previous;
      error.sessionExpired ||= window.PullTheoryHubSession.isExpiredRefresh(error);
      throw error;
    }
  });
}
async function apiRequest(path, options = {}, retry = true) {
  const requestOptions = {
    ...options,
    headers: {
      Authorization: `Bearer ${state.session.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };
  let response = await fetch(path, requestOptions);
  if (response.status === 401 && retry) {
    requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
    response = await fetch(path, requestOptions);
  }
  return readJson(response);
}

async function loadSocialProviders() {
  try {
    const settings = await authRequest("/settings");
    const external = settings.external || {};
    state.providers.google = Boolean(external.google);
    state.providers.apple = Boolean(external.apple);
  } catch (_error) {
    state.providers.google = false;
    state.providers.apple = false;
  }

  byId("owner-google").classList.toggle("hidden", !state.providers.google);
  byId("owner-apple").classList.toggle("hidden", !state.providers.apple);
  byId("owner-social-auth").classList.toggle(
    "hidden",
    !state.providers.google && !state.providers.apple
  );
}

function startOAuth(provider) {
  if (!["google", "apple"].includes(provider) || !state.providers[provider]) {
    showMessage("That sign-in provider is not enabled yet.", "error");
    return;
  }
  const authorizeUrl = new URL(`${state.config.supabase_url}/auth/v1/authorize`);
  authorizeUrl.searchParams.set("provider", provider);
  authorizeUrl.searchParams.set("redirect_to", `${window.location.origin}/owner`);
  window.location.assign(authorizeUrl.toString());
}

function parseOAuthSession() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  if (!params.get("access_token") || params.get("type") === "recovery") return false;
  saveSession({
    access_token: params.get("access_token"),
    refresh_token: params.get("refresh_token"),
    token_type: params.get("token_type") || "bearer",
    expires_in: Number(params.get("expires_in") || 3600),
  });
  history.replaceState({}, document.title, window.location.pathname);
  return true;
}

async function hydrateSessionUser() {
  if (!state.session?.access_token) return;
  const user = await authRequest("/user", {
    headers: {Authorization: `Bearer ${state.session.access_token}`},
  });
  state.session.user = user;
  saveSession(state.session);
}

function showOwnerOnboardingWelcome() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("welcome") !== "1") return;

  const panel = byId("owner-onboarding-welcome");
  if (!panel) return;
  panel.classList.remove("hidden");

  byId("owner-welcome-inventory").addEventListener("click", () => {
    activateOwnerView("inventory");
  }, {once: true});
  byId("owner-welcome-payouts").addEventListener("click", () => {
    activateOwnerView("balance");
    byId("owner-stripe-connect-panel")?.scrollIntoView({behavior: "smooth", block: "start"});
  }, {once: true});
  byId("owner-welcome-dismiss").addEventListener("click", () => {
    panel.classList.add("hidden");
  }, {once: true});

  history.replaceState({}, document.title, "/owner");
}


async function openOwnerPortal() {
  const result = await apiRequest("/api/v1/access/me");
  const access = result.access || {};

  if (access.founder_hq_allowed === true) {
    window.location.replace("/app" + window.location.search + window.location.hash);
    return;
  }
  if (access.access_role !== "OWNER" || access.portal !== "OWNER_PORTAL") {
    throw new Error("OWNER_PORTAL_ACCESS_DENIED");
  }

  const name = access.display_name || "Owner";
  byId("owner-portal-name").textContent = name;
  byId("owner-portal-initial").textContent = name.slice(0, 1).toUpperCase();
  byId("owner-portal-email").textContent = state.session?.user?.email || "Owner account";
  byId("owner-overview-name").textContent = name;

  byId("owner-auth-view").classList.add("hidden");
  byId("owner-portal-view").classList.remove("hidden");
  const hashView = window.location.hash.replace("#", "");
  activateOwnerView(["search", "inventory", "scan", "sales", "balance", "channels", "settlements", "profile", "settings", "more"].includes(hashView) ? hashView : "overview", false);
  document.body.classList.remove("hub-restoring");
  document.dispatchEvent(new Event("hub-ready"));
  await reloadOwnerDashboard();
  showOwnerOnboardingWelcome();
}

async function finishSignIn(session) {
  saveSession(session);
  await hydrateSessionUser();
  await openOwnerPortal();
}

function denyAccess(message) {
  clearSession();
  byId("owner-portal-view").classList.add("hidden");
  byId("owner-auth-view").classList.remove("hidden");
  sessionStorage.setItem("drop-rate-signin-notice", message);
  const view = window.location.hash.slice(1);
  const returnHash = ["overview", "search", "inventory", "scan", "sales", "balance", "channels", "settlements", "profile", "settings", "more"].includes(view) ? `#${view}` : "";
  window.location.replace("/app" + returnHash);
}

async function initialise() {
  const existing = window.PullTheoryHubSession.read();
  if (!existing?.access_token && !/access_token=/.test(window.location.hash)) {
    window.location.replace("/app" + window.location.search + window.location.hash);
    return;
  }
  try {
    state.config = await readJson(await fetch("/api/v1/public-config"));
  } catch (_error) {
    window.PullTheoryHubSession.showFailure("Your workspace couldn’t load. Your session is kept; please retry.");
    return;
  }

  // This route only restores existing sessions; sign-in lives at /app.

  if (parseOAuthSession()) {
    try {
      await hydrateSessionUser();
      await openOwnerPortal();
    } catch (error) {
      denyAccess(
        error.message === "OWNER_PORTAL_ACCESS_DENIED"
          || error.message === "No active owner membership"
          ? "This account does not have owner-portal access."
          : "We could not complete social sign in."
      );
    }
    return;
  }

  try {
    const stored = window.PullTheoryHubSession.read();
    if (stored?.access_token) {
      state.session = stored;
      await openOwnerPortal();
    }
  } catch (error) {
    if ("refreshSession" in error && state.session !== error.refreshSession) return;
    if(error.sessionExpired||[401,403].includes(error.status)) denyAccess("Your session has expired. Please sign in again.");
    else if(error.message==="OWNER_PORTAL_ACCESS_DENIED"||error.message==="No active owner membership") denyAccess("Please sign in with an authorised Drop Rate account.");
    else window.PullTheoryHubSession.showFailure("Your workspace couldn’t load. Your session is kept; please retry.");
  }
}

byId("owner-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage();
  try {
    const session = await readJson(await fetch("/api/v1/public/owner-session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        identifier: byId("owner-email-input").value.trim(),
        password: byId("owner-password-input").value,
      }),
    }));
    await finishSignIn(session);
  } catch (error) {
    denyAccess(
      error.message === "OWNER_PORTAL_ACCESS_DENIED"
        || error.message === "No active owner membership"
        ? "This account does not have owner-portal access."
        : error.message
    );
  } finally {
    setBusy(form, false);
  }
});

byId("owner-google").addEventListener("click", () => startOAuth("google"));
byId("owner-apple").addEventListener("click", () => startOAuth("apple"));

byId("owner-inventory-refresh").addEventListener("click", async () => {
  state.inventory.search = byId("owner-inventory-search").value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  await reloadOwnerDashboard();
});

byId("owner-inventory-search").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  state.inventory.search = event.currentTarget.value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  await reloadOwnerDashboard();
});

let ownerInventorySearchTimer = null;
byId("owner-inventory-search").addEventListener("input", (event) => {
  window.clearTimeout(ownerInventorySearchTimer);
  ownerInventorySearchTimer = window.setTimeout(async () => {
    state.inventory.search = event.currentTarget.value.trim();
    state.inventory.status = byId("owner-inventory-status").value;
    state.inventory.offset = 0;
    await loadOwnerInventory();
  }, 320);
});

byId("owner-inventory-status").addEventListener("change", async (event) => {
  state.inventory.status = event.currentTarget.value;
  state.inventory.search = byId("owner-inventory-search").value.trim();
  state.inventory.offset = 0;
  await loadOwnerInventory();
});

byId("owner-inventory-prev").addEventListener("click", async () => {
  state.inventory.offset = Math.max(0, state.inventory.offset - state.inventory.limit);
  await loadOwnerInventory();
});

byId("owner-inventory-next").addEventListener("click", async () => {
  if (state.inventory.offset + state.inventory.limit >= state.inventory.total) return;
  state.inventory.offset += state.inventory.limit;
  await loadOwnerInventory();
});

document.querySelectorAll(".owner-nav-item[data-owner-view]").forEach((button) => {
  button.addEventListener("click", () => activateOwnerView(
    button.dataset.ownerView, true, button.dataset.ownerView === "scan"
  ));
});

document.querySelectorAll("[data-owner-jump]").forEach((button) => {
  button.addEventListener("click", () => activateOwnerView(
    button.dataset.ownerJump, true, button.dataset.ownerJump === "scan"
  ));
});

document.querySelectorAll("[data-owner-inventory-layout]").forEach((button) => {
  button.addEventListener("click", () => {
    const layout = button.dataset.ownerInventoryLayout === "list" ? "list" : "grid";
    state.inventory.layout = layout;
    byId("owner-inventory-grid").classList.toggle("hidden", layout !== "grid");
    byId("owner-inventory-table-wrap").classList.toggle("hidden", layout !== "list");
    document.querySelectorAll("[data-owner-inventory-layout]").forEach((toggle) => {
      toggle.classList.toggle("active", toggle.dataset.ownerInventoryLayout === layout);
    });
  });
});

let ownerChannelsSearchTimer = null;
byId("owner-channels-search").addEventListener("input", (event) => {
  window.clearTimeout(ownerChannelsSearchTimer);
  ownerChannelsSearchTimer = window.setTimeout(async () => {
    state.channels.search = event.currentTarget.value.trim();
    state.channels.offset = 0;
    await loadOwnerChannels();
  }, 320);
});
byId("owner-channels-filter").addEventListener("change", async (event) => {
  state.channels.channel = event.currentTarget.value || "ALL";
  state.channels.offset = 0;
  await loadOwnerChannels();
});
byId("owner-channels-refresh").addEventListener("click", loadOwnerChannels);
byId("owner-channels-prev").addEventListener("click", async () => {
  state.channels.offset = Math.max(0, state.channels.offset - state.channels.limit);
  await loadOwnerChannels();
});
byId("owner-channels-next").addEventListener("click", async () => {
  if (state.channels.offset + state.channels.limit >= state.channels.total) return;
  state.channels.offset += state.channels.limit;
  await loadOwnerChannels();
});

byId("owner-sales-prev").addEventListener("click", async () => {
  state.sales.offset = Math.max(0, state.sales.offset - state.sales.limit);
  await loadOwnerSales();
});
byId("owner-sales-next").addEventListener("click", async () => {
  if (state.sales.offset + state.sales.limit >= state.sales.total) return;
  state.sales.offset += state.sales.limit;
  await loadOwnerSales();
});
byId("owner-settlements-prev").addEventListener("click", async () => {
  state.settlements.offset = Math.max(0, state.settlements.offset - state.settlements.limit);
  await loadOwnerSettlements();
});
byId("owner-settlements-next").addEventListener("click", async () => {
  if (state.settlements.offset + state.settlements.limit >= state.settlements.total) return;
  state.settlements.offset += state.settlements.limit;
  await loadOwnerSettlements();
});

byId("owner-profile-form").addEventListener("submit", saveOwnerProfile);
byId("owner-email-form").addEventListener("submit", changeOwnerEmail);
byId("owner-password-form").addEventListener("submit", changeOwnerPassword);

byId("owner-payout-cadence").addEventListener("change", updateOwnerPayoutFields);
byId("owner-payout-save").addEventListener("click", saveOwnerPayoutPreference);

byId("owner-stripe-refresh").addEventListener("click", syncOwnerStripeStatus);
byId("owner-stripe-onboard").addEventListener("click", startOwnerStripeOnboarding);

byId("owner-logout-button").addEventListener("click", () => {
  clearSession();
  byId("owner-portal-view").classList.add("hidden");
  byId("owner-auth-view").classList.remove("hidden");
  byId("owner-password-input").value = "";
  showMessage();
  window.location.replace("/app");
});

window.addEventListener("hashchange",()=>{if(state.session && !byId("owner-portal-view").classList.contains("hidden"))activateOwnerView(location.hash.slice(1)||"overview",false);});
initialise();
