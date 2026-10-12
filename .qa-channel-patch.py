from pathlib import Path
root=Path('.')
p=root/'backend/app/seller_inventory_policy.py';s=p.read_text();s+='''\n\ndef ebay_listing_scope_blocker(owner_type: str, product_type: str) -> str | None:
    """The existing v1 publisher scope, shared by readiness display and execution."""
    if owner_type == "CONSIGNOR":
        return "Consignor eBay publishing is not enabled yet"
    if product_type != "CARD":
        return "eBay v1 only supports individual physical cards"
    return None
''';p.write_text(s)
p=root/'backend/app/seller_channel_sync.py';s=p.read_text().replace('from .settings import get_settings','from .settings import get_settings\nfrom .seller_inventory_policy import ebay_listing_scope_blocker');old='''            if access["owner_type"] == "CONSIGNOR":
                raise HTTPException(409, "Consignor eBay publishing is not enabled yet")
            if item["product_type"] != "CARD":
                raise HTTPException(409, "eBay v1 only supports individual physical cards")''';assert old in s;s=s.replace(old,'''            blocker = ebay_listing_scope_blocker(access["owner_type"], item["product_type"])
            if blocker:
                raise HTTPException(409, blocker)''');p.write_text(s)
p=root/'backend/app/owner_portal_api.py';s=p.read_text().replace('from .settings import get_settings','from .settings import get_settings\nfrom .seller_inventory_policy import ebay_listing_scope_blocker')
start=s.index('@router.get("/channels")');end=s.index('@router.get("/catalogue-search")',start);section=s[start:end]
section=section.replace('''                i.id as inventory_id,
                i.inventory_code,''','''                i.id, i.id as inventory_id, i.catalogue_id,
                i.condition, i.grading_company, i.grade, i.seal_status,
                i.store_price_minor, p.product_type, p.language as catalogue_language,
                i.inventory_code,''')
a=section.index('                i.market_value_minor,');b=section.index('                p.game,p.name',a);section=section[:a]+section[b:]
a=section.index('                ebay.listing_id as ebay_listing_id,');b=section.index('            from tcg.inventory_items i',a)
section=section[:a]+'''                ebay.listing_id as ebay_listing_id
'''+section[b:]
old='\n    shopify_configured = bool('
new='''
        items = [dict(row) for row in rows]
        await add_reference_artwork(connection, items)
        await add_shared_inventory_media(connection, items)
        await add_shared_reference_values(connection, items)
        for item in items:
            # Actual remote asking prices remain in the channel-specific fields.
            item["store_value_minor"] = item.get("store_price_minor") if item.get("store_price_minor") is not None else item.get("recommended_retail_minor")
            item["channel_sync_blockers"] = {"EBAY": ebay_listing_scope_blocker(access["owner_type"], item["product_type"])}

    shopify_configured = bool('''
assert old in section;section=section.replace(old,new)
section=section.replace('"sync_enabled": bool(settings.ebay_seller_sync_enabled and settings.ebay_publish_enabled and settings.ebay_shared_store_owner_id),','''"sync_enabled": bool(settings.ebay_seller_sync_enabled and settings.ebay_publish_enabled and settings.ebay_shared_store_owner_id
                                         and not ebay_listing_scope_blocker(access["owner_type"], "CARD")),
                    "sync_unavailable_reason": ebay_listing_scope_blocker(access["owner_type"], "CARD"),''')
section=section.replace('"items": [dict(row) for row in rows],','"items": items,')
s=s[:start]+section+s[end:];p.write_text(s)
p=root/'backend/app/static/owner-portal.js';s=p.read_text();s=s.replace('      if (eligible && channel?.sync_enabled) {','''      const blocker = item.channel_sync_blockers?.[code] || channel?.sync_unavailable_reason;
      if (eligible && channel?.sync_enabled && !blocker) {''')
s=s.replace('note.textContent = !eligible ? (item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "Awaiting approval") : "Seller sync not enabled yet";','note.textContent = !eligible ? (item.sale_intent === "PERSONAL_COLLECTION" ? "Personal collection" : "Awaiting approval") : blocker || "Seller sync not enabled yet";')
start=s.index('async function loadOwnerChannels()');end=s.index('\nfunction renderInventoryPagination()',start);section=s[start:end]
section=section.replace('  const params = new URLSearchParams({','''  const revision = state.channels.requestRevision = (state.channels.requestRevision || 0) + 1;
  const account = state.session?.user?.id || state.session?.access_token;
  const current = () => revision === state.channels.requestRevision
    && account === (state.session?.user?.id || state.session?.access_token);
  const params = new URLSearchParams({''')
section=section.replace('    state.ownerChannelAccount = state.session?.user?.id || state.session?.access_token;','''    if (!current()) return;
    state.ownerChannelAccount = account;''')
section=section.replace('''  } catch (error) {
    showOwnerChannelsMessage''','''  } catch (error) {
    if (!current()) return;
    showOwnerChannelsMessage''')
s=s[:start]+section+s[end:];p.write_text(s)
versions={'hub-session.js?v=3':'hub-session.js?v=journey-v4','app.js?v=2':'app.js?v=journey-v3','owner-portal.js?v=recommendation-v22':'owner-portal.js?v=journey-v23','owner-inventory.js?v=recommendation-v11':'owner-inventory.js?v=journey-v12','owner-imports.js?v=auto-intake-v1':'owner-imports.js?v=journey-v2'}
for path in ['backend/app/static/index.html','backend/app/static/owner.html','tests/test_owner_username_login.py','tests/test_owner_portal_shell.py','tests/test_owner_csv_import_ui.py']:
 p=Path(path);s=p.read_text()
 for old,new in versions.items():s=s.replace(old,new)
 p.write_text(s)
p=Path('.github/workflows/shared-reference-consistency.yml');s=p.read_text().replace("      - 'tests/ui/recommendation-summary.py'", "      - 'tests/ui/recommendation-summary.py'\n      - 'tests/ui/journey-regressions.py'\n      - 'backend/app/seller_inventory_policy.py'\n      - 'backend/app/seller_channel_sync.py'")
s=s.replace('          python tests/ui/recommendation-summary.py\n','          python tests/ui/recommendation-summary.py\n          python tests/ui/journey-regressions.py\n')
s=s.replace('          RECOMMENDATION_LAYOUT_DIR: /tmp/reference-layout/recommendations','          RECOMMENDATION_LAYOUT_DIR: /tmp/reference-layout/recommendations\n          JOURNEY_LAYOUT_DIR: /tmp/reference-layout/journeys')
s=s.replace("'dashboard-shell.js','owner-portal.css')", "'dashboard-shell.js','owner-portal.css','hub-session.js','app.js','owner-imports.js')")
s=s.replace("source=Path('backend/app/static/owner.html').read_text()+Path('backend/app/main.py').read_text()", "source=Path('backend/app/static/owner.html').read_text()+Path('backend/app/main.py').read_text()+Path('backend/app/static/index.html').read_text()")
s=s.replace("'/api/v1/owner/overview'):", "'/api/v1/owner/overview','/api/v1/owner/channels'):");p.write_text(s)
for name in ['business-area.yml','shopify-net-postage.yml','shopify-sealed-pool.yml']:
 p=Path('.github/workflows')/name;s=p.read_text().replace('    paths:\n', "    paths:\n      - 'tests/ui/journey-regressions.py'\n",1);p.write_text(s)
