"""One-shot branch preparation; removed before PR, never executed in production."""
from pathlib import Path
import hashlib
import re
import subprocess

ROOT=Path.cwd()
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()=='fix/collection-first-confirmation-20261011'
for path,sha in {'backend/app/owner_portal_api.py':'5f1aed9e146e6168be8334de1824e5f4b8fe63a8','backend/app/static/scanner-flow.js':'c13ef972752050edeaf1f4f4d11b5399bf09f7e8','backend/app/owner_inventory.py':'f1ab59df57efa2d11896ded1446a5a53e40a6c1c'}.items():
    assert subprocess.check_output(['git','hash-object',path],text=True).strip()==sha, 'Concurrent source change: '+path

def edit(path,old,new,count=1):
    f=ROOT/path;s=f.read_text();assert s.count(old)==count,(path,old[:90],s.count(old));f.write_text(s.replace(old,new))

api='backend/app/owner_portal_api.py'
edit(api,'from pydantic import BaseModel, Field, model_validator','from pydantic import BaseModel, ConfigDict, Field, model_validator')
edit(api,'class OwnerRecognitionIntakeRequest(BaseModel):\n','class OwnerRecognitionIntakeRequest(BaseModel):\n    model_config = ConfigDict(extra="forbid")\n')
edit(api,'class OwnerGradedCertificateIntakeRequest(BaseModel):\n','class OwnerGradedCertificateIntakeRequest(BaseModel):\n    model_config = ConfigDict(extra="forbid")\n')
edit(api,'        if self.condition is None and self.grading_company is None and self.seal_status is None:\n            raise ValueError("Choose a raw-card condition, provide grading details, or provide seal status")\n','        # Unknown raw condition is allowed in a collection, never guessed as Near Mint.\n        # Type/grade conflicts are checked against the selected catalogue product.\n')
edit(api,'"status": inventory.get("status"),','"status": inventory.get("status"),\n            "sale_intent": inventory.get("sale_intent"),')
edit(api,"false,'DRAFT',$9,$10::jsonb,'FOR_SALE'","false,'DRAFT',$9,$10::jsonb,'PERSONAL_COLLECTION'")
edit(api,"$11,'DRAFT',$12,$13::jsonb,'FOR_SALE'","$11,'DRAFT',$12,$13::jsonb,'PERSONAL_COLLECTION'")
edit(api,'''        try:
            valuation = await _recalculate_one(connection, owner_id, inventory_id)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            valuation_error = str(exc.detail)
''','''        # Pricing uses the existing separate refresh operation. Missing evidence
        # or a provider failure must not delay or roll back collection admission.
''',2)
edit(api,'''    ) as connection:
        existing = await connection.fetchrow(
            """
            select i.*
            from tcg.inventory_items i
            where i.owner_id=$1 and i.intake_request_key=$2
''','''    ) as connection:
        await connection.execute(
            "select pg_advisory_xact_lock(hashtextextended($1,0))",
            f"collection-intake:{owner_id}:{request_key}",
        )
        existing = await connection.fetchrow(
            """
            select i.*
            from tcg.inventory_items i
            where i.owner_id=$1 and i.intake_request_key=$2
''',2)
edit(api,'from .pricing import _recalculate_one','from .pricing import _recalculate_one\nfrom .language import clean_language')
edit(api,'def _owner_graded_payload_hash(','''def _collection_language(supplied: str | None, catalogue_language: str | None) -> str | None:
    supplied_clean = clean_language(supplied)
    catalogue_clean = clean_language(catalogue_language)
    if supplied_clean and catalogue_clean and supplied_clean != catalogue_clean:
        raise HTTPException(422, "Language conflicts with the selected printing. Choose the correct language/version.")
    return supplied_clean or catalogue_clean


def _owner_graded_payload_hash(''')
edit(api,'physical_language = payload.language or catalogue["language"]','physical_language = _collection_language(payload.language, catalogue["language"])',2)
edit('backend/app/inventory_intake.py','                intake_request_key\n            ) values (','                intake_request_key, sale_intent\n            ) values (')
edit('backend/app/inventory_intake.py','                $17\n            )',"                $17, 'PERSONAL_COLLECTION'\n            )")
edit('backend/app/import_inventory.py','import_batch_id,source_row,source_copy,source_record\n','import_batch_id,source_row,source_copy,source_record,sale_intent\n')
edit('backend/app/import_inventory.py',"false,'DRAFT','',$12,$13,$14,$15::jsonb)","false,'DRAFT','',$12,$13,$14,$15::jsonb,'PERSONAL_COLLECTION')")
scan='backend/app/static/scanner-flow.js'
edit(scan,'usableRun(item) && (sealed(item) || conditions.includes(item.condition))','usableRun(item) && (!item.condition || conditions.includes(item.condition))')
edit(scan,'item.condition || "Choose condition"','item.condition || "Not recorded — needed when selling"')
edit(scan,'!graded(item) && !sealed(item) && !item.condition ? "Choose condition & confirm" : item.status === "unresolved" ? "Confirm match" : "Edit details"','item.status === "unresolved" ? "Confirm match" : "Confirm & add"')
edit(scan,'(missingCondition ? " · check conditions" : "")','(missingCondition ? " · condition can be added later" : "")')
edit(scan,': "Add to Inventory";',': "Confirm & add recognised";')
edit(scan,'(!done && this.items.some(item => !this.ready(item)))','(!done && !this.items.some(item => item.status !== "added" && this.ready(item)))')
edit(scan,'isGraded ? "Grade" : "Condition");\n      const condition','isGraded ? "Grade" : "Condition (optional until selling)");\n      const condition')
edit(scan,'["Choose condition", ...conditions]','["Not recorded", ...conditions]')
edit(scan,'''      const save = button("Looks Good", () => {
        if (!isGraded && !isSealed && !conditions.includes(edit.condition)) {
          condition.focus();
          try { condition.showPicker?.(); } catch (_) { /* Focus still exposes the required field. */ }
          return;
        }
        this.confirmDetails();
      }, "dr-scan-primary");''','''      content.append(node("p", "dr-scan-review-note", "Confirming saves this item to your collection, not a selling channel. Price, cost and shipping can wait."));
      const save = button("Confirm & add", () => this.confirmDetails(), "dr-scan-primary");''')
edit(scan,'save.textContent = missingCondition ? "Choose condition to continue" : "Looks Good";','save.textContent = "Confirm & add";')
edit(scan,': missingCondition ? "Select the card’s condition above, then confirm the match." : "";',': missingCondition ? "Condition is optional for your collection. Confirm it when listing for sale." : "";')
edit(scan,'      if (!graded(edit) && !sealed({...edit.item, selected: edit.selected}) && !conditions.includes(edit.condition)) return;\n','')
edit(scan,'        this.editBusy = false; this.closeDetails(); this.render();','        this.editBusy = false; this.closeDetails(); this.render();\n        await this.saveAll([edit.item]);')
edit(scan,'condition: isSealed ? null : item.condition,','condition: isSealed ? null : item.condition || null,')
edit(scan,'    async saveAll() {','    async saveAll(onlyItems = null) {')
edit(scan,'''      if (this.items.some(item => !this.ready(item))) return;
      this.saving = true; this.items.forEach(item => this.freeze(item)); this.renderReview();''','''      const targets = (onlyItems || this.items).filter(item => this.items.includes(item)
        && item.status !== "added" && this.ready(item));
      if (!targets.length) return;
      this.saving = true; targets.forEach(item => this.freeze(item)); this.renderReview();''')
edit(scan,'      let added = 0, failed = 0, marketPending = 0;\n      for (const item of this.items) {','      let added = 0, failed = 0;\n      for (const item of targets) {')
edit(scan,'            if (!data.inventory?.inventory_code)','            if (!this.active(epoch)) return;\n            if (!data.inventory?.inventory_code)')
edit(scan,'''            if (this.options.role === "seller" && sealed(item) && data.inventory.identity_confirmed && data.inventory.market_value_minor == null) {
              try {
                const market = await this.request("/api/v1/owner/inventory/" + encodeURIComponent(data.inventory.inventory_code) + "/refresh-market", {method: "POST", body: "{}"});
                if (market.valuation?.market_value_minor == null) marketPending += 1;
                else item.selected.market_value_minor = market.valuation.market_value_minor;
              } catch (_) { marketPending += 1; }
            }
''','')
edit(scan,'''        : added + " added to your inventory. " + (this.options.role === "founder" || this.items.some(item => item.requests.some(request => !request.result.inventory.identity_confirmed))
          ? "Identity review is still required before approval." : "Saved with verified identity.");
      if (marketPending) message.textContent += " Some market values are still pending.";
''','''        : added + " added to your collection. Listing for sale is a separate action.";
      if (this.items.some(item => !item.requests && !this.ready(item))) message.textContent += " Uncertain matches remain for confirmation.";
      this.status(message.textContent);
''')
inv='backend/app/owner_inventory.py'
edit(inv,' i.identity_confirmed as identity_ready,',' i.identity_confirmed as identity_ready,\n (i.acquisition_cost_minor is not null) as cost_recorded,\n (i.storage_location_id is not null) as location_recorded,')
edit(inv,'        missing.append("Drop Rate intake review")','''        if not item.get("cost_recorded"):
            missing.append("Acquisition cost needs recording by Drop Rate before sale")
        if not item.get("location_recorded"):
            missing.append("Storage / dispatch location needs recording by Drop Rate")''')
edit(inv,'missing.append("Drop Rate identity verification")','missing.append("Drop Rate selling review: confirm the exact printing before publication")')
edit(inv,'else "An approved listing photo"','else "Listing image approval / preparation (separate from collection artwork)"')
edit(inv,'from .seller_inventory_policy import sealed_seller_candidate','from .seller_inventory_policy import sealed_seller_candidate\nfrom .physical_state import CARD_CONDITIONS, validate_physical_state')
edit(inv,'class AddCopy(VersionRequest):','class ListingRequest(SellingPrice):\n    condition: str | None = Field(default=None, max_length=80)\n\n\nclass AddCopy(VersionRequest):')
edit(inv,'''        if approval_request:
            context =''','''        if approval_request:
            proposed_condition = getattr(payload, "condition", None)
            if proposed_condition is not None:
                if item["status"] not in {"DRAFT", "INSPECTION"}:
                    raise HTTPException(409, "Condition changes on approved stock need Drop Rate review")
                if proposed_condition not in CARD_CONDITIONS:
                    raise HTTPException(422, "Choose a valid raw-card condition")
                kind = await connection.fetchval("select product_type from tcg.catalogue_products where id=$1", item["catalogue_id"])
                try:
                    validate_physical_state(product_type=kind, condition=proposed_condition,
                        seal_status=item.get("seal_status"), grading_company=item.get("grading_company"),
                        grade=item.get("grade"), certificate_number=item.get("certificate_number"))
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            context =''')
edit(inv,'            if context and sealed_seller_candidate(dict(context)):','''            if (context and context["product_type"] == "CARD" and not context.get("grading_company")
                    and not (proposed_condition or context.get("condition"))):
                raise HTTPException(422, "Choose the raw-card condition for this listing; your card is already saved")
            if context and sealed_seller_candidate(dict(context)):''')
edit(inv,'set store_price_minor=$4,status=$5,sale_intent=$6,version=version+1,updated_at=clock_timestamp()','set store_price_minor=$4,status=$5,sale_intent=$6,condition=coalesce($7::text,condition),version=version+1,updated_at=clock_timestamp()')
edit(inv,'"FOR_SALE" if approval_request else item["sale_intent"])','"FOR_SALE" if approval_request else item["sale_intent"], getattr(payload, "condition", None) if approval_request else None)')
edit(inv,'payload: SellingPrice, request: Request,\n                           user:','payload: ListingRequest, request: Request,\n                           user:')
ui='backend/app/static/owner-inventory.js'
edit(ui,'''    const sale = el("section", "owner-item-section");
    sale.append(el("h3", "", "Selling price"));''','''    const sale = el("details", "owner-item-section owner-item-selling");
    sale.open = publishedOnShopify || approvedForSale || item.status === "INSPECTION";
    sale.append(el("summary", "", publishedOnShopify ? "Manage listing" : "List for sale"));
    sale.append(el("p", "owner-item-note", "Your card is already in inventory. Listing is optional and requires a separate selling request."));
    let saleCondition;
    if (item.product_type === "CARD" && !item.grading_company && ["DRAFT", "INSPECTION"].includes(item.status)) {
      const label = el("label", "", "Condition when selling"); saleCondition = el("select");
      saleCondition.setAttribute("aria-label", "Condition when selling");
      for (const value of ["", "Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"]) {
        const option = el("option", "", value || "Choose condition"); option.value = value; saleCondition.append(option);
      }
      saleCondition.value = item.condition || ""; label.append(saleCondition); sale.append(label);
    }''')
edit(ui,'      run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/${path}`, {method, body: JSON.stringify({version: item.version, store_price_minor: minor})}));','''      if (path === "approval-request" && saleCondition && !saleCondition.value) {
        status("Choose the condition for your listing. The card is already saved in inventory.", true); saleCondition.focus(); return;
      }
      const body = {version: item.version, store_price_minor: minor};
      if (path === "approval-request" && saleCondition) body.condition = saleCondition.value;
      run(() => apiRequest(`/api/v1/owner/inventory/${item.id}/${path}`, {method, body: JSON.stringify(body)}));''')
edit(ui,'item.seller_approval_available?"Approve for Shopify":','item.seller_approval_available?"List on Shopify":')
edit(ui,'item.status==="INSPECTION"?"Update Shopify approval request":"Approve sale & request review"','item.status==="INSPECTION"?"Update listing request":"Request listing review"')
edit(ui,'sale.append(el("p","","Before this copy can be published:"));','sale.append(el("p","","Known next steps before selling (channel checks run again before publication):"));')
edit(ui,'?"Approve to confirm that you hold this exact sealed product and want to sell it. Your stock stays with you and uses the approved catalogue image."','?"List on Shopify confirms that you hold this exact sealed product and want it offered for sale. Your stock stays with you and uses approved catalogue artwork."')
edit(ui,':"Approval saves your selling price and requests Drop Rate review. Approved For Sale stock can then sync to Shopify."',':"This selling request is separate from adding the card. Drop Rate selling review still applies to this item; approval can then trigger Shopify publication."')
edit(ui,'!approvedForSale?"Awaiting approval":"Ready to sync"','!approvedForSale?"Not listed — use List for sale":"Awaiting channel checks"')
edit(ui,'?"Sync to Shopify":null','?"Check & sync to Shopify":null')
edit(ui,'    content.append(sellerChannels);','    sale.append(sellerChannels);')
edit(ui,'state:"Personal seller connection awaiting Whatnot API access"','state:"Not connected in Drop Rate — publishing unavailable"')
edit(ui,'Whatnot direct seller-account authorisation is currently unavailable; your account will not be linked to Drop Rate’s Shopify admin.','Whatnot is not connected in this workflow. No seller is given access to Shopify Admin.')
f=ROOT/'backend/app/static/owner-inventory.css';f.write_text(f.read_text()+'''\n/* Collection first: opening this disclosure never changes stock. */
.owner-item-selling>summary{font-size:1.05rem;font-weight:750;cursor:pointer;min-height:44px;display:list-item;padding:10px 0}
.owner-item-selling>summary:focus-visible{outline:3px solid #198bcb;outline-offset:4px}
.owner-item-selling select{width:100%;min-height:44px;padding:10px;border:1px solid #d4deeb;border-radius:10px;background:#fff;color:#14263f}
''')
edit('tests/test_owner_scan_intake.py','def test_owner_scan_intake_runs_same_deterministic_pricing_engine()','def test_owner_scan_intake_keeps_pricing_separate_from_collection_save()')
edit('tests/test_owner_scan_intake.py','    assert "valuation = await _recalculate_one(connection, owner_id, inventory_id)" in source','    assert "valuation = await _recalculate_one(connection, owner_id, inventory_id)" not in _scan_intake_source()')
edit('tests/owner_auto_import_postgres.py','source_record jsonb,unique(import_batch_id,source_row,source_copy)',"source_record jsonb,sale_intent text default 'FOR_SALE',unique(import_batch_id,source_row,source_copy)")
edit('tests/owner_inventory_postgres.py','grant update(store_price_minor,status,sale_intent,version,updated_at,identity_confirmed)','grant update(condition,store_price_minor,status,sale_intent,version,updated_at,identity_confirmed)')
edit('tests/owner_inventory_postgres.py',"assert 'Drop Rate intake review' in detail['item']['approval_blockers']","assert any('Acquisition cost' in issue for issue in detail['item']['approval_blockers'])")
edit('tests/test_owner_batch_scanner.py',"$11,'DRAFT',$12,$13::jsonb,'FOR_SALE'","$11,'DRAFT',$12,$13::jsonb,'PERSONAL_COLLECTION'")
edit('tests/test_sealed_recognition.py','assert "_recalculate_one(connection, owner_id, inventory_id)" in block','assert "_recalculate_one(connection, owner_id, inventory_id)" not in block')
for fn in ('tests/ui/owner-inventory.cjs','tests/ui/owner-inventory-browser.cjs'):
    f=ROOT/fn;s=f.read_text().replace('Approve for Shopify','List on Shopify').replace('Approve sale & request review','Request listing review').replace('Sync to Shopify','Check & sync to Shopify');f.write_text(s)
f=ROOT/'tests/ui/owner-inventory-browser.cjs';s=f.read_text().replace("await page.getByRole('heading',{name:'Selling price',exact:true}).waitFor();", "await page.locator('.owner-item-selling summary').waitFor();\n   if(!await page.locator('.owner-item-selling').evaluate(e=>e.open))await page.locator('.owner-item-selling summary').click();");f.write_text(s)
f=ROOT/'tests/ui/scanner-flow.cjs';s=f.read_text().replace('/review is still required/','/Listing for sale is a separate action/')
s=s.replace('// Exact matches still require a physical condition; changing quantity validates integer bounds.','// Condition is optional for collection entry; confirmation saves selected copies.')
s=s.replace("const f = fixture('seller', async () => result());\n    await f.scanner.recognise('photo'); const item = f.scanner.items[0]; f.scanner.showReview();\n    assert.ok(f.scanner.find('[data-action=\"save\"]').disabled);", "const f = fixture('seller', async url => url.endsWith('/resolve') ? result() : url.endsWith('/recognition-intake') ? {inventory:{inventory_code:'INV-CONFIRMED'}} : {});\n    await f.scanner.recognise('photo'); const item = f.scanner.items[0]; f.scanner.showReview();\n    assert.ok(!f.scanner.find('[data-action=\"save\"]').disabled);")
s=s.replace("assert.equal(f.calls.length, 1, 'Detail confirmation alone does not write inventory or feedback');", "assert.equal(item.status, 'added');\n    assert.equal(f.calls.filter(call => call.url.endsWith('/recognition-intake')).length, 2, 'One confirmation saves the two selected copies');")
old='''    assert.equal(confirm.textContent,'Choose condition to continue');
    confirm.click(); await tick();
    assert.equal(f.dom.window.document.activeElement.getAttribute('aria-label'),'Condition');
    assert.equal(f.calls.length,1,'No write before condition is chosen');
    assert.match(f.scanner.details.textContent,/Market value unavailable/);
    const condition=f.scanner.details.querySelector('select'); condition.value='Near Mint';
    condition.dispatchEvent(new f.w.Event('change'));
    assert.equal(confirm.textContent,'Looks Good');
    await f.scanner.confirmDetails(); f.scanner.showReview();
'''
new='''    assert.equal(confirm.textContent,'Confirm & add');
    assert.equal(f.calls.length,1,'No write before explicit confirmation');
    assert.match(f.scanner.details.textContent,/Market value unavailable/);
    await f.scanner.confirmDetails(); f.scanner.showReview();
    const saveRequest=f.calls.find(call=>call.headers?.['Idempotency-Key']);
    assert.equal(JSON.parse(saveRequest.body).condition,null,'Unknown condition is not guessed as Near Mint');
'''
assert old in s;s=s.replace(old,new);f.write_text(s)
# Version both workspaces. Do not restore pre-#607 image delivery code.
for fn in ('backend/app/static/owner.html','tests/test_owner_portal_shell.py'):
    f=ROOT/fn;s=f.read_text();s,n=re.subn(r'(owner-inventory\.js\?v=)[^"\s]+',r'\g<1>collection-v9',s);assert n==1,(fn,n)
    s,n=re.subn(r'(scanner-flow\.js\?v=)[^"\s]+',r'\g<1>collection-v8',s);assert n==1,(fn,n);f.write_text(s)
edit('backend/app/main.py','/assets/scanner-flow.js?v=5','/assets/scanner-flow.js?v=collection-v8')
print('Prepared bounded collection/optional-selling patch. No production network or data writes.')
