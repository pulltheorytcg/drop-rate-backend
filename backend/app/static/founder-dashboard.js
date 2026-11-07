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
  const coveragePanel = node("section", "founder-control-group");
  coveragePanel.setAttribute("aria-label", "Catalogue and pricing coverage");
  coveragePanel.append(node("h2", "", "Catalogue & pricing"));
  const coverageStatus = node("p", "muted", "Check catalogue imports, price evidence and missing artwork.");
  coverageStatus.setAttribute("role", "status");
  const coverageDetails = node("div", "founder-coverage-details");
  const coverageButton = node("button", "ghost-button", "Check coverage");
  coverageButton.type = "button";
  coveragePanel.append(coverageStatus, coverageDetails, coverageButton);
  tools.append(coveragePanel);
  let coverageEpoch = 0, coverageLoaded = false, coveragePending = false;
  const count = value => Number.isInteger(value) ? value.toLocaleString("en-GB") : "Not measured";
  async function loadCoverage() {
    if (entry.hidden || coveragePending) return;
    const epoch = coverageEpoch;
    coveragePending = true; coverageButton.disabled = true;
    coverageStatus.textContent = "Checking catalogue and price evidence…";
    try {
      const data = await apiRequest("/api/v1/catalogue-browser/coverage");
      if (epoch !== coverageEpoch || entry.hidden) return;
      const catalogue = data.catalogue, prices = data.summary?.physical_cards;
      if (!catalogue || !prices || !data.automatic_price_refresh) throw new Error("Coverage report is incomplete.");
      const details = document.createDocumentFragment();
      details.append(node("p", "", `${count(catalogue.stored_physical_tcg_references)} stored TCG printing/finish references. These are catalogue entries, including future releases, not owned stock.`));
      const sources = node("ul", "");
      for (const source of catalogue.published_sources || []) {
        if (source.category !== "TCG") continue;
        sources.append(node("li", "", `${source.game}: ${count(source.stored_references)} references · product details imported; pricing and artwork feeds pending.`));
      }
      for (const source of catalogue.unpublished_tcg_games || []) sources.append(node("li", "", `${source.game}: catalogue not yet imported.`));
      details.append(sources);
      details.append(node("p", "", `Original card catalogue: ${count(prices.priced)} of ${count(prices.total)} have current source price references. This includes market guides; it does not measure exact market-value coverage across all games.`));
      const artwork = catalogue.sql_physical_artwork;
      details.append(node("p", "", `Original card artwork: ${count(artwork?.with_url)} image links; ${count(artwork?.missing_url)} missing. Link counts do not verify that images load. Slabs require the physical item's slab photo.`));
      const refresh = data.automatic_price_refresh;
      const message = refresh.status === "PAUSED"
        ? "Automatic bulk price refresh is paused by the database capacity safeguard. Existing evidence can expire while refresh is paused."
        : "Database capacity permits automatic refresh. Provider availability and successful refreshes still need verification.";
      details.append(node("p", "", message));
      coverageDetails.replaceChildren(details);
      coverageStatus.textContent = `Checked ${new Date(data.observed_at).toLocaleString("en-GB")}.`;
      coverageLoaded = true;
    } catch (error) {
      if (epoch === coverageEpoch && !entry.hidden) coverageStatus.textContent = `Could not check coverage: ${error.message}`;
    } finally {
      if (epoch === coverageEpoch) {coveragePending = false; coverageButton.disabled = false;}
    }
  }
  function clearCoverage() {
    coverageEpoch += 1; coverageLoaded = false; coveragePending = false;
    coverageButton.disabled = false; coverageDetails.replaceChildren();
    coverageStatus.textContent = "Check catalogue imports, price evidence and missing artwork.";
  }
  coverageButton.addEventListener("click", loadCoverage);
  document.addEventListener("owner-view-changed", event => {
    if (event.detail.view === "founders" && !coverageLoaded) loadCoverage();
  });
  document.addEventListener("hub:access-verified", event => {
    entry.hidden = event.detail.access.business_allowed !== true;
    if (entry.hidden) clearCoverage();
  });
  document.addEventListener("hub:founder-access", event => {
    entry.hidden = !event.detail.allowed;
    if (entry.hidden) clearCoverage();
    if (!event.detail.allowed && !panel.classList.contains("hidden")) activateOwnerView("settings", false);
  });
  window.addEventListener("hub-session-cleared", () => {entry.hidden = true; clearCoverage(); panel.classList.add("hidden");});
})();

