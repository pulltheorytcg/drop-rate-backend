"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM} = require("jsdom");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "backend/app/static/catalogue-browser.js"), "utf8");
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve}; };
const games = [
  {system_code:"POKEMON_TCG",game:"Pokémon",languages:["English","Japanese"]},
  {system_code:"ONE_PIECE_CARD_GAME",game:"One Piece",languages:["English","Japanese"]},
  {system_code:"COMICS",game:"Comics",languages:["English"]},
  {system_code:"MANGA",game:"Manga",languages:["English","Japanese"]},
];
const card = {key:"c:00000000-0000-4000-8000-000000000001",catalogue_id:"exact-card",name:"Pikachu",game:"Pokémon",system_code:"POKEMON_TCG",set_id:"base1",set_name:"Base Set",card_number:"58/102",language:"English",variant:"Normal",product_type:"CARD",owned_quantity:0,market_value_minor:null,source_kind:"CATALOGUE"};
const comic = {...card,key:"c:00000000-0000-4000-8000-000000000002",catalogue_id:"exact-comic",name:"Batman #1",system_code:"DC_COMICS",game:"Comics",product_type:"COMIC",book_details:{system_code:"DC_COMICS",series_title:"Batman",issue_number:"1"}};
const manga = {...card,key:"c:00000000-0000-4000-8000-000000000003",catalogue_id:"exact-manga",name:"One Piece Volume 1",system_code:"MANGA",game:"Manga",product_type:"COMIC",book_details:{system_code:"MANGA",series_title:"One Piece",issue_number:"1",barcode_gtin:"9781569319017"}};

function fixture(override) {
  const dom = new JSDOM("", {runScripts:"outside-only",url:"https://categories.example.test"});
  const w = dom.window, calls = [], bookIntakes = [], collectibleIntakes=[];
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.eval(fs.readFileSync(path.join(root,"backend/app/static/reference-value-display.js"),"utf8"));
  w.eval(source);
  const client={owner:"fixture-owner",active:()=>true,request:async(url,options={})=>{
    if(url.includes("/catalogue-browser/saved"))return {keys:[]};
    calls.push({url,...options});
    if(url.endsWith("/games"))return {items:games};
    if(url.endsWith("/intake"))return {inventory:{inventory_code:"INV-FIXTURE-1"}};
    const query=new URL(url,"https://categories.example.test").searchParams;
    const response=override?.(url,query,options);
    if(response!==undefined)return response;
    if(url.includes("/sets?"))return {items:[],has_more:false};
    const row=query.get("system_code")==="MANGA"?manga:query.get("system_code")==="COMICS"?comic:
      query.get("product_type")==="SEALED"?{...card,product_type:"SEALED",name:"Pokémon sealed box"}:card;
    return {items:[row],has_more:false};
  }};
  const browser=new w.DropRateCatalogue.Browser({client,navigate:()=>{},scan:()=>{},graded:()=>{},books:options=>bookIntakes.push(options),collectibles:options=>collectibleIntakes.push(options),afterSave:async()=>{}});
  const lastQuery=()=>new URL(calls.at(-1).url,"https://categories.example.test").searchParams;
  const choose=async id=>{browser.find(`[data-category="${id}"]`).click();await tick();};
  const search=async query=>{
    browser.input.value=query;
    browser.input.dispatchEvent(new w.Event("input",{bubbles:true}));
    browser.input.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true}));
    await tick();
  };
  return {browser,w,calls,bookIntakes,collectibleIntakes,lastQuery,choose,search,finish:()=>{browser.destroy();w.close();}};
}

(async()=>{
  let checks=0;
  // A typed query searches actual cards before choosing any game. Enter also
  // cancels the debounce, so the same keystrokes do not duplicate a request.
  {
    const f=fixture();await f.browser.open();
    assert.deepEqual([...f.browser.dialog.querySelectorAll(".dr-browse-categories button")].map(n=>n.getAttribute("aria-label")),["Trading Card Games","Sports Cards","Comics","Manga","Figures"]);
    assert.equal(f.browser.find('[data-category="TCG"]').getAttribute("aria-pressed"),"true");
    assert.deepEqual([...f.browser.dialog.querySelectorAll(".dr-browse-game")].map(n=>n.dataset.system),["POKEMON_TCG","ONE_PIECE_CARD_GAME"]);
    assert.equal(f.calls.length,1);
    await f.search("Pikachu");
    assert.equal(f.lastQuery().get("q"),"Pikachu");
    assert.equal(f.lastQuery().get("product_type"),"CARD");
    assert.equal(f.lastQuery().get("system_code"),null);
    assert.match(f.browser.find(".dr-browse-content").textContent,/Pikachu/);
    const count=f.calls.length;await new Promise(resolve=>setTimeout(resolve,300));assert.equal(f.calls.length,count);
    f.browser.find(".dr-browse-product-open").click();
    assert.match(f.browser.sheet.textContent,/58\/102.*English/);
    assert.match(f.browser.sheet.textContent,/Value unavailable/);
    f.browser.sheet.querySelector("[data-add]").click();await tick();
    const save=f.calls.find(call=>call.method==="POST"),body=JSON.parse(save.body);
    assert.equal(body.key,card.key);assert.equal(body.confirmed,true);
    assert.equal(body.owner_id,undefined);assert.equal(body.market_value_minor,undefined);
    assert.ok(save.headers["Idempotency-Key"]);
    f.finish();checks++;
  }
  // Confirming an IME candidate is not a search submission. This protects
  // Japanese/Korean typing; a later normal Enter still searches the final text.
  {
    const f=fixture();await f.browser.open();f.browser.input.value="ピカチュウ";
    const count=f.calls.length;
    for(const options of [{isComposing:true},{keyCode:229}]){
      const enter=new f.w.KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true,...options});
      f.browser.input.dispatchEvent(enter);await tick();
      assert.equal(enter.defaultPrevented,false);assert.equal(f.calls.length,count);
    }
    f.browser.input.dispatchEvent(new f.w.KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true}));await tick();
    assert.equal(f.lastQuery().get("q"),"ピカチュウ");assert.equal(f.lastQuery().get("product_type"),"CARD");
    f.finish();checks++;
  }
  // Card and sealed queries retain their format; game selection narrows by an
  // existing exact system, and All games removes set/language/provider scope.
  {
    const f=fixture();await f.browser.open();await f.search("Pikachu");
    f.browser.find('[data-type="SEALED"]').click();await tick();
    assert.equal(f.lastQuery().get("product_type"),"SEALED");assert.equal(f.lastQuery().get("q"),"Pikachu");
    f.browser.reset();await tick();
    f.browser.find('[data-system="POKEMON_TCG"]').click();await tick();
    assert.equal(f.lastQuery().get("system_code"),"POKEMON_TCG");assert.equal(f.lastQuery().get("product_type"),null);
    f.browser.filters.language="Japanese";f.browser.set={system_code:"POKEMON_TCG",set_id:"base1",provider:"TCGdex"};
    f.browser.find('[data-action="games"]').click();await tick();
    assert.equal(f.browser.filters.system_code,"");assert.equal(f.browser.filters.language,"");assert.equal(f.browser.set,null);
    assert.equal(f.browser.filters.product_type,"CARD");assert.ok(f.browser.find(".dr-browse-game-grid"));
    f.finish();checks++;
  }
  // Category changes preserve the user's product query while discarding the
  // previous game's filters. Comics and manga never borrow each other's scope.
  {
    const f=fixture();await f.browser.open();await f.search("One Piece");
    f.browser.filters.language="Japanese";f.browser.set={system_code:"ONE_PIECE_CARD_GAME",set_id:"OP11",provider:"Punk Records"};
    await f.choose("COMICS");
    assert.equal(f.lastQuery().get("system_code"),"COMICS");assert.equal(f.lastQuery().get("product_type"),"COMIC");
    assert.equal(f.lastQuery().get("q"),"One Piece");assert.equal(f.lastQuery().get("language"),null);
    assert.equal(f.lastQuery().get("provider"),null);assert.equal(f.lastQuery().get("set_id"),null);
    assert.equal(f.browser.find(".dr-browse-types").hidden,true);
    await f.choose("MANGA");
    assert.equal(f.lastQuery().get("system_code"),"MANGA");assert.equal(f.lastQuery().get("product_type"),"COMIC");
    assert.equal(f.browser.input.value,"One Piece");
    f.browser.find(".dr-browse-product-open").click();
    assert.match(f.browser.sheet.textContent,/Manga details/);
    [...f.browser.sheet.querySelectorAll("button")].find(n=>n.textContent==="Add to collection").click();await tick();
    assert.equal(f.bookIntakes[0].catalogue.key,manga.key);
    assert.equal(f.bookIntakes[0].book.barcode_gtin,"9781569319017");
    assert.equal(f.calls.filter(call=>call.method==="POST").length,0);
    f.finish();checks++;
  }
  // Clearing manga filters stays in manga, including its existing COMIC API
  // format. Set navigation also retains that format on return to products.
  {
    const f=fixture();await f.browser.open();await f.choose("MANGA");
    f.browser.openFilters();
    assert.doesNotMatch(f.browser.sheet.textContent,/Cards Only|Sealed Only/);
    [...f.browser.sheet.querySelectorAll("button")].find(n=>n.textContent==="Clear filters").click();await tick();
    assert.equal(f.browser.categoryId,"MANGA");assert.equal(f.lastQuery().get("system_code"),"MANGA");
    assert.equal(f.lastQuery().get("product_type"),"COMIC");
    f.browser.showSets();await tick();assert.equal(f.lastQuery().get("system_code"),"MANGA");
    f.browser.back();await tick();assert.equal(f.lastQuery().get("product_type"),"COMIC");
    f.finish();checks++;
  }
  // Newly supported categories use explicit API scopes and offer honest manual
  // entry when no verified catalogue reference matches the retained query.
  {
    const f=fixture((_url,query)=>["SPORTS","FIGURES"].includes(query.get("category"))?{items:[],has_more:false}:undefined);await f.browser.open();await f.search("Michael Jordan");
    for(const [id,system,type,label] of [["SPORTS","SPORTS_CARDS","CARD","Add a sports card"],["FIGURES","FIGURES","FIGURE","Add a figure"]]){
      await f.choose(id);assert.equal(f.browser.input.disabled,false);
      assert.equal(f.browser.find(".dr-browse-searchbar").hidden,false);
      assert.equal(f.lastQuery().get("category"),id);assert.equal(f.lastQuery().get("system_code"),system);assert.equal(f.lastQuery().get("product_type"),type);
      assert.equal(f.lastQuery().get("q"),"Michael Jordan");assert.equal(f.browser.find('[data-action="sets"]').hidden,true);
      assert.equal(f.browser.find(".dr-browse-product"),null);
      [...f.browser.find(".dr-browse-content").querySelectorAll("button")].find(button=>button.textContent===label).click();
      assert.equal(f.collectibleIntakes.at(-1).category,id.toLowerCase());assert.equal(f.collectibleIntakes.at(-1).query,"Michael Jordan");assert.equal(f.collectibleIntakes.at(-1).catalogue,undefined);
      assert.equal(f.calls.filter(call=>call.method==="POST").length,0);await f.browser.open();
    }
    await f.choose("TCG");assert.equal(f.browser.input.disabled,false);
    assert.equal(f.browser.input.value,"Michael Jordan");assert.equal(f.lastQuery().get("product_type"),"CARD");assert.equal(f.lastQuery().get("category"),"TCG");
    f.finish();checks++;
  }
  // A late previous-category request cannot replace newer results, even when
  // the underlying mock ignores the aborted signal.
  {
    const pending=deferred();
    const f=fixture((_url,query)=>query.get("system_code")==="COMICS"?pending.promise:undefined);
    await f.browser.open();await f.choose("COMICS");
    const old=f.calls.at(-1);await f.choose("MANGA");assert.equal(old.signal.aborted,true);
    pending.resolve({items:[comic],has_more:false});await tick();
    assert.match(f.browser.find(".dr-browse-content").textContent,/One Piece Volume 1/);
    assert.doesNotMatch(f.browser.find(".dr-browse-content").textContent,/Batman/);
    assert.equal(f.browser.categoryId,"MANGA");f.finish();checks++;
  }
  // Exact sports/figure references use their purpose-built copy intake, never
  // the TCG scanner or a blind generic card save.
  {
    const f=fixture();await f.browser.open();
    for(const [system,kind,category] of [["SPORTS_CARDS","CARD","sports"],["FIGURES","FIGURE","figures"]]){
      const row={...card,system_code:system,product_type:kind,name:category==="sports"?"Michael Jordan — 1991 card":"Luffy figure"};
      f.browser.openProduct(row);assert.match(f.browser.sheet.textContent,kind==="FIGURE"?/Figure details/:/Sports card details/);
      [...f.browser.sheet.querySelectorAll("button")].find(button=>button.textContent==="Add to collection").click();
      assert.equal(f.collectibleIntakes.at(-1).category,category);assert.equal(f.collectibleIntakes.at(-1).catalogue,row);
      assert.equal(f.calls.filter(call=>call.method==="POST").length,0);await f.browser.open();
    }
    f.finish();checks++;
  }
  // The empty-state action opens the real intake form in Manga mode without
  // inventing an edition, language, value or publisher. Exact rows still win.
  {
    const f=fixture(()=>({items:[],has_more:false}));
    f.w.eval('window.state={session:{user:{id:"fixture-owner"}}}; window.bookApiCalls=[]; async function apiRequest(url,options){bookApiCalls.push({url,options});return {status:"UNAVAILABLE"};} async function loadOwnerInventory(){} async function loadOwnerOverview(){}');
    f.w.eval(fs.readFileSync(path.join(root,"backend/app/static/owner-books.js"),"utf8"));
    f.browser.options.books=options=>f.w.DropRateBooks.open(options);
    await f.browser.open();await f.choose("MANGA");
    [...f.browser.find(".dr-browse-content").querySelectorAll("button")].find(n=>n.textContent==="Add manga").click();await tick();
    const doc=f.w.document;
    assert.equal(doc.getElementById("owner-book-category").value,"MANGA");
    assert.equal(doc.getElementById("owner-book-number-text").textContent,"Volume number");
    assert.equal(doc.getElementById("owner-book-title").textContent,"Add manga");
    assert.equal(doc.getElementById("owner-book-format-label").hidden,true);
    assert.equal(doc.getElementById("owner-book-publisher").required,true);
    assert.equal(doc.getElementById("owner-book-series").value,"");
    assert.equal(doc.getElementById("owner-book-selected").hidden,true);
    assert.equal(f.w.bookApiCalls.length,0);
    f.w.DropRateBooks.open({category:"MANGA",book:comic.book_details,catalogue:comic});
    assert.equal(doc.getElementById("owner-book-category").value,"DC_COMICS");
    assert.equal(doc.getElementById("owner-book-number-text").textContent,"Issue / book number");
    assert.match(doc.getElementById("owner-book-selected").textContent,/Batman #1/);
    f.w.DropRateBooks.reset();f.finish();checks++;
  }
  // Typed official edition facts remain visible before copy intake. Only the
  // explicit reference fields render; private provenance and HTML stay inert.
  {
    const f=fixture();await f.browser.open();
    const seeds=JSON.parse(fs.readFileSync(path.join(root,"backend/data/collectible_catalogue_starter_20261103.json"),"utf8")).entries;
    for(const seed of [seeds[0],seeds[5]]){
      const field=seed.sports_card?"sports_card":"figure_details",category=seed.sports_card?"sports":"figures";
      const row={...seed.catalogue,key:"c:"+seed.id,catalogue_id:seed.id,system_code:seed[field].system_code,
        [field]:{...seed[field],submitted_by_user_id:"private-user",source_url:"https://private.test/hidden"}};
      f.browser.openProduct(row);
      const facts=f.browser.sheet.querySelector(`[data-collectible-reference="${category}"]`);
      assert.ok(facts);
      assert.ok(f.browser.sheet.querySelector(".dr-browse-detail-no-art"));
      const values=Object.fromEntries([...facts.querySelectorAll("dt")].map(dt=>[dt.textContent,dt.nextElementSibling.textContent]));
      if(category==="sports"){
        assert.equal(values.Sport,"Football");assert.equal(values.Team,"Arsenal");assert.equal(values.Season,"2025/26");
        assert.equal(values["Card number"],"12");assert.equal(values.Parallel,"Base");assert.equal(values["Print run"],"Not stated");
      }else{
        assert.equal(values.Franchise,"Character Vocal Series 01: Hatsune Miku");assert.equal(values.Edition,"3.0 [Basic]");
        assert.equal(values["Barcode / JAN"],"4580828662797");assert.equal(values["Manufacturer SKU"],"Not stated");
      }
      assert.doesNotMatch(facts.textContent,/private-user|private\.test|submitted_by/);
      [...f.browser.sheet.querySelectorAll("button")].find(button=>button.textContent==="Add to collection").click();
      assert.equal(f.collectibleIntakes.at(-1).catalogue,row);await f.browser.open();
    }
    const row={...card,system_code:"SPORTS_CARDS",sports_card:{system_code:"SPORTS_CARDS",subject_name:'<img src=x onerror="alert(1)">',team:"Test"}};
    f.browser.openProduct(row);const facts=f.browser.sheet.querySelector("[data-collectible-reference]");
    assert.match(facts.textContent,/<img/);assert.equal(facts.querySelector("img"),null);
    f.browser.openProduct({...row,sports_card:{...row.sports_card,system_code:"FIGURES"}});
    assert.equal(f.browser.sheet.querySelector("[data-collectible-reference]"),null);
    f.finish();checks++;
  }
  console.log(`Catalogue categories: ${checks} interaction groups passed (real-card search, Enter/IME, scoped formats, exact intake, category navigation, empty Manga intake, sports/figure manual recovery and stale responses).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
