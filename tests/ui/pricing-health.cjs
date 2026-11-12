const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {JSDOM} = require("jsdom");
const root = path.resolve(__dirname, "../..");
const client = fs.readFileSync(path.join(root, "backend/app/static/pricing-health-widget.js"), "utf8");
const owner = fs.readFileSync(path.join(root, "backend/app/static/owner.html"), "utf8");
const legacy = fs.readFileSync(path.join(root, "backend/app/main.py"), "utf8");
const wait = () => new Promise(resolve => setImmediate(resolve));

function fixture({founder = true, ownerMode = true} = {}) {
  const html = ownerMode ?
    owner.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "") :
    '<!doctype html><html><body><section data-seller-view="settings"></section></body></html>';
  const dom = new JSDOM(html,{url:"https://app.droprate.co.uk/owner#settings",
    pretendToBeVisual:true,runScripts:"outside-only"});
  const w = dom.window, doc = w.document, ctx = dom.getInternalVMContext();
  const calls = [], errors = [];
  w.addEventListener("error",event => errors.push(event.error));
  const payload = {
    checked_at:"2026-11-12T19:45:00Z",overall_status:"BLOCKED",
    overall_label:"Sold-price evidence blocked",
    inventory:{active_items:617,stored_value_items:244,
      updated_last_7d:73,missing_value_items:373,stored_coverage_pct:39.5},
    sources:[
      {source:"EBAY_UK_SOLD",label:"eBay UK completed sales",
        role:"ACTUAL_SOLD_EVIDENCE",status:"VERIFICATION_BLOCKED",
        stored_observations:1083,normalized_uk_sold_observations:0,
        new_normalized_24h:0,last_ingested_at:"2026-11-01T23:02:00Z",
        last_run:{status:"FAILED",completed_at:"2026-11-10T01:54:00Z"},
        detail:"<script>bad</script> is just text"},
      {source:"CARDMARKET_GUIDE",label:"Cardmarket price guides",status:"STALE_CONTEXT",
        stored_observations:5238,detail:"Guide context only"},
    ],
    automation:{market_ingestion_enabled:false,bulk_refresh_held:true,
      unattended_product_research_verified:false,automatic_sold_value_publication_ready:false},
    alerts:[{severity:"CRITICAL",text:"No qualifying UK sold evidence in 24 hours."}],
  };
  w.pricingHealthRequest = async url => {
    calls.push(url);
    if (url !== "/api/v1/pricing/health") throw Error("Unexpected route");
    return payload;
  };
  const enabled = founder ? "true" : "false";
  vm.runInContext("var state={session:{user:{id:'test-user'},access_token:'token'},access:{business_allowed:"+enabled+"}};" +
    "var apiRequest=window.pricingHealthRequest;",ctx);
  vm.runInContext(client,ctx,{filename:"pricing-health-widget.js"});
  if (ownerMode) {
    doc.getElementById("owner-portal-view").classList.remove("hidden");
    doc.getElementById("owner-view-settings").classList.remove("hidden");
    doc.dispatchEvent(new w.CustomEvent("hub:access-verified",
      {detail:{access:{business_allowed:founder}}}));
  } else {
    doc.dispatchEvent(new w.Event("hub-ready"));
  }
  return {w,doc,ctx,calls,errors,close:()=>w.close()};
}

(async () => {
  assert.match(owner,/pricing-health-widget\.js/, "Owner settings loads the founder health widget");
  assert.match(owner,/pricing-health\.css/, "Owner settings styles the health widget");
  assert.match(legacy,/pricing-health-widget\.js/, "Legacy Founder HQ loads the same health widget");
  for(const [founder,ownerMode] of [[false,true],[true,true],[true,false]]) {
    const f=fixture({founder,ownerMode});
    await wait();await wait();
    const panel=f.doc.getElementById("pricing-health-panel");
    assert.ok(panel,"Widget mounted in real settings view");
    assert.equal(panel.hidden,ownerMode && !founder,"Ordinary seller cannot view founder panel");
    if(founder) {
      assert.ok(f.calls.includes("/api/v1/pricing/health"),"Founder obtains live backend telemetry");
      assert.match(f.doc.getElementById("pricing-health-banner").textContent,/Sold-price evidence blocked/);
      assert.match(f.doc.getElementById("pricing-health-metrics").textContent,/617/);
      assert.match(f.doc.getElementById("pricing-health-metrics").textContent,/244/);
      assert.match(f.doc.getElementById("pricing-health-sources").textContent,/1,083/);
      assert.equal(f.doc.querySelectorAll(".pricing-health-source").length,2);
      assert.equal(f.doc.querySelectorAll(".pricing-health-sources script").length,0,
        "Untrusted provider fields rendered as text only");
      assert.match(f.doc.getElementById("pricing-health-time").textContent,/Bulk hold: active/);
      f.doc.getElementById("pricing-health-refresh").click();
      await wait();
      assert.ok(f.calls.length>=2,"Founder can manually refresh health without repricing");
      if(ownerMode) {
        vm.runInContext("state.session=null;state.access=null;",f.ctx);
        f.w.dispatchEvent(new f.w.Event("hub-session-cleared"));
        assert.equal(panel.hidden,true,"Logout immediately hides founder telemetry");
        assert.equal(f.doc.getElementById("pricing-health-metrics").children.length,0,
          "Logout erases prior account telemetry");
      }
    } else {
      assert.equal(f.calls.length,0,"Ordinary seller never calls founder health API");
    }
    assert.equal(f.errors.length,0,"No browser exceptions");
    f.close();
  }
  console.log("PASS: live pricing health in owner and legacy founder settings, privacy, sold-only labels, refresh and logout cleanup.");
})().catch(error => {console.error(error);process.exitCode=1;});
