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

  // Real source review is five exact published printings at a time, 25/game.
  // Never automatically publishes, approves, downloads to R2 or changes prices.
  const artworkPanel = node("section", "founder-control-group");
  artworkPanel.setAttribute("aria-label", "Three-game artwork source review");
  artworkPanel.append(node("h2", "", "Official artwork review"),
    node("p", "muted", "Inspect real Yu-Gi-Oh!, Lorcana and Magic images against the exact card printing. Review only; not published."));
  const artControls = node("div", "founder-coverage-actions");
  const artGame = document.createElement("select");
  artGame.setAttribute("aria-label", "Artwork game");
  artGame.className = "owner-select";
  for(const [value,label] of [["YUGIOH","Yu-Gi-Oh!"],["DISNEY_LORCANA","Disney Lorcana"],
                              ["MAGIC_THE_GATHERING","Magic: The Gathering"]]){
    const option=document.createElement("option");option.value=value;option.textContent=label;artGame.add(option);
  }
  const artRun = node("button", "ghost-button", "Review 5 printings");
  const artNext = node("button", "ghost-button", "Next 5");
  artRun.type=artNext.type="button";
  const artStatus=node("p","muted","Select a game to check its first five printings.");
  artStatus.setAttribute("role","status");
  const artResults=node("div","founder-artwork-review-list");
  artControls.append(artGame,artRun,artNext);
  artworkPanel.append(artControls,artStatus,artResults);
  tools.append(artworkPanel);
  let artOffset=0,artEpoch=0,artBusy=false;
  async function reviewArtwork(offset=0){
    if(entry.hidden||artBusy)return;
    artBusy=true;artRun.disabled=artNext.disabled=true;
    const generation=++artEpoch,source=artGame.value;
    artStatus.textContent="Checking actual source images and file integrity…";
    try{
      const url="/api/v1/artwork/pilot/"+encodeURIComponent(source)+"?limit=5&offset="+offset+"&verify_bytes=true";
      const data=await apiRequest(url);
      if(generation!==artEpoch||entry.hidden||artGame.value!==source)return;
      const frag=document.createDocumentFragment();
      for(const rec of data.records||[]){
        const item=node("div","founder-artwork-review-card");
        const title=node("strong","",(rec.set_id||"Unknown set")+" · "+(rec.card_number||"Unknown number"));
        const detail=node("p","muted",(rec.status||"UNAVAILABLE").replace(/_/g," "));
        const approved=node("p","muted",rec.image_byte_verified
          ? "Image bytes verified · "+rec.image_dimensions.width+" × "+rec.image_dimensions.height+" · "+rec.image_size_bytes.toLocaleString("en-GB")+" bytes"
          : "Image bytes not verified or source image unavailable");
        item.append(title,detail,approved);
        if(typeof rec.candidate_image_url==="string"&&/^https:\/\//.test(rec.candidate_image_url)){
          const link=node("a","founder-control-card","Inspect source image");
          link.href=rec.candidate_image_url;link.target="_blank";link.rel="noopener noreferrer";
          item.append(link);
        }
        item.append(node("small","muted","Not approved for storefront publishing."));
        frag.append(item);
      }
      artResults.replaceChildren(frag);
      artOffset=offset;
      artStatus.textContent=data.game+": checked "+data.requested+" printings; found "+data.candidate_count+" candidates and verified "+data.byte_verified_count+" images. Batch "+(Math.floor(offset/5)+1)+" of 5.";
      artNext.disabled=offset>=20;
    }catch(error){
      if(generation===artEpoch&&!entry.hidden)
        artStatus.textContent="Artwork preview unavailable: "+error.message;
    }finally{
      if(generation===artEpoch){artBusy=false;artRun.disabled=false;if(artOffset<20)artNext.disabled=false;}
    }
  }
  artRun.addEventListener("click",()=>{artOffset=0;reviewArtwork(0);});
  artNext.addEventListener("click",()=>reviewArtwork(Math.min(20,artOffset+5)));
  artGame.addEventListener("change",()=>{artEpoch++;artOffset=0;artResults.replaceChildren();
    artStatus.textContent="Select Review 5 printings to inspect the exact image sources.";artNext.disabled=false;artBusy=false;artRun.disabled=false;});
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
  window.addEventListener("hub-session-cleared", () => {entry.hidden = true; clearCoverage(); artEpoch++; artOffset=0; artResults.replaceChildren(); artStatus.textContent="Sign in to review artwork."; panel.classList.add("hidden");});
})();

