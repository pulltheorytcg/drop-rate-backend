"use strict";

// Keep the existing forms and handlers: navigation never rebuilds unsaved work.
function installFounderWorkspace() {
  const dashboard = byId("dashboard-view");
  if (!dashboard || byId("workspace-search")) return;
  dashboard.classList.add("founder-workspace");

  const search = document.createElement("form");
  search.className = "workspace-search";
  search.setAttribute("role", "search");
  search.innerHTML = `<label class="sr-only" for="workspace-search">Find a card in inventory</label>
    <input id="workspace-search" type="search" placeholder="Find a card, set or stock code…" autocomplete="off">
    <button type="submit" aria-label="Search inventory">⌕</button>`;
  dashboard.querySelector(".topbar .brand-lockup").after(search);
  search.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(searchTimer);
    state.search = byId("workspace-search").value.trim();
    state.brand = state.status = state.saleIntent = state.storageLocationFilter = state.issue = "";
    state.offset = 0;
    byId("search-input").value = state.search;
    byId("brand-filter").value = byId("status-filter").value =
      byId("sale-intent-filter").value = "";
    if (state.readiness) renderReadiness(state.readiness);
    activateSellerView("inventory", true);
    loadInventory();
    byId("search-input").focus();
  });

  const actions = document.createElement("section");
  actions.className = "workspace-shortcuts";
  actions.setAttribute("aria-label", "Quick actions");
  [
    ["intake", "◎", "Scan a card", "Camera or photo", null],
    ["intake", "↥", "Import a CSV", "Add a whole collection", "import-inventory-button"],
    ["verification", "✓", "Review cards", "Check identities in bulk", null],
    ["media", "▧", "Photos & condition", "Prepare cards for sale", null],
  ].forEach(([view, icon, label, hint, control]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "workspace-shortcut";
    button.innerHTML = `<span class="shortcut-icon" aria-hidden="true">${icon}</span><span><strong>${label}</strong><small>${hint}</small></span><span aria-hidden="true">↗</span>`;
    button.addEventListener("click", () => {
      activateSellerView(view, true);
      if (control) byId(control)?.click();
    });
    actions.append(button);
  });
  sellerView("dashboard").querySelector(".founder-hero").after(actions);

  const filterBar = document.createElement("div");
  filterBar.className = "workspace-filter-bar";
  filterBar.innerHTML = `<span id="workspace-filter-summary" role="status">All inventory</span><button type="button" class="text-button" id="workspace-clear-filters">Clear filters</button>`;
  byId("search-input").closest(".toolbar").after(filterBar);
  byId("workspace-clear-filters").addEventListener("click", () => {
    clearTimeout(searchTimer);
    state.search = state.brand = state.status = state.saleIntent = state.storageLocationFilter = state.issue = "";
    state.offset = 0;
    ["search-input", "workspace-search", "brand-filter", "status-filter", "sale-intent-filter", "location-filter"]
      .forEach((id) => { byId(id).value = ""; });
    if (state.readiness) renderReadiness(state.readiness);
    loadInventory();
  });

  // Remember only the layout preference, never account or inventory data.
  try {
    const view = localStorage.getItem("drop-rate-inventory-layout");
    if (["visual", "table"].includes(view)) setInventoryView(view);
  } catch (_) { /* Storage may be disabled in a private browser. */ }
  ["visual", "table"].forEach((view) => byId(`inventory-view-${view}`).addEventListener("click", () => {
    try { localStorage.setItem("drop-rate-inventory-layout", view); } catch (_) { /* Optional preference. */ }
  }));

  // Group advanced settings without removing the original controls or listeners.
  const settings = sellerView("settings");
  Array.from(settings.querySelectorAll(":scope > .inventory-panel")).forEach((panel) => {
    const title = panel.querySelector("h2")?.textContent || "More settings";
    const marker = document.createComment("settings section");
    panel.before(marker);
    const drawer = utilityDrawer(title, "Settings", panel);
    marker.replaceWith(drawer);
  });

  document.addEventListener("seller-view-changed", (event) => {
    if (event.detail.view === "inventory") updateWorkspaceFilters();
  });
  updateWorkspaceFilters();
}

function updateWorkspaceFilters() {
  const summary = byId("workspace-filter-summary");
  if (!summary) return;
  const active = [state.search && `“${state.search}”`, state.brand,
    state.status && byId("status-filter").selectedOptions[0]?.textContent,
    state.saleIntent && byId("sale-intent-filter").selectedOptions[0]?.textContent,
    state.storageLocationFilter && byId("location-filter").selectedOptions[0]?.textContent,
    state.issue && (ISSUE_LABELS[state.issue] || state.issue)].filter(Boolean);
  summary.textContent = active.length ? `Showing: ${active.join(" · ")}` : "All inventory";
  byId("workspace-clear-filters").hidden = active.length === 0;
}

const loadInventoryBeforeWorkspace = loadInventory;
loadInventory = async function (...args) {
  updateWorkspaceFilters();
  return loadInventoryBeforeWorkspace(...args);
};

installFounderWorkspace();
