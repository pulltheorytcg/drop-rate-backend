const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');

const source = fs.readFileSync(path.join(__dirname, '../../backend/app/static/media-condition.js'), 'utf8');
const dom = new JSDOM('<main id="media"></main>', {url:'https://example.test',runScripts:'outside-only'});
const {window:w} = dom;
const requests = [];
w.byId = id => w.document.getElementById(id);
w.sellerView = name => name === 'media' ? w.document.getElementById('media') : null;
w.activateSellerView = () => {};
w.state = {session:null};
w.showMessage = (id, message) => {w.byId(id).textContent = message || '';};
for (const dependency of ['applyMediaCandidateDefaults','refreshShopifyMediaButton',
  'refreshBatchMediaPreview','uploadFounderMedia','uploadFounderMediaBatch']) {
  w[dependency] = () => {};
}
w.apiRequest = async (url, options = {}) => {
  requests.push({url, ...options});
  return {message:'Staff decision recorded'};
};
vm.runInContext(source, dom.getInternalVMContext());

const item = {id:'photo-1',version:7,name:'Deadpool / Batman #1',side:'FRONT',
  inventory_code:'COMIC-42',seller_name:'Consignor',approval_status:'PENDING',
  shopify_file_status:'READY',shopify_cdn_url:'https://cdn.shopify.com/s/files/cover.jpg'};
const queue = () => w.byId('comic-photo-review-queue');
const button = label => [...queue().querySelectorAll('button')].find(b => b.textContent === label);
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  w.renderComicReviewQueue({items:[item]});
  const preview = queue().querySelector('img');
  assert.ok(preview, 'Shopify CDN photo preview must be available');
  assert.equal(button('Approve exact photo').disabled, true, 'Unseen photo cannot be approved');
  preview.dispatchEvent(new w.Event('error'));
  assert.equal(button('Approve exact photo').disabled, true, 'Broken preview cannot be approved');
  assert.equal(requests.length,0);

  const retake = button('Request retake');
  retake.click();
  assert.equal(requests.length,0,'Retake requires a written reason');
  const textarea = queue().querySelector('textarea');
  textarea.value = 'Cover printing and issue number are obscured';
  retake.click();
  await tick();
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/api/v1/shopify/comic-review/photo-1/decision');
  assert.deepEqual(JSON.parse(requests[0].body),{version:7,decision:'RETAKE',reason:textarea.value});

  w.renderComicReviewQueue({items:[{...item,shopify_cdn_url:'https://malicious.example/cover.jpg'}]});
  assert.equal(queue().querySelector('img'),null,'Do not render third-party submitted preview URLs');
  assert.equal(button('Approve exact photo'),undefined);
  assert.ok(button('Refresh photo status'));
  for (const renderer of ['renderShopifyMedia','renderConditionQueue','renderFreeMediaStatus','renderFreeMediaReviewQueue']) {
    w[renderer] = () => {};
  }
  w.state.session = {access_token:'founder-session'};
  w.apiRequest = async url => {
    if (url === '/api/v1/shopify/comic-review/queue') throw new Error('Migration not available');
    return {};
  };
  await w.loadMediaConditionWorkspace();
  assert.match(queue().textContent,/Comic photo queue is temporarily unavailable.*Migration not available/);
  assert.equal(w.byId('shopify-media-message').textContent,'',
    'A comic-only failure must not block other media and condition tools');
  console.log('Comic photo review UI: preview gate, retake reason and CDN allowlist passed');
  w.close();
})().catch(error => {console.error(error);process.exitCode = 1;w.close();});
