"use strict";
// Actual Seller Hub DOM/JS, with mocked API responses. Not a live seller login.
const assert=require("node:assert/strict");
const {JSDOM}=require("jsdom");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"../../backend/app/static");
const pause=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const batchID="2ac107db-2a16-4147-adf6-96be9db1a613";
const catalogueID="b975c7e7-9d56-4414-856f-6629b2370e56";
const ready={id:"9fe4193c-82f2-48c9-a225-668731b7e9db",source_row:2,quantity:2,status:"READY",issues:[],catalogue_id:catalogueID,
  normalized_record:{name:"Known Card",game:"One Piece",set_name:"OP01",card_number:"001",product_type:"CARD",language:"English",quantity:2}};
const uncertain={...ready,id:"13b203a7-dbe7-4bfc-b671-acd3bf7e4332",source_row:3,quantity:1,status:"REVIEW",catalogue_id:null,
  issues:["catalogue_not_found","missing_language"],normalized_record:{...ready.normalized_record,name:"Review Card",language:null,quantity:1}};

function fixture(records=[ready],options={}){
  const dom=new JSDOM(fs.readFileSync(path.join(root,"owner.html"),"utf8"),{url:"https://drop-rate.test/owner",runScripts:"outside-only",pretendToBeVisual:true});
  const w=dom.window,doc=w.document,context=dom.getInternalVMContext(),calls=[];
  let rows=structuredClone(records),version=1,automatic=false,exists=Boolean(options.existing),added=0,lost=false,release,releaseSearch;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};w.confirm=()=>true;
  const status=()=>rows.some(r=>["READY","REVIEW"].includes(r.status))?"PREVIEW":"COMMITTED";
  const summary=()=>({added_units:rows.filter(r=>r.status==="COMMITTED").reduce((n,r)=>n+r.quantity,0),ready_units:rows.filter(r=>r.status==="READY").reduce((n,r)=>n+r.quantity,0),review_rows:rows.filter(r=>r.status==="REVIEW").length,review_units:rows.filter(r=>r.status==="REVIEW").reduce((n,r)=>n+r.quantity,0),skipped_rows:rows.filter(r=>r.status==="SKIPPED").length});
  const result=(created=0,candidate)=>({batch_id:batchID,version,status:status(),batch_status:status(),automatic_intake:automatic,created_count:created,replayed:created===0,summary:summary(),candidate});
  function apply(){
    let count=0;
    for(const row of rows)if(row.status==="READY"){row.status="COMMITTED";count+=row.quantity;}
    if(count||!automatic)version++;
    automatic=true;added+=count;return count;
  }
  w.__fakeApi=async(url,init={})=>{
    const method=init.method||"GET",body=init.body?JSON.parse(init.body):null;calls.push({url,method,body});
    if(url==="/api/v1/owner/imports?limit=8")return {items:exists?[{id:batchID,filename:"collection.csv",adapter:"COLLECTR",source_rows:rows.length,status:status()}]:[]};
    if(url==="/api/v1/owner/imports/upload"&&method==="POST"){
      exists=true;const count=apply();
      if(options.delay)await new Promise(resolve=>{release=resolve;});
      if(options.loseResponse&&!lost){lost=true;throw new Error("Network response interrupted");}
      return result(count);
    }
    if(url==="/api/v1/owner/imports/"+batchID)return {batch:{id:batchID,version,status:status(),automatic_intake:automatic,adapter:"COLLECTR",source_rows:rows.length,physical_units:records.reduce((n,r)=>n+r.quantity,0),filename:"collection.csv",warnings:[]},candidates:structuredClone(rows)};
    if(url.endsWith("/"+batchID+"/commit")&&method==="POST")return result(apply());
    if(url.startsWith("/api/v1/owner/imports/catalogue-search?")){
      if(options.delaySearch)await new Promise(resolve=>{releaseSearch=resolve;});
      return {items:[{id:catalogueID,name:"Known Card",game:"One Piece",set_name:"OP01",card_number:"001",product_type:"CARD",language:"English"}]};
    }
    const row=rows.find(r=>url.includes("/candidates/"+r.id+"/"));
    if(row&&url.endsWith("/resolve")&&method==="POST"){
      if(options.resolveError)throw Object.assign(new Error(options.resolveError),{status:422});
      assert.equal(body.version,version);row.catalogue_id=body.catalogue_id;row.normalized_record.language=body.language||"English";row.issues=[];row.status=automatic?"COMMITTED":"READY";version++;
      const count=automatic?row.quantity:0;added+=count;return result(count,structuredClone(row));
    }
    if(row&&url.endsWith("/skip")&&method==="POST"){
      assert.equal(body.version,version);assert.notEqual(row.status,"COMMITTED");row.status="SKIPPED";version++;return result(0,structuredClone(row));
    }
    throw new Error("Unexpected request "+method+" "+url);
  };
  w.__inventoryRefreshed=0;
  vm.runInContext("async function apiRequest(url,init){return window.__fakeApi(url,init)};async function loadOwnerInventory(){window.__inventoryRefreshed++};async function loadOwnerOverview(){};",context);
  vm.runInContext(fs.readFileSync(path.join(root,"owner-imports.js"),"utf8"),context);
  return {w,doc,calls,get added(){return added},close:()=>w.close(),release:()=>release?.(),releaseSearch:()=>releaseSearch?.(),
    open:async(source="COLLECTR")=>{doc.getElementById("owner-import-trigger").click();doc.querySelector('[data-owner-import-adapter="'+source+'"]').click();await pause();},
    file:async(name="collection.csv",contents="Product Name,Game,Set,Number,Quantity\nKnown Card,One Piece,OP01,001,2")=>{const f=new w.File([contents],name,{type:"text/csv"});Object.defineProperty(f,"text",{value:async()=>contents});const input=doc.getElementById("owner-import-file");Object.defineProperty(input,"files",{configurable:true,value:[f]});input.dispatchEvent(new w.Event("change",{bubbles:true}));await pause();},
    upload:async()=>{doc.getElementById("owner-import-form").dispatchEvent(new w.Event("submit",{bubbles:true,cancelable:true}));await pause();}};
}

(async()=>{
  let checks=0;
  {
    const f=fixture();assert.equal(f.doc.getElementById("owner-import-dialog"),null);
    assert.deepEqual([...f.doc.querySelectorAll('[data-owner-import-adapter]')].map(e=>e.dataset.ownerImportAdapter),["COLLECTR","HOLODEX","GENERIC_CSV"]);
    await f.open();assert.equal(f.doc.getElementById("owner-import-preview").textContent,"Import collection");f.close();checks++;
  }
  {
    const f=fixture();await f.open("GENERIC_CSV");await f.file("other.tsv","Character\tExpansion\tNumber\tCopies\nKnown Card\tOP01\t001\t2");
    f.doc.querySelector('[data-owner-import-field="name"]').value="Character";f.doc.querySelector('[data-owner-import-field="quantity"]').value="Copies";
    await f.upload();const call=f.calls.find(c=>c.url.endsWith("/upload"));assert.equal(call.body.adapter,"GENERIC_CSV");assert.deepEqual(call.body.column_mapping,{name:"Character",quantity:"Copies"});
    assert.equal(f.added,2);assert.equal(f.doc.getElementById("owner-import-commit").hidden,true);assert.match(f.doc.getElementById("owner-import-summary").textContent,/Copies added to inventory/);assert.ok(f.w.__inventoryRefreshed>=1);f.close();checks++;
  }
  {
    const f=fixture([ready,uncertain]);await f.open();await f.file();await f.upload();
    assert.equal(f.added,2,"One review must not hold recognised copies");assert.equal(f.doc.querySelectorAll(".owner-import-row").length,1,"Default view should show exceptions only");
    assert.match(f.doc.getElementById("owner-import-summary").textContent,/1 copies/);
    const row=f.doc.querySelector(".owner-import-row");row.querySelector(".owner-import-row-actions button").click();await pause();
    assert.ok(f.calls.some(c=>c.url.includes("catalogue-search?q=001+OP01")),"Find match should search the combined identifier immediately");
    row.querySelector('[aria-label="Card language confirmation"]').value="English";
    const choose=row.querySelector(".owner-import-resolver-result button");assert.equal(choose.textContent,"Confirm and add");choose.click();await pause();
    assert.equal(f.added,3);const call=f.calls.find(c=>c.url.endsWith("/resolve"));assert.equal(call.body.catalogue_id,catalogueID);assert.equal(call.body.language,"English");assert.match(f.doc.getElementById("owner-import-message").textContent,/Confirmed card added/);f.close();checks++;
  }
  {
    const f=fixture([ready,uncertain]);await f.open();await f.file();await f.upload();
    f.doc.querySelectorAll(".owner-import-row-actions button")[1].click();await pause();assert.equal(f.added,2,"Skipping pending stock must not remove imported copies");assert.equal(f.doc.getElementById("owner-import-commit").hidden,true);f.close();checks++;
  }
  {
    const f=fixture([ready,uncertain],{existing:true});await f.open();
    f.doc.querySelector(".owner-import-history-row button").click();await pause();assert.equal(f.added,0,"Resuming an old preview must remain read-only");
    const add=f.doc.getElementById("owner-import-commit");assert.equal(add.disabled,false);add.click();await pause();assert.equal(f.added,2);assert.match(f.doc.getElementById("owner-import-message").textContent,/1 rows still need confirmation/);f.close();checks++;
  }
  {
    const f=fixture();await f.open();await f.file();await f.upload();await f.upload();assert.equal(f.added,2,"Repeated upload must not duplicate mocked copies");assert.equal(f.calls.filter(c=>c.url.endsWith("/commit")).length,0,"New upload must not need a second whole-batch action");f.close();checks++;
  }
  {
    const f=fixture([ready,uncertain],{loseResponse:true});await f.open();await f.file();await f.upload();assert.equal(f.added,2);assert.match(f.doc.getElementById("owner-import-message").textContent,/Recent imports/);
    f.doc.querySelector(".owner-import-history-row button").click();await pause();assert.match(f.doc.getElementById("owner-import-summary").textContent,/Copies added to inventory/);assert.equal(f.added,2);f.close();checks++;
  }
  {
    const malicious={...ready,normalized_record:{...ready.normalized_record,name:"<img src=x onerror=alert(1)>",buyer_email:"secret@example.com"}};
    const f=fixture([malicious]);await f.open();await f.file();await f.upload();const row=f.doc.querySelector(".owner-import-row");assert.match(row.textContent,/<img/);assert.equal(row.querySelector("img"),null);assert.doesNotMatch(row.textContent,/secret@example.com/);f.close();checks++;
  }
  {
    const f=fixture();await f.open("HOLODEX");await f.file("bad.xlsx","not csv");assert.match(f.doc.getElementById("owner-import-message").textContent,/CSV or tab-separated TSV/);assert.equal(f.calls.some(c=>c.url.endsWith("/upload")),false);f.close();checks++;
  }
  {
    const f=fixture([ready],{delay:true});await f.open();await f.file();await f.upload();f.doc.getElementById("owner-import-close").click();f.release();await pause();assert.equal(f.doc.getElementById("owner-import-dialog").open,false);assert.equal(f.w.__inventoryRefreshed,0,"A stale completion must not update a closed account view");f.close();checks++;
  }
  {
    const badCondition={...uncertain,issues:["unrecognised_card_condition"]};
    const f=fixture([badCondition]);await f.open();await f.file();await f.upload();
    f.doc.querySelector(".owner-import-row-actions button").click();await pause();
    assert.equal(f.doc.querySelector(".owner-import-card-details").open,true);
    const choose=f.doc.querySelector(".owner-import-resolver-result button");choose.click();await pause();
    assert.equal(f.calls.some(c=>c.url.endsWith("/resolve")),false,"An unrecognised condition cannot silently become Near Mint");
    f.doc.querySelector('[aria-label="Raw card condition"]').value="Lightly Played";
    choose.click();await pause();
    assert.deepEqual(f.calls.find(c=>c.url.endsWith("/resolve")).body.card_details,{card_state:"RAW",condition:"Lightly Played",grading_company:null,grade:null,certificate_number:null});
    assert.equal(f.added,1);f.close();checks++;
  }
  {
    const slab={...uncertain,issues:["unrecognised_collectr_grade"]};
    const f=fixture([slab]);await f.open();await f.file();await f.upload();
    f.doc.querySelector(".owner-import-row-actions button").click();await pause();
    const mode=f.doc.querySelector('[aria-label="Card format"]');assert.equal(mode.value,"","Unrecognised grading must not become raw automatically");
    mode.value="GRADED";mode.dispatchEvent(new f.w.Event("change"));
    f.doc.querySelector('[aria-label="Grading company"]').value="BGS";
    const choose=f.doc.querySelector(".owner-import-resolver-result button");choose.click();await pause();
    assert.equal(f.calls.some(c=>c.url.endsWith("/resolve")),false,"Incomplete slab label cannot be submitted");
    f.doc.querySelector('[aria-label="Grade on slab label"]').value="9.5";
    f.doc.querySelector('[aria-label="Certificate number (optional)"]').value="TEST-123";
    choose.click();await pause();
    const details=f.calls.find(c=>c.url.endsWith("/resolve")).body.card_details;
    assert.equal(details.grade,"9.5");assert.equal(details.condition,null);assert.equal(details.certificate_number,"TEST-123");f.close();checks++;
  }
  {
    const f=fixture([uncertain]);await f.open();await f.file();await f.upload();
    f.doc.querySelector(".owner-import-row-actions button").click();await pause();
    const old=f.doc.querySelector(".owner-import-resolver-result button"),input=f.doc.querySelector('.owner-import-resolver input[type="search"]');
    input.value="different card";input.dispatchEvent(new f.w.Event("input"));
    assert.equal(f.doc.querySelector(".owner-import-resolver-result"),null);
    old.click();await pause();assert.equal(f.calls.some(c=>c.url.endsWith("/resolve")),false,"A stale result cannot confirm after editing the search");f.close();checks++;
  }
  {
    const f=fixture([uncertain],{delaySearch:true});await f.open();await f.file();await f.upload();
    f.doc.querySelector(".owner-import-row-actions button").click();await pause();
    const input=f.doc.querySelector('.owner-import-resolver input[type="search"]');input.value="new query";input.dispatchEvent(new f.w.Event("input"));
    f.releaseSearch();await pause();assert.equal(f.doc.querySelector(".owner-import-resolver-result"),null,"An old response cannot repopulate changed search results");f.close();checks++;
  }
  for(const action of ["close","session","navigation"]){
    const f=fixture([uncertain]);await f.open("GENERIC_CSV");await f.file();await f.upload();
    f.doc.getElementById("owner-import-game").value="Pokemon";
    f.doc.getElementById("owner-import-language").value="Japanese";
    f.doc.getElementById("owner-import-map-details").open=true;
    if(action==="close")f.doc.getElementById("owner-import-close").click();
    if(action==="session")f.w.dispatchEvent(new f.w.Event("hub-session-cleared"));
    if(action==="navigation")f.doc.dispatchEvent(new f.w.CustomEvent("owner-view-changed",{detail:{view:"search"}}));
    assert.equal(f.doc.getElementById("owner-import-game").value,"");assert.equal(f.doc.getElementById("owner-import-language").value,"");
    for(const id of ["owner-import-map-fields","owner-import-rows","owner-import-summary","owner-import-warnings","owner-import-history-list"]){
      assert.equal(f.doc.getElementById(id).childElementCount,0,`${action} must clear ${id}`);
      assert.equal(f.doc.getElementById(id).textContent,"");
    }
    assert.equal(f.doc.getElementById("owner-import-map-details").open,false);
    await f.open();const before=f.calls.filter(c=>c.url.endsWith("/upload")).length;await f.upload();
    assert.equal(f.calls.filter(c=>c.url.endsWith("/upload")).length,before,"Closed upload contents cannot be reused by another session");f.close();checks++;
  }
  {
    const f=fixture([uncertain],{resolveError:"Chosen language conflicts with the selected catalogue printing"});await f.open();await f.file();await f.upload();
    f.doc.querySelector(".owner-import-row-actions button").click();await pause();f.doc.querySelector(".owner-import-resolver-result button").click();await pause();
    assert.match(f.doc.getElementById("owner-import-message").textContent,/Chosen language conflicts/);
    assert.equal(f.added,0);assert.equal(f.doc.querySelector(".owner-import-resolver-result button").disabled,false);f.close();checks++;
  }
  console.log(`Immediate Seller Hub intake: ${checks} mocked DOM scenarios passed (not a production login/checkout test).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
