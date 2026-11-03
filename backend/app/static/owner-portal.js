"use strict";



const state = {
  config: null,
  session: null,
  providers: {google: false, apple: false},
  inventory: {offset: 0, limit: 50, total: 0, search: "", status: "", layout: "grid",
    category: "", game: "", language: "", grading: "", format: "", listing_state: "", sort: "updated", selling: false},
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

function collectionStatus(item) {
  if (item.group_members?.length > 1) {
    const labels = [...new Set(item.group_members.map(collectionStatus))];
    return labels.length > 1 ? "Mixed availability" : labels[0];
  }
  if (item.group_status_label === "Mixed status") return "Mixed availability";
  if (item.status === "SOLD") return "Sold";
  if (item.status === "RESERVED") return "Reserved";
  if (item.status === "WITHDRAWN") return "Removed";
  if (item.sale_intent === "PERSONAL_COLLECTION") return item.shopify_state === "PUBLISHED" ? "Listing needs review" : "In collection";
  if (item.shopify_state === "PUBLISHED") return "Listed";
  return {DRAFT: "Not listed", INSPECTION: "Listing review", APPROVED: "Ready to sell"}[item.status] || "In collection";
}

function sellingCopies(item) {
  return (item.group_members || [item]).filter(copy => copy.sale_intent !== "PERSONAL_COLLECTION");
}

function sellingPriceText(item) {
  const copies = sellingCopies(item);
  if (!copies.length) return "—";
  if (copies.length === 1) return copies[0].store_price_minor == null ? "Not set" : formatMoney(copies[0].store_price_minor);
  return window.DropRateInventoryGroups.moneyRange(
    {group_members: copies}, "store_price_minor", formatMoney, "Not set"
  );
}

function availabilityDescription(item) {
  const counts = new Map();
  for (const copy of item.group_members || [item]) {
    const label = collectionStatus(copy);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts].map(([label, count]) => `${count} ${label.toLowerCase()}`).join(" · ");
}

function inventoryCardSubtitle(item) {
  return [
    ["CARD", "COMIC", "FIGURE"].includes(item.product_type)
      ? conditionLabel(item) === "—" ? "Condition not recorded" : conditionLabel(item) : "",
    safeText(item.set_name, ""),
    item.card_number ? `#${item.card_number}` : "",
    safeText(item.language, "Language not recorded"),
    safeText(item.variant, ""),
  ].filter(Boolean).join(" · ") || safeText(item.game);
}

function conditionLabel(item) {
  if(item.product_type==="FIGURE")return [safeText(item.condition,"Condition not recorded"),item.seal_status==="SEALED"?"Sealed packaging":item.seal_status==="UNSEALED"?"Opened packaging":""].filter(Boolean).join(" · ");
  if (String(item.seal_status || "").toUpperCase() === "SEALED") return "Sealed";
  if (String(item.seal_status || "").toUpperCase() === "UNSEALED") return "Unsealed";
  return item.grade
    ? `${safeText(item.grading_company, "Graded")} ${item.grade}`
    : safeText(item.condition);
}

function inventoryTypeLabel(item) {
  if (item.product_type === "FIGURE") return "Figure";
  if (item.product_type === "COMIC") return item.game === "Manga" ? "Manga" : "Comic";
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

// The API pages complete groups; the same display helper is used in Founder HQ.
function ownerInventoryDisplayGroups(items) {
  return window.DropRateInventoryGroups.group(items);
}

const collectionFilterKeys = ["search", "status", "category", "game", "language", "grading", "format", "listing_state"];
const collectionDefaults = {search:"",status:"",category:"",game:"",language:"",grading:"",format:"",listing_state:"",sort:"updated",offset:0,layout:"grid"};
let collectionOwner = null, collectionPreviousFilters = null;
function collectionHasFilters() { return collectionFilterKeys.some(key => Boolean(state.inventory[key])); }
function collectionStorageKey() { return state.session?.user?.id ? `drop_rate_collection_view:${state.session.user.id}` : null; }
function saveCollectionView() {
  const key = collectionStorageKey(); if (!key || state.inventory.selling) return;
  try { sessionStorage.setItem(key, JSON.stringify(Object.fromEntries(Object.keys(collectionDefaults).map(name => [name, state.inventory[name]])))); } catch (_) { /* Session memory remains usable. */ }
}
function restoreCollectionView() {
  const account = state.session?.user?.id || state.session?.access_token;
  if (collectionOwner === account) return;
  collectionOwner = account; collectionPreviousFilters = null;
  Object.assign(state.inventory, collectionDefaults, {selling:false,facets:null});
  const key = collectionStorageKey();
  if (key) try {
    const saved = JSON.parse(sessionStorage.getItem(key));
    if (saved && typeof saved === "object") {
      for (const name of collectionFilterKeys) if (typeof saved[name] === "string" && saved[name].length <= 160) state.inventory[name] = saved[name];
      if (["updated","newest","oldest","name","name_desc","value_desc","value_asc"].includes(saved.sort)) state.inventory.sort = saved.sort;
      if (["grid","list"].includes(saved.layout)) state.inventory.layout = saved.layout;
      if (Number.isInteger(saved.offset) && saved.offset >= 0 && saved.offset <= 100000) state.inventory.offset = saved.offset;
      if (state.inventory.status === "WITHDRAWN") {state.inventory.status = "";state.inventory.offset = 0;}
    }
  } catch (_) { /* Ignore an obsolete or corrupt view preference. */ }
  updateCollectionControls();
}
function collectionControlIcon(name) {
  const paths = {
    filters:"M4 7h16M7 4v6M4 17h16M16 14v6",
    grid:"M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    list:"M4 5h3v3H4zM11 6.5h9M4 16h3v3H4zM11 17.5h9",
    refresh:"M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 17.9 17",
    close:"m6 6 12 12M6 18 18 6",
  };
  const icon=document.createElementNS("http://www.w3.org/2000/svg","svg");
  for(const [key,value] of Object.entries({viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-width":"1.6","stroke-linecap":"round","stroke-linejoin":"round","aria-hidden":"true",focusable:"false"}))icon.setAttribute(key,value);
  const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",paths[name]||paths.filters);icon.append(path);return icon;
}
function closeCollectionFilters({restoreFocus=true}={}) {
  const dialog=byId("owner-collection-filter-dialog");
  if(dialog?.open)dialog.close();
  const trigger=byId("owner-collection-filter-trigger");
  trigger?.setAttribute("aria-expanded","false");
  if(restoreFocus && trigger?.getClientRects().length)trigger.focus({preventScroll:true});
}
function updateCollectionControls() {
  const toolbar = document.querySelector(".owner-inventory-toolbar"); if (!toolbar) return;
  let controls = byId("owner-collection-controls");
  if (!controls) { controls = document.createElement("div"); controls.id = "owner-collection-controls"; toolbar.after(controls); }
  if (!controls.dataset.ready) {
    controls.dataset.ready = "true"; controls.className = "owner-collection-controls";
    const filterButton=document.createElement("button");filterButton.type="button";filterButton.id="owner-collection-filter-trigger";filterButton.className="owner-collection-filter-trigger";
    filterButton.setAttribute("aria-haspopup","dialog");filterButton.setAttribute("aria-controls","owner-collection-filter-dialog");filterButton.setAttribute("aria-expanded","false");
    const caption=document.createElement("span");caption.textContent="Filter & sort";
    const badge=document.createElement("span");badge.id="owner-collection-filter-count";badge.className="owner-collection-filter-count";badge.hidden=true;
    filterButton.append(collectionControlIcon("filters"),caption,badge);
    const layout=toolbar.querySelector(".owner-layout-toggle"),refresh=byId("owner-inventory-refresh");
    toolbar.append(filterButton);
    if(layout){
      layout.setAttribute("role","group");layout.setAttribute("aria-label","Collection view");
      for(const control of layout.querySelectorAll("button"))control.replaceChildren(collectionControlIcon(control.dataset.ownerInventoryLayout));
      toolbar.append(layout);
    }
    if(refresh){refresh.replaceChildren(collectionControlIcon("refresh"));refresh.title="Refresh collection";refresh.setAttribute("aria-label","Refresh collection");toolbar.append(refresh);}
    const dialog=document.createElement("dialog");dialog.id="owner-collection-filter-dialog";dialog.className="owner-collection-filter-dialog";dialog.setAttribute("aria-labelledby","owner-collection-filter-title");
    const heading=document.createElement("header"),headingCopy=document.createElement("div"),title=document.createElement("h2"),intro=document.createElement("p");
    title.id="owner-collection-filter-title";title.textContent="Filter & sort";intro.textContent="Find the right items in your collection.";headingCopy.append(title,intro);
    const close=document.createElement("button");close.type="button";close.className="owner-collection-filter-close";close.setAttribute("aria-label","Close collection filters");close.append(collectionControlIcon("close"));close.addEventListener("click",()=>closeCollectionFilters());heading.append(headingCopy,close);
    const body=document.createElement("div");body.className="owner-collection-filter-body";
    const section=(label)=>{const area=document.createElement("section"),heading=document.createElement("h3");area.className="owner-collection-filter-section";heading.textContent=label;area.append(heading);body.append(area);return area;};
    const order=section("Sort order");
    const sortLabel = document.createElement("label"); sortLabel.className = "owner-collection-sort"; sortLabel.textContent = "Order your items";
    const sort = document.createElement("select"); sort.id = "owner-collection-sort"; sort.setAttribute("aria-label","Sort collection");
    for (const [value,label] of [["updated","Recently updated"],["newest","Recently added"],["oldest","Oldest added"],["name","Name A–Z"],["name_desc","Name Z–A"],["value_desc","Displayed value: high to low"],["value_asc","Displayed value: low to high"]]) { const option = document.createElement("option"); option.value=value;option.textContent=label;sort.append(option); }
    sort.addEventListener("change", () => window.DropRateCollection.setFilters({sort:sort.value}));sortLabel.append(sort);order.append(sortLabel);
    const valueNote=document.createElement("p");valueNote.id="owner-collection-value-sort-note";valueNote.className="owner-item-note";valueNote.textContent="Uses the displayed value, including labelled guides and historical values. Items without a value appear last.";order.append(valueNote);
    const items=section("Items"),fields=document.createElement("div");fields.className="owner-collection-filter-fields";items.append(fields);
    for (const [key,label] of [["category","Category"],["game","Game / series"],["language","Language"],["grading","Physical format"],["format","Card or sealed"]]) {
      const field = document.createElement("label"); field.textContent = label;
      const select = document.createElement("select"); select.id = `owner-collection-${key}`; select.setAttribute("aria-label", `Filter collection by ${label.toLowerCase()}`);
      select.addEventListener("change", () => window.DropRateCollection.setFilters({[key]:select.value}));
      field.append(select); fields.append(field);
    }
    const selling=section("Selling & availability"),sellingFields=document.createElement("div");sellingFields.className="owner-collection-filter-fields";selling.append(sellingFields);
    const sellingLabel=document.createElement("label");sellingLabel.textContent="Selling status";
    const sellingState=document.createElement("select");sellingState.id="owner-collection-listing_state";sellingState.setAttribute("aria-label","Filter collection by selling status");sellingState.addEventListener("change",()=>window.DropRateCollection.setFilters({listing_state:sellingState.value}));sellingLabel.append(sellingState);sellingFields.append(sellingLabel);
    const status=byId("owner-inventory-status");
    if(status){
      status.querySelector('option[value="WITHDRAWN"]')?.remove();
      const all=status.querySelector('option[value=""]');if(all)all.textContent="Active collection";
      const label=document.createElement("label");label.textContent="Inventory status";label.append(status);sellingFields.append(label);
    }
    const footer=document.createElement("footer"),clear=document.createElement("button"),done=document.createElement("button");
    clear.type=done.type="button";clear.id="owner-collection-clear-filters";clear.className="owner-collection-filter-reset";clear.textContent="Clear filters";clear.addEventListener("click",()=>window.DropRateCollection.clearFilters());
    done.className="owner-collection-filter-done";done.textContent="Show collection";done.addEventListener("click",()=>closeCollectionFilters());footer.append(clear,done);
    dialog.append(heading,body,footer);document.body.append(dialog);
    filterButton.addEventListener("click",()=>{
      if(!dialog.open){
        dialog.showModal();
        window.DropRateHub?.animate(dialog,[{opacity:0,transform:"translateY(12px)"},{opacity:1,transform:"translateY(0)"}],280);
      }
      filterButton.setAttribute("aria-expanded","true");
    });
    dialog.addEventListener("cancel",event=>{event.preventDefault();closeCollectionFilters();});
    dialog.addEventListener("close",()=>filterButton.setAttribute("aria-expanded","false"));
    document.addEventListener("owner-view-changed",()=>closeCollectionFilters({restoreFocus:false}));
    window.addEventListener("hub-session-cleared",()=>closeCollectionFilters({restoreFocus:false}));
    const context=document.createElement("p");context.id="owner-collection-context";context.className="owner-collection-context";context.setAttribute("role","status");controls.append(context);
    const chips = document.createElement("div");chips.id="owner-collection-filter-chips";chips.className="owner-collection-filter-chips";controls.append(chips);
  }
  const facets = state.inventory.facets || {}, category = state.inventory.category || "";
  const setOptions = (key, choices) => {
    const field = byId(`owner-collection-${key}`); if (!field) return;
    const current = state.inventory[key] || "";field.replaceChildren();
    if (current && !choices.some(([value]) => value===current)) choices.push([current,current]);
    for (const [value,label] of choices) {const option=document.createElement("option");option.value=value;option.textContent=label;field.append(option);}field.value=current;
  };
  setOptions("category",[["","All categories"],["TCG","Trading Card Games"],["SPORTS","Sports Cards"],["COMICS","Comics"],["MANGA","Manga"],["FIGURES","Figures"]]);
  const combinations = (facets.combinations || []).filter(row => !category || row.category===category);
  const games = category ? [...new Set(combinations.map(row=>row.game))] : facets.games || [];
  setOptions("game",[["",["COMICS","MANGA"].includes(category)?"All series":"All games"],...games.map(value=>[value,value])]);
  setOptions("language",[["","All languages"],...(facets.languages || []).map(value=>[value,value])]);
  setOptions("grading",[["","All formats"],["RAW","Ungraded"],["GRADED","Graded / certified"]]);
  byId("owner-collection-grading").disabled=category==="FIGURES";
  byId("owner-collection-grading").closest("label").hidden=category==="FIGURES";
  setOptions("format",[["","Cards & sealed"],["CARD","Cards"],["SEALED","Sealed products"]]);
  byId("owner-collection-format").disabled = ["COMICS","MANGA","FIGURES"].includes(category);
  byId("owner-collection-format").closest("label").hidden=byId("owner-collection-format").disabled;
  setOptions("listing_state",[["","All states"],["PERSONAL","Personal collection"],["ALL_FOR_SALE","All items for sale"],["PREPARING","Preparing to sell"],["REVIEW","Under review"],["READY","Ready to publish"],["LISTED","Live on Drop Rate"]]);
  byId("owner-collection-sort").value=state.inventory.sort || "updated";
  byId("owner-collection-value-sort-note").hidden=!["value_desc","value_asc"].includes(state.inventory.sort);
  if (byId("owner-inventory-search")) byId("owner-inventory-search").value=state.inventory.search || "";
  if (byId("owner-inventory-status")) byId("owner-inventory-status").value=state.inventory.status || "";
  const active = collectionFilterKeys.filter(key=>state.inventory[key]);
  const filterCount=active.filter(key=>key!=="search").length;
  const badge=byId("owner-collection-filter-count");badge.textContent=String(filterCount);badge.hidden=!filterCount;
  byId("owner-collection-filter-trigger").setAttribute("aria-label",`Filter and sort collection${filterCount?`, ${filterCount} active ${filterCount===1?"filter":"filters"}`:""}`);
  byId("owner-collection-clear-filters").disabled=!active.length;
  const sortText=byId("owner-collection-sort").selectedOptions[0]?.textContent || "Recently updated";
  const total=Number(state.inventory.total||0);
  byId("owner-collection-context").textContent=`${total.toLocaleString("en-GB")} ${total===1?"product":"products"}${active.length?" found":""} · ${sortText}`;
  document.querySelectorAll("[data-owner-inventory-layout]").forEach(control=>{
    const selected=control.dataset.ownerInventoryLayout===(state.inventory.layout||"grid");control.classList.toggle("active",selected);control.setAttribute("aria-pressed",String(selected));
  });
  const chips=byId("owner-collection-filter-chips");chips.replaceChildren();
  for (const key of active) {
    const choice = byId(`owner-collection-${key}`)?.selectedOptions?.[0]?.textContent || (key==="status" ? byId("owner-inventory-status")?.selectedOptions?.[0]?.textContent : null) || state.inventory[key];
    const chip=document.createElement("button");chip.type="button";const label=document.createElement("span");label.textContent=`${key==="search" ? "Search: " : ""}${choice}`;chip.append(label,collectionControlIcon("close"));chip.setAttribute("aria-label",`Clear ${key.replaceAll("_"," ")} filter`);
    chip.addEventListener("click",()=>window.DropRateCollection.setFilters({[key]:""}));chips.append(chip);
  }
  if(active.length){const clear=document.createElement("button");clear.type="button";clear.textContent="Clear filters";clear.addEventListener("click",()=>window.DropRateCollection.clearFilters());chips.append(clear);}
  chips.hidden=!active.length;
  let picker=byId("owner-selling-picker-status");
  if(!picker){picker=document.createElement("section");picker.id="owner-selling-picker-status";controls.after(picker);}
  picker.className="owner-selling-picker-status";picker.hidden=!state.inventory.selling;picker.replaceChildren();
  if(state.inventory.selling){
    const copy=document.createElement("div"),heading=document.createElement("strong"),note=document.createElement("p");
    heading.textContent="Choose the item you want to sell";note.textContent="Select an item, then confirm the exact copy. Your collection stays private until you choose a selling action.";copy.append(heading,note);
    const cancel=document.createElement("button");cancel.type="button";cancel.textContent="Back to collection";cancel.addEventListener("click",()=>window.DropRateCollection.cancelSelling());picker.append(copy,cancel);
  }
}
function collectionOpenItem(item) {
  if (!item?.id) return;
  const options={selling:state.inventory.selling===true};
  window.DropRateInventory?.open(item,options);
}
window.DropRateCollection = {
  setFilters: async (changes={}, {reset=false,navigate=false}={}) => {
    window.clearTimeout(ownerInventorySearchTimer);
    const previousSort=state.inventory.sort,previousOffset=state.inventory.offset;
    if(reset) Object.assign(state.inventory,collectionDefaults);
    if(navigate){state.inventory.selling=false;collectionPreviousFilters=null;}
    for(const key of [...collectionFilterKeys,"sort"]) if(Object.hasOwn(changes,key))state.inventory[key]=String(changes[key]??"");
    if(Object.hasOwn(changes,"category")){if(!Object.hasOwn(changes,"game"))state.inventory.game="";if(["COMICS","MANGA","FIGURES"].includes(state.inventory.category))state.inventory.format="";if(state.inventory.category==="FIGURES")state.inventory.grading="";}
    if(Object.hasOwn(changes,"listing_state"))state.inventory.status="";
    if(Object.hasOwn(changes,"status"))state.inventory.listing_state="";
    state.inventory.offset=0;updateCollectionControls();saveCollectionView();
    if(navigate)activateOwnerView("inventory");
    try{await loadOwnerInventory();}catch(error){if(Object.hasOwn(changes,"sort")){state.inventory.sort=previousSort;state.inventory.offset=previousOffset;updateCollectionControls();saveCollectionView();}showPortalMessage(error.message||"Your collection could not load. Try again.","error");}
  },
  clearFilters(){return this.setFilters(Object.fromEntries(collectionFilterKeys.map(key=>[key,""])));},
  async startSelling(){
    if(!state.inventory.selling)collectionPreviousFilters=Object.fromEntries(Object.keys(collectionDefaults).map(key=>[key,state.inventory[key]]));
    Object.assign(state.inventory,collectionDefaults,{selling:true});updateCollectionControls();activateOwnerView("inventory");
    try{await loadOwnerInventory();}catch(error){showPortalMessage(error.message||"Your collection could not load. Try again.","error");}
  },
  async cancelSelling(){state.inventory.selling=false;Object.assign(state.inventory,collectionPreviousFilters||collectionDefaults);collectionPreviousFilters=null;updateCollectionControls();saveCollectionView();await loadOwnerInventory();},
  openItem:collectionOpenItem,
  async openItemById(id){if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(id||"")))return;await window.DropRateInventory?.open({id});},
};
document.addEventListener("hub:inventory-open",event=>window.DropRateCollection.openItemById(event.detail?.inventoryId));
document.addEventListener("owner-inventory-changed",()=>{
  if(!state.session?.access_token)return;
  state.inventory.facets=null;
  Promise.allSettled([loadOwnerInventory(),loadOwnerOverview()]);
});

function renderInventoryRows(items) {
  const body = byId("owner-inventory-body");
  body.replaceChildren();
  body.closest("table")?.classList.add("owner-collection-table");

  if (!items.length) {
    const row = document.createElement("tr");row.className="owner-collection-empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "muted";
    cell.textContent = "No inventory matches these filters.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");row.className="owner-collection-row";

    const cardCell = document.createElement("td");cardCell.className="owner-collection-product-cell";
    const canOpen=Boolean(item.id && window.DropRateInventory);
    const cardWrap = document.createElement(canOpen?"button":"div");
    cardWrap.className = "owner-table-card" + (canOpen?" owner-inventory-open":"");
    const image=createCardImage(item,"owner-table-mini-image");
    if((item.grouped_quantity||1)>1){const quantity=document.createElement("span");quantity.className="owner-list-quantity";quantity.textContent="×"+item.grouped_quantity;image.append(quantity);}
    cardWrap.append(image);
    const cardCopy = document.createElement("div");
    cardCopy.className = "owner-table-card-copy";
    const cardName = document.createElement("strong");
    cardName.textContent = safeText(item.name);
    cardName.title=safeText(item.name);
    const edition=document.createElement("small");edition.className="owner-list-edition";
    edition.textContent=[safeText(item.set_name,""),item.card_number?`#${item.card_number}`:"",safeText(item.variant,"")].filter(Boolean).join(" · ") || inventoryTypeLabel(item);
    edition.title=edition.textContent;
    const cardCode = document.createElement("small");cardCode.className="owner-list-copy-details";
    cardCode.textContent=[safeText(item.language,"Language not recorded"),conditionLabel(item)==="—"?"Condition not recorded":conditionLabel(item)].join(" · ");
    cardCode.title=cardCode.textContent;
    cardCopy.append(cardName,edition,cardCode);
    if (canOpen) {
      cardWrap.type="button";
      cardWrap.setAttribute("aria-label",`View ${item.name} · ${cardCode.textContent}${(item.grouped_quantity||1)>1?` · ${item.grouped_quantity} copies`:""}`);
      cardWrap.addEventListener("click",()=>collectionOpenItem(item));
    }
    cardWrap.append(cardCopy);
    cardCell.append(cardWrap);

    const statusCell = document.createElement("td");statusCell.className="owner-collection-status-cell";
    const status = document.createElement("span");
    status.className = `owner-status-pill ${statusClass(collectionStatus(item) === "Mixed availability" ? "mixed" : item.status)}`;
    status.textContent = collectionStatus(item);
    status.title = availabilityDescription(item);
    statusCell.append(status);

    const marketCell = document.createElement("td");marketCell.className="owner-collection-market-cell";
    marketCell.dataset.label=(window.DropRateReferenceValue?.label(item)||"Market value")+((item.grouped_quantity||1)>1?" · each":"");
    const valueText=item.reference_value ? window.DropRateReferenceValue.compactText(item, formatMoney) : item.market_value_minor == null
      ? "Value unavailable" : "Value: " + formatMoney(item.market_value_minor);
    const value=document.createElement("strong");value.textContent=valueText.replace(/^Value:\s*/,"");
    value.className=/^Value:\s*£/.test(valueText)?"owner-list-value":"owner-list-value is-unavailable";marketCell.append(value);
    // Keep source age discoverable without putting a long timestamp in a
    // narrow inventory list cell. Full evidence/date remain in item details.
    if(item.reference_value && window.DropRateReferenceValue?.isHistorical(item)){
      const age=document.createElement("small");
      age.className="owner-table-historical-label";
      age.textContent="Historical value";
      marketCell.append(age);
    }
    if((item.grouped_quantity||1)>1 && item.group_valued_count>0 && item.group_valued_count<item.grouped_quantity)
      {const coverage=document.createElement("small");coverage.className="owner-list-value-coverage";coverage.textContent=item.group_valued_count+"/"+item.grouped_quantity+" copies valued";marketCell.append(coverage);}
    const storeCell = document.createElement("td");storeCell.className="owner-collection-price-cell";storeCell.dataset.label="Selling price";
    storeCell.textContent = sellingPriceText(item);
    storeCell.classList.toggle("is-personal",!sellingCopies(item).length);

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
    title.textContent = collectionHasFilters()
      ? "No items match these filters"
      : state.inventory.selling ? "No items available to prepare for sale" : "Your collection starts here";
    const copy = document.createElement("span");
    copy.textContent = collectionHasFilters()
      ? "Your items are still saved. Clear a filter to see more of your collection."
      : state.inventory.selling ? "Add an item to your collection first. Sold, reserved and removed copies cannot be prepared for a new listing."
        : "Scan, search the catalogue or import a collection to get started.";
    empty.append(icon, title, copy);
    const action=document.createElement("button");action.type="button";action.className="owner-primary-action";
    action.textContent=collectionHasFilters()?"Clear filters":"Add an item";
    action.addEventListener("click",()=>collectionHasFilters()?window.DropRateCollection.clearFilters():document.dispatchEvent(new CustomEvent("hub:add-requested",{detail:{source:"collection"}})));
    empty.append(action);
    grid.append(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "owner-inventory-card";

    // Image and details are a single keyboard-accessible tile target.
    // Do not nest interactive buttons inside a clickable card.
    const imageWrap = document.createElement("div");
    imageWrap.className = "owner-card-image-wrap";
    imageWrap.append(createCardImage(item, "owner-card-thumb"));
    if((item.grouped_quantity||1)>1){
      const count=document.createElement("span");count.className="owner-card-quantity";
      count.textContent="×"+item.grouped_quantity;
      count.setAttribute("aria-label",item.grouped_quantity+" physical copies");
      imageWrap.append(count);
      // The quantity also appears in the full-tile button's accessible name.
    }
    // Full-tile button is rendered below, above artwork and body.

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
    status.className = `owner-status-pill ${statusClass(collectionStatus(item) === "Mixed availability" ? "mixed" : item.status)}`;
    status.textContent = collectionStatus(item);
    status.title = availabilityDescription(item);
    heading.append(title, status);

    const prices = document.createElement("div");
    prices.className = "owner-card-prices";
    const storeText = sellingPriceText(item);
    const storeLabel = "Selling price";
    for (const [labelText, valueText] of [
      ["Market value", item.reference_value ? window.DropRateReferenceValue.compactText(item, formatMoney) : item.market_value_minor == null ? "Value pending" : "Value: " + formatMoney(item.market_value_minor)],
      [storeLabel, storeText],
    ]) {
      if (labelText === storeLabel && !sellingCopies(item).length) continue;
      const box = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = labelText === "Market value"
        ? (window.DropRateReferenceValue?.label(item) || labelText) + (item.grouped_quantity > 1 ? " · each" : "") : labelText;
      const value = document.createElement("strong");
      value.textContent = labelText === "Market value" ? valueText.replace(/^Value:\s*/, "") : valueText;
      box.append(label, value);
      // Stale values stay explicitly historical, but their date/source detail
      // lives in the item view instead of cluttering small mobile tiles.
      if(labelText==="Market value" && item.reference_value && window.DropRateReferenceValue?.isHistorical(item)){
        const historical=document.createElement("small");
        historical.className="owner-card-historical-label";
        historical.textContent="Historical value";
        box.append(historical);
      }
      if(labelText==="Market value" && (item.grouped_quantity||1)>1 && item.group_valued_count>0){
        const note=document.createElement("small");
        note.className="owner-card-value-coverage";
        note.textContent=item.group_valued_count+"/"+item.grouped_quantity+" copies valued";
        box.append(note);
      }
      prices.append(box);
    }

    const identity = document.createElement("div");identity.className="owner-card-identity";
    for(const value of [safeText(item.language,"Language not recorded"),inventoryTypeLabel(item)]){
      const detail=document.createElement("span");detail.textContent=value;identity.append(detail);
    }
    body.append(heading, identity, prices);
    const actions = document.createElement("div");
    actions.className = "owner-card-actions";
    // One button stretches over the entire tile. The independent refresh
    // control sits above it and never opens details or double-submits.
    const openDetails = document.createElement("button");
    openDetails.type="button";
    openDetails.className="owner-card-open-overlay";
    openDetails.setAttribute("aria-label",
      `${state.inventory.selling ? "Prepare listing for" : "View details for"} ${item.grouped_quantity>1 ? item.grouped_quantity+" copies of " : ""}${item.name}`);
    openDetails.addEventListener("click",()=>collectionOpenItem(item));

    if (item.can_refresh_market) {
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "owner-market-refresh";
      refresh.title = "Refresh market value";
      refresh.setAttribute("aria-label", `Refresh market value for ${item.name}`);
      refresh.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6.1 6.1a8 8 0 0 1 13 2.9M4.9 15a8 8 0 0 0 13 2.9"/></svg>';
      refresh.addEventListener("click", async () => {
        refresh.disabled = true;
        refresh.setAttribute("aria-busy", "true");
        refresh.setAttribute("aria-label", `Refreshing market value for ${item.name}`);
        refresh.title = "Refreshing market value…";
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
          refresh.removeAttribute("aria-busy");
          refresh.setAttribute("aria-label", `Refresh market value for ${item.name}`);
          refresh.title = "Refresh market value";
        }
      });
      actions.append(refresh);
    }

    card.append(imageWrap, body, openDetails);
    // An unrefreshable item has no action bar at all; do not leave an empty
    // absolute wrapper that could appear clipped on 320px Safari layouts.
    if(actions.children.length)card.append(actions);
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
    status.textContent = collectionStatus(item);
    status.title = item.group_status_description || "";
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

function ownerMoverNumber(value) {
  if (!["number", "string"].includes(typeof value) || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function ownerMoverDate(value) {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}

function ownerWeeklyContext(summary, hasRows) {
  const messages = {
    EMPTY_COLLECTION: ["Your collection is empty", "Add an item to your collection to see any available weekly comparisons."],
    NO_CURRENT_VALUES: ["No current values to compare", "Weekly changes need a current value and matching earlier evidence for an item in your collection."],
    WAITING_FOR_HISTORY: ["Not enough weekly history", "Your valued items do not yet have matching evidence from about a week earlier."],
    NO_CHANGE: ["No change in comparable values", "The available weekly comparisons are unchanged. This covers only items with matching history."],
    READY: ["Weekly comparison coverage", "Changes are shown only for comparable items in your collection."],
  };
  const [title, note] = messages[summary?.status] || (hasRows ? messages.READY :
    ["Weekly comparisons unavailable", "Only your items with a current value and matching weekly history can be compared."]);
  const lines = [note];
  const count = (key) => Number.isSafeInteger(summary?.[key]) && summary[key] >= 0 ? summary[key] : null;
  const owned = count("owned_item_count"), current = count("current_value_item_count");
  const profiles = count("current_value_product_count"), compared = count("comparable_item_count");
  if (owned > 0 && current !== null) {
    lines.push(`${current} of ${owned} ${owned === 1 ? "copy has" : "copies have"} current values` +
      (profiles > 0 ? ` across ${profiles} distinct ${profiles === 1 ? "item" : "items"}.` : "."));
  }
  if (owned > 0 && compared !== null) {
    lines.push(`Comparable weekly history covers ${compared} of ${owned} ${owned === 1 ? "copy" : "copies"}.`);
  }
  const guides = count("guide_comparison_count"), stale = count("stale_item_count"), details = count("needs_details_item_count");
  if (guides > 0) lines.push(`${guides} ${guides === 1 ? "comparison uses a guide estimate" : "comparisons use guide estimates"}.`);
  if (stale > 0) lines.push(`${stale} ${stale === 1 ? "copy has" : "copies have"} stale evidence.`);
  if (details > 0) lines.push(`Details need confirming for ${details} ${details === 1 ? "copy" : "copies"}.`);
  if (!hasRows && summary?.history_ready) {
    const first = ownerMoverDate(summary.earliest_baseline_at), last = ownerMoverDate(summary.latest_current_at);
    if (first && last) lines.push(`Compared evidence: ${first} to ${last}.`);
  }
  return {title, lines};
}

function renderOwnerInsightList(containerId, items, mover = false, summary = null) {
  const container = byId(containerId);
  if (!container) return;
  container.replaceChildren();

  if (mover) {
    const context = ownerWeeklyContext(summary, items.length > 0);
    const panel = document.createElement("div");
    panel.className = "owner-empty-inline";
    const title = document.createElement("strong");
    title.textContent = context.title;
    panel.append(title);
    for (const text of context.lines) {
      const line = document.createElement("span");
      line.textContent = text;
      panel.append(line);
    }
    container.append(panel);
    if (!items.length) return;
  }

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "owner-empty-inline";
    const title = document.createElement("strong");
    title.textContent = "No valuation data yet";
    const copy = document.createElement("span");
    copy.textContent = "Cards appear here after the pricing engine produces a market value.";
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
    if (mover && Number.isSafeInteger(item.quantity) && item.quantity > 0) {
      sub.textContent += ` · Qty ${item.quantity}`;
      sub.className = "owner-mover-context";
    }
    copy.append(name, meta, sub);

    if (mover) {
      const source = {CATALOGUE_CARDMARKET_V1: "Cardmarket", CATALOGUE_EBAY_V4: "eBay sold evidence"}[item.method] || "Source unavailable";
      const label = safeText(item.comparison_label, item.comparison_kind === "GUIDE_ESTIMATE" ? "Guide estimate change" : "Value change");
      const basis = document.createElement("small");
      basis.className = "owner-mover-context";
      basis.textContent = `${label} · ${source}`;
      const dates = document.createElement("small");
      dates.className = "owner-mover-context";
      const first = ownerMoverDate(item.baseline_at), last = ownerMoverDate(item.current_at);
      const days = ownerMoverNumber(item.comparison_days);
      dates.textContent = first && last ? `${first} → ${last}` +
        (days !== null && days > 0 ? ` · ${days.toLocaleString("en-GB", {maximumFractionDigits: 2})} days` : "") : "Evidence dates unavailable";
      copy.append(basis, dates);
    }

    const value = document.createElement("div");
    value.className = "owner-insight-value";
    const current = document.createElement("strong");
    const currentAmount = mover ? ownerMoverNumber(item.current_value_minor) : item.market_value_minor;
    current.textContent = mover && currentAmount === null ? "Value unavailable" : formatMoney(currentAmount);
    value.append(current);

    if (mover) {
      const pct = ownerMoverNumber(item.change_pct);
      const difference = ownerMoverNumber(item.change_minor);
      const direction = difference !== null && difference !== 0 ? Math.sign(difference) : Math.sign(pct || 0);
      const smallChange = pct !== null && Math.abs(pct) < 0.01 && difference !== null && difference !== 0;
      const movement = document.createElement("span");
      movement.className =
        "owner-movement " + (pct !== null && direction > 0 ? "up" : pct !== null && direction < 0 ? "down" : "flat");
      movement.textContent = pct === null ? "Change unavailable" :
        (direction > 0 ? "↑ " : direction < 0 ? "↓ " : "→ ")
        + (smallChange ? "<0.01" : Math.abs(pct).toFixed(2).replace(/\.00$/, ""))
        + "%";
      const delta = document.createElement("small");
      delta.className = "owner-mover-context";
      delta.textContent = difference === null ? "Amount unavailable" :
        (difference >= 0 ? "+" : "") + formatMoney(difference) + (item.quantity > 1 ? " per copy" : "");
      value.append(movement, delta);
    } else {
      const store = document.createElement("small");
      store.textContent = "Recommended retail: " +
        (window.DropRateReferenceValue?.recommendationText(item, formatMoney) || "Recommendation unavailable");
      value.append(store);
    }

    row.append(rank, copy, value);
    container.append(row);
  });
}

async function loadOwnerInsights() {
  const data = await apiRequest("/api/v1/owner/insights");
  renderOwnerInsightList("owner-top-valued-cards", data.top_valued || [], false);
  renderOwnerInsightList("owner-weekly-movers", data.weekly_movers || [], true, data.weekly_movers_summary);
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
  if (["ERROR", "ACTION_REQUIRED", "REVIEW_REQUIRED"].includes(stateValue)) return "withdrawn";
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
    (ownerChannelCount(shopify, "ERROR") + ownerChannelCount(shopify, "REVIEW_REQUIRED")).toLocaleString("en-GB");

  const ebayStatus = byId("owner-channel-ebay-status");
  ebayStatus.textContent = ebay.connected
    ? (ebay.sync_enabled ? "Connected · publishing enabled" : "Connected · publishing unavailable")
    : "Not connected";
  ebayStatus.className =
    "owner-status-pill " + (ebay.connected && ebay.sync_enabled ? "approved" : "inspection");
  byId("owner-channel-ebay-note").textContent = ebay.sync_unavailable_reason ||
    (ebay.connected && !ebay.sync_enabled ? "Publishing is not enabled. You can still prepare your cards below."
      : "Open a card to check its price, condition, photos and listing readiness.");
  byId("owner-channel-ebay-live").textContent =
    ownerChannelCount(ebay, "LIVE").toLocaleString("en-GB");
  byId("owner-channel-ebay-errors").textContent =
    (ownerChannelCount(ebay, "ERROR") + ownerChannelCount(ebay, "REVIEW_REQUIRED")).toLocaleString("en-GB");
}

function renderOwnerChannelState(item, code) {
  const savedState = String(item[code === "SHOPIFY" ? "shopify_state" : "ebay_state"] || "NOT_LINKED").toUpperCase();
  const testOnly = code === "SHOPIFY" && item.shopify_test_mode === true;
  const needsReview = !testOnly && item.sale_intent === "PERSONAL_COLLECTION"
    && savedState === (code === "SHOPIFY" ? "PUBLISHED" : "LIVE");
  const badge = document.createElement("span");
  badge.className = "owner-status-pill " + ownerChannelStatusClass(testOnly ? "TEST_ONLY" : needsReview ? "REVIEW_REQUIRED" : savedState);
  badge.textContent = testOnly ? "Test listing" : needsReview ? "Listing needs review" : savedState.replaceAll("_", " ");
  if (needsReview) badge.title = "This copy is in your personal collection, but its saved channel status is published. Drop Rate needs to review the listing.";
  return badge;
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
    shopifyCell.append(renderOwnerChannelState(item, "SHOPIFY"));
    if (item.shopify_price_minor != null) {
      const price = document.createElement("small");
      price.className = "owner-channel-price";
      price.textContent = formatMoney(item.shopify_price_minor);
      shopifyCell.append(price);
    }

    const ebayCell = document.createElement("td");
    ebayCell.append(renderOwnerChannelState(item, "EBAY"));
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

    const personalShopify = item.sale_intent === "PERSONAL_COLLECTION"
      && ["PUBLISHED", "ERROR"].includes(item.shopify_state) && item.shopify_test_mode !== true;
    const personalEbay = item.sale_intent === "PERSONAL_COLLECTION"
      && ["LIVE", "ERROR"].includes(item.ebay_state);
    if (personalShopify || personalEbay) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "ghost-button compact";
      retry.textContent = "Retry removal";
      retry.title = "Remove this personal copy from sale, preserving other sellable copies.";
      retry.addEventListener("click", async () => {
        const account = state.session?.user?.id;
        retry.disabled = true;
        retry.textContent = "Removing…";
        try {
          await apiRequest(`/api/v1/inventory/${encodeURIComponent(item.inventory_id || item.id)}/sale-intent`, {
            method: "POST", body: JSON.stringify({version: item.version, sale_intent: "PERSONAL_COLLECTION"})
          });
          if (state.session?.user?.id !== account) return;
          showOwnerChannelsMessage("Personal copy removed from sale. Other sellable copies remain available.", "success");
          await loadOwnerChannels();
          await loadOwnerInventory();
        } catch (error) {
          if (state.session?.user?.id === account) showOwnerChannelsMessage(error.message, "error");
          retry.disabled = false;
          retry.textContent = "Retry removal";
        }
      });
      (personalShopify ? shopifyCell : ebayCell).append(retry);
    }

    for (const [code, cell, linked] of [["SHOPIFY", shopifyCell, item.shopify_state === "PUBLISHED"], ["EBAY", ebayCell, item.ebay_state === "LIVE"]]) {
      if (linked) continue;
      const channel = channels.find(value => value.code === code);
      const eligible = item.inventory_status === "APPROVED" && item.sale_intent === "FOR_SALE";
      const blocker = item.channel_sync_blockers?.[code] || channel?.sync_unavailable_reason;
      if (eligible && channel?.sync_enabled && !blocker) {
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
        note.textContent = !eligible ? (item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "Awaiting approval") : blocker || "Seller sync not enabled yet";
        cell.append(note);
      }
      if (code === "EBAY" && item.product_type === "CARD") {
        const prepare = document.createElement("button");
        prepare.type = "button";
        prepare.className = "ghost-button compact";
        prepare.textContent = "Prepare for eBay";
        prepare.addEventListener("click", () => window.DropRateInventory.open(
          {...item, id: item.inventory_id || item.id}, {prepareEbay: true}
        ));
        cell.append(prepare);
      }
    }

    const marketCell = document.createElement("td");
    marketCell.textContent =
      item.reference_value ? window.DropRateReferenceValue.text(item, formatMoney) : item.market_value_minor == null ? "Value pending" : formatMoney(item.market_value_minor)+(item.pricing_method==="CARDMARKET_GUIDE_V1"?" · Cardmarket estimate":"");

    const storeCell = document.createElement("td");
    storeCell.textContent =
      item.sale_intent === "PERSONAL_COLLECTION" ? "—"
        : item.store_price_minor == null ? "Not set" : formatMoney(item.store_price_minor);

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
    : "0 items";
  byId("owner-channels-prev").disabled = offset <= 0;
  byId("owner-channels-next").disabled = offset + limit >= total;
}

function showOwnerChannelsMessage(text = "", kind = "") {
  const node = byId("owner-channels-message");
  node.textContent = text;
  node.className = "owner-inline-message" + (kind ? " " + kind : "");
}

async function loadOwnerChannels() {
  const revision = state.channels.requestRevision = (state.channels.requestRevision || 0) + 1;
  const account = state.session?.user?.id || state.session?.access_token;
  const current = () => revision === state.channels.requestRevision
    && account === (state.session?.user?.id || state.session?.access_token);
  const params = new URLSearchParams({
    limit: String(state.channels.limit),
    offset: String(state.channels.offset),
    channel: state.channels.channel,
  });
  if (state.channels.search) params.set("search", state.channels.search);

  try {
    const data = await apiRequest("/api/v1/owner/channels?" + params.toString());
    if (!current()) return;
    state.ownerChannelAccount = account;
    state.ownerChannelSummaries = Array.isArray(data.channels)?data.channels:[];
    state.channels.total = Number(data.total || 0);
    byId("owner-channels-total").textContent =
      state.channels.total.toLocaleString("en-GB");
    renderOwnerChannelSummary(data);
    renderOwnerChannelsRows(data.items || [], data.channels || []);
    renderOwnerChannelsPagination();
    showOwnerChannelsMessage();
  } catch (error) {
    if (!current()) return;
    showOwnerChannelsMessage(error.message, "error");
    throw error;
  }
}

function renderInventoryPagination() {
  const {offset, limit, total} = state.inventory;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  byId("owner-inventory-page").textContent = total
    ? `${start}–${end} of ${total} entries`
    : "0 items";
  byId("owner-inventory-prev").disabled = offset <= 0;
  byId("owner-inventory-next").disabled = offset + limit >= total;
}

async function loadOwnerOverview() {
  const revision=state.overviewRequestRevision=(state.overviewRequestRevision||0)+1;
  const account=state.session?.user?.id || state.session?.access_token;
  const data = await apiRequest("/api/v1/owner/overview");
  if(revision!==state.overviewRequestRevision || account!==(state.session?.user?.id || state.session?.access_token))return;
  const summary = data.summary || {};
  state.hubOverview={userId:state.session?.user?.id || null,summary};
  const total = Number(summary.total_inventory_count || 0);
  byId("owner-total-inventory").textContent = total.toLocaleString("en-GB");
  const cardCount = summary.total_card_count, sealedCount = summary.total_sealed_count;
  const kindNote = byId("owner-inventory-type-note");
  if (kindNote) {
    const validBreakdown = Number.isInteger(cardCount) && Number.isInteger(sealedCount)
      && cardCount >= 0 && sealedCount >= 0 && cardCount + sealedCount <= total;
    kindNote.textContent = total === 0 ? "No physical inventory added yet"
      : validBreakdown && cardCount + sealedCount === total
        ? `${cardCount} cards · ${sealedCount} sealed products`
        : "Physical cards, sealed products and other collectibles";
  }
  const unvalued = Number(summary.active_unvalued_count || 0);
  const valued = Number(summary.active_valued_count || 0);
  const activeCount = Number.isInteger(summary.active_inventory_count) ? summary.active_inventory_count : total;
  const marketIncomplete = activeCount > 0 && unvalued > 0;
  const marketUnavailable = activeCount > 0 && valued === 0;
  const marketLabel = byId("owner-market-value-label");
  if (marketLabel) marketLabel.textContent = marketIncomplete ? "Known market value · partial" : "Market value";
  byId("owner-market-value").textContent = marketUnavailable
    ? "Unavailable" : formatMoney(summary.active_market_value_minor);
  byId("owner-market-value").classList.toggle("owner-value-unavailable", marketUnavailable);
  byId("owner-market-value-note").textContent = activeCount === 0
    ? "Add stock to see sourced market valuations"
    : marketIncomplete
      ? `${valued} of ${activeCount} valued · ${unvalued} awaiting eligible prices`
      : `${valued} of ${activeCount} valued from current evidence`;
  if(summary.guide_estimate_count)
    byId("owner-market-value-note").textContent += ` · ${summary.guide_estimate_count} guide estimate${summary.guide_estimate_count === 1 ? "" : "s"}`;

  // Saved Store Prices represent real owner-entered asking prices. Never
  // replace that headline with £1 automatic floor-priced recommendations.
  const askingCount = Number(summary.recorded_asking_count || 0);
  const askingTotal = summary.recorded_asking_value_minor;
  const hasAsking = askingCount > 0 && Number.isInteger(askingTotal) && askingTotal > 0;
  byId("owner-store-value").textContent = activeCount === 0 ? formatMoney(0)
    : hasAsking ? formatMoney(askingTotal) : "Not set";
  byId("owner-store-value").classList.toggle("owner-value-unavailable", activeCount > 0 && !hasAsking);
  const askingNote = byId("owner-asking-price-note");
  if (askingNote) askingNote.textContent = activeCount === 0 ? "No items available for pricing yet"
    : hasAsking
      ? `${askingCount} of ${activeCount} copies have saved Store Prices · incomplete total`
      : `0 of ${activeCount} copies have saved Store Prices`;
  const recommendedCount = Number(summary.active_recommended_count || 0);
  const recommendationTotal = summary.active_recommended_retail_minor;
  const hasRecommendation = recommendedCount > 0 && Number.isInteger(recommendationTotal) && recommendationTotal > 0;
  const recommendationNote = byId("owner-recommendation-note");
  if (recommendationNote) recommendationNote.textContent = hasRecommendation
    ? `Automatic suggestion: ${formatMoney(recommendationTotal)} on ${recommendedCount} of ${activeCount}`
        + (summary.recommendation_guide_count ? ` · ${summary.recommendation_guide_count} guide estimate${summary.recommendation_guide_count === 1 ? "" : "s"}` : "")
    : "Automatic recommendation unavailable · does not alter your asking prices";
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
  document.dispatchEvent(new CustomEvent("hub:overview-updated",{detail:{summary}}));
}

async function loadOwnerInventory() {
  const revision = state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  const account = state.session?.user?.id || state.session?.access_token;
  const current=()=>revision===state.inventory.requestRevision && account===(state.session?.user?.id || state.session?.access_token);
  state.inventory.controller?.abort();
  const controller=new AbortController();state.inventory.controller=controller;
  const params = new URLSearchParams({
    limit: String(state.inventory.limit),
    offset: String(state.inventory.offset),
    group_copies: "true",
  });
  if (state.inventory.search) params.set("search", state.inventory.search);
  if (state.inventory.status) params.set("status", state.inventory.status);
  for(const key of ["category","game","language","grading","format","listing_state","sort"]){if(state.inventory[key])params.set(key,state.inventory[key]);}
  if(state.inventory.selling)params.set("prepare_selling","true");
  if(!state.inventory.facets)params.set("include_facets","true");
  byId("owner-inventory-grid")?.setAttribute("aria-busy","true");
  byId("owner-inventory-table-wrap")?.setAttribute("aria-busy","true");
  if(byId("owner-collection-context"))byId("owner-collection-context").textContent="Updating collection…";

  let data;
  try{data=await apiRequest(`/api/v1/owner/inventory?${params.toString()}`,{signal:controller.signal});}
  catch(error){if(!current() || error.name==="AbortError")return;if(byId("owner-collection-context"))byId("owner-collection-context").textContent="Collection could not update. Try again.";throw error;}
  finally{if(current()){byId("owner-inventory-grid")?.removeAttribute("aria-busy");byId("owner-inventory-table-wrap")?.removeAttribute("aria-busy");}}
  if (!current()) return;
  state.inventory.total = Number(data.total || 0);
  if(data.facets)state.inventory.facets=data.facets;
  // Removing the last item on a page returns to the nearest real page.
  if(state.inventory.offset>0 && !(data.items||[]).length){
    state.inventory.offset=state.inventory.total>0 ? Math.floor((state.inventory.total-1)/state.inventory.limit)*state.inventory.limit : 0;
    if(state.inventory.total>0)return loadOwnerInventory();
  }
  const items = data.items || [];
  const displayGroups=ownerInventoryDisplayGroups(items);
  renderInventoryRows(displayGroups);
  renderInventoryCards(displayGroups);
  renderInventoryPagination();
  updateCollectionControls();saveCollectionView();
  const layout=state.inventory.layout || "grid";
  byId("owner-inventory-grid")?.classList.toggle("hidden",layout!=="grid");
  byId("owner-inventory-table-wrap")?.classList.toggle("hidden",layout!=="list");
  const totalLabel = byId("owner-inventory-total-label");
  if (totalLabel) {
    totalLabel.textContent = displayGroups.length.toLocaleString("en-GB");
    const copyTotal = Number(data.copy_total ?? data.total ?? 0);
    const units = copyTotal.toLocaleString("en-GB");
    const fullyLoaded = state.inventory.offset===0 && (data.grouped ? displayGroups.length : items.length)>=state.inventory.total;
    if(totalLabel.nextElementSibling)
      totalLabel.nextElementSibling.textContent =
        (fullyLoaded? (displayGroups.length===1?"product":"products") : "products shown")+
        " · "+units+" "+(copyTotal===1?"copy":"copies");
  }
  if (state.inventory.offset === 0 && !collectionHasFilters() && !state.inventory.selling && ["updated","newest"].includes(state.inventory.sort||"updated")) {
    renderOverviewLatestInventory(displayGroups);
  }
  document.dispatchEvent(new CustomEvent("hub:inventory-updated",{detail:{items:displayGroups,total:state.inventory.total,copyTotal:data.copy_total,filtered:collectionHasFilters()||state.inventory.selling}}));
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
  window.DropRateAccountExperience?.setAccount(user);
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
    search: ["Search", "Find a card, comic or manga and add it to your collection."],
    overview: ["Home", "Your collection, at a glance."],
    inventory: ["Collection", "Everything you've added, in one place."],
    scan: ["Scan", "Take a photo, check the match and add it to your collection."],
    selling: ["Selling", "List items and manage your sales when you're ready."],
    sales: ["Orders", "Prepare orders and review each sale."],
    balance: ["Payouts", "Manage your payout account, balance and preferred payout schedule."],
    channels: ["Channels", "See exactly where your inventory is synced and whether each channel is healthy."],
    settlements: ["Sale breakdowns", "See each sale, fee and your proceeds."],
    more: ["More", "Selling, payouts and your account."],
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
    const primary = ["overview", "search", "inventory", "scan", "selling"].includes(target) ? target
      : ["sales","balance","channels","settlements"].includes(target)?"selling":null;
    button.classList.toggle("active", button.dataset.ownerView === primary);
    if (button.dataset.ownerView === primary) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  // One heading per section: content-led views already have a local title.
  // Keep the global title for Home, Payouts, Profile, Settings and More only.
  const contentLed = new Set(["search", "inventory", "scan", "sales", "selling", "channels", "settlements"]);
  const pageHeader = document.querySelector(".owner-page-header");
  if (pageHeader) pageHeader.hidden = contentLed.has(target);
  document.querySelector(".owner-dashboard-content")?.setAttribute("data-active-owner-view", target);
  byId("owner-page-title").textContent = views[target][0];
  byId("owner-page-subtitle").textContent = views[target][1];
  const destination=target === "overview" ? "/owner" : `/owner#${target}`;
  if(location.pathname+location.hash!==destination) history[pushHistory?"pushState":"replaceState"]({}, document.title, destination);
  document.dispatchEvent(new CustomEvent("owner-view-changed", {detail:{view:target}}));
  window.scrollTo({top: 0, behavior: "instant"});
  if(target!=="inventory" && state.inventory.selling){
    state.inventory.selling=false;Object.assign(state.inventory,collectionPreviousFilters||collectionDefaults);collectionPreviousFilters=null;
    updateCollectionControls();saveCollectionView();
    if(state.session?.access_token)loadOwnerInventory().catch(error=>showPortalMessage(error.message||"Your collection could not load. Try again.","error"));
  }
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
  if (detail?.message) {
    // The Shopify publisher supplies the precise blockers but used to show
    // only its generic heading, leaving sellers unsure why nothing listed.
    const reasons=Array.isArray(detail.missing)?detail.missing:detail.blockers;
    const safe=Array.isArray(reasons)?reasons.filter(value=>typeof value==="string" && value.trim()).slice(0,12):[];
    return safe.length?`${detail.message} Required: ${safe.join("; ")}`:detail.message;
  }
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
  state.overviewRequestRevision=(state.overviewRequestRevision||0)+1;
  window.clearTimeout(ownerInventorySearchTimer);
  state.inventory.controller?.abort();
  state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  state.channels.requestRevision = (state.channels.requestRevision || 0) + 1;
  state.ownerChannelAccount = null;
  state.ownerChannelSummaries = [];
  state.financeSummary = null;
  state.payoutPreference = null;
  state.profile = null;
  state.hubOverview = null;
  collectionOwner=null;collectionPreviousFilters=null;
  Object.assign(state.inventory,collectionDefaults,{selling:false,facets:null});
  window.DropRateInventory?.reset();
  window.DropRateBooks?.reset();
  window.dropRateCatalogue?.destroy();
  window.dropRateCatalogue = null;
  window.dropRateScanner?.destroy();
  window.dropRateScanner = null;
  state.session = null;
  window.PullTheoryHubSession.clear();
}

async function refreshSession() {
  const previous = state.session;
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  return window.PullTheoryHubSession.refresh(async () => {
    try {
      checkSession();
      if (!previous?.refresh_token) {
        const error = new Error("Your session has expired.");
        error.sessionExpired = true;
        throw error;
      }
      const session = await authRequest("/token?grant_type=refresh_token", {method:"POST", body:JSON.stringify({refresh_token:previous.refresh_token})});
      checkSession();
      if (session.user?.id && previous.user?.id && session.user.id !== previous.user.id) {
        throw new Error("Your account changed. Please sign in again.");
      }
      if (!session.user && previous.user) session.user = previous.user;
      saveSession(session);
      return session.access_token;
    } catch (error) {
      checkSession();
      error.refreshSession = previous;
      error.sessionExpired ||= window.PullTheoryHubSession.isExpiredRefresh(error);
      throw error;
    }
  });
}
async function apiRequest(path, options = {}, retry = true) {
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  checkSession();
  const requestOptions = {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {}), Authorization: `Bearer ${state.session.access_token}`},
  };
  try {
    let response = await fetch(path, requestOptions);
    checkSession();
    if (response.status === 401 && retry) {
      requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
      checkSession();
      response = await fetch(path, requestOptions);
      checkSession();
    }
    const data = await readJson(response);
    checkSession();
    return data;
  } catch (error) { checkSession(); throw error; }
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
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  try {
    const user = await authRequest("/user", {
      headers: {Authorization: `Bearer ${state.session.access_token}`},
    });
    checkSession();
    state.session.user = user;
    saveSession(state.session);
  } catch (error) { checkSession(); throw error; }
}

function showOwnerOnboardingWelcome() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("welcome") !== "1") return;

  const panel = byId("owner-onboarding-welcome");
  if (!panel) return;
  panel.classList.remove("hidden");

  const firstItem=byId("owner-welcome-inventory");
  if(!firstItem.hasAttribute("data-hub-add"))firstItem.addEventListener("click", () => {
    activateOwnerView("inventory");
  }, {once: true});
  byId("owner-welcome-search").addEventListener("click", () => {
    activateOwnerView("search");
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
  restoreCollectionView();
  const hashView = window.location.hash.replace("#", "");
  activateOwnerView(["search", "inventory", "scan", "selling", "sales", "balance", "channels", "settlements", "profile", "settings", "more"].includes(hashView) ? hashView : "overview", false);
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
  window.clearTimeout(ownerInventorySearchTimer);
  state.inventory.search = byId("owner-inventory-search").value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  await reloadOwnerDashboard();
});

byId("owner-inventory-search").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.isComposing || event.keyCode===229) return;
  event.preventDefault();
  window.clearTimeout(ownerInventorySearchTimer);
  state.inventory.search = event.currentTarget.value.trim();
  state.inventory.status = byId("owner-inventory-status").value;
  state.inventory.offset = 0;
  try{await loadOwnerInventory();}catch(error){showPortalMessage(error.message||"Search could not load. Try again.","error");}
});

let ownerInventorySearchTimer = null;
byId("owner-inventory-search").addEventListener("input", (event) => {
  const search = event.currentTarget.value.trim();
  window.clearTimeout(ownerInventorySearchTimer);
  ownerInventorySearchTimer = window.setTimeout(async () => {
    state.inventory.search = search;
    state.inventory.status = byId("owner-inventory-status").value;
    state.inventory.offset = 0;
    try { await loadOwnerInventory(); }
    catch (error) { showPortalMessage(error.message || "Search could not load. Try again.", "error"); }
  }, 320);
});

byId("owner-inventory-status").addEventListener("change", async (event) => {
  window.clearTimeout(ownerInventorySearchTimer);
  state.inventory.status = event.currentTarget.value;
  state.inventory.listing_state="";
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
  button.addEventListener("click", () => button.hasAttribute("data-owner-selling-start")
    ? window.DropRateCollection.startSelling()
    : activateOwnerView(button.dataset.ownerJump, true, button.dataset.ownerJump === "scan"));
});

document.querySelectorAll("[data-owner-inventory-layout]").forEach((button) => {
  button.addEventListener("click", () => {
    const layout = button.dataset.ownerInventoryLayout === "list" ? "list" : "grid";
    state.inventory.layout = layout;
    saveCollectionView();
    byId("owner-inventory-grid").classList.toggle("hidden", layout !== "grid");
    byId("owner-inventory-table-wrap").classList.toggle("hidden", layout !== "list");
    document.querySelectorAll("[data-owner-inventory-layout]").forEach((toggle) => {
      toggle.classList.toggle("active", toggle.dataset.ownerInventoryLayout === layout);
      toggle.setAttribute("aria-pressed",String(toggle.dataset.ownerInventoryLayout === layout));
    });
  });
});

let ownerChannelsSearchTimer = null;
byId("owner-channels-search").addEventListener("input", (event) => {
  const search = event.currentTarget.value.trim();
  window.clearTimeout(ownerChannelsSearchTimer);
  ownerChannelsSearchTimer = window.setTimeout(async () => {
    state.channels.search = search;
    state.channels.offset = 0;
    try { await loadOwnerChannels(); } catch (_) { /* The channel panel shows the request error. */ }
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
updateCollectionControls();
initialise();
