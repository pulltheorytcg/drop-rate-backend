/* Drop Rate interaction layer. All writes remain in the existing authorised
 * workflows; this module connects destinations and presents their real state. */
"use strict";
(() => {
  const workspace = window.DropRateWorkspace;
  if (!workspace) return;
  document.body.classList.add("hub-experience");
  const {seller, icon} = workspace;
  const $ = id => document.getElementById(id);
  const node = (tag, className = "", text = "") => {
    const item = document.createElement(tag); item.className = className;
    if (text) item.textContent = text;
    return item;
  };
  const button = (label, action, className = "hub-button") => {
    const item = node("button", className, label); item.type = "button";
    item.addEventListener("click", action); return item;
  };
  const navigate = view => workspace.navigate(view === "home" ? seller ? "overview" : "dashboard" : view);
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const activeAnimations = new Set();
  let motionOff = false;
  try { motionOff = localStorage.getItem("drop-rate-interface-motion") === "off"; } catch (_) {}
  const animate = (element, frames, duration = 300, delay = 0) => {
    if (!element?.animate || reduced?.matches || motionOff || document.hidden) return;
    const animation = element.animate(frames, {duration, delay, easing: "cubic-bezier(.22,1,.36,1)", fill: "backwards"});
    activeAnimations.add(animation);
    animation.finished?.catch(() => {}).finally(() => activeAnimations.delete(animation));
  };
  const motionState = () => {
    document.body.dataset.hubMotion = motionOff || reduced?.matches ? "off" : "on";
    if (motionOff || reduced?.matches) {activeAnimations.forEach(animation => animation.cancel()); activeAnimations.clear();}
    document.querySelectorAll("[data-hub-motion]").forEach(control => {
      control.checked = !motionOff && !reduced?.matches;
      control.disabled = Boolean(reduced?.matches);
    });
    document.querySelectorAll(".hub-motion-note").forEach(note => {
      note.textContent = reduced?.matches ? "Reduced motion is enabled in your device settings." : "Short transitions and gentle artwork movement. Saved on this device.";
    });
  };
  reduced?.addEventListener?.("change", motionState);
  motionState();

  // A single add entry, while Scan remains a direct shortcut for repeat use.
  let addDialog, addFocus;
  function closeAdd() {
    if (addDialog?.open) addDialog.close();
    addFocus?.focus?.();
  }
  function chooseAdd(action) { closeAdd(); action(); }
  function addChoice(title, description, symbol, action) {
    const choice = button("", () => chooseAdd(action), "hub-add-choice");
    const mark = node("span", "hub-choice-symbol"); mark.append(icon(symbol));
    const copy = node("span", "hub-choice-copy"); copy.append(node("strong", "", title), node("small", "", description));
    choice.append(mark, copy, icon("arrow")); return choice;
  }
  function importChoices(body) {
    body.replaceChildren(node("p", "hub-add-hint", "Choose where your collection file came from."));
    for (const [adapter, label, hint] of [["COLLECTR", "Collectr", "Use your collection CSV export"], ["HOLODEX", "Holodex", "Import and review your exported collection"], ["GENERIC_CSV", "Other spreadsheet", "Use a CSV or TSV file"]]) {
      body.append(addChoice(label, hint, "collection", () => {
        navigate("inventory");
        document.querySelector(`[data-owner-import-adapter="${adapter}"]`)?.click();
      }));
    }
    body.append(button("Back to add item", renderAdd, "hub-text-button"));
  }
  function renderAdd() {
    const body = addDialog.querySelector(".hub-add-body"); body.replaceChildren();
    body.append(addChoice("Scan an item", "Take a photo and confirm the exact match", "scan", () => {
      if (seller) activateOwnerView("scan", true, true);
      else navigate("intake");
    }));
    body.append(addChoice("Search the catalogue", "Find a card, book or collectible by name", "search", () => window.openDropRateCatalogue?.()));
    if (seller && window.DropRateBooks) body.append(addChoice("Add a comic or manga", "Confirm the edition and details from your copy", "collection", () => window.DropRateBooks.open()));
    if (window.DropRateCollectibles) body.append(addChoice("Add sports cards or figures", "Record the exact item in your collection", "collection", () => window.DropRateCollectibles.open()));
    if (!seller && typeof openInventoryIntake === "function") body.append(addChoice("Enter item details", "Create a draft from a confirmed identity", "collection", () => openInventoryIntake()));
    const canImport = seller ? document.querySelector("[data-owner-import-adapter]") : typeof openInventoryImport === "function";
    if (canImport) {
      const item = button("", () => seller ? importChoices(body) : chooseAdd(() => openInventoryImport()), "hub-add-choice");
      const copy = node("span", "hub-choice-copy"); copy.append(node("strong", "", "Import a collection"), node("small", "", "Bring your existing collection from a file"));
      const mark = node("span", "hub-choice-symbol"); mark.append(icon("collection"));
      item.append(mark, copy, icon("arrow")); body.append(item);
    }
    body.append(node("p", "hub-add-hint", "Items are added to your collection. You choose separately whether to sell them."));
  }
  function openAdd() {
    if (!addDialog) {
      addDialog = node("dialog", "hub-add-dialog"); addDialog.id = "hub-add-dialog";
      addDialog.setAttribute("aria-labelledby", "hub-add-title");
      const header = node("header", "hub-dialog-heading");
      const copy = node("div"); copy.append(node("span", "hub-eyebrow", "Your next addition"));
      const heading = node("h2", "", "Add to your collection"); heading.id = "hub-add-title"; copy.append(heading);
      const close = button("×", closeAdd, "hub-icon-button"); close.setAttribute("aria-label", "Close add item");
      header.append(copy, close); addDialog.append(header, node("div", "hub-add-body")); document.body.append(addDialog);
      addDialog.addEventListener("cancel", event => {event.preventDefault(); closeAdd();});
    }
    addFocus = document.activeElement; renderAdd();
    if (!addDialog.open) addDialog.showModal();
    animate(addDialog, [{opacity: 0, transform: "translateY(14px)"}, {opacity: 1, transform: "translateY(0)"}], 320);
    return true;
  }
  window.DropRateHub = {openAdd, navigate, animate};
  document.addEventListener("hub:add-requested", openAdd);
  document.querySelectorAll("[data-hub-add]").forEach(control => control.addEventListener("click", openAdd));

  // Account controls use the role's existing allowed destinations and sign-out.
  const oldAccount = document.querySelector(seller ? ".owner-topbar .user-chip" : ".topbar .user-chip");
  const signOut = $(seller ? "owner-logout-button" : "logout-button");
  let accountMenu, accountTrigger;
  function closeAccount(restore = false) {
    if (!accountMenu) return;
    accountMenu.hidden = true; accountTrigger.setAttribute("aria-expanded", "false");
    if (restore) accountTrigger.focus();
  }
  if (oldAccount && signOut) {
    accountTrigger = node("button", "user-chip workspace-account-trigger"); accountTrigger.type = "button";
    accountTrigger.setAttribute("aria-label", "Open account and workspace tools");
    accountTrigger.setAttribute("aria-haspopup", "menu"); accountTrigger.setAttribute("aria-expanded", "false");
    accountTrigger.setAttribute("aria-controls", "hub-account-menu");
    accountTrigger.append(...oldAccount.childNodes); oldAccount.replaceWith(accountTrigger);
    accountMenu = node("div", "hub-account-menu"); accountMenu.id = "hub-account-menu";
    accountMenu.setAttribute("role", "menu"); accountMenu.setAttribute("aria-label", "Your account"); accountMenu.hidden = true;
    function syncAccountMenu() {
      const restoreFocus = accountMenu.contains(document.activeElement);
      accountMenu.replaceChildren();
      for (const [key, label] of [["profile", "Your account"], ["settings", "Appearance & settings"], ["accounts", "Business"], ["more", "All workspace tools"]]) {
      const original = workspace.toolButtons.get(key);
      if (key !== "more" && (!original || original.hidden || original.disabled || original.getAttribute("aria-hidden") === "true")) continue;
      const choice = button(label, () => {closeAccount(); navigate(key);}, "hub-account-option");
      choice.setAttribute("role", "menuitem"); choice.prepend(icon(key === "more" ? "more" : key)); accountMenu.append(choice);
      }
      accountMenu.append(signOut);
      if (restoreFocus) accountMenu.querySelector("button")?.focus();
    }
    signOut.className = "hub-account-option hub-signout-option"; signOut.setAttribute("role", "menuitem");
    signOut.addEventListener("click", () => closeAccount()); syncAccountMenu();
    const permissionChanges = new MutationObserver(syncAccountMenu);
    for (const key of ["profile", "settings", "accounts"]) {
      const source = workspace.toolButtons.get(key);
      if (source) permissionChanges.observe(source, {attributes: true, attributeFilter: ["hidden", "disabled", "aria-hidden"]});
    }
    accountTrigger.after(accountMenu);
    accountTrigger.addEventListener("click", () => {
      if (!accountMenu.hidden) {closeAccount(); return;}
      syncAccountMenu();
      accountMenu.hidden = false; accountTrigger.setAttribute("aria-expanded", "true");
      accountMenu.querySelector("button")?.focus();
      animate(accountMenu, [{opacity: 0, transform: "translateY(-5px)"}, {opacity: 1, transform: "translateY(0)"}], 180);
    });
    accountMenu.addEventListener("keydown", event => {
      if (event.key === "Escape") {event.preventDefault(); closeAccount(true); return;}
      const choices = [...accountMenu.querySelectorAll("button:not(:disabled)")];
      let position = choices.indexOf(document.activeElement);
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault(); position = event.key === "Home" ? 0 : event.key === "End" ? choices.length - 1 : (position + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length;
        choices[position]?.focus();
      }
    });
    document.addEventListener("click", event => {if (!accountMenu.hidden && !accountMenu.contains(event.target) && !accountTrigger.contains(event.target)) closeAccount();});
    accountMenu.addEventListener("focusout", event => {if (event.relatedTarget && !accountMenu.contains(event.relatedTarget) && event.relatedTarget !== accountTrigger) closeAccount();});
  }

  const appearance = document.querySelector(".collector-appearance");
  if (appearance) {
    const option = node("label", "hub-motion-option"); const copy = node("span");
    copy.append(node("strong", "", "Interface animation"), node("small", "hub-motion-note"));
    const toggle = node("input"); toggle.type = "checkbox"; toggle.dataset.hubMotion = "";
    toggle.addEventListener("change", () => {
      motionOff = !toggle.checked;
      try {localStorage.setItem("drop-rate-interface-motion", motionOff ? "off" : "auto");} catch (_) {}
      motionState();
    });
    option.append(copy, toggle); appearance.append(option); motionState();
  }

  // A repeat visit starts with the collection and real outstanding work.
  let summary = null;
  const home = $(seller ? "owner-view-overview" : "seller-view-dashboard");
  let attention;
  if (seller && home) {
    attention = node("section", "hub-attention"); attention.hidden = true;
    attention.setAttribute("aria-label", "Your next steps");
    home.querySelector(".owner-kpi-grid")?.after(attention);
  }
  function attentionItem(title, description, action, mark) {
    const item = button("", action, "hub-attention-item");
    const copy = node("span"); copy.append(node("strong", "", title), node("small", "", description));
    item.append(icon(mark), copy, icon("arrow")); return item;
  }
  function renderAttention() {
    if (!attention) return;
    attention.replaceChildren();
    const dispatchText = $("owner-dispatch-count")?.textContent?.trim() || "";
    const orders = /^\d+$/.test(dispatchText) ? Number(dispatchText) : 0;
    if (orders) attention.append(attentionItem(`${orders} ${orders === 1 ? "order" : "orders"} to prepare`, "See the next available action for each order", () => navigate("sales"), "sales"));
    const review = Number(summary?.collection_states?.review || 0);
    if (review > 0) attention.append(attentionItem(`${review} ${review === 1 ? "listing" : "listings"} in review`, "Follow your listing progress", () => window.DropRateCollection?.setFilters?.({listing_state: "REVIEW"}, {reset: true, navigate: true}), "verification"));
    attention.hidden = !attention.childElementCount;
  }
  document.addEventListener("hub:overview-updated", event => {
    summary = event.detail?.summary || null;
    for (const [id, key] of [["draft", "preparing"], ["inspection", "review"], ["approved", "ready"], ["listed", "listed"]]) {
      const amount = $("owner-pipeline-" + id);
      if (amount && Number.isInteger(summary?.collection_states?.[key])) {
        amount.textContent = String(summary.collection_states[key]);
        const bar = $("owner-pipeline-" + id + "-bar");
        if (bar) bar.style.width = `${Math.min(100, summary.collection_states[key] / Math.max(1, summary.collection_states.for_sale || 0) * 100)}%`;
      }
    }
    const total = summary?.total_inventory_count;
    if (Number.isInteger(total)) {
      const empty = total === 0; home?.classList.toggle("hub-first-collection", empty);
      const title = home?.querySelector(".collector-headline");
      if (title) {
        const emphasis = document.createElement("em");
        emphasis.textContent = "collection";
        title.replaceChildren("Your ", emphasis, empty ? " starts here." : ".");
      }
      const intro = home?.querySelector(".collector-intro");
      if (intro) intro.textContent = empty ? "Add your first item. Scan it or find its exact edition in the catalogue." : "Every find, in one place.";
      const add = home?.querySelector(".collector-primary");
      if (add) add.textContent = empty ? "Add your first item" : "Add item";
    }
    renderAttention();
  });
  if ($("owner-dispatch-count")) new MutationObserver(renderAttention).observe($("owner-dispatch-count"), {childList: true, characterData: true, subtree: true});

  // Selling offers direct work areas. Existing content and API contracts stay intact.
  const selling = $(seller ? "owner-view-selling" : "seller-view-selling");
  if (seller && selling) {
    const sections = node("nav", "hub-selling-nav"); sections.setAttribute("aria-label", "Selling workspace");
    for (const [view, label, description] of [["inventory", "Your listings", "Prepare and manage items you want to sell"], ["sales", "Orders", "Review sales and prepare orders"], ["balance", "Payouts", "Your balance and payments"]]) {
      const link = button("", () => view === "inventory" ? window.DropRateCollection?.setFilters?.({listing_state: "ALL_FOR_SALE"}, {reset: true, navigate: true}) : navigate(view), "hub-selling-destination");
      link.append(icon(view === "inventory" ? "selling" : view), node("strong", "", label), node("small", "", description), icon("arrow"));
      sections.append(link);
    }
    const intro = selling.querySelector(".owner-selling-intro"); intro?.after(sections);
    const pipeline = selling.querySelector(".owner-pipeline-panel"); if (pipeline) sections.after(pipeline);
    const states = {draft: "PREPARING", inspection: "REVIEW", approved: "READY", listed: "LISTED", reserved: "RESERVED"};
    for (const [stage, filter] of Object.entries(states)) {
      const row = $(`owner-pipeline-${stage}`)?.closest(".owner-pipeline-row"); if (!row) continue;
      const action = button("View", () => window.DropRateCollection?.setFilters?.(filter === "RESERVED" ? {status: "RESERVED"} : {listing_state: filter}, {reset: true, navigate: true}), "hub-text-button");
      action.setAttribute("aria-label", `View ${row.querySelector("strong")?.textContent?.toLowerCase() || "listings"}`); row.append(action);
    }
    const sales = $("owner-view-sales"), orders = $("owner-dispatch-review");
    if (sales && orders) sales.prepend(orders);
  }

  // Read-only finance tables keep their detailed desktop comparison view.
  // Mobile cards are made from the same rendered values, never recalculated totals.
  const transactionLists = [];
  let transactionEpoch = 0;
  const currentAccount = () => typeof state === "undefined" ? null : state.session?.user?.id || null;
  function mobileTransactions(bodyId, config) {
    const body = $(bodyId), table = body?.closest("table"), wrap = table?.parentElement;
    if (!body || !table || !wrap) return;
    wrap.classList.add("hub-desktop-transactions");
    const cards = node("div", "hub-mobile-transactions"); cards.setAttribute("aria-label", config.label); wrap.after(cards);
    let queued = false, frame = null;
    transactionLists.push({clear() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null; queued = false; cards.replaceChildren(); body.replaceChildren();
    }});
    function render() {
      queued = false;
      const expanded = new Set([...cards.querySelectorAll("details[open]")].map(item => item.dataset.key));
      cards.replaceChildren();
      const headers = [...table.querySelectorAll("thead th")].map(cell => cell.textContent.trim());
      const rows = [...body.querySelectorAll("tr")];
      for (const row of rows) {
        const cells = [...row.cells];
        if (cells.length === 1 && cells[0].colSpan > 1) {cards.append(node("p", "hub-transaction-empty", cells[0].textContent)); continue;}
        const values = cells.map(cell => cell.textContent.trim());
        const item = node("article", "hub-transaction-card");
        const heading = node("div", "hub-transaction-heading");
        heading.append(node("h3", "", values[config.title] || "Transaction"), node("strong", "hub-transaction-amount", values[config.amount] || "—"));
        item.append(heading);
        const meta = node("div", "hub-transaction-meta");
        if (config.date != null) meta.append(node("span", "", values[config.date] || ""));
        if (config.status != null) meta.append(node("span", "hub-transaction-status", values[config.status] || ""));
        if (meta.childElementCount) item.append(meta);
        const detail = node("details", "hub-transaction-detail");
        detail.dataset.key = values.slice(0, 2).join("|"); detail.open = expanded.has(detail.dataset.key);
        detail.append(node("summary", "", "View breakdown"));
        const breakdown = node("dl");
        cells.forEach((cell, index) => {
          breakdown.append(node("dt", "", headers[index] || "Details"), node("dd", "", values[index] || "—"));
        });
        detail.append(breakdown); item.append(detail); cards.append(item);
      }
    }
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      const epoch = transactionEpoch, account = currentAccount();
      frame = requestAnimationFrame(() => {
        frame = null; queued = false;
        if (epoch !== transactionEpoch || !account || account !== currentAccount()) return;
        render();
      });
    }).observe(body, {childList: true, characterData: true, subtree: true});
    render();
  }
  if (seller) {
    mobileTransactions("owner-sales-body", {label: "Your sales", title: 1, date: 0, amount: 6, status: 7});
    mobileTransactions("owner-payouts-body", {label: "Your payouts", title: 0, amount: 1, status: 3, date: 4});
    mobileTransactions("owner-settlements-body", {label: "Your sale breakdowns", title: 0, date: 1, amount: 6, status: 7});
  }

  // Brief route transitions and image reveals. No operational amount is animated.
  const reveal = panel => {
    if (!panel || panel.classList.contains("hidden")) return;
    const pieces = [...panel.children].filter(item => !item.hidden && !item.classList.contains("hidden") && item.tagName !== "SCRIPT").slice(0, 5);
    pieces.forEach((item, index) => animate(item, [{opacity: .25, transform: "translateY(9px)"}, {opacity: 1, transform: "translateY(0)"}], 340, index * 28));
  };
  document.addEventListener(seller ? "owner-view-changed" : "seller-view-changed", event => {
    closeAccount();
    reveal($(seller ? `owner-view-${event.detail.view}` : `seller-view-${event.detail.view}`));
  });
  document.addEventListener("hub-ready", () => reveal(document.querySelector(seller ? ".owner-view:not(.hidden)" : "[data-seller-view]:not(.hidden)")));
  window.addEventListener("hub-session-cleared", () => {
    closeAdd(); closeAccount(); summary = null;
    if (attention) {attention.replaceChildren(); attention.hidden = true;}
    transactionEpoch++;
    transactionLists.forEach(list => list.clear());
    activeAnimations.forEach(animation => animation.cancel()); activeAnimations.clear();
  });
  // A restored session may finish its first overview before this deferred
  // presentation script loads. Reuse that account's response without refetching.
  if (seller && typeof state !== "undefined" && state.hubOverview?.userId === currentAccount() && currentAccount()) {
    document.dispatchEvent(new CustomEvent("hub:overview-updated", {detail: {summary: state.hubOverview.summary}}));
  }
})();
