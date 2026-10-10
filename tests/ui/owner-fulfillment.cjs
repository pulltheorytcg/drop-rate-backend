// Seller Hub dispatch review: real DOM event flow; all Shopify API calls mocked.
const {JSDOM}=require("jsdom");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const assert=require("node:assert/strict");

const root=path.join(__dirname,"../../backend/app/static");
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const pending=()=>{
  let resolve,reject;
  const promise=new Promise((ok,no)=>{resolve=ok;reject=no;});
  return {promise,resolve,reject};
};
const disabled={
  carrier_label_purchase:false,
  dispatch_confirmation:false,
  shopify_tracking_sync:false,
  buyer_address_access:false,
};
const paidItem={
  order_item_id:"0dbb6005-7be1-43cf-b872-3ba4a1bdbffe",
  order_number:"#1009",order_status:"PAID",
  inventory_code:"INV-OP17-EXAMPLE",card_name:"OP17 Booster Pack",
  set_name:"World's Strongest Warriors",card_number:null,net_sale_minor:1000,
  blockers:["PHYSICAL_SHIPPER_UNVERIFIED","CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED"],
  state:"AWAITING_DISPATCH_SETUP",can_buy_label:false,can_confirm_dispatched:false,
};
const result=(items=[],total=items.length)=>({
 total,limit:25,offset:0,capabilities:disabled,items,
});
function fixture(handler=async()=>result()){
  const html=fs.readFileSync(path.join(root,"owner.html"),"utf8")
    .replace(/<script[^>]*><\/script>/g,"");
  const dom=new JSDOM(html,{
    url:"https://drop-rate.test/owner",runScripts:"outside-only",pretendToBeVisual:true,
  });
  const w=dom.window,context=dom.getInternalVMContext(),requests=[];
  w.scrollTo=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=async()=>({ok:true,json:async()=>({})});
  const run=(src)=>vm.runInContext(src,context);
  const portal=fs.readFileSync(path.join(root,"owner-portal.js"),"utf8")
    .replace(/\ninitialise\(\);\s*$/,"");
  run(portal);
  w.__mockDispatchApi=async(url)=>{
    requests.push(url);
    if(url==="/api/v1/fulfilment/shopify-status")
      return {store_connected:true,shopify_fulfilment_read_access:true,shop:"Drop Rate",carrier_label_purchase:false};
    if(/^\/api\/v1\/fulfilment\/to-ship\/[a-f0-9-]+\/packing-slip$/i.test(url))
      return {
        source:"SHOPIFY_ADMIN_ORDER",document_type:"OWNER_PACKING_SLIP",
        order_number:"#1009",customer_personal_data_included:false,
        ship_to:null,item_count:1,
        items:[{title:"Booster Pack OP17",sku:"DR-OP17",inventory_id:"INV-OWNER-COPY",quantity:"1"}],
        notice:"Pack only your allocated items.",
      };
    if(/^\/api\/v1\/fulfilment\/to-ship\/[a-f0-9-]+\/shopify$/i.test(url))
      return {
        shopify_connected:true,state:"REVIEW_REQUIRED",
        blockers:["PHYSICAL_SHIPPER_UNVERIFIED","SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING"],
        can_buy_label:false,can_confirm_dispatched:false,
        shipping_address:"must not be shown",customer_email:"must not be shown",
      };
    if(!url.startsWith("/api/v1/fulfilment/to-ship?"))
      throw new Error("Unexpected API call "+url);
    return handler(url);
  };
  run("apiRequest=window.__mockDispatchApi;");
  run(fs.readFileSync(path.join(root,"owner-fulfillment.js"),"utf8"));
  run(fs.readFileSync(path.join(root,"owner-fulfill-wizard.js"),"utf8"));
  run(`state.session={access_token:"test-owner-token",user:{id:"owner-a"}};
    document.getElementById("owner-portal-view").classList.remove("hidden");
    document.getElementById("owner-auth-view").classList.add("hidden");
    activateOwnerView("sales",false);`);
  w.document.dispatchEvent(new w.Event("hub-ready"));
  return {
    w,requests,run,
    list:()=>w.document.getElementById("owner-dispatch-list"),
    status:()=>w.document.getElementById("owner-dispatch-message").textContent,
    finish:()=>w.close(),
  };
}
(async()=>{
  let checks=0;
  {
    const f=fixture();
    await tick();await tick();
    assert.equal(f.requests.length,1);
    assert.match(f.list().textContent,/No paid Shopify order items/);
    assert.match(f.status(),/Carrier labels are not yet connected/);
    assert.equal(f.list().querySelectorAll(".owner-dispatch-item").length,0);
    assert.equal(f.w.document.querySelectorAll(".owner-dispatch-item button").length,0);
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>result([{
      ...paidItem,card_name:"<script>alert('x')</script>",
      customer_email:"buyer@example.test",shipping_address:"Private buyer home",
    }]));
    await tick();await tick();
    assert.equal(f.list().querySelectorAll(".owner-dispatch-item").length,1);
    assert.equal(f.list().querySelectorAll("script").length,0);
    assert.match(f.list().textContent,/<script>alert\('x'\)<\/script>/);
    assert.match(f.list().textContent,/Sender \/ custody not verified/);
    assert.doesNotMatch(f.list().textContent,/buyer@example.test|Private buyer home/);
    assert.equal(f.list().querySelectorAll(".owner-dispatch-remote-check").length,1);
    assert.equal(f.list().querySelectorAll(".owner-dispatch-fulfill").length,1);
    assert.equal(f.list().querySelectorAll("button:not(.owner-dispatch-remote-check):not(.owner-dispatch-fulfill)").length,0);
    f.finish();checks++;
  }
  {
    const outstanding=pending();
    const f=fixture(()=>outstanding.promise);
    f.run('activateOwnerView("inventory",false)');
    outstanding.resolve(result([paidItem]));
    await tick();await tick();
    assert.equal(f.list().querySelectorAll(".owner-dispatch-item").length,0,
      "Response from left-behind Sales view must not render");
    f.finish();checks++;
  }
  {
    let calls=0;
    const f=fixture(async()=>{
      calls++;
      if(calls===1)return result([paidItem],26);
      return result([{...paidItem,inventory_code:"INV-SECOND"}],26);
    });
    await tick();await tick();
    f.w.document.getElementById("owner-dispatch-next").click();
    await tick();await tick();
    assert.equal(f.requests.length,2);
    assert.match(f.requests[1],/offset=25/);
    assert.match(f.list().textContent,/INV-SECOND/);
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>{throw new Error("Private provider failure and buyer info");});
    await tick();await tick();
    assert.match(f.status(),/Unable to verify dispatch/);
    assert.doesNotMatch(f.status(),/Private provider|buyer info/);
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>result([paidItem]));
    await tick();await tick();
    const button=f.list().querySelector(".owner-dispatch-remote-check");
    assert.equal(button.textContent,"Check Shopify");
    button.click();await tick();await tick();
    assert.match(f.list().textContent,/Shopify checked/);
    assert.match(f.list().textContent,/No label purchased/);
    assert.doesNotMatch(f.list().textContent,/must not be shown/);
    assert.ok(f.requests.some(x=>x.endsWith("/shopify") && x.includes(paidItem.order_item_id)));
    f.finish();checks++;
  }
  {
    const f=fixture();
    await tick();await tick();
    f.w.document.getElementById("owner-dispatch-shopify-check").click();
    await tick();await tick();
    assert.match(f.w.document.getElementById("owner-dispatch-shopify-status").textContent,/Shopify connected/);
    assert.match(f.w.document.getElementById("owner-dispatch-shopify-status").textContent,/Label purchases still require/);
    assert.ok(f.requests.includes("/api/v1/fulfilment/shopify-status"));
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>result([paidItem]));
    await tick();await tick();
    const card=f.list().querySelector(".owner-dispatch-item");
    card.querySelector(".owner-dispatch-fulfill").click();
    await tick();await tick();
    const modal=f.w.document.getElementById("owner-fulfill-dialog");
    assert.equal(modal.open,true);
    assert.match(modal.textContent,/Fulfill #1009/);
    const packing=f.w.document.getElementById("owner-fulfill-print-packing");
    assert.equal(packing.disabled,false,"Paid Shopify items should allow verified packing slip printing");
    assert.equal(f.w.document.getElementById("owner-fulfill-print-label").disabled,true);
    assert.equal(f.w.document.getElementById("owner-fulfill-confirm").disabled,true);
    f.w.document.getElementById("owner-fulfill-close").click();
    assert.equal(modal.open,false);
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>result([{...paidItem,order_status:"PARTIALLY_REFUNDED"}]));
    await tick();await tick();
    f.list().querySelector(".owner-dispatch-fulfill").click();
    await tick();await tick();
    assert.equal(f.w.document.getElementById("owner-fulfill-print-packing").disabled,true);
    assert.equal(f.w.document.getElementById("owner-fulfill-print-label").disabled,true);
    assert.equal(f.w.document.getElementById("owner-fulfill-confirm").disabled,true);
    f.finish();checks++;
  }
  {
    const f=fixture(async()=>result([paidItem]));
    await tick();await tick();
    const popup=new JSDOM("<!doctype html><html><head></head><body></body></html>", {
      url:"about:blank",pretendToBeVisual:true
    });
    let printed=0;
    popup.window.print=()=>{printed++;};
    f.w.open=()=>popup.window;
    f.list().querySelector(".owner-dispatch-fulfill").click();
    await tick();await tick();
    assert.equal(f.w.document.getElementById("owner-fulfill-print-packing").disabled,false);
    f.w.document.getElementById("owner-fulfill-print-packing").click();
    await tick();await tick();
    assert.equal(printed,1,"A valid Shopify slip must invoke browser print");
    assert.match(popup.window.document.body.textContent,/Booster Pack OP17/);
    assert.match(popup.window.document.body.textContent,/INV-OWNER-COPY/);
    assert.doesNotMatch(popup.window.document.body.textContent,/private|secret|other seller/i);
    assert.ok(f.requests.some(url=>url.endsWith("/packing-slip")));
    assert.equal(f.w.document.getElementById("owner-fulfill-print-label").disabled,true);
    popup.window.close();f.finish();checks++;
  }
  {
    const pendingSlip=pending();
    const f=fixture(async()=>result([paidItem]));
    await tick();await tick();
    f.w.open=()=>({
      document:{body:{textContent:""},head:{},title:""},
      close:()=>{},focus:()=>{},print:()=>{}
    });
    f.list().querySelector(".owner-dispatch-fulfill").click();
    await tick();await tick();
    f.w.document.getElementById("owner-fulfill-close").click();
    assert.equal(f.w.document.getElementById("owner-fulfill-dialog").open,false);
    assert.equal(f.w.document.getElementById("owner-fulfill-print-label").disabled,true);
    f.finish();checks++;
  }
  console.log("Seller dispatch review: "+checks+" DOM scenarios passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
