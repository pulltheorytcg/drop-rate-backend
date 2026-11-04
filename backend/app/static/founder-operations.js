/* Existing privileged forms, reached from Settings > Founders dashboard. */
"use strict";
(() => {
  if (location.pathname !== "/founders") return;
  document.body.classList.add("founder-operations");
  const {icon} = window.DropRateWorkspace;
  const back = document.createElement("a");
  back.className = "workspace-back founder-dashboard-back";
  back.href = "/owner#founders"; back.append(icon("back"), "Founders dashboard");
  document.querySelector(".dashboard-content").prepend(back);
  const nav = document.getElementById("seller-nav");
  const menu = document.createElement("nav");
  menu.className = "founder-shared-nav"; menu.setAttribute("aria-label", "Seller Hub navigation");
  for (const [key, label, symbol] of [["overview", "Home", "home"], ["inventory", "Collection", "collection"],
    ["scan", "Scan", "scan"], ["search", "Search", "search"], ["selling", "Selling", "selling"]]) {
    const link = document.createElement("a"); link.className = "owner-nav-item";
    link.href = key === "overview" ? "/owner" : `/owner#${key}`;
    const text = document.createElement("span"); text.textContent = label;
    link.append(icon(symbol), text); menu.append(link);
  }
  nav.before(menu); nav.hidden = true;
  document.querySelector(".workspace-inventory-search")?.remove();
  document.querySelector(".business-entry")?.remove();
  document.querySelector(".workspace-brand-caption").textContent = "Seller Hub";
  document.querySelectorAll(".workspace-back:not(.founder-dashboard-back)").forEach(button => {
    const link = back.cloneNode(true); link.classList.remove("founder-dashboard-back"); button.replaceWith(link);
  });
  // Account shortcuts always return to the common account/settings pages.
  document.getElementById("hub-account-menu")?.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || button.id === "logout-button") return;
    const label = button.textContent.trim();
    const target = {"Appearance & settings": "settings", "Business": "founders", "All workspace tools": "more", "Your account": "profile"}[label];
    if (target) {event.stopImmediatePropagation(); event.preventDefault(); location.assign(`/owner#${target}`);}
  }, true);
  if (!location.hash || ["accounts", "more", "search", "intake"].includes(location.hash.slice(1))) {
    location.replace("/owner#founders");
  }
})();
