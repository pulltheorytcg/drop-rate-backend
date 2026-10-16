"use strict";
// Standalone owner-specific homepage value contract. No private account access,
// no provider requests or writes; no price may be derived from another owner.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {JSDOM}=require("jsdom");
const base=path.join(__dirname,"../../backend/app/static");
const markup=fs.readFileSync(path.join(base,"owner.html"),"utf8")
  .replace(/<script[^>]*><\/script>/g,"");
const src=fs.readFileSync(path.join(base,"owner-portal.js"),"utf8")
  .replace(/\ninitialise\(\);\s*$/,"");

async function render(summary) {
  const dom=new JSDOM(markup,{url:"https://example.test/owner",runScripts:"outside-only",pretendToBeVisual:true});
  const w=dom.window,ctx=dom.getInternalVMContext();
  vm.runInContext(src,ctx);
  const calls=[];
  w.testOverviewRequest=async (url,options)=>{
    calls.push({url,options});
    if(url!=="/api/v1/owner/overview")throw new Error("Unexpected provider or write request");
    return {summary,owner:{display_name:"Seller",owner_type:"CONSIGNOR"}};
  };
  vm.runInContext("apiRequest=window.testOverviewRequest",ctx);
  await vm.runInContext("loadOwnerOverview()",ctx);
  const read=id=>w.document.getElementById(id)?.textContent;
  return {dom,calls,read};
}

(async()=>{
  let checks=0;
  {
    // Observed in founder's 16 Oct iPhone recording and verified from production.
    const {dom,read,calls}=await render({
      total_inventory_count:104,total_card_count:101,total_sealed_count:3,
      active_inventory_count:104,active_valued_count:1,active_unvalued_count:103,
      active_market_value_minor:3,guide_estimate_count:1,
      active_recommended_count:1,active_recommended_retail_minor:100,
      recommendation_guide_count:1,recorded_asking_count:2,
      recorded_asking_value_minor:2000,draft_count:102,inspection_count:0,
      approved_count:2,reserved_count:0,sold_count:0
    });
    assert.equal(read("owner-total-inventory"),"104");
    assert.equal(read("owner-inventory-type-note"),"101 cards · 3 sealed products");
    assert.equal(read("owner-market-value"),"£0.03");
    assert.match(read("owner-market-value-label"),/partial/i);
    assert.match(read("owner-market-value-note"),/1 of 104 valued.*103 awaiting eligible prices/);
    assert.match(read("owner-market-value-note"),/1 guide estimate/);
    assert.equal(read("owner-store-value"),"£20.00","Headline must show saved Store Prices, not £1 guide-floor suggestion");
    assert.match(read("owner-asking-price-note"),/2 of 104 copies have saved Store Prices/);
    assert.match(read("owner-recommendation-note"),/Automatic suggestion: £1.00 on 1 of 104/);
    assert.match(read("owner-recommendation-note"),/guide estimate/);
    assert.deepEqual(calls.map(x=>x.url),["/api/v1/owner/overview"]);
    assert.equal(calls.some(x=>x.options?.method && x.options.method!=="GET"),false);
    dom.window.close();checks++;
  }
  {
    const {dom,read}=await render({
      total_inventory_count:12,total_card_count:12,total_sealed_count:0,
      active_inventory_count:12,active_valued_count:0,active_unvalued_count:12,
      active_market_value_minor:null,recorded_asking_count:0,recorded_asking_value_minor:null,
      active_recommended_count:0,active_recommended_retail_minor:null,
      draft_count:12,approved_count:0,sold_count:0
    });
    assert.equal(read("owner-market-value"),"Unavailable","Missing quotes cannot be presented as £0 holdings");
    assert.equal(read("owner-store-value"),"Not set","No saved asks cannot be presented as £0 selling price");
    assert.match(read("owner-asking-price-note"),/0 of 12/);
    assert.match(read("owner-recommendation-note"),/unavailable/);
    dom.window.close();checks++;
  }
  {
    const {dom,read}=await render({
      total_inventory_count:2,total_card_count:1,total_sealed_count:1,
      active_inventory_count:2,active_valued_count:2,active_unvalued_count:0,
      active_market_value_minor:3850,guide_estimate_count:0,
      active_recommended_count:2,active_recommended_retail_minor:5200,
      recorded_asking_count:1,recorded_asking_value_minor:5500,
      draft_count:0,approved_count:2,sold_count:0
    });
    assert.equal(read("owner-market-value"),"£38.50");
    assert.equal(read("owner-market-value-label"),"Market value");
    assert.equal(read("owner-store-value"),"£55.00");
    assert.match(read("owner-asking-price-note"),/1 of 2/);
    assert.match(read("owner-recommendation-note"),/£52.00/);
    dom.window.close();checks++;
  }
  {
    const {dom,read}=await render({
      total_inventory_count:1,active_inventory_count:1,
      active_valued_count:0,active_unvalued_count:1,
      recorded_asking_count:0,recorded_asking_value_minor:null,
      active_recommended_count:0,active_recommended_retail_minor:null
    });
    assert.match(read("owner-inventory-type-note"),/Physical cards, sealed products/);
    assert.equal(read("owner-store-value"),"Not set");
    dom.window.close();checks++;
  }
  console.log("Owner homepage valuation integrity: "+checks+" truthful totals, partial coverages and read-only scenarios passed.");
})().catch(e=>{console.error(e);process.exitCode=1});
