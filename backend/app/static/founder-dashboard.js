/* Founder tools live inside Settings; personal journeys use the Seller Hub itself. */
"use strict";
(() => {
  const panel = document.getElementById("owner-view-founders");
  const settings = document.getElementById("owner-view-settings");
  if (!panel || !settings || !window.DropRateWorkspace) return;
  const {icon} = window.DropRateWorkspace;
  const node = (tag, cls, text) => {
    const el = document.createElement(tag); el.className = cls;
    if (text) el.textContent = text;
    return el;
  };
  const entry = node("button", "founder-settings-entry");
  entry.type = "button"; entry.hidden = true;
  entry.setAttribute("aria-controls", "owner-view-founders");
  const entryCopy = node("span", "founder-entry-copy");
  entryCopy.append(node("small", "founder-kicker", "FOUNDERS ONLY"), node("strong", "", "Founders dashboard"),
    node("span", "", "Manage stock, sellers, finance and business settings."));
  entry.append(icon("accounts"), entryCopy, icon("arrow"));
  entry.addEventListener("click", () => activateOwnerView("founders"));
  const backToTools = settings.querySelector(".workspace-back");
  if (backToTools) backToTools.after(entry); else settings.prepend(entry);

  const back = node("button", "workspace-back", "Settings"); back.type = "button";
  back.prepend(icon("back")); back.addEventListener("click", () => {activateOwnerView("settings"); entry.focus();});
  panel.prepend(back);
  const heading = panel.querySelector(".business-heading");
  heading.querySelector("h1").replaceChildren("Founders ", node("em", "", "dashboard."));
  heading.querySelector("p:last-child").textContent = "Everything you need to run Drop Rate. One shared workspace.";
  panel.setAttribute("aria-label", "Founders dashboard");

  const groups = [
    ["Stock & reviews", [
      ["inventory", "Stock management", "Edit costs, condition, location and purchase lots.", "collection"],
      ["verification", "Identity reviews", "Check exact matches and resolve card identities.", "verification"],
      ["media", "Photos & condition", "Review physical copies and prepare listing photos.", "media"],
      ["dashboard", "Action required", "Work through missing information and outstanding reviews.", "reports"],
    ]],
    ["Finance & operations", [
      ["reports", "Reports & settlements", "Review revenue, costs, fees and sale allocations.", "reports"],
      ["balance", "Payout management", "Review balances, requests and payout history.", "balance"],
      ["sales", "Sales performance", "Inspect sales and proceeds by date.", "sales"],
      ["settings", "Business settings", "Manage Shopify, eBay, seller invitations and pricing.", "settings"],
    ]],
  ];
  const tools = node("section", "founder-control-groups");
  tools.setAttribute("aria-label", "Founder controls");
  for (const [title, items] of groups) {
    const group = node("section", "founder-control-group");
    group.append(node("h2", "", title));
    const grid = node("div", "founder-control-grid");
    for (const [view, label, description, symbol] of items) {
      const link = node("a", "founder-control-card"); link.href = `/founders#${view}`;
      const mark = node("span", "founder-control-icon"); mark.append(icon(symbol));
      const copy = node("span", "founder-control-copy");
      copy.append(node("strong", "", label), node("small", "", description));
      link.append(mark, copy, icon("arrow")); grid.append(link);
    }
    group.append(grid); tools.append(group);
  }
  document.getElementById("business-content").append(tools);
  document.addEventListener("hub:access-verified", event => {
    entry.hidden = event.detail.access.business_allowed !== true;
  });
  document.addEventListener("hub:founder-access", event => {
    entry.hidden = !event.detail.allowed;
    if (!event.detail.allowed && !panel.classList.contains("hidden")) activateOwnerView("settings", false);
  });
  window.addEventListener("hub-session-cleared", () => {entry.hidden = true; panel.classList.add("hidden");});
})();
