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
  const w = dom.window, calls = [], bookIntakes = [];
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.eval(fs.readFileSync(path.join(root,"backend/app/static/reference-value-display.js"),"utf8"));
  w.eval(source);
  const client={owner:"fixture-owner",active:()=>true,request:async(url,options={})=>{
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
  const browser=new w.DropRateCatalogue.Browser({client,navigate:()=>{},scan:()=>{},graded:()=>{},books:options=>bookIntakes.push(options),afterSave:async()=>{}});
  const lastQuery=()=>new URL(calls.at(-1).url,"https://categories.example.test").searchParams;
  const choose=async id=>{browser.find(`[data-category="${id}"]`).click();await tick();};
  const search=async query=>{
    browser.input.value=query;
    browser.input.dispatchEvent(new w.Event("input",{bubbles:true}));
    browser.input.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true}));
    await tick();
  };
  return {browser,w,calls,bookIntakes,lastQuery,choose,search,finish:()=>{browser.destroy();w.close();}};
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
  // Unsupported catalogues have a clear empty state, not manufactured records,
  // unsupported API filters or an unscoped fallback to TCG products.
  {
    const f=fixture();await f.browser.open();await f.search("Pikachu");
    for(const id of ["SPORTS","FIGURES"]){
      const count=f.calls.length;await f.choose(id);
      assert.equal(f.calls.length,count);assert.equal(f.browser.input.disabled,true);
      assert.equal(f.browser.find(".dr-browse-searchbar").hidden,true);
      assert.match(f.browser.find(".dr-browse-content").textContent,/Catalogue unavailable/);
      assert.equal(f.browser.find(".dr-browse-product"),null);
      await f.browser.load();assert.equal(f.calls.length,count);
    }
    await f.choose("TCG");assert.equal(f.browser.input.disabled,false);
    assert.equal(f.browser.input.value,"Pikachu");assert.equal(f.lastQuery().get("product_type"),"CARD");
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
  console.log(`Catalogue categories: ${checks} interaction groups passed (real-card search, Enter/IME, scoped formats, exact intake, category navigation, empty Manga intake, unavailable catalogues and stale responses).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
