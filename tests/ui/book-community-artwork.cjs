const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../../backend/app/static');
const source=name=>fs.readFileSync(path.join(base,name),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const id='00000000-0000-4000-8000-000000000001';
const cover={kind:'OPEN_LIBRARY_EDITION_REFERENCE',provider:'OPEN_LIBRARY',edition_id:'OL8537239M',language:'English',
  image_url:'https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false',
  detail_image_url:'https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false',
  source_url:'https://openlibrary.org/books/OL8537239M',scope:'COMMUNITY_EDITION',status:'REFERENCE_ONLY'};
const book={id,catalogue_id:id,key:'c:'+id,product_type:'COMIC',system_code:'MANGA',name:'+Anima Volume 1',
  language:'English',market_value_minor:null,community_cover:cover,artwork_kind:cover.kind,
  book_details:{system_code:'MANGA',series_title:'+Anima',issue_number:'1',publisher:'Tokyopop',book_format:'MANGA',language:'English',release_year:2006,barcode_gtin:'9781598163476'}};
function fixture(html='') {
  const dom=new JSDOM(html,{url:'https://example.test/owner',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,run=code=>vm.runInContext(code,dom.getInternalVMContext());
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=async()=>{throw new Error('Community images must use direct img src, never fetch');};
  run('const state={session:{user:{id:"seller-a"},access_token:"private-token"}};');
  run(source('book-community-artwork.js'));
  return {w,run,finish:()=>w.close()};
}
function imageContract(img,url) {
  assert.equal(img.src,url);assert.equal(img.loading,'lazy');
  assert.equal(img.referrerPolicy,'no-referrer');assert.equal(img.decoding,'async');
  assert.match(img.alt,/community cover reference/i);
}
(async()=>{
  let checks=0;
  {
    const f=fixture();assert.equal(f.w.DropRateBookArtwork.reference(book).image_url,cover.image_url);
    for(const changes of [
      {image_url:cover.image_url.replace('covers.openlibrary.org','covers.openlibrary.org.evil.test')},
      {image_url:cover.image_url+'&url=https://example.test'}, {source_url:'javascript:alert(1)'},
      {edition_id:'OL8537239W'}, {scope:'APPROVED'}, {status:'VERIFIED'},
      {detail_image_url:'https://covers.openlibrary.org/b/isbn/9781598163476-L.jpg'},
    ])assert.equal(f.w.DropRateBookArtwork.reference({...book,community_cover:{...cover,...changes}}),null);
    assert.equal(f.w.DropRateBookArtwork.reference({...book,language:'Japanese'}),null);
    assert.equal(f.w.DropRateBookArtwork.reference({...book,product_type:'CARD'}),null);
    f.finish();checks++;
  }
  {
    const f=fixture();f.run(source('catalogue-browser.js'));
    const browser=new f.w.DropRateCatalogue.Browser({client:{owner:'seller-a',active:()=>true,request:async()=>({items:[]})},books:()=>{throw new Error('Source link must not launch intake');}});
    let proxy=0;browser.loadReferenceImage=()=>{proxy++;};
    browser.rows=[book];browser.renderRows();
    const img=browser.dialog.querySelector('.dr-browse-product-image img');imageContract(img,cover.image_url);
    assert.equal(proxy,0);
    const sourceLink=browser.dialog.querySelector('.dr-browse-product a');
    assert.equal(sourceLink.closest('button'),null,'No anchors inside product-selection buttons');
    assert.equal(sourceLink.href,cover.source_url);assert.equal(sourceLink.rel,'noopener noreferrer');
    let bubbled=0;sourceLink.parentElement.parentElement.addEventListener('click',()=>bubbled++);
    sourceLink.addEventListener('click',event=>event.preventDefault());sourceLink.click();assert.equal(bubbled,0);
    img.dispatchEvent(new f.w.Event('error'));
    assert.equal(browser.dialog.querySelector('.dr-browse-product-image img'),null);
    assert.match(browser.dialog.querySelector('.dr-browse-product-image').textContent,/Image unavailable/);
    assert.equal(proxy,0,'A 404 must not start an ISBN, title, proxy or retry fallback');
    browser.openProduct(book);imageContract(browser.sheet.querySelector('img'),cover.detail_image_url);
    assert.match(browser.sheet.textContent,/Cover reference.*Open Library.*Cover may vary/);
    assert.doesNotMatch(browser.sheet.textContent,/Verified cover|Publisher reference cover/);
    const preferred=browser.productImage({...book,image_url:'https://cdn.shopify.com/approved.jpg'});
    assert.equal(preferred.querySelector('img').src,'https://cdn.shopify.com/approved.jpg');
    browser.destroy();f.finish();checks++;
  }
  {
    const f=fixture();f.run(source('owner-inventory.js'));
    const panel=f.w.DropRateInventory.image(book,'owner-card-thumb');f.w.document.body.append(panel);await tick();
    imageContract(panel.querySelector('img'),cover.image_url);
    assert.match(panel.title,/Open Library cover reference.*Cover may vary/);
    panel.querySelector('img').dispatchEvent(new f.w.Event('error'));await tick();
    assert.equal(panel.querySelector('img'),null);assert.match(panel.textContent,/Image unavailable/);
    const preferred=f.w.DropRateInventory.image({...book,image_url:'https://cdn.shopify.com/copy.jpg'},'owner-item-art');
    f.w.document.body.append(preferred);await tick();assert.equal(preferred.querySelector('img').src,'https://cdn.shopify.com/copy.jpg');
    f.finish();checks++;
  }
  {
    const f=fixture(source('owner.html').replace(/<script[^>]*><\/script>/g,''));
    f.run('async function apiRequest(){return {status:"UNAVAILABLE",market_value_minor:null};} async function loadOwnerInventory(){} async function loadOwnerOverview(){}');
    f.run(source('owner-books.js'));f.w.DropRateBooks.open({book:book.book_details,catalogue:book});
    const preview=f.w.document.getElementById('owner-book-selected'),img=preview.querySelector('img');
    imageContract(img,cover.detail_image_url);
    assert.match(preview.textContent,/Cover reference.*Open Library.*Cover may vary/);
    assert.equal(f.w.document.getElementById('owner-book-printing').value,'');
    assert.equal(f.w.document.getElementById('owner-book-condition').value,'');
    img.dispatchEvent(new f.w.Event('error'));assert.equal(preview.querySelector('img'),null);
    assert.match(preview.textContent,/Cover unavailable/);f.finish();checks++;
  }
  {
    const f=fixture();
    // Execute the actual founder renderer without bootstrapping account APIs.
    const app=source('app.js'),start=app.indexOf('function inventoryImageFigure(item) {'),end=app.indexOf('\nfunction inventoryVisualCard(',start);
    f.run('function openInventoryCopies(){throw new Error("Unexpected selection");}\n'+app.slice(start,end));
    f.w.bookFixture=book;const figure=f.run('inventoryImageFigure(bookFixture)');f.w.document.body.append(figure);
    imageContract(figure.querySelector('img'),cover.image_url);
    assert.equal(figure.dataset.imageState,'community-reference');
    assert.match(figure.textContent,/Cover reference.*Cover may vary/);
    figure.querySelector('img').dispatchEvent(new f.w.Event('error'));
    assert.equal(figure.querySelector('img'),null);assert.match(figure.textContent,/Cover unavailable/);
    f.finish();checks++;
  }
  for(const htmlName of ['owner.html','index.html']){
    const html=source(htmlName);assert.ok(html.includes('/assets/book-community-artwork.js?v=1'));
    assert.ok(html.indexOf('/assets/book-community-artwork.js')<html.indexOf(htmlName==='owner.html'?'/assets/owner-inventory.js':'/assets/app.js'));
  }
  console.log(`book community artwork: ${checks} behavioral groups passed`);
})().catch(error=>{console.error(error);process.exit(1);});
