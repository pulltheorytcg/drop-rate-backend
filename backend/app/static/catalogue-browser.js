"use strict";

window.DropRateCatalogue = (() => {
  const node = (tag, cls = "", text) => { const el = document.createElement(tag); el.className = cls; if (text != null) el.textContent = text; return el; };
  const button = (text, action, cls = "") => { const el = node("button", cls, text); el.type = "button"; el.addEventListener("click", action); return el; };
  const money = value => value == null ? "Value pending" : new Intl.NumberFormat("en-GB", {style:"currency", currency:"GBP"}).format(value / 100);
  const marketPrice = row => row.market_value_minor==null?(row.market_refresh_failed?"Price temporarily unavailable":row.market_refresh_needed?"Checking price…":"Price unavailable"):(row.market_value_source==="CARDMARKET_ESTIMATE"?"Estimate: ":["TCGDEX_CARDMARKET","TCGDEX_CARDMARKET_VARIANT","CARDMARKET_CATALOGUE","CARDMARKET_BULK","CARDMARKET_BULK_SINGLES"].includes(row.market_value_source)?"Reference: ":"")+money(row.market_value_minor)+(row.market_value_high_minor>row.market_value_minor?"–"+money(row.market_value_high_minor):"");
  const conditions = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
  const decode = value => { const el = document.createElement("textarea"); el.innerHTML = String(value || ""); return el.value; };
  const sorts = {newest:"Newest first", name:"Name A–Z", number:"Card number", value_desc:"Value: high to low", value_asc:"Value: low to high"};
  const gameTitles = {POKEMON_TCG:["Pokémon","TRADING CARD GAME"], ONE_PIECE_CARD_GAME:["ONE PIECE","CARD GAME"],
    DRAGON_BALL_SUPER_MASTERS:["DRAGON BALL","SUPER · MASTERS"], DRAGON_BALL_SUPER_FUSION_WORLD:["DRAGON BALL","FUSION WORLD"],
    NARUTO:["NARUTO","TRADING CARD GAME"],
    RIFTBOUND:["RIFTBOUND","LEAGUE OF LEGENDS"], YUGIOH:["Yu-Gi-Oh!","TRADING CARD GAME"], DISNEY_LORCANA:["LORCANA","TRADING CARD GAME"]};

  class Browser {
    constructor(options) {
      this.options = options; this.client = options.client;
      this.artworkQueue=[];this.artworkActive=0;this.artworkEpoch=0;this.artworkControllers=new Set();this.artworkUrls=new Map();
      this.artworkCache=new Map();this.artworkBytes=0;this.pageCache=new Map();this.artworkWaiting=new Map();
      this.revision = 0; this.pending = new Map(); this.watchlist = new Set(); this.games = Object.entries(gameTitles).slice(0,5).map(([system_code,[game]]) => ({system_code,game,languages:[]})); this.gamesLoaded = false;
      this.defaults();
      this.storageKey = "drop-rate-watchlist:" + this.client.owner;
      try {
        const saved = JSON.parse(localStorage.getItem(this.storageKey) || "[]");
        if (Array.isArray(saved)) this.watchlist = new Set(saved.filter(x => typeof x === "string" && /^[crs]:[a-f0-9-]+$/.test(x)).slice(0,100));
      } catch (_) { /* Private browsing may disable storage. */ }
      this.build();
    }
    active() { return !this.destroyed && this.client.active(); }
    defaults() { this.filters = {q:"",system_code:"",language:"",product_type:"",owned:"all",sort:"newest",watch:false}; this.set = null; this.page = "products"; this.setQuery = ""; this.rows = []; this.offset = 0; }
    find(selector) { return this.dialog.querySelector(selector); }
    build() {
      this.embedded = Boolean(this.options.host);
      this.dialog = node(this.embedded ? "section" : "dialog", "dr-browser" + (this.embedded ? " dr-browser-embedded" : "")); this.dialog.setAttribute("aria-label", "Search Drop Rate products");
      this.dialog.innerHTML = `<header class="dr-browse-header"><div class="dr-browse-set-heading" hidden><button type="button" data-action="back" aria-label="Back to products">←</button><h2></h2></div>
        <div class="dr-browse-searchbar"><button type="button" data-action="camera" aria-label="Open scanner">◎</button><input type="search" maxlength="160" placeholder="Search for products" aria-label="Search for products"><button type="button" data-action="clear-query" aria-label="Clear search">×</button><button type="button" data-action="watch" aria-label="Watchlist">☆</button><button type="button" data-action="menu" aria-label="Sort and filter">☷</button></div>
        <div class="dr-browse-menu" hidden><button type="button" data-action="sort">Sort ↕</button><button type="button" data-action="filters">Filter ☷</button></div>
        <div class="dr-browse-context"><span>Browse: <strong>All products</strong></span><button type="button" data-action="sets">Show Sets</button></div>
        <nav class="dr-browse-types" aria-label="Product type"><button type="button" data-type="">All products</button><button type="button" data-type="CARD">Cards</button><button type="button" data-type="SEALED">Sealed products</button></nav>
        <div class="dr-browse-chips"></div><nav class="dr-browse-languages" aria-label="Set language" hidden></nav><button type="button" class="dr-browse-pending" hidden></button></header>
        <div class="dr-browse-scroll"><p class="dr-browse-status" role="status"></p><div class="dr-browse-content"></div><button type="button" data-action="more" class="dr-browse-load" hidden>Load more</button><div class="dr-browse-sentinel"></div></div>
        <nav class="dr-browse-nav" aria-label="App navigation"><button type="button" data-action="home"><span>⌂</span>Home</button><button type="button" class="active" data-action="search"><span>⌕</span>Search</button><button type="button" data-action="camera"><span>◎</span>Scan</button><button type="button" data-action="inventory"><span>▣</span>Inventory</button><button type="button" data-action="tools"><span>•••</span>More</button></nav>
        <div class="dr-browse-backdrop" hidden><section class="dr-browse-sheet" role="dialog" aria-modal="true"></section></div>`;
      (this.options.host || document.body).append(this.dialog);
      this.input = this.find("input[type=search]"); this.scroll = this.find(".dr-browse-scroll"); this.sheet = this.find(".dr-browse-sheet");
      const actions = {back:()=>this.back(), camera:()=>this.scan(), home:()=>this.navigate("home"), inventory:()=>this.navigate("inventory"), tools:()=>this.navigate("more"),
        search:()=>this.reset(), "clear-query":()=>{ if(this.page === "sets") this.setQuery=""; else this.filters.q=""; this.input.value=""; this.load(); },
        sets:()=>this.showSets(), more:()=>this.load(true), filters:()=>this.openFilters(), sort:()=>this.openSort(),
        menu:()=>{ this.find(".dr-browse-menu").hidden = !this.find(".dr-browse-menu").hidden; }, watch:()=>{ this.filters.watch=!this.filters.watch; this.page="products"; this.load(); }};
      this.dialog.querySelectorAll("[data-action]").forEach(control=>control.addEventListener("click",()=>actions[control.dataset.action]()));
      this.dialog.querySelectorAll('[data-type]').forEach(control=>control.addEventListener('click',()=>{
        this.filters.product_type=control.dataset.type;this.set=null;this.page='products';this.load();
      }));
      this.input.addEventListener("input",()=>{
        clearTimeout(this.timer); this.revision += 1; this.controller?.abort(); this.loading=false;
        if (this.page === "sets") this.setQuery=this.input.value; else this.filters.q=this.input.value;
        this.find(".dr-browse-status").textContent="Searching…";
        this.timer=setTimeout(()=>this.load(),260);
      });
      this.dialog.addEventListener("cancel",event=>{event.preventDefault();if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet();else this.close();});
      this.dialog.addEventListener("keydown",event=>{
        if(event.key==="Escape"&&!this.find(".dr-browse-backdrop").hidden){event.preventDefault();this.closeSheet();return;}
        if(event.key!=="Tab" || this.find(".dr-browse-backdrop").hidden)return;
        const controls=[...this.sheet.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];
        const first=controls[0],last=controls.at(-1);
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
      });
      if("IntersectionObserver" in window){ this.observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&this.hasMore&&!this.loading)this.load(true);},{root:this.scroll,rootMargin:"160px"}); this.observer.observe(this.find(".dr-browse-sentinel")); }
      if('IntersectionObserver' in window)this.artworkObserver=new IntersectionObserver(entries=>{
        for(const entry of entries){if(!entry.isIntersecting)continue;
          const job=this.artworkWaiting.get(entry.target);this.artworkWaiting.delete(entry.target);this.artworkObserver.unobserve(entry.target);
          if(job)this.artworkQueue.push(job);
        }this.drainArtwork();
      },{root:this.scroll,rootMargin:'640px'});
    }
    async open(productKey = "") {
      if(!this.active())throw new Error("Sign in again to search products.");
      this.returnFocus=document.activeElement;
      if(this.embedded) this.dialog.hidden=false;
      else {this.dialog.showModal();document.body.classList.add("dr-browser-open");}
      // Show known game artwork immediately, before any network round trip.
      if(this.isHome()){this.header();this.renderGames();}
      else {this.header();if(!this.rows.length)this.skeleton();}
      if(productKey){await this.openReference(productKey);return;}
      const revision=this.revision;
      const home=this.isHome();
      if(!this.gamesLoaded) {
        if(!this.gamesRequest) this.gamesRequest=this.client.request("/api/v1/catalogue-browser/games").then(data=>{
          if(!this.active())return;
          const order=Object.keys(gameTitles),rank=game=>order.includes(game.system_code)?order.indexOf(game.system_code):order.length;
          this.games=(data.items||[]).sort((a,b)=>rank(a)-rank(b)||a.game.localeCompare(b.game));
          this.gamesLoaded=true;
        }).finally(()=>{this.gamesRequest=null;});
        // A known game/search can load independently of the game directory.
        // Metadata failure must not block a working product endpoint.
        if(!home){
          this.gamesRequest.then(()=>{if(this.active()&&!this.dialog.hidden)this.header();}).catch(()=>{});
          await this.load();return;
        }
        try {await this.gamesRequest;}
        catch(error){if(this.active()&&revision===this.revision&&this.isHome())this.find(".dr-browse-status").textContent="Catalogue details couldn’t refresh. Choose a game to browse, or reopen Search to retry.";return;}
      }
      if(!this.active() || revision!==this.revision)return;
      await this.load();
    }
    async openReference(key) {
      const revision=++this.revision;this.controller?.abort();this.controller=new AbortController();
      clearTimeout(this.timer);this.hasMore=false;this.loading=true;this.find('[data-action="more"]').hidden=true;
      const status=this.find('.dr-browse-status');status.textContent='Opening card…';
      try {
        const data=await this.client.request('/api/v1/catalogue-browser/products?'+new URLSearchParams({keys:key,limit:'1'}),{signal:this.controller.signal});
        if(!this.active()||revision!==this.revision)return;
        const row=(data.items||[]).find(item=>item.key===key);
        status.textContent=row?'':'This printing is currently unavailable. Search the catalogue to explore more cards.';
        if(row){this.openProduct(row);this.refreshPrices([row],revision);}
      } catch(error) {if(this.active()&&revision===this.revision)status.textContent=error.message;}
      finally {if(revision===this.revision)this.loading=false;}
    }
    close() {
      if(this.saving)return;
      if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet(false);
      this.restoreOuter();this.revision+=1;this.controller?.abort();clearTimeout(this.timer);this.loading=false;
      this.clearArtwork();
      if(this.embedded)this.dialog.hidden=true;else this.dialog.close();
      document.body.classList.remove("dr-browser-open");if(!this.embedded)this.returnFocus?.focus();
    }
    restoreOuter() { (this.outerInert||[]).forEach(([el,was])=>{el.inert=was;});this.outerInert=null; }
    destroy() { this.restoreOuter();this.destroyed=true;this.clearArtwork();this.artworkCache.clear();this.artworkBytes=0;this.pageCache.clear();this.revision+=1;this.controller?.abort();clearTimeout(this.timer);this.observer?.disconnect();this.pending.clear();this.dialog.remove();document.body.classList.remove("dr-browser-open"); }
    navigate(view) { if(this.saving)return;this.close();this.options.navigate(view); }
    scan(mode="RAW") { if(this.saving)return;this.close();this.options.scan(typeof mode === "string" ? mode : "RAW"); }
    reset() { if(this.saving)return;this.defaults();this.input.value="";this.load(); }
    game() { return this.games.find(game=>game.system_code===this.filters.system_code); }
    isHome() { const f=this.filters;return this.page!=="sets" && !f.q.trim()&&!f.system_code&&!f.language&&!f.product_type&&f.owned==="all"&&!f.watch; }
    pickGame(game) { this.filters.system_code=game.system_code;this.filters.language="";this.set=null;this.page="products";this.load(); }
    showSets() { if(!this.filters.system_code)return;this.page="sets";this.setQuery="";this.set=null;
      this.filters.q="";this.filters.owned="all";this.filters.watch=false;this.filters.product_type="";
      const langs=this.game()?.languages||[];if(!this.filters.language)this.filters.language=langs.includes("English")?"English":langs[0]||"";this.load(); }
    back() { if(this.page==="sets"){this.page="products";this.setQuery="";this.load();}
      else if(this.set){this.set=null;this.showSets();}else this.reset(); }
    header() {
      const sets=this.page==="sets",home=this.isHome();
      this.find(".dr-browse-set-heading").hidden=!sets;
      this.find(".dr-browse-set-heading h2").textContent=(this.game()?.game||"Product")+" Sets";
      this.input.value=sets?this.setQuery:this.filters.q; this.input.placeholder=sets?"Search by sets":"Search for products";
      this.input.setAttribute("aria-label",this.input.placeholder);
      this.find(".dr-browse-context").hidden=sets||home;
      this.find('.dr-browse-types').hidden=sets;
      this.dialog.querySelectorAll('[data-type]').forEach(control=>control.setAttribute('aria-pressed',String(control.dataset.type===this.filters.product_type)));
      this.find(".dr-browse-context strong").textContent=this.filters.watch?"Watchlist":this.filters.owned==="owned"?"Products owned":this.filters.owned==="not_owned"?"Products not owned":"All products";
      this.find('[data-action="sets"]').hidden=!this.filters.system_code;
      this.find('[data-action="watch"]').textContent=this.filters.watch?"★":"☆";
      this.find('[data-action="watch"]').setAttribute("aria-pressed",String(this.filters.watch));
      this.find(".dr-browse-menu").hidden=true;
      const chips=this.find(".dr-browse-chips");chips.replaceChildren();chips.hidden=sets;
      const chip=(label,action)=>chips.append(button(label+" ×",()=>{action();this.load();},"dr-browse-chip"));
      if(this.filters.system_code)chip(this.game()?.game||this.filters.system_code,()=>{this.filters.system_code="";this.filters.language="";this.set=null;});
      if(this.set)chip(decode(this.set.set_name),()=>{this.set=null;});
      if(this.filters.language)chip(this.filters.language,()=>{this.filters.language="";this.set=null;});
      if(this.filters.product_type)chip(this.filters.product_type==="SEALED"?"Sealed Only":"Cards Only",()=>{this.filters.product_type="";});
      if(this.filters.owned!=="all")chip(this.filters.owned==="owned"?"Products Owned":"Products Not Owned",()=>{this.filters.owned="all";});
      if(this.filters.watch)chip("Watchlist",()=>{this.filters.watch=false;});
      if(chips.childElementCount)chips.append(button("Clear filters",()=>this.reset(),"dr-browse-clear"));
      const languages=this.find(".dr-browse-languages");languages.hidden=!sets;languages.replaceChildren();
      if(sets)(this.game()?.languages||[]).forEach(language=>{const tab=button(language,()=>{this.filters.language=language;this.set=null;this.load();});tab.setAttribute("aria-pressed",String(this.filters.language===language));languages.append(tab);});
      const pending=[...this.pending.values()].filter(entry=>entry.requests?.some(req=>!req.result));
      const banner=this.find(".dr-browse-pending");banner.hidden=!pending.length;banner.textContent=pending.length+" addition(s) need a retry →";
      banner.onclick=()=>this.openProduct(pending[0].row);
    }
    skeleton() { const grid=node("div","dr-browse-grid");for(let i=0;i<6;i++){const card=node("div","dr-browse-skeleton");card.append(node("span"),node("i"),node("i"));grid.append(card);}this.find(".dr-browse-content").replaceChildren(grid); }
    async load(more=false) {
      if(!this.active() || (more&&this.loading))return;
      clearTimeout(this.timer);const revision=++this.revision;this.controller?.abort();this.controller=new AbortController();this.loading=true;
      if(!more){this.clearArtwork();this.rows=[];this.offset=0;this.hasMore=false;this.scroll.scrollTop=0;}
      this.header();
      const status=this.find(".dr-browse-status");status.textContent="";
      if(this.isHome()){this.loading=false;this.renderGames();this.find('[data-action="more"]').hidden=true;return;}
      if(!more)this.skeleton();
      const nextOffset=more?this.rows.length:0;
      const params=new URLSearchParams({limit:"40",offset:String(nextOffset)});
      if(this.page==="sets") {
        params.set("system_code",this.filters.system_code);params.set("language",this.filters.language);params.set("q",this.setQuery.trim());
      } else {
        for(const key of ["q","system_code","language","product_type","owned","sort"])if(this.filters[key])params.set(key,this.filters[key]);
        if(this.set){params.set("system_code",this.set.system_code);params.set("set_id",this.set.set_id);params.set("provider",this.set.provider);}
        if(this.filters.watch)params.set("keys",[...this.watchlist].join(","));
      }
      try {
        const path="/api/v1/catalogue-browser/"+(this.page==="sets"?"sets":"products")+"?"+params;
        const cached=this.pageCache.get(path);
        let renderedCache=false;
        if(!more && cached && Date.now()-cached.at<60000){
          this.rows=cached.data.items||[];this.hasMore=Boolean(cached.data.has_more);this.renderRows();
          renderedCache=true;
        }
        const data=await this.client.request(path,{signal:this.controller.signal});
        if(!this.active() || revision!==this.revision)return;
        this.pageCache.delete(path);this.pageCache.set(path,{at:Date.now(),data});
        while(this.pageCache.size>12)this.pageCache.delete(this.pageCache.keys().next().value);
        const unchanged=renderedCache && JSON.stringify(this.rows)===JSON.stringify(data.items||[]);
        if(!unchanged)this.rows=more?this.rows.concat(data.items||[]):data.items||[];
        this.hasMore=Boolean(data.has_more);this.offset=nextOffset;
        if(!unchanged)this.renderRows(more?nextOffset:0);
        status.textContent=this.rows.length?"":"No matches. Try another search or clear the filters.";
        if(this.page==="sets" && this.rows.length && Number.isInteger(data.total_count))status.textContent=data.total_count.toLocaleString()+" sets · Includes sets you don’t own";
        if(this.page!=="sets" && !this.rows.length && this.set?.checklist_status==="UNAVAILABLE" && !this.filters.q && this.filters.owned==="all" && !this.filters.watch && !this.filters.product_type)status.textContent="This set is in the catalogue. Its card checklist is currently unavailable.";
        if(this.filters.watch)status.textContent=this.rows.length?"Watchlist saved on this device.":"Your watchlist is empty for these filters. Star a product to save it on this device.";
        this.find('[data-action="more"]').hidden=!this.hasMore;
        if(this.page!=="sets")this.refreshPrices(this.rows,revision);
      } catch(error){if(this.active()&&revision===this.revision){status.textContent=this.rows.length?'Showing recently loaded results. Refresh failed; try again shortly.':error.message;this.hasMore=false;if(!more&&!this.rows.length)this.find(".dr-browse-content").replaceChildren(button("Try again",()=>this.load()));}}
      finally{if(revision===this.revision)this.loading=false;}
    }
    async refreshPrices(rows,revision) {
      const pending=rows.filter(row=>row.market_refresh_needed && !["STORED_SNAPSHOT","CARDMARKET_ESTIMATE"].includes(row.market_value_source));
      if(!pending.length)return;
      try {
        const data=await this.client.request("/api/v1/catalogue-browser/market-values",{method:"POST",body:JSON.stringify({keys:pending.slice(0,40).map(row=>row.key)}),signal:this.controller?.signal});
        if(!this.active()||revision!==this.revision)return;
        const updates=new Map((data.items||[]).map(row=>[row.key,row]));let changed=false;
        for(const row of pending.slice(0,40)){
          const update=updates.get(row.key);if(!update)continue;
          changed=changed||row.market_value_minor!==update.market_value_minor;
          Object.assign(row,update,{market_refresh_failed:Boolean(update.provider_refresh_failed)});
          this.dialog.querySelectorAll('[data-price-key]').forEach(el=>{if(el.dataset.priceKey===row.key)el.textContent=marketPrice(row);});
          const detail=this.sheet.querySelector('[data-market-details]');
          if(detail?.dataset.marketDetails===row.key)this.renderMarketDetails(detail,row);
        }
        // Requery value sorts after new quotes are cached, preserving server-side
        // ordering before pagination. Other sorts keep focus/scroll untouched.
        if(changed&&this.filters.sort.startsWith("value_")&&this.rows.length){this.load();return;}
        if(pending.length>40)this.refreshPrices(pending.slice(40),revision);
      } catch(_) {
        if(!this.active()||revision!==this.revision)return;
        for(const row of pending){
          row.market_refresh_failed=true;
          for(const label of this.dialog.querySelectorAll('[data-price-key]'))if(label.dataset.priceKey===row.key)label.textContent=marketPrice(row);
        }
        const detail=this.sheet.querySelector('[data-market-details]');
        const selected=pending.find(row=>row.key===detail?.dataset.marketDetails);
        if(selected)this.renderMarketDetails(detail,selected);
      }
    }
    renderMarketDetails(content,row) {
      content.replaceChildren(node("strong","dr-browse-detail-value",marketPrice(row)));
      if(row.market_value_minor==null)content.append(node("p","dr-browse-reference-note","No verified market value is available for this exact product yet. This does not mean the card is worth £0."));
      if(row.basis_condition)content.append(node("small","","Reference value: "+row.basis_condition+" · "+(row.pricing_updated_at?new Date(row.pricing_updated_at).toLocaleDateString("en-GB"):"stored snapshot")));
      for(const quote of row.market_quotes||[]){
        const label=quote.source==="TCGDEX_TCGPLAYER"?"TCGplayer US context · "+new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(quote.original_minor/100):money(quote.price_gbp_minor);
        const source=quote.source==="TCGDEX_TCGPLAYER"?"TCGplayer":"Cardmarket";
        const evidence=[quote.product_id?source+" #"+quote.product_id:"",quote.observed_at?new Date(quote.observed_at).toLocaleDateString("en-GB"):""].filter(Boolean).join(" · ");
        content.append(node("p","dr-browse-reference-note",(quote.variant_label||quote.finish)+": "+label+(evidence?" · "+evidence:"")));
      }
      if(["TCGDEX_CARDMARKET","TCGDEX_CARDMARKET_VARIANT"].includes(row.market_value_source)){
        content.append(node("p","dr-browse-reference-note","Cardmarket reference via TCGdex, converted from EUR. This is separate from your collection’s eBay UK sold-market valuation."));
      }
      if(row.market_value_source==="CARDMARKET_CATALOGUE")content.append(node("p","dr-browse-reference-note","Cardmarket catalogue guide, converted from EUR. Matched by a unique card name in both complete release checklists. The guide spans languages, conditions and foil treatments; it is not an exact physical-copy valuation."));
      if((row.market_quotes||[]).some(q=>q.source==="TCGDEX_TCGPLAYER"))content.append(node("p","dr-browse-reference-note","TCGplayer is supporting US market context. Its dollar price is not used as a UK sold-market valuation."));
      if(row.market_value_source==="CARDMARKET_BULK")content.append(node("p","dr-browse-reference-note","Cardmarket daily packaging guide, converted from EUR. This aggregate spans languages and conditions; confirm your exact package before valuing a physical item."));
      if(row.market_value_source==="CARDMARKET_BULK_SINGLES")content.append(node("p","dr-browse-reference-note","Cardmarket daily guide for this printing’s release, converted from EUR. It combines languages and conditions; it is separate from a condition-adjusted eBay UK sold value."));
      if(row.market_value_source==="CARDMARKET_ESTIMATE")content.append(node("p","dr-browse-reference-note","Cardmarket estimate for this printing and finish, converted from EUR. The guide combines languages and conditions; it is not a condition-adjusted UK sold value. Fresh exact eBay UK evidence takes priority."));
    }
    renderGames() {
      const content=this.find(".dr-browse-content"),grid=node("div","dr-browse-game-grid");
      for(const game of this.games){const tile=button("",()=>this.pickGame(game),"dr-browse-game");tile.dataset.system=game.system_code;
        const [name,line]=gameTitles[game.system_code]||[game.game,"TRADING CARD GAME"];
        const fallback=node("span","dr-browse-game-fallback");fallback.append(node("strong","",name),node("small","",line));tile.append(fallback);
        const artwork=window.DropRateTitleArt?.game(game.system_code);
        if(artwork){tile.prepend(this.titleImage(artwork,"dr-browse-game-logo",tile,"has-title-art"));
          if(artwork.caption)tile.append(node("small","dr-browse-publisher",artwork.caption));}
        tile.setAttribute("aria-label",game.game);grid.append(tile);}
      content.replaceChildren(node("h2","dr-browse-quick-heading","Browse card games"),grid);
      if(!this.games.length)content.append(node("p","dr-browse-empty","The catalogue is being prepared. Try scanning an item."));
    }
    titleImage(artwork,cls,host,loadedClass,onError) {
      const image=node("img",cls);image.alt="";image.decoding="async";image.loading="eager";
      image.addEventListener("load",()=>host.classList.add(loadedClass));
      image.addEventListener("error",()=>{host.classList.remove(loadedClass);image.remove();onError?.();});
      image.referrerPolicy="no-referrer";
      image.src=artwork.url||"/assets/title-art/"+artwork.file;return image;
    }
    clearArtwork() {
      this.artworkEpoch++;this.artworkQueue=[];
      this.artworkObserver?.disconnect();this.artworkWaiting.clear();
      for(const controller of this.artworkControllers)controller.abort();
      for(const url of this.artworkUrls.values())URL.revokeObjectURL(url);
      this.artworkUrls.clear();
    }
    loadReferenceImage(image,path,fallback) {
      const job={image,path,fallback,epoch:this.artworkEpoch};
      if(this.artworkObserver && image.loading==='lazy' && !this.artworkCache.has(path)){
        this.artworkWaiting.set(image,job);this.artworkObserver.observe(image);
      }else {this.artworkQueue.push(job);queueMicrotask(()=>this.drainArtwork());}
    }
    cacheArtwork(path,blob) {
      const previous=this.artworkCache.get(path);if(previous)this.artworkBytes-=previous.blob.size;
      this.artworkCache.delete(path);this.artworkCache.set(path,{blob,at:Date.now()});this.artworkBytes+=blob.size;
      while(this.artworkCache.size>128 || this.artworkBytes>16000000){
        const key=this.artworkCache.keys().next().value;this.artworkBytes-=this.artworkCache.get(key).blob.size;this.artworkCache.delete(key);
      }
    }
    drainArtwork() {
      while(this.active() && this.artworkActive<4 && this.artworkQueue.length){
        const job=this.artworkQueue.shift();if(!job.image.isConnected || job.epoch!==this.artworkEpoch)continue;
        const controller=new AbortController();this.artworkControllers.add(controller);this.artworkActive++;
        (async()=>{
          try {
            const cached=this.artworkCache.get(job.path);
            const blob=cached && Date.now()-cached.at<3600000?cached.blob:await this.client.requestImage(job.path,{signal:controller.signal});
            if(!this.active() || job.epoch!==this.artworkEpoch)return;
            this.cacheArtwork(job.path,blob);
            if(!job.image.isConnected)return;
            for(const [image,url]of this.artworkUrls){if(!image.isConnected){URL.revokeObjectURL(url);this.artworkUrls.delete(image);}}
            const url=URL.createObjectURL(blob);this.artworkUrls.set(job.image,url);job.image.src=url;
          } catch(_) {if(this.active() && job.epoch===this.artworkEpoch && job.image.isConnected)job.fallback();}
          finally {this.artworkControllers.delete(controller);this.artworkActive--;this.drainArtwork();}
        })();
      }
    }
    productImage(row,cls="dr-browse-product-image") {
      const wrap=node("div",cls);
      const urls=[...new Set([row.display_image_url,row.image_url,row.fallback_image_url]
        .filter(url=>typeof url==="string").map(url=>url.trim())
        .filter(url=>/^https:\/\//.test(url)||/^\/(?!\/)/.test(url)))];
      // TCGdex serves a grid-sized asset for the exact same card. Keep the
      // original as fallback and use it unchanged in the detail sheet.
      if(cls!=="dr-browse-detail-image" && /^https:\/\/assets\.tcgdex\.net\/[^?#]+\/high\.webp(?:\?|$)/.test(urls[0]||"")){
        urls.unshift(urls[0].replace('/high.webp','/low.webp'));
      }
      const placeholder=node("span","dr-browse-image-placeholder",urls.length?"Loading image…":"Artwork unavailable");
      wrap.append(placeholder);
      if(urls.length){
        const image=node("img");image.alt=decode(row.name);image.loading="lazy";image.decoding="async";image.referrerPolicy="no-referrer";
        if(cls==="dr-browse-detail-image")image.loading="eager";
        image.addEventListener("load",()=>{placeholder.hidden=true;});
        const referencePath=row.reference_image_path?.startsWith('/api/v1/catalogue-browser/reference-image?')?row.reference_image_path+(cls==="dr-browse-detail-image"?"":"&size=grid"):null;
        let proxyTried=Boolean(referencePath);
        const fallback=()=>{if(urls.length)image.src=urls.shift();else {image.remove();placeholder.textContent="Image unavailable";placeholder.hidden=false;}};
        image.addEventListener("error",()=>{
          if(!proxyTried && row.reference_image_path?.startsWith('/api/v1/catalogue-browser/reference-image?')){
            proxyTried=true;this.loadReferenceImage(image,row.reference_image_path,fallback);
          } else fallback();
        });
        // These official hosts reject cross-site <img> loads. Use the exact,
        // authenticated reference route first instead of waiting for a failure.
        if(referencePath){const source=urls.indexOf(row.image_url);if(source>=0)urls.splice(source,1);this.loadReferenceImage(image,referencePath,fallback);}
        else image.src=urls.shift();wrap.append(image);
      }
      return wrap;
    }
    renderRows(start=0) {
      const content=this.find(".dr-browse-content");
      const previous=start?content.querySelector('.dr-browse-grid'):null;
      const grid=previous||node("div",this.page==="sets"?"dr-browse-grid dr-browse-set-grid":"dr-browse-grid");
      for(const row of this.rows.slice(previous?start:0)){
        if(this.page==="sets") {
          const tile=button("",()=>{this.set=row;Object.assign(this.filters,{language:row.language,q:"",owned:"all",watch:false,product_type:""});this.page="products";this.load();},"dr-browse-set");
          tile.dataset.system=row.system_code;
          const art=node("div","dr-browse-set-art");
          if(row.release_date)art.append(node("small","dr-browse-release",new Date(row.release_date+"T12:00:00").toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"})));
          const visual=node("div","dr-browse-set-visual");
          const fallback=node("span","dr-browse-set-fallback","✦");fallback.setAttribute("aria-hidden","true");
          visual.append(fallback);
          // Set art comes exclusively from approved title-logo mappings.
          // Individual card or sealed-product previews must never become set covers.
          const exactArt=window.DropRateTitleArt?.set({...row,set_name:decode(row.set_name)});
          const artwork=exactArt||window.DropRateTitleArt?.game(row.system_code);
          if(artwork)visual.append(this.titleImage(artwork,"dr-browse-set-logo",visual,exactArt?"has-set-logo":"has-game-logo"));
          if(exactArt)art.title=exactArt.title;
          art.append(visual);
          const info=node("div","dr-browse-set-info");
          info.append(node("small","dr-browse-set-game",this.game()?.game||row.system_code),
            node("strong","dr-browse-set-name",decode(row.set_name)),
            node("small","dr-browse-set-code",row.set_id||""));
          const stats=node("div","dr-browse-set-stats");
          stats.append(node("span","","Progress: "+row.owned_count+"/"+(row.card_count||row.indexed_count||"—")),
            node("small","","Total Value: "+(row.owned_count===0?"£0":row.owned_value_minor==null?"Pending":money(row.owned_value_minor)+(row.unknown_values?" + pending":""))));
          if(row.checklist_status==="UNAVAILABLE")stats.append(node("small","dr-browse-checklist-note","Card checklist unavailable"));
          else if(row.checklist_status==="PARTIAL")stats.append(node("small","dr-browse-checklist-note",row.indexed_count+" cards available to browse"));
          tile.append(art,info,stats);
          tile.setAttribute("aria-label",decode(row.set_name)+" · "+row.language);grid.append(tile);continue;
        }
        const card=node("article","dr-browse-product");
        const open=button("",()=>this.openProduct(row),"dr-browse-product-open");open.append(this.productImage(row),node("strong","dr-browse-product-title",decode(row.name)));
        open.setAttribute("aria-label","View "+decode(row.name));
        const meta=[row.rarity,row.card_number].filter(Boolean).join(" · ");
        open.append(node("small","",decode(row.set_name)),node("small","",meta),node("small","",row.language+" · "+(row.product_type==="SEALED"?"Sealed":decode(row.variant))));
        card.append(open);
        const footer=node("div","dr-browse-product-footer"),copy=node("div"),price=node("strong","",marketPrice(row));price.dataset.priceKey=row.key;
        copy.append(price,node("small","","Qty: "+row.owned_quantity));
        const plus=button("+",()=>this.openProduct(row),"dr-browse-plus");plus.setAttribute("aria-label","Add "+decode(row.name));footer.append(copy,plus);card.append(footer);
        if(row.owned_quantity>0)card.append(node("span","dr-browse-owned","✓"));
        grid.append(card);
      }
      if(!previous)content.replaceChildren(grid);
    }
    openSheet(title) {
      this.sheetReturn=document.activeElement;this.sheet.replaceChildren(node("div","dr-browse-handle"));
      const header=node("header"),heading=node("h2","",title);heading.id="dr-browse-sheet-title";
      const close=button("×",()=>this.closeSheet());close.setAttribute("aria-label","Close "+title);
      header.append(heading,close);this.sheet.append(header);this.sheet.setAttribute("aria-labelledby",heading.id);
      this.find(".dr-browse-backdrop").hidden=false;
      // Re-rendering filters or save feedback must retain the original workspace state.
      if(this.embedded && !this.outerInert){
        this.outerInert=[...document.querySelectorAll(".topbar,.seller-nav,.owner-sidebar,.owner-page-header")].map(el=>[el,el.inert]);
        this.outerInert.forEach(([el])=>{el.inert=true;});
      }
      for(const cls of [".dr-browse-header",".dr-browse-scroll",".dr-browse-nav"])this.find(cls).inert=true;
      close.focus();this.find(".dr-browse-menu").hidden=true;
    }
    closeSheet(restoreFocus=true) { if(this.saving)return;this.restoreOuter();this.find(".dr-browse-backdrop").hidden=true;
      for(const cls of [".dr-browse-header",".dr-browse-scroll",".dr-browse-nav"])this.find(cls).inert=false;
      if(restoreFocus){if(this.sheetReturn?.isConnected)this.sheetReturn.focus();else this.input.focus();}this.header(); }
    filterGroup(title,hint,choices,current,onChange) {
      const group=node("fieldset","dr-browse-filter-group");group.append(node("legend","",title),node("p","",hint));
      for(const [value,label] of choices){const wrap=node("label","",label),input=node("input");input.type="checkbox";input.checked=current===value;input.setAttribute("aria-label",label);
        input.addEventListener("change",()=>{onChange(input.checked?value:"");this.load();this.openFilters();});wrap.append(input);group.append(wrap);}
      return group;
    }
    openFilters() {
      this.openSheet("Filters");
      this.sheet.append(this.filterGroup("Watchlist","Saved products on this device.",[["watch","Watchlist"]],this.filters.watch?"watch":"",value=>{this.filters.watch=Boolean(value);}),
        this.filterGroup("Product Type","Filter by type of product.",[["CARD","Cards Only"],["SEALED","Sealed Only"]],this.filters.product_type,value=>{this.filters.product_type=value;}),
        this.filterGroup("Product Status within Inventory","All products are shown unless you select a filter.",[["owned","Products Owned"],["not_owned","Products Not Owned"]],this.filters.owned,value=>{this.filters.owned=value||"all";}));
      const footer=node("footer");footer.append(button("Clear filters",()=>{this.defaults();this.closeSheet();this.load();},"dr-browse-secondary"),button("Show results",()=>this.closeSheet(),"dr-browse-primary"));this.sheet.append(footer);
    }
    openSort() { this.openSheet("Sort");const list=node("div","dr-browse-sort-list");
      for(const [value,label] of Object.entries(sorts)){const choice=button(label+(this.filters.sort===value?" ✓":""),()=>{this.filters.sort=value;this.closeSheet();this.load();});choice.setAttribute("aria-pressed",String(this.filters.sort===value));list.append(choice);}this.sheet.append(list); }
    toggleWatch(row,control) {
      if(this.watchlist.has(row.key))this.watchlist.delete(row.key);
      else {if(this.watchlist.size>=100){this.sheet.querySelector(".dr-browse-detail-message").textContent="Your watchlist can hold 100 products.";return;}this.watchlist.add(row.key);}
      control.textContent=this.watchlist.has(row.key)?"★ Saved":"☆ Watchlist";control.setAttribute("aria-pressed",String(this.watchlist.has(row.key)));
      try{localStorage.setItem(this.storageKey,JSON.stringify([...this.watchlist]));}catch(_){this.sheet.querySelector(".dr-browse-detail-message").textContent="Browser storage is unavailable. This watchlist lasts for this session.";}
    }
    openProduct(row) {
      this.openSheet("Product Details");
      let edit=this.pending.get(row.key);
      if(!edit){edit={row,condition:"",language:"",quantity:1,confirmed:false,requests:null};this.pending.set(row.key,edit);}
      this.edit=edit;
      const content=node("div","dr-browse-product-details");
      content.append(this.productImage(row,"dr-browse-detail-image"),node("h3","",decode(row.name)),node("p","",[decode(row.set_name),row.card_number,row.language,decode(row.variant)].filter(Boolean).join(" · ")));
      if(row.provider&&row.provider_id){
        const reference=node("div","dr-browse-reference-note");reference.dataset.cardReference=row.key;
        reference.append(node("strong","","Card reference"),node("p","",row.provider+" · "+row.provider_id),node("small","","Set reference: "+row.set_id+" · "+row.language));
        content.append(reference);
      } else if(row.catalogue_id)content.append(node("p","dr-browse-reference-note","Drop Rate reference: "+row.catalogue_id));
      const pricing=node("div");pricing.dataset.marketDetails=row.key;this.renderMarketDetails(pricing,row);content.append(pricing);
      const watch=button(this.watchlist.has(row.key)?"★ Saved":"☆ Watchlist",()=>this.toggleWatch(row,watch),"dr-browse-watch-product");watch.setAttribute("aria-pressed",String(this.watchlist.has(row.key)));content.append(watch);
      if(row.source_kind==="REFERENCE")content.append(node("p","dr-browse-reference-note","Reference artwork · check the exact printing and finish against your copy. New inventory remains pending identity review."));
      if(row.source_kind==='SEALED_REFERENCE')content.append(node('p','dr-browse-reference-note','Packaging reference · confirm the exact product, language, edition and pack count. Your item stays in review before it can be listed.'));
      const fields=node("div","dr-browse-physical");
      if(row.product_type==='SEALED' && row.language==='Unknown'){
        const label=node('label','','Product language'),select=node('select');select.setAttribute('aria-label','Product language');
        for(const language of ['','English','Japanese','Chinese','Korean','French','German','Italian','Spanish']){const option=node('option','',language||'Choose language');option.value=language;select.append(option);}
        select.value=edit.language;select.disabled=Boolean(edit.requests);
        select.addEventListener('change',()=>{edit.language=select.value;this.validateAdd();});label.append(select);fields.append(label);
      }
      const conditionLabel=node("label","",row.product_type==="SEALED"?"Seal status":"Condition"),condition=node("select");
      for(const label of row.product_type==="SEALED"?["Sealed"]:["Choose condition",...conditions]){const option=node("option","",label);option.value=label==="Choose condition"?"":label;condition.append(option);}
      condition.value=row.product_type==="SEALED"?"Sealed":edit.condition;condition.setAttribute("aria-label","Condition");condition.disabled=Boolean(edit.requests)||row.product_type==="SEALED";
      condition.addEventListener("change",()=>{edit.condition=condition.value;this.validateAdd();});conditionLabel.append(condition);
      const quantityLabel=node("label","","Quantity"),quantity=node("input");quantity.type="number";quantity.min="1";quantity.max="50";quantity.step="1";quantity.inputMode="numeric";quantity.value=edit.quantity;quantity.setAttribute("aria-label","Quantity");quantity.disabled=Boolean(edit.requests);
      quantity.addEventListener("input",()=>{edit.quantity=Number(quantity.value);this.validateAdd();});quantityLabel.append(quantity);fields.append(conditionLabel,quantityLabel);content.append(fields);
      const confirm=node("label","dr-browse-confirm"),checkbox=node("input");checkbox.type="checkbox";checkbox.checked=edit.confirmed;checkbox.disabled=Boolean(edit.requests);checkbox.setAttribute("aria-label","Confirm exact product");
      checkbox.addEventListener("change",()=>{edit.confirmed=checkbox.checked;this.validateAdd();});confirm.append(checkbox,node("span","",row.product_type==="SEALED"?"This is the exact product and it is still sealed.":"This is the exact card, printing and language I own."));content.append(confirm);
      if(row.product_type==="CARD")content.append(button("Adding a graded slab?",()=>{this.closeSheet();this.close();this.options.graded(row);},"dr-browse-graded-link"));
      content.append(node("p","dr-browse-detail-message",edit.error||""));this.sheet.append(content);
      const footer=node("footer"),save=button("Add to Inventory",()=>this.save(),"dr-browse-primary");save.dataset.add="true";footer.append(save);this.sheet.append(footer);this.validateAdd();
    }
    validateAdd() { const edit=this.edit;if(!edit)return;const done=edit.requests?.every(request=>request.result);
      const save=this.sheet.querySelector("[data-add]");if(!save)return;
      save.textContent=this.saving?"Adding…":done?"Added · Done":edit.requests?"Retry remaining saves":"Add to Inventory";
      save.disabled=this.saving||(!edit.requests&&(!edit.confirmed||!Number.isInteger(edit.quantity)||edit.quantity<1||edit.quantity>50||(edit.row.product_type!=="SEALED"&&!conditions.includes(edit.condition))||(edit.row.product_type==='SEALED'&&edit.row.language==='Unknown'&&!edit.language))); }
    async save() {
      const edit=this.edit;if(!edit||this.saving||this.sheet.querySelector("[data-add]").disabled||!this.active())return;
      if(edit.requests?.every(request=>request.result)){this.pending.delete(edit.row.key);this.edit=null;this.closeSheet();this.load();return;}
      if(!edit.requests){const body=JSON.stringify({key:edit.row.key,condition:edit.row.product_type==="SEALED"?null:edit.condition,seal_status:edit.row.product_type==="SEALED"?"SEALED":null,confirmed:true,...(edit.row.product_type==='SEALED'&&edit.row.language==='Unknown'?{language:edit.language}:{})});
        edit.requests=Array.from({length:edit.quantity},()=>({key:crypto.randomUUID(),body,result:null}));}
      this.saving=true;this.sheet.querySelectorAll("button,input,select").forEach(control=>{control.disabled=true;});this.validateAdd();
      try {
        for(const request of edit.requests){if(request.result)continue;
          const result=await this.client.request("/api/v1/catalogue-browser/intake",{method:"POST",headers:{"Idempotency-Key":request.key},body:request.body});
          if(!result.inventory?.inventory_code)throw new Error("Save confirmation was incomplete. Retry this same addition.");request.result=result;this.pageCache.clear();}
        edit.error=edit.quantity+" added to your inventory. Identity review is still required before approval.";
        try{await this.options.afterSave();}catch(_){edit.error+=" Refresh inventory to update totals.";}
      }catch(error){if(this.active())edit.error=error.message+" Retry uses the same requests to avoid duplicate copies.";}
      finally{if(this.active()){this.saving=false;this.openProduct(edit.row);}}
    }
  }
  return {Browser};
})();
