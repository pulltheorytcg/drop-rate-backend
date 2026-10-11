"use strict";
// Real Seller Hub collection importer DOM tests; all backend responses mocked.
const assert = require("node:assert/strict");
const {JSDOM} = require("jsdom");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.join(__dirname, "../../backend/app/static");
const pause = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};
const batchID = "2ac107db-2a16-4147-adf6-96be9db1a613";
const candidateID = "9fe4193c-82f2-48c9-a225-668731b7e9db";
const catalogID = "b975c7e7-9d56-4414-856f-6629b2370e56";

const readyCandidate = {
  id:candidateID,source_row:2,quantity:2,status:"READY",issues:[],catalogue_id:catalogID,
  normalized_record:{
    name:"Known Card",game:"One Piece",set_name:"OP01",card_number:"001",
    product_type:"CARD",language:"English",quantity:2,
  },
};

function fixture(initialCandidate=readyCandidate, options={}) {
  const html=fs.readFileSync(path.join(root,"owner.html"),"utf8");
  const dom=new JSDOM(html,{url:"https://drop-rate.test/owner",
    runScripts:"outside-only",pretendToBeVisual:true});
  const w=dom.window, doc=w.document, context=dom.getInternalVMContext();
  const calls=[];
  let imported=0;
  let candidate={...initialCandidate};
  let version=1;
  let committed=false;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.confirm=()=>true;
  w.__fakeApi=async(url, init={})=>{
    calls.push({url,method:init.method||"GET",body:init.body ? JSON.parse(init.body) : null});
    const method=init.method||"GET";
    if (url==="/api/v1/owner/imports?limit=8")return {
      items:committed?[{id:batchID,filename:"collection.csv",adapter:"COLLECTR",
        status:"COMMITTED",source_rows:1}]:[],
    };
    if (url==="/api/v1/owner/imports/preview"&&method==="POST") {
      if(options.duplicate)throw new Error("This exact file has already been imported or previewed");
      const ready = candidate.status==="READY" ? candidate.quantity : 0;
      return {batch_id:batchID,version:1,adapter:init.body && JSON.parse(init.body).adapter,
        source_rows:1,physical_units:2,ready_units:ready,
        review_rows:candidate.status==="REVIEW"?1:0,
        skipped_rows:candidate.status==="SKIPPED"?1:0,warnings:[]};
    }
    if(url==="/api/v1/owner/imports/"+batchID)return {
      batch:{id:batchID,version,status:committed?"COMMITTED":"PREVIEW",
        adapter:"COLLECTR",source_rows:1,physical_units:2,
        filename:"collection.csv",warnings:[]},
      candidates:[candidate],
    };
    if(url==="/api/v1/owner/imports/"+batchID+"/commit"&&method==="POST"){
      committed=true;
      imported++;
      return {created_count:candidate.status==="READY"?candidate.quantity:0,status:"COMMITTED"};
    }
    if(url.startsWith("/api/v1/owner/imports/catalogue-search?"))return {
      items:[{id:catalogID,name:"Known Card",game:"One Piece",set_name:"OP01",
        card_number:"001",product_type:"CARD",language:"English"}],
    };
    if(url.includes("/candidates/"+candidateID+"/resolve")&&method==="POST"){
      version++;
      candidate={...candidate,status:"READY",issues:[],catalogue_id:catalogID};
      return {batch_id:batchID,version,candidate,
        summary:{ready_units:2,review_rows:0,skipped_rows:0}};
    }
    if(url.includes("/candidates/"+candidateID+"/skip")&&method==="POST"){
      version++;
      candidate={...candidate,status:"SKIPPED",issues:[]};
      return {batch_id:batchID,version,candidate,
        summary:{ready_units:0,review_rows:0,skipped_rows:1}};
    }
    throw new Error("Unexpected owner import request "+method+" "+url);
  };
  w.__inventoryRefreshed=0;
  vm.runInContext(
    "async function apiRequest(url,init){return window.__fakeApi(url,init);};"
    + "async function loadOwnerInventory(){window.__inventoryRefreshed++};"
    + "async function loadOwnerOverview(){};",
    context,
  );
  vm.runInContext(fs.readFileSync(path.join(root,"owner-imports.js"),"utf8"),context);
  return {
    w,doc,calls,
    get imported(){return imported;},
    close:()=>w.close(),
    open:async(source="COLLECTR")=>{
      doc.getElementById("owner-import-trigger").click();
      const menu=doc.getElementById("owner-import-menu");
      assert.equal(menu.hidden,false);
      menu.querySelector('[data-owner-import-adapter="'+source+'"]').click();
      await pause();
    },
    file:async(filename,contents)=>{
      const file=new w.File([contents],filename,{type:"text/csv"});
      Object.defineProperty(file,"text",{value:async()=>contents});
      const input=doc.getElementById("owner-import-file");
      Object.defineProperty(input,"files",{configurable:true,value:[file]});
      input.dispatchEvent(new w.Event("change",{bubbles:true}));
      await pause();
    },
    preview:async()=>{
      const form=doc.getElementById("owner-import-form");
      form.dispatchEvent(new w.Event("submit",{bubbles:true,cancelable:true}));
      await pause();
    },
  };
}

(async()=>{
  let checks=0;
  {
    const f=fixture();
    assert.equal(f.doc.getElementById("owner-import-dialog"),null,
      "Importer must mount lazily to preserve inventory dialogs");
    const menu=f.doc.getElementById("owner-import-menu");
    assert.deepEqual([...menu.querySelectorAll("[data-owner-import-adapter]")]
      .map(x=>x.dataset.ownerImportAdapter),["COLLECTR","HOLODEX","GENERIC_CSV"]);
    await f.open("COLLECTR");
    assert.equal(f.doc.getElementById("owner-import-dialog").open,true);
    assert.equal(f.doc.getElementById("owner-import-adapter").value,"COLLECTR");
    f.close();checks++;
  }
  {
    const f=fixture();
    await f.open("GENERIC_CSV");
    await f.file("other.tsv","Character\tExpansion\tNumber\tCopies\nKnown Card\tOP01\t001\t2");
    const mapped=f.doc.querySelector('[data-owner-import-field="name"]');
    const quantity=f.doc.querySelector('[data-owner-import-field="quantity"]');
    assert.ok(mapped,"Custom export column mapping must be available");
    mapped.value="Character";
    quantity.value="Copies";
    await f.preview();
    const input=f.calls.find(x=>x.url==="/api/v1/owner/imports/preview");
    assert.ok(input);
    assert.equal(input.body.adapter,"GENERIC_CSV");
    assert.equal(input.body.filename,"other.tsv");
    assert.deepEqual(input.body.column_mapping,{name:"Character",quantity:"Copies"});
    assert.equal(f.doc.querySelectorAll(".owner-import-row").length,1);
    const commit=f.doc.getElementById("owner-import-commit");
    assert.equal(commit.disabled,false);
    assert.equal(commit.textContent,"Import 2 Draft copies");
    commit.click();await pause();
    assert.equal(f.imported,1);
    assert.match(f.doc.getElementById("owner-import-message").textContent,/Draft copies added/);
    assert.ok(f.w.__inventoryRefreshed>=1);
    assert.equal(commit.hidden,true);
    f.close();checks++;
  }
  {
    const f=fixture({...readyCandidate,status:"REVIEW",
      issues:["catalogue_not_found","catalogue_admin_review_required"],catalogue_id:null});
    await f.open("HOLODEX");
    await f.file("holodex.csv","Card Name,Set,Number,Quantity\nKnown Card,OP01,001,2");
    await f.preview();
    const commit=f.doc.getElementById("owner-import-commit");
    assert.equal(commit.disabled,true);
    const review=f.doc.querySelector(".owner-import-row");
    assert.match(review.textContent,/Needs review/);
    review.querySelector(".owner-import-row-actions button").click();
    await pause();
    const search=review.querySelector(".owner-import-resolver button");
    search.click();await pause();
    const choose=review.querySelector(".owner-import-resolver-result button");
    assert.ok(choose,"Seller must be able to select an existing canonical match");
    choose.click();await pause();
    assert.equal(commit.disabled,false);
    const last=f.calls.find(x=>x.url.includes("/resolve"));
    assert.equal(last.body.version,1);
    assert.equal(last.body.catalogue_id,catalogID);
    f.close();checks++;
  }
  {
    const f=fixture({...readyCandidate,status:"REVIEW",issues:["missing_set"]});
    await f.open("COLLECTR");
    await f.file("collectr.csv","Product Name,Game,Set,Number,Quantity\nKnown Card,One Piece,OP01,001,2");
    await f.preview();
    const skip=f.doc.querySelectorAll(".owner-import-row-actions button")[1];
    skip.click();await pause();
    assert.equal(f.doc.getElementById("owner-import-commit").disabled,false);
    assert.match(f.doc.getElementById("owner-import-commit").textContent,/0 new copies/);
    f.close();checks++;
  }
  {
    const f=fixture({...readyCandidate,normalized_record:{
      ...readyCandidate.normalized_record,name:"<img src=x onerror=alert(1)>",
      buyer_email:"secret@example.com",
    }});
    await f.open("COLLECTR");
    await f.file("collectr.csv","Product Name,Game,Set,Number,Quantity\nKnown Card,One Piece,OP01,001,2");
    await f.preview();
    const row=f.doc.querySelector(".owner-import-row");
    assert.match(row.textContent,/<img src=x onerror=alert\(1\)>/);
    assert.equal(row.querySelector("img"),null);
    assert.doesNotMatch(row.textContent,/secret@example.com/);
    f.close();checks++;
  }
  {
    const f=fixture(readyCandidate,{duplicate:true});
    await f.open("COLLECTR");
    await f.file("collectr.csv","Product Name,Game,Set,Number,Quantity\nKnown Card,One Piece,OP01,001,2");
    await f.preview();
    assert.equal(f.imported,0);
    assert.equal(f.doc.getElementById("owner-import-commit").hidden,true);
    assert.match(f.doc.getElementById("owner-import-message").textContent,/already uploaded/);
    f.close();checks++;
  }
  {
    const f=fixture();
    await f.open("GENERIC_CSV");
    await f.file("bad.xlsx","not a CSV");
    assert.match(f.doc.getElementById("owner-import-message").textContent,/CSV or tab-separated TSV/);
    assert.equal(f.doc.getElementById("owner-import-commit").hidden,true);
    f.close();checks++;
  }
  console.log("Seller Hub CSV importer: "+checks+" DOM scenarios passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
