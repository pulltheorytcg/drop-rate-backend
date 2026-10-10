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
  w.fetch=async()=>({ok:true,json:async()=>({})});
  const run=(src)=>vm.runInContext(src,context);
  const portal=fs.readFileSync(path.join(root,"owner-portal.js"),"utf8")
    .replace(/\ninitialise\(\);\s*$/,"");
  run(portal);
  w.__mockDispatchApi=async(url)=>{
    requests.push(url);
    if(!url.startsWith("/api/v1/fulfilment/to-ship?"))
      throw new Error("Unexpected API call "+url);
    return handler(url);
  };
  run("apiRequest=window.__mockDispatchApi;");
  run(fs.readFileSync(path.join(root,"owner-fulfillment.js"),"utf8"));
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
    assert.equal(f.list().querySelectorAll("button").length,0);
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
  console.log("Seller dispatch review: "+checks+" DOM scenarios passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
