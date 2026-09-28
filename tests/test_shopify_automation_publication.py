from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260928175500_shopify_automation_publication.sql"
)
BASE_LINK_MIGRATION = ROOT / "migrations" / "006_shopify_inventory_links.sql"


def test_dr01_keeps_one_physical_inventory_to_one_shopify_link() -> None:
    base = BASE_LINK_MIGRATION.read_text().lower()
    assert "inventory_id uuid not null unique references tcg.inventory_items(id)" in base
    assert "unique(listing_key, allocation_priority)" in base


def test_dr01_machine_attribution_never_fakes_a_founder_user() -> None:
    sql = MIGRATION.read_text().lower()
    assert "alter column created_by_user_id drop not null" in sql
    assert "created_by_automation_event_id uuid" in sql
    assert "shopify_inventory_links_creator_check" in sql
    assert "created_by_user_id is null and created_by_automation_event_id is not null" in sql
    assert "automation:" in sql
    assert "event_type='inventory.approved'" in sql
    assert "aggregate_type='inventory_item'" in sql


def test_dr01_database_capabilities_are_narrow_and_not_public() -> None:
    sql = MIGRATION.read_text().lower()
    functions = (
        "tcg.shopify_publication_context(uuid,uuid)",
        "tcg.save_shopify_inventory_draft(",
        "tcg.mark_shopify_inventory_published(",
    )
    for function in functions:
        assert function in sql

    assert sql.count("security definer") == 3
    assert "revoke all on function tcg.shopify_publication_context(uuid,uuid) from public" in sql
    assert "from anon, authenticated, service_role" in sql
    assert "grant execute on function tcg.shopify_publication_context(uuid,uuid) to tcg_api" in sql
    assert "grant execute on function tcg.save_shopify_inventory_draft" in sql
    assert "grant execute on function tcg.mark_shopify_inventory_published" in sql

    assert "alter role tcg_api" not in sql
    assert "bypassrls" not in sql
    assert "create policy" not in sql


def test_dr01_database_revalidates_inventory_before_draft_and_publish() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert lower.count("v_item.version <> p_expected_version") == 2
    assert lower.count("v_item.status <> 'approved'") == 2
    assert lower.count("v_item.sale_intent <> 'for_sale'") == 2
    assert "Existing Shopify link remote identity changed" in sql
    assert "Shopify remote identity changed before publication finalization" in sql
    assert "sync_state='PUBLISHED'" in sql
    assert "sync_state='DRAFT'" in sql


def test_dr01_database_validates_manual_and_automation_actors() -> None:
    sql = MIGRATION.read_text().lower()
    assert sql.count("om.role='platform_admin'") == 2
    assert sql.count("ae.id=p_automation_event_id") == 2
    assert sql.count("ae.owner_id=p_owner_id") == 2
    assert sql.count("ae.aggregate_id=p_inventory_id::text") == 2
