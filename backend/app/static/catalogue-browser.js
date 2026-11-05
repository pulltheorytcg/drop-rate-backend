"use strict";

window.DropRateCatalogue = (() => {
  const node = (tag, cls = "", text) => { const el = document.createElement(tag); el.className = cls; if (text != null) el.textContent = text; return el; };
  const button = (text, action, cls = "") => { const el = node("button", cls, text); el.type = "button"; el.addEventListener("click", action); return el; };
  const money = value => value == null ? "Value pending" : new Intl.NumberFormat("en-GB", {style:"currency", currency:"GBP"}).format(value / 100);
  const ukEuEstimate = row => window.DropRateReferenceValue?.ukEuEstimate(row.uk_eu_market_estimate) || null;
  const currentValue = row => (Number.isSafeInteger(row.market_value_minor) && row.market_value_minor > 0) ||
    (["AVAILABLE", "REFERENCE_ESTIMATE", "CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(row.shared_price?.status)
      && Number.isSafeInteger(row.shared_price.market_value_minor) && row.shared_price.market_value_minor > 0);
  const askingEstimate = row => {
    // Asking evidence is a separate fallback, never a physical market value.
    const estimate=row.asking_price_estimate, shared=row.shared_price, now=Date.now(), maxAge=3*24*60*60*1000;
    if(row.product_type!=="CARD" || row.market_value_minor!=null ||
      (["AVAILABLE","REFERENCE_ESTIMATE","CATALOGUE_GUIDE","CONDITION_REFERENCE"].includes(shared?.status) && Number.isInteger(shared.market_value_minor) && shared.market_value_minor>0))return null;
    if(!estimate || estimate.status!=="ASKING_PRICE_ESTIMATE" || estimate.source!=="EBAY_OFFICIAL_BROWSE" ||
      estimate.method_version!=="EBAY_UK_RAW_ASK_V1" || estimate.currency!=="GBP" || estimate.shipping_basis!=="ITEM_PLUS_SHIPPING" ||
      estimate.shipping_context!=="CONFIGURED_SHOP_POSTCODE_BENCHMARK" ||
      estimate.physical_valuation_eligible!==false || estimate.recommended_retail_minor!==null || estimate.condition!=="Near Mint" ||
      !["Normal","Holo","Reverse Holo","Foil","Parallel","Alt Art","Manga"].includes(estimate.finish) ||
      !Number.isSafeInteger(estimate.estimate_minor) || estimate.estimate_minor<=0 ||
      !Number.isSafeInteger(estimate.estimate_high_minor) || estimate.estimate_high_minor<estimate.estimate_minor ||
      !Number.isSafeInteger(estimate.listing_count) || estimate.listing_count<3 ||
      !Number.isSafeInteger(estimate.seller_count) || estimate.seller_count<3 || estimate.seller_count>estimate.listing_count ||
      typeof estimate.observed_at!=="string" || typeof estimate.expires_at!=="string")return null;
    const observed=Date.parse(estimate.observed_at), expires=Date.parse(estimate.expires_at);
    return Number.isFinite(observed) && Number.isFinite(expires) && observed<=now && observed>=now-maxAge && expires>now && expires<=observed+maxAge ? estimate : null;
  };
  // Neither internal predicted values nor listing asks can become Market Value,
  // including if an older API response persists in an account-scoped page cache.
  const unsupportedMarketSource = row =>
    ["DROP_RATE_COMPUTED_MARKET_V1","CARDTRADER_EXPANSION_ASKING",
     "TCGCSV_TCGPLAYER_CATALOGUE"].includes(row.market_value_source);
  const marketPrice = row => {
    if (row.shared_price && !["DROP_RATE_COMPUTED_MARKET_V1","DROP_RATE_UK_EU_MARKET_V1"].includes(row.shared_price.method))
      return window.DropRateReferenceValue.text({reference_value:row.shared_price}, money).replace(/^Value:/, "Market value:");
    if(unsupportedMarketSource(row))return "Value unavailable";
    return row.market_value_minor==null
      ? (row.product_type==="COMIC"?"Value pending":row.market_refresh_failed?"Value temporarily unavailable":row.market_refresh_needed?"Value pending":"Value unavailable")
      : "Market value: "+money(row.market_value_minor);
  };
  const historicalPrice = row =>
    row.shared_price && window.DropRateReferenceValue?.isHistorical({reference_value:row.shared_price})
      ? row.shared_price : null;
  const conditions = ["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"];
  const decode = value => { const el = document.createElement("textarea"); el.innerHTML = String(value || ""); return el.value; };
  const sorts = {newest:"Newest first", oldest:"Oldest first", name:"Name A–Z", name_desc:"Name Z–A",
    number:"Card number", value_desc:"Value: high to low", value_asc:"Value: low to high"};
  // Bandai's _pN is a distinct publisher reference: show it without assuming
  // a grade, rarity or market value from the base card.
  const printingMarker = row => {
    if(row.metadata_only && row.identity_review_required)return row.product_type==="FIGURE"?"Edition details need review":"Printing details need review";
    if (row.source_kind!=="REFERENCE" || row.provider!=="Bandai Official" || !String(row.system_code||"").startsWith("DRAGON_BALL"))return null;
    const match=String(row.provider_id||row.variant||"").match(/_p([1-9][0-9]*)$/);
    return match ? "Printing variant p"+match[1] : null;
  };
  // An English checklist is not evidence of a physical sports card's language;
  // figures have no card-language field at all.
  const displayLanguage = row => row.product_type==="FIGURE"?"":
    row.metadata_only&&row.system_code==="SPORTS_CARDS"?row.sports_card?.language||"":row.language||"";
  const gameTitles = {POKEMON_TCG:["Pokémon","TRADING CARD GAME"], ONE_PIECE_CARD_GAME:["ONE PIECE","CARD GAME"],
    DRAGON_BALL_SUPER_MASTERS:["DRAGON BALL","SUPER · MASTERS"], DRAGON_BALL_SUPER_FUSION_WORLD:["DRAGON BALL","FUSION WORLD"],
    NARUTO:["NARUTO","TRADING CARD GAME"], COMICS:["COMICS","MARVEL · DC · INDIE"], MANGA:["MANGA","COLLECTIBLE VOLUMES"],
    RIFTBOUND:["RIFTBOUND","LEAGUE OF LEGENDS"], YUGIOH:["Yu-Gi-Oh!","TRADING CARD GAME"], DISNEY_LORCANA:["LORCANA","TRADING CARD GAME"],
    MAGIC_THE_GATHERING:["MAGIC","THE GATHERING"]};
  // Navigation categories do not create product types or catalogue sources.
  // Comics and manga retain their existing COMIC storage type and exact systems.
  const categories = {
    TCG:{label:"Trading Card Games",short:"TCG",hint:"Search cards across the catalogue, or choose a game to narrow your search.",type:"CARD",system:""},
    SPORTS:{label:"Sports Cards",short:"Sports",hint:"Find an available reference, or add your sports card by entering its details.",type:"CARD",system:"SPORTS_CARDS"},
    COMICS:{label:"Comics",short:"Comics",hint:"Find the exact issue, cover and edition for your collection.",type:"COMIC",system:"COMICS"},
    MANGA:{label:"Manga",short:"Manga",hint:"Browse by demographic, then find the exact series, volume and language. Demographics are separate from genres.",type:"COMIC",system:"MANGA"},
    FIGURES:{label:"Figures",short:"Figures",hint:"Find an available reference, or add your figure by entering its details.",type:"FIGURE",system:"FIGURES"},
  };
  const tcgSystems = new Set(Object.keys(gameTitles).filter(code=>!["COMICS","MANGA"].includes(code))
    .concat(["NARUTO_KAYOU","NARUTO_BANDAI_LEGACY","NARUTO_BANDAI"]));
  const bookSystems = {COMICS:"All comics",MARVEL_COMICS:"Marvel Comics",DC_COMICS:"DC Comics",OTHER_COMICS:"Other comics",MANGA:"Manga"};
  // Display groups refine existing references; they never change canonical
  // identity, ownership or whether a provider is approved and available.
  const browseGroups = {
    COMICS:{label:"Publisher",choices:[["","All comics"],["MARVEL","Marvel"],["DC","DC"],["INDIE","Indie"],["OTHER","Other / unclassified"]]},
    MANGA:{label:"Demographic",choices:[["","All manga"],["SHONEN","Shōnen"],["SHOJO","Shōjo"],["SEINEN","Seinen"],["JOSEI","Josei"],["KODOMO","Kodomo"],["UNKNOWN","Unclassified"]]},
    SPORTS:{label:"Manufacturer",choices:[["","All sports cards"],["PANINI","Panini"],["TOPPS","Topps"],["OTHER","Other / unclassified"]]},
    FIGURES:{label:"Figure type",choices:[["","All figures"],["FUNKO_POP","Funko Pops"],["FIGURINES","Figurines"],["OTHER","Other / unclassified"]]},
  };
  const referenceKey = value => typeof value === "string" && /^(?:[rs]:[a-f0-9]{32}|x:[a-f0-9]{64}|c:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/.test(value);
  const sourceLink = value => {
    if(typeof value!=="string"||value.length>2048||/[\s\\\u0000-\u001f\u007f]/.test(value))return null;
    try {
      const url=new URL(value),host=url.hostname.toLowerCase().replace(/\.$/,"");
      if(url.protocol!=="https:"||url.username||url.password||url.port||!host.includes(".")||host.includes(":")||
        /^[0-9.]+$/.test(host)||host.endsWith(".localhost")||host.endsWith(".local")||host.endsWith(".internal")||host.endsWith(".home.arpa"))return null;
      return url.href;
    }catch(_){return null;}
  };

  class Browser {
    constructor(options) {
      this.options = options; this.client = options.client;
      this.artworkQueue=[];this.artworkActive=0;this.artworkEpoch=0;this.artworkControllers=new Set();this.artworkUrls=new Map();
      this.artworkCache=new Map();this.artworkBytes=0;this.pageCache=new Map();this.artworkWaiting=new Map();
      this.revision = 0; this.pending = new Map(); this.watchlist = new Set(); this.games = Object.entries(gameTitles).filter(([code])=>["POKEMON_TCG","ONE_PIECE_CARD_GAME","DRAGON_BALL_SUPER_MASTERS","DRAGON_BALL_SUPER_FUSION_WORLD","NARUTO","COMICS","MANGA"].includes(code)).map(([system_code,[game]]) => ({system_code,game,languages:[]})); this.gamesLoaded = false;
      this.defaults();
      this.storageKey = "drop-rate-watchlist:" + this.client.owner;
      this.deviceSaved = new Set();this.savedState="idle";this.savedError="";
      try {
        const saved = JSON.parse(localStorage.getItem(this.storageKey) || "[]");
        if (Array.isArray(saved)) this.deviceSaved = new Set(saved.filter(referenceKey).slice(0,100));
      } catch (_) { /* Private browsing may disable storage. */ }
      this.build();
      this.bookContexts = window.DropRateBookEbay && new window.DropRateBookEbay.Session({client:this.client, root:this.scroll,
        active:()=>this.active() && !this.dialog.hidden && (this.embedded || this.dialog.open)});
    }
    active() { return !this.destroyed && this.client.active(); }
    defaults(categoryId="TCG") {
      this.resume=null;this.productsReturn=null;
      this.categoryId=Object.hasOwn(categories,categoryId)?categoryId:"TCG";
      const category=categories[this.categoryId];
      this.filters = {q:"",system_code:category.system||"",language:"",product_type:category.type||"",browse_group:"",owned:"all",sort:"newest",watch:false};
      this.set = null; this.page = "products"; this.setQuery = ""; this.rows = []; this.offset = 0;this.browseAll=false;
    }
    find(selector) { return this.dialog.querySelector(selector); }
    build() {
      this.embedded = Boolean(this.options.host);
      this.dialog = node(this.embedded ? "section" : "dialog", "dr-browser" + (this.embedded ? " dr-browser-embedded" : "")); this.dialog.setAttribute("aria-label", "Search Drop Rate products");
      this.dialog.innerHTML = `<header class="dr-browse-header"><nav class="dr-browse-categories" aria-label="Collectible categories"></nav>
        <div class="dr-browse-category-heading"><div><h2></h2><p></p></div><button type="button" data-action="games" hidden>← All games</button></div>
        <div class="dr-browse-set-heading" hidden><button type="button" data-action="back" aria-label="Back to products">←</button><h2></h2></div>
        <nav class="dr-browse-groups" aria-label="Catalogue groups" hidden></nav>
        <div class="dr-browse-searchbar"><button type="button" data-action="camera" aria-label="Open scanner">◎</button><input type="search" maxlength="160" placeholder="Search for products" aria-label="Search for products"><button type="button" data-action="clear-query" aria-label="Clear search">×</button></div>
        <div class="dr-browse-context"><span>Browse: <strong>All products</strong></span><button type="button" data-action="sets">Show Sets</button></div>
        <nav class="dr-browse-types" aria-label="Product type"><button type="button" data-type="">All products</button><button type="button" data-type="CARD">Cards</button><button type="button" data-type="SEALED">Sealed products</button></nav>
        <div class="dr-browse-chips"></div><div class="dr-browse-toolbar" role="group" aria-label="Catalogue controls"><button type="button" data-action="filters-visible">Filter & sort</button><button type="button" data-action="watch" aria-label="Saved references" aria-pressed="false">☆ Saved</button></div><p class="dr-browse-saved-note" hidden></p><nav class="dr-browse-languages" aria-label="Set language" hidden></nav><button type="button" class="dr-browse-pending" hidden></button></header>
        <div class="dr-browse-scroll"><p class="dr-browse-status" role="status"></p><div class="dr-browse-content"></div><button type="button" data-action="more" class="dr-browse-load" hidden>Load more</button><div class="dr-browse-sentinel"></div></div>
        <nav class="dr-browse-nav" aria-label="App navigation"><button type="button" data-action="home"><span>⌂</span>Home</button><button type="button" class="active" data-action="search"><span>⌕</span>Search</button><button type="button" data-action="camera"><span>◎</span>Scan</button><button type="button" data-action="inventory"><span>▣</span>Collection</button><button type="button" data-action="tools"><span>•••</span>More</button></nav>
        <div class="dr-browse-backdrop" hidden><section class="dr-browse-sheet" role="dialog" aria-modal="true"></section></div>`;
      (this.options.host || document.body).append(this.dialog);
      this.input = this.find("input[type=search]"); this.scroll = this.find(".dr-browse-scroll"); this.sheet = this.find(".dr-browse-sheet");
      for(const [id,category] of Object.entries(categories)){
        const control=button(category.short,()=>this.pickCategory(id));control.dataset.category=id;
        control.setAttribute("aria-label",category.label);control.title=category.label;
        this.find(".dr-browse-categories").append(control);
      }
      const actions = {back:()=>this.back(), camera:()=>this.scan(), home:()=>this.navigate("home"), inventory:()=>this.navigate("inventory"), tools:()=>this.navigate("more"),
        games:()=>this.reset(),
        search:()=>this.reset(), "clear-query":()=>{ if(this.page === "sets") this.setQuery=""; else this.filters.q=""; this.input.value=""; this.load(); },
        sets:()=>this.showSets(), more:()=>this.load(true), filters:()=>this.openFilters(), sort:()=>this.openSort(),
        "sort-visible":()=>this.openSort(), "filters-visible":()=>this.openFilters(),
        watch:()=>{ this.filters.watch=!this.filters.watch;this.page="products";this.browseAll=true;this.load(); }};
      this.dialog.querySelectorAll("[data-action]").forEach(control=>control.addEventListener("click",()=>actions[control.dataset.action]()));
      this.dialog.querySelectorAll('[data-type]').forEach(control=>control.addEventListener('click',()=>{
        if(this.categoryId!=="TCG")return;
        this.filters.product_type=control.dataset.type;this.browseAll=true;this.set=null;this.page='products';this.load();
      }));
      this.input.addEventListener("input",()=>{
        clearTimeout(this.timer); this.revision += 1; this.controller?.abort(); this.bookContexts?.reset(); this.loading=false;
        if (this.page === "sets") this.setQuery=this.input.value; else this.filters.q=this.input.value;
        this.find(".dr-browse-status").textContent="Searching…";
        this.timer=setTimeout(()=>this.load(),260);
      });
      this.input.addEventListener("keydown",event=>{
        if(event.key!=="Enter"||event.isComposing||event.keyCode===229)return;
        event.preventDefault();clearTimeout(this.timer);
        if(this.page==="sets")this.setQuery=this.input.value;else this.filters.q=this.input.value;
        this.load();
      });
      this.dialog.addEventListener("cancel",event=>{event.preventDefault();if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet();else this.close();});
      this.dialog.addEventListener("keydown",event=>{
        if(event.key==="Escape"&&!this.find(".dr-browse-backdrop").hidden){event.preventDefault();this.closeSheet();return;}
        if(event.key!=="Tab" || this.find(".dr-browse-backdrop").hidden)return;
        const controls=[...this.sheet.querySelectorAll('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled)')];
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
      this.loadSaved();
      if(!productKey && this.resume && (this.rows.length || this.isHome())){
        this.header();if(this.isHome())this.renderGames();else this.renderRows();
        this.scroll.scrollTop=this.resume.scrollTop;
        const target=[...this.dialog.querySelectorAll("[data-product-key]")].find(el=>el.dataset.productKey===this.resume.focusKey);
        target?.focus({preventScroll:true});this.resume=null;return;
      }
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
        if(row)this.openProduct(row);
      } catch(error) {if(this.active()&&revision===this.revision)status.textContent=error.message;}
      finally {if(revision===this.revision)this.loading=false;}
    }
    close() {
      if(this.saving)return;
      this.resume={scrollTop:this.scroll.scrollTop,focusKey:document.activeElement?.closest?.("[data-product-key]")?.dataset.productKey||this.lastProductKey};
      if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet(false);
      this.restoreOuter();this.revision+=1;this.controller?.abort();clearTimeout(this.timer);this.loading=false;
      this.clearArtwork();
      if(this.embedded)this.dialog.hidden=true;else this.dialog.close();
      document.body.classList.remove("dr-browser-open");if(!this.embedded)this.returnFocus?.focus();
    }
    restoreOuter() { (this.outerInert||[]).forEach(([el,was])=>{el.inert=was;});this.outerInert=null; }
    destroy() { this.restoreOuter();this.destroyed=true;this.bookContexts?.destroy();this.clearArtwork();this.artworkCache.clear();this.artworkBytes=0;this.pageCache.clear();this.revision+=1;this.controller?.abort();clearTimeout(this.timer);this.observer?.disconnect();this.pending.clear();this.dialog.remove();document.body.classList.remove("dr-browser-open"); }
    navigate(view) { if(this.saving)return;this.close();this.options.navigate(view); }
    scan(mode="RAW") { if(this.saving)return;this.close();this.options.scan(typeof mode === "string" ? mode : "RAW"); }
    reset() { if(this.saving)return;this.resume=null;this.defaults();this.input.value="";this.load(); }
    pickCategory(id) {
      if(this.saving||!Object.hasOwn(categories,id))return;
      const query=this.page==="products"?this.filters.q:"",saved=this.filters.watch;
      this.defaults(id);this.filters.q=query;this.filters.watch=saved;this.browseAll=saved;this.input.value=query;this.load();
    }
    clearCategoryFilters() {
      const {q,watch,product_type}=this.filters;this.defaults(this.categoryId);
      Object.assign(this.filters,{q,watch,product_type:product_type||categories[this.categoryId].type||""});
      this.input.value=q;this.browseAll=true;
    }
    game() { return this.games.find(game=>game.system_code===this.filters.system_code)
      || (bookSystems[this.filters.system_code]?{system_code:this.filters.system_code,game:bookSystems[this.filters.system_code],languages:this.games.find(game=>game.system_code===this.categoryId)?.languages||[]}:null); }
    isHome() { const f=this.filters;return this.categoryId==="TCG" && !this.browseAll && this.page!=="sets" && !f.q.trim()&&!f.system_code&&!f.language&&["","CARD"].includes(f.product_type)&&f.owned==="all"&&!f.watch; }
    isBookFamily(code=this.filters.system_code){ return Object.hasOwn(bookSystems,code); }
    async resumeSearch() {
      if(!this.active())return;
      try{
        if(this.options.returnToSearch)await this.options.returnToSearch();
        else {this.options.navigate("search");await this.open();}
      }catch(error){if(this.active())this.find(".dr-browse-status").textContent=error.message;}
    }
    openBookIntake(row){
      if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet();this.close();
      if(typeof this.options.books==="function")this.options.books({...(row?{book:row.book_details,catalogue:row}:{category:this.categoryId,query:this.filters.q}),
        onAddAnother:()=>this.resumeSearch()});
      else this.options.navigate("inventory");
    }
    openCollectibleIntake(row) {
      const category=(row?row.product_type==="FIGURE":this.categoryId==="FIGURES")?"figures":"sports";
      const handler=this.options.collectibles;
      if(typeof handler!=="function"){
        const message=this.sheet.querySelector(".dr-browse-detail-message")||this.find(".dr-browse-status");
        message.textContent="Item entry is still loading. Please reopen Search and try again.";return;
      }
      if(!this.find(".dr-browse-backdrop").hidden)this.closeSheet();this.close();
      const opened=handler({category,query:this.filters.q,...(row?{catalogue:row}:{}),onAddAnother:()=>this.resumeSearch()});
      if(opened===false)this.resumeSearch().then(()=>{if(this.active())this.find(".dr-browse-status").textContent="Item entry is still loading. Please try again shortly.";});
    }
    pickGame(game) { this.categoryId=this.isBookFamily(game.system_code)?game.system_code:"TCG";this.filters.system_code=game.system_code;this.filters.language="";this.filters.product_type=this.isBookFamily(game.system_code)?"COMIC":"";this.filters.browse_group="";this.set=null;this.page="products";this.load(); }
    pickBrowseGroup(value) {
      if(this.saving || !browseGroups[this.categoryId]?.choices.some(([id])=>id===value))return;
      this.filters.browse_group=value;this.filters.system_code=categories[this.categoryId].system;
      this.set=null;this.browseAll=true;this.load();
    }
    renderBrowseGroups() {
      const nav=this.find(".dr-browse-groups"),group=browseGroups[this.categoryId];
      nav.hidden=!group;if(!group)return;
      nav.setAttribute("aria-label",group.label);
      // Keep the focused control mounted while results load and paginate.
      if(nav.dataset.groupCategory!==this.categoryId){
        nav.replaceChildren();nav.dataset.groupCategory=this.categoryId;
        for(const [id,label] of group.choices){
          const control=button(label,()=>this.pickBrowseGroup(id));control.dataset.browseGroup=id;nav.append(control);
        }
      }
      nav.querySelectorAll("[data-browse-group]").forEach(control=>control.setAttribute("aria-pressed",String(control.dataset.browseGroup===this.filters.browse_group)));
    }
    showSets() { if(!this.filters.system_code)return;
      this.productsReturn={filters:{...this.filters},set:this.set,browseAll:this.browseAll,scrollTop:this.scroll.scrollTop};
      this.page="sets";this.setQuery="";this.set=null;
      this.filters.q="";this.filters.owned="all";this.filters.watch=false;this.filters.product_type=this.isBookFamily()?"COMIC":"";
      const langs=this.game()?.languages||[];if(!this.filters.language)this.filters.language=langs.includes("English")?"English":langs[0]||"";this.load(); }
    back() { if(this.page==="sets"){
      const previous=this.productsReturn;this.productsReturn=null;this.page="products";this.setQuery="";
      if(previous){this.filters=previous.filters;this.set=previous.set;this.browseAll=previous.browseAll;}
      this.load().then(()=>{if(previous&&this.active())this.scroll.scrollTop=previous.scrollTop;});}
      else if(this.set){this.set=null;this.showSets();}else this.reset(); }
    header() {
      const sets=this.page==="sets",home=this.isHome();
      if(this.isBookFamily()){this.categoryId=this.filters.system_code==="MANGA"?"MANGA":"COMICS";this.filters.product_type="COMIC";}
      const category=categories[this.categoryId],unavailable=Boolean(category.unavailable),book=this.isBookFamily();
      this.dialog.dataset.category=this.categoryId;
      this.dialog.querySelectorAll('[data-category]').forEach(control=>control.setAttribute('aria-pressed',String(control.dataset.category===this.categoryId)));
      this.find('.dr-browse-category-heading h2').textContent=category.label;
      this.find('.dr-browse-category-heading p').textContent=category.hint;
      this.renderBrowseGroups();
      this.find('[data-action="games"]').hidden=this.categoryId!=="TCG"||!this.filters.system_code;
      this.find('.dr-browse-searchbar').hidden=unavailable;
      this.input.disabled=unavailable;
      this.find(".dr-browse-set-heading").hidden=!sets;
      this.find(".dr-browse-set-heading h2").textContent=(this.game()?.game||"Product")+(this.isBookFamily()?" Series":" Sets");
      this.input.value=sets?this.setQuery:this.filters.q;
      this.input.placeholder=sets?(book?"Search by series":"Search by sets"):book?(this.categoryId==="MANGA"?"Title, volume or ISBN":"Comic title or issue"):
        this.categoryId==="SPORTS"?"Player, team or card":this.categoryId==="FIGURES"?"Character, figure or maker":
        this.filters.product_type==="SEALED"?"Search sealed products":"Card name or number";
      this.input.setAttribute("aria-label",this.input.placeholder);
      this.find(".dr-browse-context").hidden=sets||home||unavailable;
      this.find('.dr-browse-types').hidden=sets||this.categoryId!=="TCG";
      this.find('[data-type=""]').hidden=!this.filters.system_code;
      this.find('.dr-browse-toolbar').hidden=sets||unavailable;
      const refineCount=Number(Boolean(this.categoryId==="TCG"&&this.filters.system_code||this.categoryId==="COMICS"&&this.filters.system_code!=="COMICS"&&!this.filters.browse_group))+Number(Boolean(this.filters.browse_group))+Number(Boolean(this.filters.language))+Number(Boolean(this.set))+Number(this.filters.owned!=="all");
      this.find('[data-action="filters-visible"]').textContent="Filter & sort"+(refineCount?" · "+refineCount:"");
      this.find('[data-action="filters-visible"]').setAttribute("aria-label","Filter and sort, current order "+(sorts[this.filters.sort]||sorts.newest));
      this.dialog.querySelectorAll('[data-type]').forEach(control=>control.setAttribute('aria-pressed',String(control.dataset.type===this.filters.product_type)));
      this.find(".dr-browse-context strong").textContent=this.filters.watch?category.label+" · Saved references":this.filters.owned==="owned"?"Items in your collection":this.filters.owned==="not_owned"?"Items not in your collection":this.game()?.game||category.label;
      this.find('[data-action="sets"]').hidden=!this.filters.system_code||["SPORTS","FIGURES"].includes(this.categoryId);
      this.find('[data-action="sets"]').textContent=this.isBookFamily()?"Browse Series":"Show Sets";
      this.find('[data-action="watch"]').textContent=(this.filters.watch?"★":"☆")+" Saved"+(this.savedState==="ready"&&this.watchlist.size?" · "+this.watchlist.size:"");
      this.find('[data-action="watch"]').setAttribute("aria-pressed",String(this.filters.watch));
      this.renderSavedNote();
      const chips=this.find(".dr-browse-chips");chips.replaceChildren();chips.hidden=sets||unavailable;
      const chip=(label,action)=>chips.append(button(label+" ×",()=>{action();this.load();},"dr-browse-chip"));
      if(this.filters.system_code&&this.categoryId==="TCG")chip(this.game()?.game||this.filters.system_code,()=>{this.filters.system_code="";this.filters.language="";this.filters.product_type="CARD";this.set=null;});
      if(this.categoryId==="COMICS"&&this.filters.system_code!=="COMICS"&&!this.filters.browse_group)chip(bookSystems[this.filters.system_code]||this.filters.system_code,()=>{this.filters.system_code="COMICS";this.set=null;});
      if(this.filters.browse_group){
        const label=browseGroups[this.categoryId]?.choices.find(([id])=>id===this.filters.browse_group)?.[1];
        if(label)chip(label,()=>{this.filters.browse_group="";this.filters.system_code=categories[this.categoryId].system;this.set=null;});
      }
      if(this.set)chip(decode(this.set.set_name),()=>{this.set=null;});
      if(this.filters.language)chip(this.filters.language,()=>{this.filters.language="";this.set=null;});
      // Format is a navigation choice above, not a removable default filter.
      if(this.filters.owned!=="all")chip(this.filters.owned==="owned"?"Items you own":"Items you don’t own",()=>{this.filters.owned="all";});
      if(chips.childElementCount)chips.append(button("Clear filters",()=>{this.clearCategoryFilters();this.load();},"dr-browse-clear"));
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
      if(categories[this.categoryId].unavailable){this.loading=false;this.hasMore=false;this.renderUnavailable();this.find('[data-action="more"]').hidden=true;return;}
      if(this.isHome()){this.loading=false;this.renderGames();this.find('[data-action="more"]').hidden=true;return;}
      if(this.filters.watch && this.savedState!=="ready"){
        this.loading=false;this.find(".dr-browse-content").replaceChildren();
        status.textContent=this.savedState==="error"?"Saved references could not sync. Your collection is unaffected.":"Loading your saved references…";
        if(this.savedState==="error")this.find(".dr-browse-content").append(button("Try again",()=>this.loadSaved(true),"dr-browse-empty-action"));
        else this.loadSaved();return;
      }
      if(!more)this.skeleton();
      const nextOffset=more?this.rows.length:0;
      const params=new URLSearchParams({limit:"40",offset:String(nextOffset)});
      if(this.page==="sets") {
        params.set("system_code",this.filters.system_code);params.set("language",this.filters.language);params.set("q",this.setQuery.trim());
      } else {
        params.set("category",this.categoryId);
        for(const key of ["q","system_code","language","product_type","owned","sort"])if(this.filters[key])params.set(key,this.filters[key]);
        // Default TCG search excludes COMIC records. A chosen game can return
        // its cards and sealed products together using the existing endpoint.
        if(this.categoryId==="TCG"&&!this.filters.system_code&&!this.filters.product_type)params.set("product_type","CARD");
        if(this.set){params.set("system_code",this.set.system_code);params.set("set_id",this.set.set_id);params.set("provider",this.set.provider);}
        if(this.filters.watch)params.set("keys",[...this.watchlist].join(","));
      }
      if(this.filters.browse_group)params.set("browse_group",this.filters.browse_group);
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
        if(this.page==="products"&&!this.rows.length&&this.isBookFamily()
          && this.filters.owned==="all"&&!this.filters.watch&&!this.filters.q.trim()&&!this.filters.browse_group&&!this.set){
          status.textContent=(this.filters.system_code==="MANGA"?"Manga":"Comics")+" catalogue is ready for your first verified book. No books have been added yet.";
        }
        if(this.page==="products" && !this.rows.length && this.filters.system_code==="NARUTO"
           && this.filters.product_type==="SEALED" && this.filters.owned==="all" && !this.filters.watch && !this.filters.q.trim()){
          status.textContent="Naruto sealed products are not yet indexed from a verified product source. Naruto cards are available.";
          this.find(".dr-browse-content").append(button("Browse Naruto cards",()=>{this.filters.product_type="CARD";this.load();},"dr-browse-empty-action"));
        }
        if(this.page==="sets" && this.rows.length && Number.isInteger(data.total_count))status.textContent=data.total_count.toLocaleString()+" sets · Includes sets you don’t own";
        if(this.page!=="sets" && !this.rows.length && this.set?.checklist_status==="UNAVAILABLE" && !this.filters.q && this.filters.owned==="all" && !this.filters.watch && !this.filters.product_type)status.textContent="This set is in the catalogue. Its card checklist is currently unavailable.";
        if(this.filters.watch)status.textContent=this.rows.length?"":"No saved references match this view. Save an item from its details to find it here.";
        if(this.page==="products"&&!this.rows.length)this.renderEmptyActions();
        this.find('.dr-browse-r2-scope')?.remove();
        if(this.categoryId==='TCG' && !this.filters.watch && !this.filters.system_code
           && data.catalogue_scope==='LEGACY_WITH_SEPARATE_R2_SYSTEMS'){
          const systems=new Set(data.additional_catalogue_systems||[]);
          const games=this.games.filter(game=>systems.has(game.system_code)&&tcgSystems.has(game.system_code));
          if(games.length){
            const scope=node('section','dr-browse-empty-actions dr-browse-r2-scope');
            scope.append(node('p','dr-browse-reference-note','New catalogues currently have a separate game search. Search the same name or number below:'));
            for(const game of games)scope.append(button('Search '+game.game,()=>{
              this.filters.system_code=game.system_code;this.set=null;this.page='products';this.browseAll=true;this.load();
            },'dr-browse-empty-action'));
            this.find('.dr-browse-content').append(scope);
          }
        }
        this.find('[data-action="more"]').hidden=!this.hasMore;
        // Market references arrive from stored snapshots; browsing never starts provider refreshes.
      } catch(error){if(this.active()&&revision===this.revision){status.textContent=this.rows.length?'Showing recently loaded results. Refresh failed; try again shortly.':error.message;this.hasMore=false;if(!more&&!this.rows.length)this.find(".dr-browse-content").replaceChildren(button("Try again",()=>this.load()));}}
      finally{if(revision===this.revision)this.loading=false;}
    }
    renderMarketDetails(content,row) {
      content.replaceChildren(node("strong","dr-browse-detail-value",marketPrice(row)));
      const history=historicalPrice(row);
      if(history){
        const checked=new Date(history.checked_at);
        content.append(node("small","dr-browse-historical-label",Number.isNaN(checked.getTime())?"Historical value":"Historical value · Last known "+checked.toLocaleDateString("en-GB")));
      }
      const evidence=node("details","dr-browse-extra dr-browse-price-details");evidence.append(node("summary","","About this value"));content.append(evidence);
      // Internal/asking estimates remain auditable, not monetary market values.
      if(row.asking_price_estimate || row.uk_eu_market_estimate ||
         unsupportedMarketSource(row))
        evidence.append(node("p","dr-browse-reference-note",
          "A provisional estimate or active listing was observed but is not an independently verified market value."));
      if(row.shared_price)evidence.append(node("p","dr-browse-reference-note",window.DropRateReferenceValue.description({reference_value:row.shared_price})));
      if((row.market_value_minor==null || unsupportedMarketSource(row)) && !row.shared_price?.last_known_minor)evidence.append(node("p","dr-browse-reference-note","No verified market value is available for this exact product yet. This does not mean the card is worth £0."));
      if(row.basis_condition && !unsupportedMarketSource(row))evidence.append(node("small","","Price basis: "+row.basis_condition+" · "+(row.pricing_updated_at?new Date(row.pricing_updated_at).toLocaleDateString("en-GB"):"stored snapshot")));
      for(const quote of row.market_quotes||[]){
        if(["DROP_RATE_COMPUTED_MARKET_V1","CARDTRADER_EXPANSION_ASKING",
            "TCGCSV_TCGPLAYER_CATALOGUE"].includes(quote.source))continue;
        const label=quote.source==="TCGDEX_TCGPLAYER"?"TCGplayer US context · "+new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(quote.original_minor/100):money(quote.price_gbp_minor);
        const computed=quote.source==="DROP_RATE_COMPUTED_MARKET_V1";
        const source=computed?"Drop Rate":quote.source==="CARDTRADER_EXPANSION_ASKING"?"CardTrader":quote.source==="TCGDEX_TCGPLAYER"||quote.market==="TCGPLAYER"?"TCGplayer":"Cardmarket";
        const productId=quote.product_id||quote.source_product_id;
        const quoteEvidence=[productId?source+" #"+productId:"",quote.observed_at?new Date(quote.observed_at).toLocaleDateString("en-GB"):""].filter(Boolean).join(" · ");
        evidence.append(node("p","dr-browse-reference-note",(quote.variant_label||quote.finish||(computed?"Drop Rate estimate":source+" guide"))+": "+label+(quoteEvidence?" · "+quoteEvidence:"")));
      }
      if(["TCGDEX_CARDMARKET","TCGDEX_CARDMARKET_VARIANT"].includes(row.market_value_source)){
        evidence.append(node("p","dr-browse-reference-note","Cardmarket reference via TCGdex, converted from EUR. This is separate from your collection’s eBay UK sold-market valuation."));
      }
      if(row.market_value_source==="POKEWALLET_POKEMON_CARDMARKET_CATALOGUE")evidence.append(node("p","dr-browse-reference-note","Cardmarket Non-English regional guide via PokéWallet, converted from EUR. Japanese language and your copy’s condition are not verified by this guide; it is not an exact UK sold valuation."));
      if(row.market_value_source==="TCGCSV_TCGPLAYER_CATALOGUE")evidence.append(node("p","dr-browse-reference-note","TCGplayer US marketplace guide via TCGCSV, converted from USD. Matched to the exact release, card number and unique source product. This is not a UK sold price or a valuation of your copy’s condition."));
      if(row.market_value_source==="CARDMARKET_CATALOGUE")evidence.append(node("p","dr-browse-reference-note","Cardmarket catalogue guide, converted from EUR. Matched by a unique card name in both complete release checklists. The guide spans languages, conditions and foil treatments; it is not an exact physical-copy valuation."));
      if((row.market_quotes||[]).some(q=>q.source==="TCGDEX_TCGPLAYER"))evidence.append(node("p","dr-browse-reference-note","TCGplayer is supporting US market context. Its dollar price is not used as a UK sold-market valuation."));
      if(row.market_value_source==="CARDMARKET_BULK")evidence.append(node("p","dr-browse-reference-note","Cardmarket daily packaging guide, converted from EUR. This aggregate spans languages and conditions; confirm your exact package before valuing a physical item."));
      if(row.market_value_source==="CARDMARKET_BULK_SINGLES")evidence.append(node("p","dr-browse-reference-note","Cardmarket daily guide for this printing’s release, converted from EUR. It combines languages and conditions; it is separate from a condition-adjusted eBay UK sold value."));
      if(row.market_value_source==="CARDMARKET_ESTIMATE")evidence.append(node("p","dr-browse-reference-note","Cardmarket estimate for this printing and finish, converted from EUR. The guide combines languages and conditions; it is not a condition-adjusted UK sold value. Fresh exact eBay UK evidence takes priority."));
    }
    renderGames() {
      const content=this.find(".dr-browse-content"),grid=node("div","dr-browse-game-grid");
      const games=this.games.filter(game=>tcgSystems.has(game.system_code));
      for(const game of games){const tile=button("",()=>this.pickGame(game),"dr-browse-game");tile.dataset.system=game.system_code;
        const [name,line]=gameTitles[game.system_code]||[game.game,"TRADING CARD GAME"];
        const fallback=node("span","dr-browse-game-fallback");fallback.append(node("strong","",name),node("small","",line));tile.append(fallback);
        const artwork=window.DropRateTitleArt?.game(game.system_code);
        if(artwork){tile.prepend(this.titleImage(artwork,"dr-browse-game-logo",tile,"has-title-art"));
          if(artwork.caption)tile.append(node("small","dr-browse-publisher",artwork.caption));}
        tile.setAttribute("aria-label",game.game);grid.append(tile);}
      content.replaceChildren(node("h2","dr-browse-quick-heading","Browse by game"),grid);
      if(!games.length)content.append(node("p","dr-browse-empty","Game browsing is currently unavailable. You can still search cards by name or number."));
    }
    renderUnavailable() {
      const category=categories[this.categoryId],panel=node("section","dr-browse-category-empty");
      panel.setAttribute("aria-label",category.label+" catalogue status");
      panel.append(node("span","dr-browse-category-status","Catalogue unavailable"),
        node("h3","",category.label),
        node("p","","The "+(this.categoryId==="SPORTS"?"sports card":"figure")+" catalogue is not available yet. Explore trading card games, comics or manga in the meantime."),
        button("Explore Trading Card Games",()=>this.reset(),"dr-browse-empty-action"));
      this.find(".dr-browse-content").replaceChildren(panel);
    }
    titleImage(artwork,cls,host,loadedClass,onError) {
      const image=node("img",cls);image.alt="";image.decoding="async";image.loading=cls==="dr-browse-set-logo"?"lazy":"eager";
      image.addEventListener("load",()=>host.classList.add(loadedClass));
      image.addEventListener("error",()=>{host.classList.remove(loadedClass);image.remove();onError?.();});
      image.referrerPolicy="no-referrer";
      image.src=artwork.url||"/assets/title-art/"+artwork.file;return image;
    }
    clearArtwork() {
      this.artworkEpoch++;this.artworkQueue=[];
      this.bookContexts?.reset();
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
    productImage(row,cls="dr-browse-product-image",listingCredit=null) {
      const wrap=node("div",cls);
      const epoch=this.artworkEpoch;
      const current=()=>this.active() && epoch===this.artworkEpoch && wrap.isConnected;
      const community=window.DropRateBookArtwork?.reference(row,cls==="dr-browse-detail-image");
      // R2 mirrors are signed, short-lived object links for rights-approved
      // canonical media. Keep the original provider source as a fallback.
      const urls=[...new Set([row.r2_image_url,row.display_image_url,row.image_url,row.fallback_image_url]
        .filter(url=>typeof url==="string").map(url=>url.trim())
        .filter(url=>/^https:\/\//.test(url)||/^\/(?!\/)/.test(url)))];
      if(community)urls.push(community.image_url);
      // TCGdex serves a grid-sized asset for the exact same card. Keep the
      // original as fallback and use it unchanged in the detail sheet.
      if(cls!=="dr-browse-detail-image" && /^https:\/\/assets\.tcgdex\.net\/[^?#]+\/high\.webp(?:\?|$)/.test(urls[0]||"")){
        urls.unshift(urls[0].replace('/high.webp','/low.webp'));
      }
      const publisherReference=row.source_kind==="SEALED_REFERENCE"&&row.provider==="Kayou Official";
      const missingPokemonSource=row.source_kind==="REFERENCE"&&row.provider==="TCGdex"&&row.system_code==="POKEMON_TCG";
      const referencePath=row.reference_image_path?.startsWith('/api/v1/catalogue-browser/reference-image?')?row.reference_image_path+(cls==="dr-browse-detail-image"?"":"&size=grid"):null;
      const placeholder=node("span","dr-browse-image-placeholder",(urls.length||referencePath)?"Loading image…":publisherReference?"Verified Kayou product · Packaging photo pending":missingPokemonSource?"Card image not yet available · Reference only":"Artwork unavailable");
      if(publisherReference&&!urls.length)wrap.classList.add("dr-browse-publisher-photo-pending");
      if(missingPokemonSource&&!urls.length)wrap.classList.add("dr-browse-reference-photo-pending");
      wrap.append(placeholder);
      let exhausted=!(urls.length||referencePath),listingData=null,listingImage=null,attempted=new Set();
      const clearListing=()=>{listingImage?.remove();listingImage=null;listingCredit?.replaceChildren();wrap.dispatchEvent(new CustomEvent("listing-photo-change",{detail:false}));};
      const listingFallback=()=>{
        if(!exhausted || !listingCredit || !current())return;
        const item=window.DropRateBookEbay?.photos(row,listingData).find(item=>!attempted.has(item.item_id));
        if(!item)return;
        attempted.add(item.item_id);clearListing();
        const photo=node("img");listingImage=photo;photo.loading="lazy";photo.decoding="async";
        photo.referrerPolicy="no-referrer";photo.crossOrigin="anonymous";
        photo.alt=decode(row.name)+" — eBay listing photo; copy may vary";
        placeholder.hidden=false;placeholder.textContent="Loading listing photo…";
        photo.addEventListener("load",()=>{
          if(!current() || listingImage!==photo || !window.DropRateBookEbay?.validate(row,listingData)){photo.remove();return;}
          placeholder.hidden=true;listingCredit.replaceChildren(window.DropRateBookEbay.photoCredit(item));wrap.dispatchEvent(new CustomEvent("listing-photo-change",{detail:true}));
        });
        photo.addEventListener("error",()=>{
          if(!current() || listingImage!==photo)return;
          clearListing();placeholder.hidden=false;placeholder.textContent="Image unavailable";listingFallback();
        });
        wrap.append(photo);photo.src=item.image_url;
      };
      wrap.setListingContext=data=>{
        listingData=window.DropRateBookEbay?.validate(row,data);attempted=new Set();clearListing();
        if(exhausted){placeholder.hidden=false;placeholder.textContent="Image unavailable";listingFallback();}
      };
      if(urls.length||referencePath){
        const image=node("img");image.alt=decode(row.name);image.loading="lazy";image.decoding="async";image.referrerPolicy="no-referrer";
        if(row.artwork_kind==="PUBLISHER_REFERENCE")image.alt+=" — publisher reference cover";
        if(community)image.alt+=" — community cover reference; cover may vary";
        if(cls==="dr-browse-detail-image"&&!community)image.loading="eager";
        image.addEventListener("load",()=>{placeholder.hidden=true;});
        // One Piece's publisher blocks direct cross-site card images. Other
        // reference providers first load from their own origin so Railway only
        // relays an image if the browser could not load the source URL.
        const directProviderFirst=new Set(["POKEMON_TCG","DRAGON_BALL_SUPER_MASTERS","DRAGON_BALL_SUPER_FUSION_WORLD"]).has(row.system_code);
        const useReferenceFirst=Boolean(referencePath&&!row.r2_image_url&&!directProviderFirst);
        let proxyTried=useReferenceFirst;
        const fallback=()=>{if(!this.active() || epoch!==this.artworkEpoch)return;if(urls.length)image.src=urls.shift();else {image.remove();exhausted=true;placeholder.textContent=missingPokemonSource?"Card image not yet available · Reference only":"Image unavailable";placeholder.hidden=false;if(missingPokemonSource)wrap.classList.add("dr-browse-reference-photo-pending");listingFallback();}};
        image.addEventListener("error",()=>{
          if(!proxyTried && referencePath){
            proxyTried=true;this.loadReferenceImage(image,referencePath,fallback);
          } else fallback();
        });
        // These official hosts reject cross-site <img> loads. Use the exact,
        // authenticated reference route first instead of waiting for a failure.
        if(useReferenceFirst){const source=urls.indexOf(row.image_url);if(source>=0)urls.splice(source,1);this.loadReferenceImage(image,referencePath,fallback);}
        else image.src=urls.shift();wrap.append(image);
      }
      return wrap;
    }
    watchBookContext(row,target,panel,artwork,{detail=false,immediate=detail,current=()=>true}={}) {
      if(!this.bookContexts || !window.DropRateBookEbay.identity(row))return ()=>{};
      return this.bookContexts.watch(row,target,(data,options)=>{
        window.DropRateBookEbay.render(panel,row,data,{...options,detail});artwork.setListingContext?.(data);
      },{immediate,current,allowPriced:detail});
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
          // Prefer the backend's typed, provenance-bound set-artwork contract.
          // Legacy lookup only supports cached/fixture responses without artwork.
          const serverArt=row.artwork;
          const trustedLogoUrl=value=>{
            if(typeof value!=="string")return false;
            try {
              const source=new URL(value);
              return source.protocol==="https:" && source.host==="assets.tcgdex.net" &&
                source.pathname.startsWith("/en/") && source.pathname.endsWith("/logo.webp") &&
                !source.pathname.includes("..") && !source.search && !source.hash;
            } catch(_) {return false;}
          };
          const sourceValid=serverArt && ["SET_LOGO","GAME_LOGO","BRANDED_FALLBACK"].includes(serverArt.type) &&
            (serverArt.type==="BRANDED_FALLBACK" ||
              (typeof serverArt.file==="string" && /^[a-z0-9][a-z0-9-]*[.](png|jpg|jpeg|webp|svg)$/.test(serverArt.file)) ||
              trustedLogoUrl(serverArt.url));
          const typedArt=sourceValid?serverArt:null;
          const exactArt=typedArt?(typedArt.type==="SET_LOGO"?typedArt:null):
            window.DropRateTitleArt?.set({...row,set_name:decode(row.set_name)});
          const artwork=typedArt?(typedArt.type==="BRANDED_FALLBACK"?null:typedArt):
            exactArt||window.DropRateTitleArt?.game(row.system_code);
          if(artwork)visual.append(this.titleImage(artwork,"dr-browse-set-logo",visual,exactArt?"has-set-logo":"has-game-logo"));
          if(exactArt)art.title=exactArt.title;
          tile.dataset.artworkStatus=typedArt?.status||(exactArt?"SOURCE_INDEXED":"SET_LOGO_MISSING");
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
        const listingCredit=node("div","book-ebay-credit-slot"),artwork=this.productImage(row,"dr-browse-product-image",listingCredit);
        const open=button("",()=>this.openProduct(row),"dr-browse-product-open");open.dataset.productKey=row.key;open.append(artwork,node("strong","dr-browse-product-title",decode(row.name)));
        open.setAttribute("aria-label","View "+decode(row.name));
        const meta=[row.rarity,row.card_number].filter(Boolean).join(" · ");
        open.append(node("small","",decode(row.set_name)),node("small","",meta),node("small","",[displayLanguage(row),
          row.product_type==="SEALED"?"Sealed":row.product_type==="COMIC"?"Collectible book":printingMarker(row)||decode(row.variant)].filter(Boolean).join(" · ")));
        card.append(open);
        const community=window.DropRateBookArtwork?.reference(row);
        if(community){const note=window.DropRateBookArtwork.credit(community,"dr-browse-reference-note");card.append(note);artwork.addEventListener("listing-photo-change",event=>{note.hidden=event.detail;});}
        card.append(listingCredit);
        if(row.product_type==="COMIC" && row.market_value_minor==null && window.DropRateBookEbay?.identity(row)){
          const panel=node("div");card.append(panel);
          // Browsing and scrolling never triggers a book-by-book provider
          // lookup. Only a deliberate hover/focus (or opening book details)
          // requests current eBay asking context for this exact edition.
          let requested=false;
          const onInterest=()=>{
            if(requested||!card.isConnected||!this.active())return;
            requested=true;
            this.watchBookContext(row,card,panel,artwork,{immediate:true});
          };
          card.addEventListener("focusin",onInterest,{once:true});
          card.addEventListener("pointerenter",onInterest,{once:true});
        }
        const footer=node("div","dr-browse-product-footer"),copy=node("div"),price=node("strong","",marketPrice(row));price.dataset.priceKey=row.key;
        copy.append(price,node("small","","Qty: "+row.owned_quantity));
        if(historicalPrice(row))copy.append(node("small","dr-browse-historical-label","Historical value"));
        const plus=button("+",()=>row.product_type==="COMIC"?this.openBookIntake(row):this.openProduct(row),"dr-browse-plus");plus.setAttribute("aria-label","Add "+decode(row.name));footer.append(copy,plus);card.append(footer);
        if(row.owned_quantity>0)card.append(node("span","dr-browse-owned","✓"));
        grid.append(card);
      }
      if(!previous)content.replaceChildren(grid);
    }
    openSheet(title) {
      this.stopBookDetail?.();this.stopBookDetail=null;this.bookDetailEpoch=(this.bookDetailEpoch||0)+1;
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
      close.focus();
    }
    closeSheet(restoreFocus=true) { if(this.saving)return;this.restoreOuter();this.find(".dr-browse-backdrop").hidden=true;
      this.stopBookDetail?.();this.stopBookDetail=null;this.bookDetailEpoch=(this.bookDetailEpoch||0)+1;
      for(const cls of [".dr-browse-header",".dr-browse-scroll",".dr-browse-nav"])this.find(cls).inert=false;
      if(restoreFocus){if(this.sheetReturn?.isConnected)this.sheetReturn.focus();else this.input.focus();}this.header(); }
    filterGroup(title,hint,choices,current,onChange) {
      const group=node("fieldset","dr-browse-filter-group");group.append(node("legend","",title),node("p","",hint));
      for(const [value,label] of choices){const wrap=node("label","",label),input=node("input");input.type="checkbox";input.checked=current===value;input.setAttribute("aria-label",label);
        input.addEventListener("change",()=>{onChange(input.checked?value:"");this.load();this.openFilters();});wrap.append(input);group.append(wrap);}
      return group;
    }
    openFilters() {
      this.openSheet("Filter & sort");
      const draft={...this.filters},fields=node("div","dr-browse-refine-fields");
      const select=(label,key,choices)=>{
        const wrap=node("label","",label),control=node("select");control.setAttribute("aria-label",label);control.dataset.filter=key;
        choices.forEach(([value,text])=>{const option=node("option","",text);option.value=value;control.append(option);});
        control.value=draft[key];control.addEventListener("change",()=>{draft[key]=control.value;});wrap.append(control);fields.append(wrap);return control;
      };
      if(this.categoryId==="TCG")select("Game","system_code",[["","All trading card games"],...this.games.filter(game=>tcgSystems.has(game.system_code)).map(game=>[game.system_code,game.game])]);
      else if(browseGroups[this.categoryId])select(browseGroups[this.categoryId].label,"browse_group",browseGroups[this.categoryId].choices);
      const languages=[...new Set(this.games.filter(game=>this.categoryId==="TCG"?tcgSystems.has(game.system_code):[this.categoryId,categories[this.categoryId].system].includes(game.system_code)).flatMap(game=>game.languages||[]))].sort();
      if(this.filters.language&&!languages.includes(this.filters.language))languages.push(this.filters.language);
      if(languages.length)select("Language","language",[["","All languages"],...languages.map(language=>[language,language])]);
      select("In your collection","owned",[["all","All catalogue references"],["owned","Items you own"],["not_owned","Items you don’t own"]]);
      select("Sort by","sort",Object.entries(sorts).filter(([value])=>!(this.categoryId!=="TCG"&&value==="number")).map(([value,label])=>[value,label]));
      fields.append(node("p","dr-browse-reference-note","Saved references are bookmarks. They are separate from the physical items in your collection."));this.sheet.append(fields);
      const footer=node("footer");
      footer.append(button("Clear filters",()=>{this.clearCategoryFilters();this.closeSheet();this.load();},"dr-browse-secondary"),button("Show results",()=>{
        if(draft.system_code!==this.filters.system_code||draft.language!==this.filters.language||draft.browse_group!==this.filters.browse_group)this.set=null;
        if(browseGroups[this.categoryId])draft.system_code=categories[this.categoryId].system;
        this.filters=draft;if(this.categoryId==="TCG"&&!draft.system_code&&!draft.product_type)this.filters.product_type="CARD";
        this.browseAll=true;this.page="products";this.closeSheet();this.load();
      },"dr-browse-primary"));this.sheet.append(footer);
    }
    openSort() { this.openSheet("Sort");const list=node("div","dr-browse-sort-list");
      for(const [value,label] of Object.entries(sorts)){const choice=button(label+(this.filters.sort===value?" ✓":""),()=>{this.filters.sort=value;this.closeSheet();this.load();});choice.setAttribute("aria-pressed",String(this.filters.sort===value));list.append(choice);}this.sheet.append(list); }
    renderSavedNote() {
      const note=this.find(".dr-browse-saved-note");note.replaceChildren();note.hidden=!this.filters.watch;
      if(note.hidden)return;
      note.append(document.createTextNode(this.savedState==="ready"?"Saved to your account. Bookmarks do not add items to your collection.":this.savedState==="error"?"Account saves are not synced. Try again when your connection is available.":"Syncing saved references…"));
      if(this.deviceSaved.size){
        note.append(document.createTextNode(" "+this.deviceSaved.size+" older saves are still on this device only. "));
        const migrate=button("Import device saves to this account",()=>this.importDeviceSaved(),"dr-browse-device-import");migrate.disabled=this.savedState!=="ready"||this.savedMutation;note.append(migrate);
      }
      if(this.savedImportMessage)note.append(node("span","dr-browse-saved-feedback",this.savedImportMessage));
    }
    updateSavedControls() {
      this.dialog.querySelectorAll("[data-saved-key]").forEach(control=>{
        const saved=this.watchlist.has(control.dataset.savedKey);control.textContent=saved?"★ Saved to your account":"☆ Save reference";
        control.setAttribute("aria-pressed",String(saved));control.disabled=Boolean(this.savedMutation);
      });
    }
    async loadSaved(force=false) {
      if(this.savedRequest)return this.savedRequest;
      if(this.savedState==="ready"&&!force&&Date.now()-(this.savedCheckedAt||0)<60000)return true;
      this.savedState="loading";this.savedError="";
      this.savedRequest=(async()=>{
        try{
          const data=await this.client.request("/api/v1/catalogue-browser/saved");
          if(!this.active())return false;
          if(!Array.isArray(data.keys)||data.keys.some(key=>!referenceKey(key)))throw new Error("Saved references could not sync. Please try again.");
          this.watchlist=new Set(data.keys);this.savedState="ready";this.savedCheckedAt=Date.now();this.updateSavedControls();this.header();
          if(this.filters.watch)this.load();return true;
        }catch(error){if(this.active()){this.savedState="error";this.savedError=error.message;this.header();if(this.filters.watch)this.load();}return false;}
        finally{this.savedRequest=null;}
      })();
      return this.savedRequest;
    }
    savedControl(row) {
      const control=button(this.watchlist.has(row.key)?"★ Saved to your account":"☆ Save reference",()=>this.toggleWatch(row,control),"dr-browse-watch-product");
      control.dataset.savedKey=row.key;control.setAttribute("aria-pressed",String(this.watchlist.has(row.key)));return control;
    }
    async toggleWatch(row,control) {
      if(this.savedMutation||!this.active())return;
      const message=this.sheet.querySelector(".dr-browse-detail-message");
      const ready=await this.loadSaved();if(!this.active()||!control.isConnected)return;
      if(!ready){if(message)message.textContent="Not saved. Your account saves could not sync; please try again.";return;}
      const removing=this.watchlist.has(row.key);this.savedMutation=true;control.disabled=true;
      try{
        const data=await this.client.request("/api/v1/catalogue-browser/saved"+(removing?"/"+encodeURIComponent(row.key):""),removing?{method:"DELETE"}:{method:"PUT",body:JSON.stringify({key:row.key})});
        if(!this.active())return;
        if(!Array.isArray(data.keys))throw new Error("Save confirmation was incomplete.");
        this.watchlist=new Set(data.keys);if(message)message.textContent=removing?"Removed from saved references. Your collection is unchanged.":"Reference saved to your account. It has not been added to your collection.";
        if(removing&&this.filters.watch){
          this.rows=this.rows.filter(item=>this.watchlist.has(item.key));this.renderRows();
          if(!this.rows.length){this.find(".dr-browse-status").textContent="No saved references match this view.";this.renderEmptyActions();}
        }
      }catch(error){if(this.active()&&message)message.textContent="Not synced: "+error.message+" Try again.";}
      finally{if(this.active()){this.savedMutation=false;this.updateSavedControls();this.header();}}
    }
    async importDeviceSaved() {
      if(this.savedMutation||this.savedState!=="ready"||!this.deviceSaved.size||!this.active())return;
      this.savedMutation=true;this.renderSavedNote();
      try{
        const data=await this.client.request("/api/v1/catalogue-browser/saved/import",{method:"POST",body:JSON.stringify({keys:[...this.deviceSaved],confirmed:true})});
        if(!this.active())return;
        if(!Array.isArray(data.keys))throw new Error("Import confirmation was incomplete.");
        this.watchlist=new Set(data.keys);for(const key of data.keys)this.deviceSaved.delete(key);
        try{localStorage.setItem(this.storageKey,JSON.stringify([...this.deviceSaved]));}catch(_){/* Server receipt is authoritative; a repeat import is idempotent. */}
        this.savedImportMessage=(data.imported_count||0)+" references imported."+(this.deviceSaved.size?" Some older references are no longer available.":"");
        if(this.filters.watch)this.load();
      }catch(error){if(this.active())this.savedImportMessage="Import not completed: "+error.message;}
      finally{if(this.active()){this.savedMutation=false;this.updateSavedControls();this.header();}}
    }
    renderEmptyActions() {
      const actions=node("div","dr-browse-empty-actions");
      if(this.set||this.filters.language||this.filters.browse_group||this.filters.owned!=="all")actions.append(button("Clear refinements",()=>{this.clearCategoryFilters();this.load();},"dr-browse-empty-action"));
      if(this.filters.watch)actions.append(button("Browse catalogue",()=>{this.filters.watch=false;this.load();},"dr-browse-empty-action"));
      else if(["SPORTS","FIGURES"].includes(this.categoryId)){
        const context=node("p","dr-browse-manual-note","Enter your item’s details to add it to your collection.");
        actions.append(context,button(this.categoryId==="SPORTS"?"Add a sports card":"Add a figure",()=>this.openCollectibleIntake(),"dr-browse-empty-action"));
      }
      else if(this.isBookFamily())actions.append(button(this.categoryId==="MANGA"?"Add manga":"Add a comic",()=>this.openBookIntake(),"dr-browse-empty-action"));
      else {
        if(this.filters.system_code)actions.append(button("Search all games",()=>{this.filters.system_code="";this.filters.language="";this.set=null;this.filters.product_type||="CARD";this.load();},"dr-browse-empty-action"));
        actions.append(button("Scan this item",()=>this.scan(this.filters.product_type==="SEALED"?"SEALED":"RAW"),"dr-browse-empty-action"));
      }
      this.find(".dr-browse-content").append(actions);
    }
    collectibleReference(row) {
      const figure=row.product_type==="FIGURE"&&row.system_code==="FIGURES";
      const sports=row.product_type==="CARD"&&row.system_code==="SPORTS_CARDS";
      const details=figure?row.figure_details:sports?row.sports_card:null;
      if(!details||typeof details!=="object"||Array.isArray(details)||(details.system_code&&details.system_code!==row.system_code))return null;
      const fields=figure?[
        ["Manufacturer",details.manufacturer],["Franchise",details.franchise],["Character",details.character],
        ["Product line",details.product_line],["Edition",details.edition],["Scale",details.scale],
        ["Release year",details.release_year],["Manufacturer SKU",details.manufacturer_sku],["Barcode / JAN",details.barcode_gtin],
      ]:[
        ["Sport",details.sport],["League",details.league],["Player / subject",details.subject_name],["Team",details.team],
        ["Manufacturer",details.manufacturer],["Set",details.set_name],["Season",details.season],
        ["Release year",details.release_year],["Card number",details.card_number],["Parallel",details.parallel],
        ["Print run",details.print_run],["Language",displayLanguage(row)],
      ];
      const section=node("section","dr-browse-reference-edition"),facts=node("dl","dr-browse-reference-facts");
      facts.dataset.collectibleReference=figure?"figures":"sports";
      section.append(node("h4","",row.metadata_only?"Metadata reference":"Reference edition"),facts);
      for(const [label,value] of fields){
        const text=typeof value==="string"&&value.trim()&&value!=="Unknown"?decode(value):
          Number.isSafeInteger(value)&&value>0?String(value):"Not stated";
        facts.append(node("dt","",label),node("dd","",text));
      }
      return section;
    }
    sourceAttribution(row) {
      const source=row.source_attribution;
      if(!source||typeof source!=="object"||Array.isArray(source))return null;
      const section=node("section","dr-browse-reference-note dr-browse-source-attribution");
      const label=typeof source.label==="string"?source.label.trim().slice(0,160):"";
      const href=sourceLink(source.url);
      if(label){
        const credit=node("p","","Metadata source: ");
        if(href){const link=node("a","",label);link.href=href;link.target="_blank";link.rel="noopener noreferrer";credit.append(link);}
        else credit.append(document.createTextNode(label));
        section.append(credit);
      }
      if(typeof source.coverage==="string"&&source.coverage.trim())section.append(node("p","",source.coverage.trim().slice(0,1000)));
      if(row.metadata_only&&typeof row.details?.source_note==="string"&&row.details.source_note.trim())section.append(node("p","","Checklist note: "+row.details.source_note.trim().slice(0,256)));
      if(source.notice_url==="/assets/catalogue-source-notices.txt"){
        const notice=node("a","","Source notices and coverage");notice.href=source.notice_url;
        notice.target="_blank";notice.rel="noopener noreferrer";section.append(notice);
      }
      return section.childNodes.length?section:null;
    }
    openProduct(row) {
      this.lastProductKey=row.key;
      const pending=this.pending.get(row.key);
      if(pending?.requests?.length&&pending.requests.every(request=>request.result)){this.showAdded(pending);return;}
      if(row.product_type==="FIGURE"||row.system_code==="SPORTS_CARDS"){
        this.openSheet(row.product_type==="FIGURE"?"Figure details":"Sports card details");
        const content=node("div","dr-browse-product-details"),artwork=this.productImage(row,"dr-browse-detail-image");
        if(!artwork.querySelector("img"))artwork.classList.add("dr-browse-detail-no-art");
        content.append(artwork,node("h3","",decode(row.name)),
          node("p","",[decode(row.set_name),row.card_number,displayLanguage(row),
            row.metadata_only?printingMarker(row)||"Edition details need review":decode(row.variant)].filter(Boolean).join(" · ")));
        const reference=this.collectibleReference(row);if(reference)content.append(reference);
        const attribution=this.sourceAttribution(row);if(attribution)content.append(attribution);
        const pricing=node("section");this.renderMarketDetails(pricing,row);content.append(pricing,this.savedControl(row),
          node("p","dr-browse-reference-note",row.metadata_only||row.reference_verified===false
            ? "Metadata reference only, not a verified physical item. Confirm the exact edition or parallel and any missing details. Artwork, condition and market value are not verified."
            : "Check the exact edition and variant against your item. Your copy’s condition is confirmed separately."),node("p","dr-browse-detail-message"));
        const footer=node("footer");footer.append(button("Add to collection",()=>this.openCollectibleIntake(row),"dr-browse-primary"));this.sheet.append(content,footer);return;
      }
      if(row.product_type==="COMIC"){
        this.openSheet(row.system_code==="MANGA"||row.book_details?.system_code==="MANGA"?"Manga details":"Comic details");
        const content=node("div","dr-browse-product-details");
        const listingCredit=node("div","book-ebay-credit-slot"),artwork=this.productImage(row,"dr-browse-detail-image",listingCredit);
        content.append(artwork,listingCredit,
          node("h3","",decode(row.name)),
          node("p","",[decode(row.set_name),row.card_number,row.language,decode(row.variant)].filter(Boolean).join(" · ")));
        content.append(node("p","dr-browse-reference-note", row.market_value_minor == null
          ? row.book_market_status === "PRINTING_REVIEW_REQUIRED"
            ? "Market value pending: the printing and cover need confirmation before matching sold prices."
            : "Market value pending: at least five matching recent sales are needed for this printing."
          : money(row.market_value_minor) + " · " + row.basis_condition + " · UK sold reference"));
        content.append(node("p","dr-browse-reference-note","Check the cover and edition. Condition can wait until you’re ready to sell."));
        const sourceCredit=this.sourceAttribution(row);if(sourceCredit)content.append(sourceCredit);
        if(row.book_details?.barcode_gtin)content.append(node("p","dr-browse-reference-note","ISBN / barcode: "+row.book_details.barcode_gtin));
        const attribution=row.book_data_attribution;
        if(attribution && /^https:\/\/www\.comics\.org\/issue\/[1-9][0-9]*\/$/.test(attribution.source_url) && attribution.license_url === "https://creativecommons.org/licenses/by-sa/4.0/"){
          const credit=node("p","dr-browse-reference-note","Edition data adapted from ");
          const source=node("a","","Grand Comics Database"),license=node("a","","CC BY-SA 4.0");
          source.href=attribution.source_url;license.href=attribution.license_url;
          for(const link of [source,license]){link.target="_blank";link.rel="noopener noreferrer";}
          credit.append(source,document.createTextNode(" · "),license);content.append(credit);
        }
        if(attribution && /^https:\/\/openlibrary\.org\/books\/OL[1-9][0-9]*M$/.test(attribution.source_url)
          && attribution.license_url === "https://openlibrary.org/developers/licensing"){
          const credit=node("p","dr-browse-reference-note","Edition metadata from ");
          const source=node("a","","Open Library"),license=node("a","","Data licensing");
          source.href=attribution.source_url;license.href=attribution.license_url;
          for(const link of [source,license]){link.target="_blank";link.rel="noopener noreferrer";}
          credit.append(source,document.createTextNode(" · "),license);content.append(credit);
        }
        if(row.publisher_source_url && (/^https:\/\/(?:www\.viz\.com\/manga-books\/manga\/|www\.dc\.com\/(?:comics|graphic-novels)\/|www\.marvel\.com\/comics\/issue\/)[^?#]+$/.test(row.publisher_source_url)
          || /^https:\/\/prhcomics\.com\/book\/\?isbn=(?:[0-9]{13}|[0-9]{17})$/.test(row.publisher_source_url))){
          const source=node("a","dr-browse-publisher-source","View publisher details and cover ↗");
          source.href=row.publisher_source_url;source.target="_blank";source.rel="noopener noreferrer";content.append(source);
        }
        if(row.artwork_kind==="PUBLISHER_REFERENCE"){const note=node("p","dr-browse-reference-note","Publisher reference cover. Your copy's printing or cover may differ.");content.append(note);artwork.addEventListener("listing-photo-change",event=>{note.hidden=event.detail;});}
        const community=window.DropRateBookArtwork?.reference(row,true);
        if(community){const note=window.DropRateBookArtwork.credit(community,"dr-browse-reference-note");content.append(note);artwork.addEventListener("listing-photo-change",event=>{note.hidden=event.detail;});}
        if(row.book_sold_search_url?.startsWith("https://www.ebay.co.uk/sch/i.html?")){
          const sold=node("a","dr-browse-publisher-source","Compare sold listings on eBay UK ↗");
          sold.href=row.book_sold_search_url;sold.target="_blank";sold.rel="noopener noreferrer";content.append(sold);
        }
        const buttonRow=node("footer");
        content.append(this.savedControl(row),node("p","dr-browse-detail-message"));
        buttonRow.append(button("Add to collection",()=>this.openBookIntake(row),"dr-browse-primary"));
        const contextPanel=node("section");
        if(window.DropRateBookEbay?.identity(row))content.append(contextPanel);
        this.sheet.append(content,buttonRow);
        const detailEpoch=this.bookDetailEpoch;
        this.stopBookDetail=this.watchBookContext(row,contextPanel,contextPanel,artwork,{detail:true,
          current:()=>this.bookDetailEpoch===detailEpoch && !this.find(".dr-browse-backdrop").hidden});
        return;
      }
      this.openSheet("Is this your item?");
      let edit=this.pending.get(row.key);
      if(!edit){edit={row,condition:"",language:"",quantity:1,confirmed:false,requests:null};this.pending.set(row.key,edit);}
      this.edit=edit;
      const content=node("div","dr-browse-product-details");
      content.append(this.productImage(row,"dr-browse-detail-image"),node("h3","",decode(row.name)),node("p","",[decode(row.set_name),row.card_number,row.language,printingMarker(row)||decode(row.variant)].filter(Boolean).join(" · ")));
      if(row.provider&&row.provider_id){
        const reference=node("details","dr-browse-reference-note dr-browse-extra");reference.dataset.cardReference=row.key;reference.append(node("summary","","Reference details"));
        reference.append(node("strong","","Card reference"),node("p","",row.provider+" · "+row.provider_id),node("small","","Set reference: "+row.set_id+" · "+row.language));
        content.append(reference);
      }
      const attribution=this.sourceAttribution(row);if(attribution)content.append(attribution);
      const pricing=node("div");pricing.dataset.marketDetails=row.key;this.renderMarketDetails(pricing,row);content.append(pricing);
      content.append(this.savedControl(row));
      if(row.source_kind==="REFERENCE")content.append(node("p","dr-browse-reference-note",row.metadata_only
        ? "Metadata reference only. Artwork and market value are not verified. Check the exact edition, finish and language against your physical item."
        : "Check that the picture, edition and language match your item."));
      if(row.source_kind==='SEALED_REFERENCE')content.append(node('p','dr-browse-reference-note','Check the packaging, edition, pack count and language. Add only if your product is still sealed.'));
      if(row.source_kind==="SEALED_REFERENCE"&&row.provider==="Kayou Official"
         && /^https:\/\/www\.kayouofficial\.com\/en-US\/series\/series-[a-z0-9]{8}$/.test(row.source_url||"")){
        const source=node("a","dr-browse-publisher-source","See official Kayou product details ↗");
        source.href=row.source_url;source.target="_blank";source.rel="noopener noreferrer";
        content.append(source);
      }
      const optional=node("details","dr-browse-extra dr-browse-copy-details");optional.append(node("summary","","Quantity & condition (optional)"));
      const fields=node("div","dr-browse-physical");
      if(row.product_type==='SEALED' && row.language==='Unknown'){
        const label=node('label','','Product language'),select=node('select');select.setAttribute('aria-label','Product language');
        for(const language of ['','English','Japanese','Chinese','Korean','French','German','Italian','Spanish']){const option=node('option','',language||'Choose language');option.value=language;select.append(option);}
        select.value=edit.language;select.disabled=Boolean(edit.requests);
        select.addEventListener('change',()=>{edit.language=select.value;this.validateAdd();});label.append(select);content.append(label);
      }
      const conditionLabel=node("label","",row.product_type==="SEALED"?"Seal status":"Condition"),condition=node("select");
      for(const label of row.product_type==="SEALED"?["Sealed"]:["Not assessed yet",...conditions]){const option=node("option","",label);option.value=label==="Not assessed yet"?"":label;condition.append(option);}
      condition.value=row.product_type==="SEALED"?"Sealed":edit.condition;condition.setAttribute("aria-label","Condition");condition.disabled=Boolean(edit.requests)||row.product_type==="SEALED";
      condition.addEventListener("change",()=>{edit.condition=condition.value;this.validateAdd();});conditionLabel.append(condition);
      const quantityLabel=node("label","","Quantity"),quantity=node("input");quantity.type="number";quantity.min="1";quantity.max="50";quantity.step="1";quantity.inputMode="numeric";quantity.value=edit.quantity;quantity.setAttribute("aria-label","Quantity");quantity.disabled=Boolean(edit.requests);
      quantity.addEventListener("input",()=>{edit.quantity=Number(quantity.value);this.validateAdd();});quantityLabel.append(quantity);fields.append(conditionLabel,quantityLabel);optional.append(fields);content.append(optional);
      content.append(node("p","dr-browse-confirm-note",row.product_type==="SEALED"
        ? "Add confirms this is your sealed product."
        : "Add confirms this is the item you own. Condition can wait."));
      if(row.product_type==="CARD")content.append(button("Adding a graded slab?",()=>{this.closeSheet();this.close();this.options.graded(row);},"dr-browse-graded-link"));
      content.append(node("p","dr-browse-detail-message",edit.error||""));this.sheet.append(content);
      const footer=node("footer"),save=button("Add to collection",()=>this.save(),"dr-browse-primary");save.dataset.add="true";footer.append(save);this.sheet.append(footer);this.validateAdd();
    }
    showAdded(edit) {
      this.edit=edit;this.openSheet("Added to your collection");
      if(!edit.ownedUpdated){
        this.rows=this.rows.map(row=>row.key===edit.row.key?{...row,owned_quantity:(row.owned_quantity||0)+edit.quantity}:row);
        edit.ownedUpdated=true;
      }
      const content=node("div","dr-browse-product-details dr-browse-added");
      content.append(node("span","dr-browse-success-mark","✓"),node("h3","",decode(edit.row.name)),
        node("p","",edit.quantity+" "+(edit.quantity===1?"copy":"copies")+" added. Your item is in your personal collection."));
      if(edit.error?.includes("Refresh your collection"))content.append(node("p","dr-browse-detail-message",edit.error));
      const receipt=edit.requests[0].result,footer=node("footer");
      const finish=()=>{this.pending.delete(edit.row.key);this.edit=null;const top=this.scroll.scrollTop;this.closeSheet();if(this.rows.length)this.renderRows();this.scroll.scrollTop=top;};
      const viewItem=button(edit.quantity===1?"View item":"View collection",async()=>{
        finish();this.close();
        if(edit.quantity===1&&this.options.viewItem)await this.options.viewItem(receipt);
        else if(this.options.viewCollection)this.options.viewCollection();else this.options.navigate("inventory");
      },"dr-browse-primary");viewItem.dataset.addedAction="view";
      const another=button("Add another",()=>{finish();this.input.focus({preventScroll:true});this.input.select();},"dr-browse-secondary");another.dataset.addedAction="another";
      footer.append(viewItem,another);this.sheet.append(content,footer);
    }
    validateAdd() { const edit=this.edit;if(!edit)return;const done=edit.requests?.every(request=>request.result);
      const save=this.sheet.querySelector("[data-add]");if(!save)return;
      save.textContent=this.saving?"Adding…":done?"Done":edit.requests?"Retry remaining saves":"Add to collection";
      save.disabled=this.saving||(!edit.requests&&(!Number.isInteger(edit.quantity)||edit.quantity<1||edit.quantity>50||(edit.row.product_type!=="SEALED"&&edit.condition&&!conditions.includes(edit.condition))||(edit.row.product_type==='SEALED'&&edit.row.language==='Unknown'&&!edit.language))); }
    async save() {
      const edit=this.edit;if(!edit||this.saving||this.sheet.querySelector("[data-add]")?.disabled||!this.active())return;
      if(edit.requests?.every(request=>request.result)){this.pending.delete(edit.row.key);this.edit=null;this.closeSheet();this.load();return;}
      if(!edit.requests){edit.confirmed=true;const body=JSON.stringify({key:edit.row.key,condition:edit.row.product_type==="SEALED"?null:edit.condition||null,seal_status:edit.row.product_type==="SEALED"?"SEALED":null,confirmed:true,...(edit.row.product_type==='SEALED'&&edit.row.language==='Unknown'?{language:edit.language}:{})});
        edit.requests=Array.from({length:edit.quantity},()=>({key:crypto.randomUUID(),body,result:null}));}
      this.saving=true;this.sheet.querySelectorAll("button,input,select").forEach(control=>{control.disabled=true;});this.validateAdd();
      try {
        for(const request of edit.requests){if(request.result)continue;
          const result=await this.client.request("/api/v1/catalogue-browser/intake",{method:"POST",headers:{"Idempotency-Key":request.key},body:request.body});
          if(!result.inventory?.inventory_code)throw new Error("Save confirmation was incomplete. Retry this same addition.");request.result=result;this.pageCache.clear();}
        edit.error=edit.quantity+" added to your collection.";
        try{await this.options.afterSave();}catch(_){edit.error+=" Refresh your collection to update totals.";}
      }catch(error){if(this.active())edit.error=error.message+" Retry to finish adding these copies.";}
      finally{if(this.active()){this.saving=false;this.openProduct(edit.row);}}
    }
  }
  return {Browser};
})();

