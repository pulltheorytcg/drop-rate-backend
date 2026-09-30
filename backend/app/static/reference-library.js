"use strict";
(() => {
  const host = document.getElementById("owner-view-scan") || document.getElementById("recognition-scanner-panel");
  if (!host) return;
  const panel = document.createElement("details");
  panel.className = "utility-drawer reference-library";
  panel.innerHTML = `
    <summary><strong>Card & set library</strong><span>Browse beyond your inventory</span></summary>
    <div class="reference-library-body">
      <p>Reference records help identify cards you have never scanned. Coverage is separate from exact-printing accuracy.</p>
      <p id="library-coverage" role="status">Open to load catalogue coverage.</p>
      <form id="library-search-form" class="reference-library-controls">
        <label>Game<select id="library-game"></select></label>
        <label>Browse<select id="library-kind"><option value="sets">Sets</option><option value="cards">Cards</option></select></label>
        <label>Search<input id="library-search" maxlength="160" placeholder="Name, set or printed number"></label>
        <button type="submit">Search library</button>
      </form>
      <p id="library-scope"></p><div id="library-results" aria-live="polite"></div>
      <div class="reference-library-controls"><button id="library-prev" type="button" disabled>Previous</button><button id="library-next" type="button" disabled>Next</button></div>

    </div>`;
  host.append(panel);
  const el = id => document.getElementById(id);
  let coverage = [], offset = 0, selectedSet = null, revision = 0, initialized = false;
  async function browse(reset = false) {
    if (reset) offset = 0;
    const current = ++revision;
    const game = coverage.find(g => g.system_code === el("library-game").value);
    if (!game) return;
    const sources = game.sources || [];
    const count = sources.reduce((n,s) => n + Number(s.cards || 0),0);
    const sets = sources.reduce((n,s) => n + Number(s.sets || 0),0);
    el("library-coverage").textContent = `${game.game}: ${count.toLocaleString()} reference records · ${sets.toLocaleString()} set/language records. ${game.coverage_note}`;
    if (game.latest_sync && game.latest_sync.status !== "COMPLETE") {
      el("library-coverage").textContent += " Latest import is incomplete; some source checklists remain unavailable.";
    }
    if (game.status === "DEFERRED") el("library-coverage").textContent += " Planned for a later expansion.";
    el("library-scope").textContent = selectedSet ? `Set: ${selectedSet.name} · ${selectedSet.language}` : "All indexed sets and cards for this game";
    el("library-results").textContent = "Loading…";
    const kind = el("library-kind").value;
    const params = new URLSearchParams({system_code:game.system_code,search:el("library-search").value.trim(),offset:String(offset),limit:"30"});
    if (selectedSet && kind === "cards") {
      params.set("set_id",selectedSet.set_id); params.set("provider",selectedSet.provider); params.set("language",selectedSet.language);
    }
    try {
      const data = await apiRequest(`/api/v1/reference-library/${kind}?${params}`);
      if (current !== revision) return;
      el("library-results").replaceChildren();
      for (const item of data.items || []) {
        const row = document.createElement("div"); row.className = "reference-library-row";
        const title = document.createElement("strong"); title.textContent = item.name;
        const detail = document.createElement("span");
        detail.textContent = kind === "sets"
          ? `${item.language} · ${item.indexed_cards} records · ${item.release_status === "UPCOMING" ? "Upcoming" : item.release_status === "RELEASED" ? "Released" : "Release date unverified"} · ${item.provider}`
          : [item.card_number,item.rarity,item.finish || "Finish requires review",item.language,item.provider].filter(Boolean).join(" · ");
        row.append(title,detail);
        if (kind === "sets") {
          const button = document.createElement("button"); button.type = "button"; button.textContent = "Browse cards";
          button.addEventListener("click",() => { selectedSet=item; el("library-kind").value="cards"; el("library-search").value=""; browse(true); });
          row.append(button);
        }
        el("library-results").append(row);
      }
      if (!(data.items || []).length) el("library-results").textContent = "No indexed results. This is a coverage gap, not proof that the card or set does not exist.";
      el("library-prev").disabled = offset === 0;
      el("library-next").disabled = !data.has_more;
    } catch (error) { if (current === revision) el("library-results").textContent=error.message; }
  }
  panel.addEventListener("toggle",async () => {
    if (!panel.open || initialized || !state.session?.access_token) return;
    initialized=true;
    try {
      const data=await apiRequest("/api/v1/reference-library/coverage"); coverage=data.games || [];
      for (const game of coverage) {
        const option=document.createElement("option"); option.value=game.system_code; option.textContent=game.game; el("library-game").append(option);
      }
      await browse(true);
    } catch(error) { initialized=false; el("library-coverage").textContent=error.message; }
  });
  el("library-search-form").addEventListener("submit",event => {event.preventDefault();browse(true);});
  for (const id of ["library-game","library-kind"]) el(id).addEventListener("change",() => {selectedSet=null;browse(true);});
  el("library-prev").addEventListener("click",() => {offset=Math.max(0,offset-30);browse();});
  el("library-next").addEventListener("click",() => {offset+=30;browse();});
})();
