const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const money=value=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(value/100);
const estimate=(patch={})=>({status:'UK_EU_MARKET_ESTIMATE',method:'DROP_RATE_UK_EU_MARKET_V1',
 label:'Drop Rate UK/EU estimate',currency:'GBP',estimate_minor:1234,estimate_low_minor:1100,estimate_high_minor:1400,
 confidence:.60,observed_at:new Date(Date.now()-60000).toISOString(),expires_at:new Date(Date.now()+3600000).toISOString(),
 shipping_basis:'ITEM_ONLY',physical_valuation_eligible:false,source_estimates:[],
 reason:'Calculated from eBay UK asking prices and Cardmarket guides. Provisional; not a completed-sale value.',...patch});
const card={key:'c:00000000-0000-0000-0000-000000000001',catalogue_id:'card-1',name:'Fixture card',
 game:'One Piece',system_code:'ONE_PIECE_CARD_GAME',set_name:'Fixture release',set_id:'OP11',language:'English',
 product_type:'CARD',variant:'Foil',card_number:'OP11-118',owned_quantity:0,market_value_minor:null,source_kind:'CATALOGUE'};
function fixture(){
 const dom=new JSDOM('',{runScripts:'outside-only',url:'https://example.test'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.eval(fs.readFileSync(path.join(base,'reference-value-display.js'),'utf8'));
 w.eval(fs.readFileSync(path.join(base,'catalogue-browser.js'),'utf8'));
 const browser=new w.DropRateCatalogue.Browser({client:{owner:'owner',active:()=>true,request:async()=>({keys:[]})},
 navigate:()=>{},scan:()=>{},graded:()=>{},afterSave:async()=>{}});
 return {w,browser,finish:()=>{browser.destroy();w.close();}};
}
let checks=0;
// Render the server estimate across each supported product type without mutating values.
for(const type of ['CARD','SEALED','COMIC','FIGURE']){
 const f=fixture(),row={...card,product_type:type,uk_eu_market_estimate:estimate()},original=JSON.stringify(row);
 f.browser.rows=[row];f.browser.renderRows();
 assert.equal(f.browser.find('[data-price-key]').textContent,'Drop Rate UK/EU estimate: £12.34');
 f.browser.openProduct(row);
 assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Drop Rate UK/EU estimate: £12.34');
 assert.match(f.browser.sheet.textContent,/Provisional; not a completed-sale value/);
 assert.match(f.browser.sheet.textContent,/Reference range: £11.00–£14.00 · Item price only; postage excluded/);
 assert.equal(JSON.stringify(row),original);
 f.finish();checks++;
}
// Existing prices stay primary; the model is an explicitly labelled additional reference.
for(const stronger of [{market_value_minor:900,market_value_source:'CARDMARKET_BULK_SINGLES'},
 {shared_price:{status:'CONDITION_REFERENCE',market_value_minor:900,label:'Exact condition reference'}},
 {shared_price:{status:'AVAILABLE',market_value_minor:900}},
 {shared_price:{status:'CATALOGUE_GUIDE',market_value_minor:900}}]){
 const f=fixture(),row={...card,...stronger,uk_eu_market_estimate:estimate()};
 f.browser.rows=[row];f.browser.renderRows();
 assert.equal(f.browser.find('[data-price-key]').textContent,'Value: £9.00');
 assert.equal(f.browser.find('[data-uk-eu-estimate-key]').textContent,'Drop Rate UK/EU estimate: £12.34');
 f.browser.openProduct(row);
 assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Value: £9.00');
 assert.match(f.browser.sheet.textContent,/Drop Rate UK\/EU estimate: £12.34/);
 f.finish();checks++;
}
// Invalid or expired model evidence cannot be presented as a current reference.
for(const patch of [{method:'unknown'},{currency:'USD'},{shipping_basis:'UNKNOWN'},{physical_valuation_eligible:true},
 {estimate_minor:'1234'},{estimate_minor:0},{estimate_minor:12.5},{estimate_low_minor:1400},{estimate_high_minor:1100},
 {confidence:.99},{confidence:NaN},{observed_at:'invalid'},{expires_at:'invalid'},
 {observed_at:new Date(Date.now()+60000).toISOString()},{expires_at:new Date(Date.now()-60000).toISOString()}]){
 const f=fixture();f.browser.openProduct({...card,uk_eu_market_estimate:estimate(patch)});
 assert.equal(f.browser.sheet.querySelector('.dr-browse-detail-value').textContent,'Value unavailable');
 assert.doesNotMatch(f.browser.sheet.textContent,/Drop Rate UK\/EU estimate/);
 f.finish();checks++;
}
// Inventory uses a catalogue guide label only, never a retail recommendation.
{
 const f=fixture(),ref=f.w.DropRateReferenceValue,model=estimate({status:'CATALOGUE_GUIDE',market_value_minor:1234,recommended_retail_minor:9900}),
 item={market_value_minor:null,catalogue_reference:model,store_price_minor:555};
 assert.equal(ref.text(item,money),'Drop Rate UK/EU estimate: £12.34');
 assert.equal(ref.label(item),'Drop Rate UK/EU estimate');
 assert.equal(ref.recommendedMinor(item),null);
 assert.equal(item.store_price_minor,555);
 for(const status of ['AVAILABLE','REFERENCE_ESTIMATE','CONDITION_REFERENCE']){
  const stronger={...item,reference_value:{status,market_value_minor:900,recommended_retail_minor:1000}};
  assert.equal(ref.text(stronger,money),'Value: £9.00');
 }
 assert.equal(ref.recommendedMinor({reference_value:{...model,status:'AVAILABLE'}}),null);
 assert.equal(ref.text({...item,catalogue_reference:{...model,expires_at:'2000-01-01T00:00:00Z'}},money),'Value unavailable');
 f.finish();checks++;
}
// Provider text stays text, including malicious-looking content.
{
 const f=fixture();f.browser.openProduct({...card,uk_eu_market_estimate:estimate({reason:'<img src=x onerror=alert(1)><script>unsafe</script>'})});
 assert.match(f.browser.sheet.textContent,/<img src=x/);
 assert.equal(f.browser.sheet.querySelector('.dr-browse-price-details img,.dr-browse-price-details script'),null);
 f.finish();checks++;
}
console.log(`${checks} UK/EU estimate display checks passed`);
