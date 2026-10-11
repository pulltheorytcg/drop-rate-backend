"""Temporary branch preparation; never run against a production database."""
from pathlib import Path


def replace(path, before, after, count=1):
    file=Path(path);text=file.read_text()
    assert text.count(before)==count,(path,'Unexpected source; stop rather than overwrite')
    file.write_text(text.replace(before,after))

replace('backend/app/access_control.py','"founder_hq_allowed": role == "PLATFORM_ADMIN",','"founder_hq_allowed": role == "PLATFORM_ADMIN",\n        "business_allowed": (role == "PLATFORM_ADMIN" and row["owner_type"] == "FOUNDER"\n                             and row["founder_slot"] in (1, 2, 3)),')
p=Path('backend/app/access_control.py')
p.write_text(p.read_text()+'''\n\nasync def require_business_founder(connection: asyncpg.Connection) -> dict:\n    """Only the existing three verified founder-roster accounts, never role claims.\n\n    current_access_context calls the database roster predicate on every request.\n    This adds no membership, service-role bypass or cross-owner write authority.\n    """\n    context = await require_platform_admin(connection)\n    if not context["business_allowed"]:\n        raise HTTPException(status_code=403, detail="Verified founder Business access required")\n    return context\n''')
replace('backend/app/founder_accounts.py','from .access_control import require_platform_admin','from .access_control import require_business_founder')
replace('backend/app/founder_accounts.py','await require_platform_admin(conn)','await require_business_founder(conn)',3)
replace('backend/app/founder_accounts.py','select o.id,o.display_name,o.owner_type,o.founder_slot,','select o.id,o.display_name,o.username,o.owner_type,o.founder_slot,\n            coalesce(i.active_stock,0) as active_stock_count,coalesce(i.drafts,0) as draft_count,')
replace('backend/app/founder_accounts.py','select count(*)::int as items,',"select count(*)::int as items,\n              count(*) filter(where status in ('DRAFT','INSPECTION','APPROVED','RESERVED'))::int as active_stock,\n              count(*) filter(where status='DRAFT')::int as drafts,")
replace('backend/app/founder_accounts.py',"concat_ws(' ',i.inventory_code,p.name,p.card_number,p.set_name)","concat_ws(' ',i.inventory_code,p.name,p.card_number,p.set_name,o.display_name,o.username,i.certificate_number)")
replace('backend/app/founder_accounts.py','p.name,p.card_number,p.set_name,p.game,i.language,i.condition,i.grading_company,i.grade,','p.name,p.card_number,p.set_name,p.game,p.product_type,p.variant,\n            i.language,i.condition,i.grading_company,i.grade,i.certificate_number,i.location,i.pricing_updated_at,')
replace('backend/app/static/workspace-shell.js',"accounts:['Accounts','Founder oversight of inventory and balances','◎']","accounts:['Business','Company overview, sellers and stock ownership','◎']")
replace('backend/app/main.py','<script src="/assets/founder-accounts.js" defer></script>','<script src="/assets/founder-accounts.js?v=business-v1" defer></script>')
replace('backend/app/main.py','<script src="/assets/workspace-shell.js?v=3" defer></script>','<script src="/assets/workspace-shell.js?v=4" defer></script>')
replace('BUILD_STATUS.md','# Drop Rate — Live Build Status\n','# Drop Rate — Live Build Status\n\n## 11 October 2026 — Founder-only Business area (implementation; release evidence pending)\n\nThe user selected the Seller Hub visual approach with a dedicated Business area for the three verified founder accounts only. The first bounded release replaces the existing Accounts presentation with Overview, Sellers, Stock ownership and recorded Sales & payouts. Search active accounts by name/username and inspect their exact physical inventory; retain IDs, owners, history and private API/RLS boundaries. Ordinary sellers get no Business entry or API access; generic admin/metadata claims do not bypass the verified founder roster.\n\nReuses existing founder account APIs, adds explicit Business capability/guard and richer read-only stock fields. No new service, database migration, role enrollment, account merge, ownership change, import commit, publishing, money movement or n8n workflow. Counts are labelled stock records, not a deduplicated portfolio valuation; known overlapping Draft imports remain unreconciled. Existing founder tools remain linked with their existing scope. See `docs/FOUNDER_BUSINESS_AREA.md`; exact-head CI, deployment and real-session acceptance are separate evidence categories. Account consolidation and further editing functions remain later work.\n')
# A nested Business tablist must not be mistaken for a second primary tab.
replace('tests/ui/founder-workspace.cjs',"assert.equal(doc.querySelectorAll('[role=tab][aria-selected=true]').length,1);", "assert.equal(doc.querySelectorAll('.seller-nav-tab[role=tab][aria-selected=true]').length,1);\n  assert.equal(doc.querySelectorAll('.business-tabs [role=tab][aria-selected=true]').length,1);")
# Explicit fixture canonical foreign key, not a changed application rule.
replace('tests/business_area_postgres.py',"item,f'INV-TEST-{i}',owners[i], 'APPROVED'", "item,f'INV-TEST-{i}',owners[i],card, 'APPROVED'")
