"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM, VirtualConsole} = require("jsdom");
const source = fs.readFileSync(path.join(__dirname, "../../backend/app/static/owner-collectibles.js"), "utf8");
const result = {catalogue: {name: "Fixture collectible"}, inventory: {id: "fixture-copy", inventory_code: "INV-FIXTURE"}};
const sports = {sport: "Basketball", release_year: "2024", manufacturer: "Fixture Cards", set_name: "Chrome",
  subject_name: "Fixture Player", card_number: "23", parallel: "Blue", language: "English"};
const figure = {manufacturer: "Fixture Maker", franchise: "Fixture World", character: "Fixture Character", product_line: "Collector Line", edition: "First edition"};

async function settle(predicate) {
  for (let i = 0; i < 50; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 0)); }
  assert.fail("Collectible flow did not reach the expected state");
}
function mount({seller = true, responses = []} = {}) {
  const errors = [], virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", error => errors.push(error.message));
  const dom = new JSDOM(`<body>${seller ? '<section id="owner-view-scan"></section>' : ''}</body>`, {url:"https://hub.example.test/owner", runScripts:"outside-only", virtualConsole});
  const w = dom.window, calls = [], changes = [], opened = [], views = [];
  let keys = 0;
  w.crypto.randomUUID = () => `00000000-0000-4000-8000-${String(++keys).padStart(12,"0")}`;
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new w.Event("close")); };
  w.state = {session: {user: {id:"collector-a"}, access_token:"fixture-token"}};
  w.apiRequest = async (url, options) => {
    calls.push({url, ...options});
    const response = responses.shift();
    if (typeof response === "function") return response();
    if (response instanceof Error) throw response;
    return response || result;
  };
  w.activateOwnerView = view => views.push(view); w.activateSellerView = view => views.push(view);
  w.document.addEventListener("owner-inventory-changed", event => changes.push(event.detail));
  w.document.addEventListener("hub:inventory-open", event => opened.push(event.detail));
  w.eval(source);
  const node = id => w.document.getElementById("owner-collectible-"+id);
  const fill = (kind, values) => Object.entries(values).forEach(([key, value]) => { node(kind+"-"+key).value=value; });
  return {w, calls, changes, opened, views, node, fill, open: options => w.DropRateCollectibles.open(options),
    submit: () => node("form").dispatchEvent(new w.Event("submit", {bubbles:true,cancelable:true})),
    close() { assert.deepEqual(errors, []); w.close(); }};
}

(async () => {
  let groups = 0;
  {
    const f = mount();
    assert.equal(f.w.DropRateCollectibles, f.w.DropRateOwnerCollectibles);
    assert.equal(f.open({category:"sports", query:"Search player"}), true);
    assert.equal(f.calls.length,0); assert.equal(f.node("sports-subject_name").value,"Search player");
    assert.equal(f.node("sports-language").value, "");
    f.submit(); assert.equal(f.calls.length,0);
    f.fill("sports",sports); f.node("serial").value="12/99"; f.submit(); f.submit();
    await settle(() => !f.node("success").hidden);
    assert.equal(f.calls.length,1); assert.equal(f.calls[0].url,"/api/v1/owner/collectibles/intake");
    const data=JSON.parse(f.calls[0].body);
    assert.equal(data.category,"SPORTS"); assert.equal(data.copy_serial_number,"12/99");
    assert.equal(data.new_catalogue.sports_card.subject_name,"Fixture Player");
    assert.equal(data.new_catalogue.sports_card.print_run,null); assert.equal(data.condition,null);
    assert.equal(data.new_catalogue.language,"English"); assert.ok(!("store_price_minor" in data));
    assert.equal(data.new_catalogue.sports_card.language,undefined);
    assert.equal(f.changes.length,1); assert.equal(f.changes[0].actorId,"collector-a");
    f.node("view").click(); assert.deepEqual(f.views,["inventory"]); assert.equal(f.opened[0].inventoryId,"fixture-copy");
    f.close(); groups++;
  }
  {
    const f=mount({seller:false}); f.open({category:"figures"}); f.fill("figures",figure);
    assert.equal(f.node("sports").disabled,true); assert.equal(f.node("grading").disabled,true);
    assert.deepEqual(Array.from(f.node("condition").options, o=>o.value),["","New","Like New","Very Good","Good","Fair","Damaged"]);
    f.node("condition").value="Like New"; f.node("seal").value="UNSEALED"; f.submit();
    await settle(()=>!f.node("success").hidden);
    const data=JSON.parse(f.calls[0].body);
    assert.equal(f.calls[0].url,"/api/v1/inventory/collectibles/intake");
    assert.equal(data.new_catalogue.product_type,"FIGURE"); assert.equal(data.new_catalogue.figure_details.scale,null);
    assert.equal(data.new_catalogue.language,undefined); assert.equal(data.grading_company,null);
    assert.equal(data.condition,"Like New"); assert.equal(data.seal_status,"UNSEALED");
    f.node("add-another").click(); assert.equal(f.node("category").value,"figures"); assert.equal(f.node("figures-character").value,"");
    f.close(); groups++;
  }
  {
    const f=mount(); const id="00000000-0000-4000-8000-000000000020";
    f.open({category:"figures",catalogue:{catalogue_id:id,name:"<img src=x onerror=alert(1)>",set_name:"Fixture Line"}});
    assert.equal(f.node("reference-name").textContent,"<img src=x onerror=alert(1)>");
    assert.equal(f.node("reference-name").querySelector("img"),null);
    assert.equal(f.node("figures").disabled,true); assert.equal(f.node("sports").disabled,true);
    f.submit(); await settle(()=>!f.node("success").hidden);
    const data=JSON.parse(f.calls[0].body); assert.equal(data.catalogue_id,id); assert.equal(data.new_catalogue,undefined);
    f.close(); groups++;
  }
  {
    const f=mount(); f.open({category:"figures"}); f.fill("figures",figure);
    f.node("figures-barcode_gtin").value="123"; f.submit();
    assert.equal(f.calls.length,0); assert.match(f.node("figures-barcode_gtin").validationMessage,/8, 12, 13 or 14/);
    assert.equal(f.node("figures-barcode_gtin").closest("details").open,true);
    f.node("figures-barcode_gtin").value="123-4567 890123";
    f.node("figures-barcode_gtin").dispatchEvent(new f.w.Event("input",{bubbles:true}));
    assert.equal(f.node("figures-barcode_gtin").validationMessage,"");
    f.submit(); await settle(()=>!f.node("success").hidden);
    assert.equal(f.calls.length,1); f.close(); groups++;
  }
  {
    const f=mount({responses:[new TypeError("fixture connection lost"),result]});
    f.open({category:"sports"}); f.fill("sports",sports); f.submit();
    await settle(()=>f.node("save").textContent==="Retry this item");
    assert.equal(f.node("fields").disabled,true); assert.equal(f.changes.length,0);
    f.node("cancel").click(); f.open({category:"figures"});
    assert.equal(f.node("category").value,"sports"); assert.match(f.node("message").textContent,/previous save/);
    f.submit(); await settle(()=>!f.node("success").hidden);
    assert.equal(f.calls.length,2); assert.equal(f.calls[0].body,f.calls[1].body);
    assert.equal(f.calls[0].headers["Idempotency-Key"],f.calls[1].headers["Idempotency-Key"]);
    f.close(); groups++;
  }
  {
    const invalid=Object.assign(new Error("Check the edition"),{status:422});
    const f=mount({responses:[invalid,result]}); f.open({category:"figures"}); f.fill("figures",figure); f.submit();
    await settle(()=>f.node("message").textContent==="Check the edition");
    assert.equal(f.node("fields").disabled,false); f.node("figures-edition").value="Second edition"; f.submit();
    await settle(()=>!f.node("success").hidden);
    assert.notEqual(f.calls[0].headers["Idempotency-Key"],f.calls[1].headers["Idempotency-Key"]);
    f.close(); groups++;
  }
  {
    let resolve; const f=mount({responses:[()=>new Promise(done=>{resolve=done;})]});
    f.open({category:"sports"}); f.fill("sports",sports); f.node("notes").value="Private collector note"; f.submit();
    await settle(()=>typeof resolve==="function");
    f.w.state.session=null; f.w.dispatchEvent(new f.w.Event("hub-session-cleared"));
    assert.equal(f.w.document.getElementById("owner-collectible-dialog").open,false);
    assert.equal(f.node("notes").value,"");
    f.w.state.session={user:{id:"collector-b"},access_token:"fixture-new-token"};
    f.open({category:"figures"}); resolve(result); await new Promise(done=>setTimeout(done,0));
    assert.equal(f.changes.length,0); assert.equal(f.node("category").value,"figures");
    assert.equal(f.node("success").hidden,true); assert.equal(f.node("close").disabled,false);
    f.close(); groups++;
  }
  {
    let another=0;
    const f=mount(); f.open({category:"sports",onAddAnother:()=>another++,onSaved:()=>{throw new Error("presentation callback");}});
    f.fill("sports",sports); f.submit(); await settle(()=>!f.node("success").hidden);
    f.node("add-another").click(); assert.equal(another,1); assert.equal(f.calls.length,1);
    f.close(); groups++;
  }
  // R2 checklist references are not canonical editions: keep identity inputs
  // editable, and never guess a parallel, language, copy state, cost or owner.
  {
    const f=mount(),row={catalogue_id:null,id:"00000000-0000-4000-8000-000000000099",
      source_kind:"REFERENCE",metadata_only:true,reference_verified:false,
      name:"Fixture Player checklist reference",set_name:"2026 Bowman Baseball",language:"English",
      reference_scope:"CHECKLIST_REFERENCE_ONLY_PHYSICAL_IDENTITY_UNVERIFIED",
      sports_card:{system_code:"SPORTS_CARDS",sport:"Baseball",release_year:2026,
        manufacturer:"Topps",set_name:"Bowman Baseball",subject_name:"Fixture Player",
        card_number:"BP-42",team:"Fixture Team",parallel:null,condition:"Near Mint",owner_id:"other-owner"},
      source_attribution:{label:"Card Collector Capital",url:"https://cardcollectorcapital.com/data",
        notice_url:"/assets/catalogue-source-notices.txt",coverage:"1,722 selected checklist references, not a complete sports catalogue."}};
    assert.equal(f.open({category:"sports",catalogue:row}),true);
    assert.equal(f.node("reference").hidden,false); assert.equal(f.node("sports").hidden,false);
    assert.equal(f.node("sports").disabled,false); assert.equal(f.node("figures").disabled,true);
    assert.equal(f.node("sports-release_year").value,"2026");
    assert.equal(f.node("sports-set_name").value,"Bowman Baseball");
    assert.equal(f.node("sports-subject_name").value,"Fixture Player");
    assert.equal(f.node("sports-team").value,"Fixture Team");
    assert.equal(f.node("sports-parallel").value,"");assert.equal(f.node("sports-parallel").required,true);
    assert.equal(f.node("sports-language").value,"");assert.equal(f.node("sports-language").required,true);
    assert.equal(f.node("condition").value,"");assert.equal(f.node("cost").value,"");
    assert.match(f.node("reference-review").textContent,/Metadata reference only.*not verified/);
    assert.match(f.node("reference-provenance").textContent,/1,722 selected.*not a complete/);
    const links=[...f.node("reference-provenance").querySelectorAll("a")];
    assert.equal(links[0].href,"https://cardcollectorcapital.com/data");
    assert.equal(links[1].pathname,"/assets/catalogue-source-notices.txt");
    assert.ok(links.every(link=>link.target==="_blank"&&link.rel==="noopener noreferrer"));
    f.submit();assert.equal(f.calls.length,0);
    f.node("sports-parallel").value="Blue Refractor";f.node("sports-language").value="English";
    f.node("sports-team").value="Corrected Team";f.submit();
    await settle(()=>!f.node("success").hidden);
    const data=JSON.parse(f.calls[0].body);
    assert.equal(data.catalogue_id,undefined);assert.equal(data.new_catalogue.sports_card.parallel,"Blue Refractor");
    assert.equal(data.new_catalogue.sports_card.team,"Corrected Team");
    assert.equal(data.new_catalogue.sports_card.owner_id,undefined);
    assert.equal(data.acquisition_cost_minor,null);assert.equal(data.condition,null);
    f.close();groups++;
  }
  // Figure seeds can prefill evidence-backed fields only; an absent edition
  // remains required, not silently converted into a Standard/Base variant.
  {
    const f=mount(),row={catalogue_id:null,source_kind:"REFERENCE",metadata_only:true,
      name:"Fixture Pop",language:null,figure_details:{manufacturer:"Funko",franchise:"Fixture World",
        character:"Fixture Character",product_line:"Pop!",edition:null,release_year:2026,
        manufacturer_sku:"SKU-001",barcode_gtin:null,scale:null},
      source_attribution:{label:"Reviewed publisher metadata",url:"https://github.com/pulltheorytcg/drop-rate-backend",
        coverage:"Six starter figure references; not the complete Funko catalogue."}};
    assert.equal(f.open({category:"figures",catalogue:row}),true);
    assert.equal(f.node("figures").hidden,false);assert.equal(f.node("figures").disabled,false);
    assert.equal(f.node("figures-manufacturer").value,"Funko");
    assert.equal(f.node("figures-manufacturer_sku").value,"SKU-001");
    assert.equal(f.node("figures-release_year").value,"2026");
    assert.equal(f.node("figures-edition").value,"");assert.equal(f.node("figures-edition").required,true);
    assert.equal(f.node("figures-scale").value,"");assert.equal(f.node("figures-barcode_gtin").value,"");
    assert.doesNotMatch(f.node("reference-details").textContent,/null|undefined|English/);
    assert.match(f.node("reference-provenance").textContent,/Six starter.*not the complete/);
    f.submit();assert.equal(f.calls.length,0);
    f.node("figures-edition").value="Convention exclusive";f.submit();
    await settle(()=>!f.node("success").hidden);
    const data=JSON.parse(f.calls[0].body);
    assert.equal(data.catalogue_id,undefined);assert.equal(data.new_catalogue.figure_details.edition,"Convention exclusive");
    assert.equal(data.new_catalogue.language,undefined);assert.equal(data.seal_status,null);
    f.close();groups++;
  }
  // Partial structured metadata never borrows identity from display text or
  // arbitrary source keys. A reviewed, supplied edition may remain prefilled.
  {
    const f=mount();
    f.open({category:"figures",catalogue:{catalogue_id:"not-a-canonical-id",name:"Display-only Name",
      set_name:"Display-only Line",figure_details:{manufacturer:"Fixture Maker",edition:"Deluxe edition",
        character:{text:"Invalid object"},franchise:"Unknown",release_year:"2026",condition:"New"}}});
    assert.equal(f.node("figures").disabled,false);
    assert.equal(f.node("figures-edition").value,"Deluxe edition");
    assert.equal(f.node("figures-character").value,"");assert.equal(f.node("figures-product_line").value,"");
    assert.equal(f.node("figures-franchise").value,"");assert.equal(f.node("figures-release_year").value,"");
    assert.equal(f.node("condition").value,"");f.submit();assert.equal(f.calls.length,0);
    f.close();groups++;
  }
  // Metadata flags cannot be bypassed with a valid-looking canonical UUID.
  // Plain text attribution and a fixed local notices URL do not inject HTML.
  {
    const f=mount();
    for(const url of ["javascript:alert(1)","data:text/html,unsafe","http://source.example/path",
      "https://user:password@source.example/path","https://127.0.0.1/path","https://local.internal/path",
      "https://localhost/path","https://localhost./path","https://device.home.arpa/path","https://[::1]/path","https://source.example\\@localhost/path"]){
      f.open({category:"figures",catalogue:{catalogue_id:"00000000-0000-4000-8000-000000000020",
        source_kind:"REFERENCE",metadata_only:true,name:"Fixture",figure_details:{...figure},
        source_attribution:{label:"<img src=x onerror=alert(1)>",url,coverage:"<script>unsafe</script>",notice_url:"//private.invalid/notices"}}});
      assert.equal(f.node("figures").disabled,false);
      assert.equal(f.node("reference-provenance").querySelector("a,img,script"),null);
      assert.match(f.node("reference-provenance").textContent,/<img src=x/);
    }
    f.w.state.session=null;f.w.dispatchEvent(new f.w.Event("hub-session-cleared"));
    assert.equal(f.node("reference-provenance").textContent,"");
    f.close();groups++;
  }
  // An interrupted reference-assisted save has the same retry/idempotency
  // guarantees as manual intake, even if another reference is selected.
  {
    const f=mount({responses:[new TypeError("connection lost"),result]});
    f.open({category:"figures",catalogue:{catalogue_id:null,metadata_only:true,
      figure_details:{...figure}}});f.submit();
    await settle(()=>f.node("save").textContent==="Retry this item");
    f.open({category:"sports",catalogue:{catalogue_id:null,metadata_only:true,sports_card:{sport:"Baseball"}}});
    assert.equal(f.node("category").value,"figures");assert.match(f.node("message").textContent,/previous save/);
    f.submit();await settle(()=>!f.node("success").hidden);
    assert.equal(f.calls[0].body,f.calls[1].body);
    assert.equal(f.calls[0].headers["Idempotency-Key"],f.calls[1].headers["Idempotency-Key"]);
    f.close();groups++;
  }
  console.log(`Sports/Figures UI: ${groups} interaction groups passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
