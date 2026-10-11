"""Temporary preparation for a reviewed feature branch; no live database access."""
from pathlib import Path

def replace(path, before, after, count=1):
    p=Path(path); s=p.read_text(); assert s.count(before)==count,(path,'Source changed; stop');p.write_text(s.replace(before,after))

replace('backend/app/api.py','    "cards.tcggraph.io",\n}', '    "cards.tcggraph.io",\n    "cardtrader.com",\n    "www.cardtrader.com",\n    "www.dbs-cardgame.com",\n    "narutocardgame.gg",\n}')
replace('backend/app/api.py','        parsed = urlparse(url)\n    except ValueError:', '        parsed = urlparse(url)\n        if parsed.port not in (None, 443):\n            return False\n    except ValueError:',2)
p=Path('backend/app/api.py');s=p.read_text();start=s.index('            where ma.owner_id = $1',s.index('async def inventory_card_image'));end=s.index('            order by',start)
s=s[:start]+'''            where ma.side = 'FRONT'
              and ma.media_kind = 'IMAGE'
              and ma.source_status = 'ACTIVE'
              and ma.rights_status = 'VERIFIED'
              and ma.approval_status in ('PENDING','APPROVED')
              and ma.revoked_at is null
              and coalesce(nullif(btrim(ma.shopify_cdn_url),''),nullif(btrim(ma.public_source_url),'')) is not null
              and (
                (ma.scope = 'INVENTORY_ITEM' and ma.inventory_id = $2 and ma.owner_id = $1)
                or
                (ma.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
                 and ma.inventory_id is null and ma.catalogue_id = $3
                 and (ma.approval_status='APPROVED' or ma.owner_id=$1)
                 and ma.rights_tier='STOREFRONT_ALLOWED'
                 and exists (
                   select 1 from tcg.catalogue_products p
                   join tcg.inventory_items i on i.catalogue_id=p.id
                   where i.id=$2 and i.owner_id=$1 and p.id=$3
                     and lower(btrim(coalesce(ma.media_language,'')))=lower(btrim(coalesce(i.language,p.language,'')))
                     and lower(btrim(coalesce(ma.media_variant,'')))=lower(btrim(coalesce(p.variant,'')))
                 ))
              )
'''+s[end:];p.write_text(s)
replace('backend/app/api.py','    Dashboard display eligibility is deliberately separate from exact-print\n    recognition approval. Pending but rights-verified images may display.','    Shared by Founder HQ and Seller Hub. Authorize the physical item first;\n    canonical artwork follows catalogue identity, never its uploader\'s account.\n    Only approved canonical artwork is shared across owners. A holder may still\n    preview their own pending, rights-verified media. No publication approval,\n    inventory duplication, or foreign physical-photo access is implied.')
replace('backend/app/api.py','"User-Agent": "DropRateFounderHQ/1.0"','"User-Agent": "DropRateInventory/1.0"')
replace('backend/app/api.py','"X-Drop-Rate-Media-Provider": str(asset["source_provider"] or ""),','"X-Drop-Rate-Media-Provider": str(asset["source_provider"] or ""),\n                        "X-Drop-Rate-Media-Scope": str(asset["scope"]),\n                        "Cache-Control": "private, no-store",\n                        "Vary": "Authorization",\n                        "X-Content-Type-Options": "nosniff",')
p=Path('backend/app/static/owner-inventory.js');s=p.read_text();start=s.index('  function image(item, cls) {');end=s.index('\n  function close(',start);s=s[:start]+r'''  function image(item, cls) {
    const wrap = el("div", cls), placeholder = el("span", "owner-image-placeholder", "Loading image…");
    const img = el("img");
    img.alt = `${item.name || "Inventory item"} reference image`;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    wrap.append(placeholder, img);
    const owner = account(), attempts = [];
    const validId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.id || "");
    const directUrl = (value) => {
      try {
        const url = new URL(value);
        if (url.protocol !== "https:" || url.username || url.password || url.hash || (url.port && url.port !== "443")) return null;
        const host = url.hostname.toLowerCase();
        return host === "cdn.shopify.com" || host === "assets.tcgdex.net" || host.endsWith(".shopifycdn.com") || host.endsWith(".shopifycdn.net") ? url.href : null;
      } catch (_) { return null; }
    };
    // Same delivery route as Founder HQ; a provider's public URL need not work
    // in a browser. Send credentials ONLY to our owned-item API, never a CDN.
    const direct = directUrl(item.image_url);
    if (direct) attempts.push({url: direct});
    if (validId) attempts.push({path: `/api/v1/inventory/${item.id}/image`});
    const reference = directUrl(item.reference_image_url);
    if (reference && reference !== direct) attempts.push({url: reference});
    const referencePath = `/api/v1/owner/inventory/${item.id}/reference-image`;
    if (validId && item.reference_image_path === referencePath) attempts.push({path: referencePath});
    let index = 0, objectUrl = null, loading = false, started = false;
    const current = () => owner === account() && wrap.isConnected;
    const release = () => {if (objectUrl) {URL.revokeObjectURL(objectUrl); objectUrl = null;}};
    const unavailable = () => {release(); img.remove(); placeholder.textContent = "Image unavailable"; placeholder.hidden = false;};
    async function next() {
      if (loading || !current()) return;
      release();
      while (index < attempts.length && current()) {
        const attempt = attempts[index++];
        if (attempt.url) {img.src = attempt.url; return;}
        loading = true;
        try {
          const get = token => fetch(attempt.path, {headers: {Authorization: `Bearer ${token}`}, cache: "no-store"});
          let response = await get(state.session.access_token);
          if (response.status === 401 && current()) {
            const token = await refreshSession();
            if (!current()) return;
            response = await get(token);
          }
          if (!response.ok) throw new Error("Image unavailable");
          const blob = await response.blob();
          if (!current()) return;
          if (!/^image\/(png|jpeg|webp)$/.test(blob.type) || blob.size > 12 * 1024 * 1024) throw new Error("Invalid image response");
          objectUrl = URL.createObjectURL(blob); img.src = objectUrl; return;
        } catch (_) { /* Try only the next bounded, authenticated source. */ }
        finally {loading = false;}
      }
      if (current()) unavailable();
    }
    img.addEventListener("load", () => {release(); if (current()) placeholder.hidden = true; else img.remove();});
    img.addEventListener("error", next);
    const start = () => {if (!started) {started = true; next();}};
    if (!attempts.length) unavailable();
    else if (typeof window.IntersectionObserver === "function") {
      const observer = new window.IntersectionObserver(entries => {
        if (!current()) {observer.disconnect(); return;}
        if (entries.some(entry => entry.isIntersecting)) {observer.disconnect(); start();}
      }, {rootMargin: "320px 0px"});
      observer.observe(wrap);
    } else {
      // Queue after the caller inserts the returned element in the document.
      queueMicrotask(start);
    }
    return wrap;
  }
'''+s[end:];p.write_text(s)
replace('backend/app/static/owner.html','/assets/owner-inventory.js?v=7','/assets/owner-inventory.js?v=shared-art-v8')
replace('tests/ui/owner-inventory.cjs','w.scrollTo=()=>{};w.fetch=async()=>({ok:true,json:async()=>({})});',"w.scrollTo=()=>{};w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};w.fetch=async()=>({ok:true,json:async()=>({}),blob:async()=>new w.Blob(['image'],{type:'image/webp'})});")
replace('tests/ui/owner-inventory.cjs',"assert.equal(f.w.document.querySelector('.owner-card-thumb img').src,item.reference_image_url);","await tick();assert.equal(f.w.document.querySelector('.owner-card-thumb img').src,'blob:fixture');")
replace('tests/ui/owner-inventory.cjs',"img.dispatchEvent(new f.w.Event('error'));assert.equal(img.src,item.reference_image_url);img.dispatchEvent(new f.w.Event('error'));await tick();assert.equal(img.src,'blob:safe');","await tick();img.dispatchEvent(new f.w.Event('error'));await tick();assert.equal(img.src,'blob:safe');assert.equal(calls[0].url,`/api/v1/inventory/${id}/image`);")
replace('tests/ui/owner-inventory-browser.cjs',"    if(u.href===artwork)return route.fulfill({body:pack,contentType:'image/webp'});","    if(u.href===artwork)return route.fulfill({body:pack,contentType:'image/webp'});\n    if(u.pathname===`/api/v1/inventory/${item.id}/image`){assert.equal(route.request().headers().authorization,'Bearer isolated-fixture');return route.fulfill({body:pack,contentType:'image/webp'});}")
p=Path('BUILD_STATUS.md');p.write_text(p.read_text().replace('# Drop Rate — Live Build Status\n','# Drop Rate — Live Build Status\n\n## 11 October 2026 — Shared inventory artwork delivery (implementation; release verification pending)\n\nFounder HQ and Seller Hub now use the same bounded authenticated image route for provider-hosted inventory artwork. Catalogue artwork is selected by exact catalogue identity, independent of the uploading owner; physical photos remain restricted to the exact owned copy. Seller images load near the viewport, use trusted CDN fast paths, and fall back through the shared route/reference endpoint without forwarding credentials to providers. An additive SELECT-only policy covers approved shared CANONICAL_PRODUCT media, matching the already shared card-art concept. No inventory, import, price, ownership, listing or finance write. See docs/SHARED_INVENTORY_IMAGES.md. Real database and browser tests, migration, deployment, live source checks and real signed-in acceptance are separately reported.\n',1))
