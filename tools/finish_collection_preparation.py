"""Branch-only preparation companion; removed before PR."""
from pathlib import Path

def replace(path,old,new,count=1):
    f=Path(path);s=f.read_text();assert s.count(old)==count,(path,old[:70],s.count(old));f.write_text(s.replace(old,new))

replace('tests/owner_inventory_postgres.py',"        print('Seller inventory PostgreSQL:","        from collection_selling_postgres import verify_collection_selling\n        await verify_collection_selling(db,pool,request,user,access,foreign)\n        print('Seller inventory PostgreSQL:")
replace('tests/test_whatnot_owner_connection_readiness.py',"state:\"Personal seller connection awaiting Whatnot API access\"","state:\"Not connected in Drop Rate — publishing unavailable\"")
replace('tests/test_whatnot_owner_connection_readiness.py',"assert 'Personal seller connection' in ITEM","assert 'Whatnot is not connected in this workflow' in ITEM")
replace('tests/ui/owner-inventory.cjs','/Personal seller connection awaiting Whatnot API access/','/Not connected in Drop Rate — publishing unavailable/')
replace('tests/ui/owner-inventory.cjs',"assert.ok(modal.querySelector('.owner-item-section h3').textContent==='Selling price');","assert.equal(modal.querySelector('.owner-item-selling summary').textContent,'Manage listing');\n  assert.ok(modal.querySelector('.owner-item-selling').open);")
# Readback always derives the exact versioned URL from the committed page instead
# of pinning an obsolete version that fails on the next reviewed feature.
p='.github/workflows/shared-inventory-images.yml'
replace(p,'import hashlib,json,time,urllib.request,urllib.error','import hashlib,json,re,time,urllib.request,urllib.error')
replace(p,"          result={}\n", "          asset=re.search(r'src=\"([^\"]*owner-inventory\\.js\\?v=[^\"]+)\"',Path('backend/app/static/owner.html').read_text()).group(1)\n          result={}\n")
replace(p,"base+'/assets/owner-inventory.js?v=shared-art-v8'","base+asset")
replace(p,"assert b'owner-inventory.js?v=shared-art-v8' in response.read()","assert asset.encode() in response.read()")
# Keep the current status document; historical entries are not overwritten.
p=Path('BUILD_STATUS.md');s=p.read_text();header='# Drop Rate — Live Build Status\n'
assert s.startswith(header)
entry='''
## 11 October 2026 — Collection-first confirmation / separate selling (implementation; release evidence pending)

The existing scanner now saves a confirmed selection immediately, without a second whole-queue save or waiting for uncertain neighbours. Newly added scan/manual/CSV physical copies explicitly start DRAFT / PERSONAL_COLLECTION. Missing raw condition, acquisition cost, selling price or market value does not block collection admission. Canonical language is reused with conflict checks; owner/request locking and retry receipts prevent duplicate submissions. Pricing is no longer awaited inside the scan save transaction.

Seller inventory keeps selling fields and channel controls under an optional List for sale disclosure. Raw condition can be supplied in that explicit versioned listing request; existing raw/slab selling review and channel publication guards remain. Approved sealed selling is unchanged. No account merge, existing-row rewrite, overlapping-import reconciliation, media-policy relaxation, channel activation, product/theme publication, migration, new service or n8n flow. The existing overlapping Draft import and explicit hold remain separate work. #607 shared-artwork loading is preserved.

See docs/COLLECTION_FIRST_INTAKE.md. Source checks, real restricted PostgreSQL/signed HTTP, mocked browser tests, exact deployment/readback and real physical-device acceptance are distinct. PR release comment must record actual results; this entry is not evidence that deployment or signed-in production acceptance passed.

'''
p.write_text(header+entry+s[len(header):])
print('Updated dependent tests, dynamic asset readback, and bounded build status. No production mutation.')
