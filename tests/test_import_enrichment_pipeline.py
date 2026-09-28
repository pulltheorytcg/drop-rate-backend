from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
ENRICHMENT = ROOT / "backend" / "app" / "import_enrichment.py"
ACTION_REQUIRED = ROOT / "backend" / "app" / "action_required.py"
IMPORTS = ROOT / "backend" / "app" / "imports.py"
UI = ROOT / "backend" / "app" / "static" / "inventory-imports.js"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260928211713_import_enrichment_action_queue.sql"
)


def test_enrichment_and_action_required_routes_are_founder_admin_only() -> None:
    source = MAIN.read_text()

    assert "from .action_required import router as action_required_router" in source
    assert "from .import_enrichment import router as import_enrichment_router" in source
    assert (
        "app.include_router(action_required_router, dependencies=[Depends(require_platform_admin_request)])"
        in source
    )
    assert (
        "app.include_router(import_enrichment_router, dependencies=[Depends(require_platform_admin_request)])"
        in source
    )


def test_enrichment_schema_is_durable_owner_scoped_and_restart_safe() -> None:
    sql = MIGRATION.read_text()

    assert "create table tcg.import_enrichment_items" in sql
    assert "unique(batch_id,inventory_id)" in sql
    assert "overall_status text not null default 'PENDING'" in sql
    assert "attempts integer not null default 0" in sql
    assert "create policy own_enrichment_access" in sql
    assert "om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid" in sql
    assert "revoke delete on tcg.import_enrichment_items from tcg_api" in sql

    # Progress is derived operational state. Business mutations are already
    # audited in their source tables, so this high-volume table is not noisy.
    assert "create trigger import_enrichment_items_audit" not in sql


def test_action_required_queue_is_deduplicated_owner_scoped_and_audited() -> None:
    sql = MIGRATION.read_text()

    assert "create table tcg.action_required_items" in sql
    assert "unique(owner_id,dedupe_key)" in sql
    assert "status in ('OPEN','RESOLVED','DISMISSED')" in sql
    assert "create policy own_action_required_access" in sql
    assert "create trigger action_required_items_audit" in sql
    assert "revoke delete on tcg.action_required_items from tcg_api" in sql


def test_import_commit_emits_durable_automation_event_without_private_inventory_data() -> None:
    sql = MIGRATION.read_text()
    start = sql.index("create or replace function tcg.emit_import_committed_event")
    end = sql.index("create trigger import_batches_emit_committed_event_insert", start)
    block = sql[start:end]

    assert "'import.committed'" in block
    assert "'IMPORT_BATCH'" in block
    assert "'batch_id',new.id" in block
    assert "'adapter',new.adapter" in block
    assert "'source_rows',new.source_rows" in block
    assert "'physical_units',new.physical_units" in block
    assert "acquisition_cost" not in block
    assert "notes" not in block
    assert "customer" not in block.lower()


def test_identity_verification_supports_explicit_import_language_evidence() -> None:
    sql = MIGRATION.read_text()
    source = ENRICHMENT.read_text()

    assert "'IMPORT_DEFAULT_LANGUAGE'" in sql
    assert "'PROVIDER_EXACT'" in sql
    assert "default_language_selected_by_admin" in source
    assert "_unmarked_import_identity_evidence" in source
    assert "explicit_languages" in source
    assert "_variant_equivalent" in source


def test_enrichment_never_auto_approves_provider_media() -> None:
    source = ENRICHMENT.read_text()

    free_start = source.index("async def _insert_free_media")
    free_end = source.index("async def _insert_tcggraph_media", free_start)
    free_block = source[free_start:free_end]
    graph_end = source.index("async def _resolve_media_candidate", free_end)
    graph_block = source[free_end:graph_end]

    assert "'STOREFRONT_ALLOWED'" in free_block
    assert "'VERIFIED',$10,'PENDING'" in free_block
    assert "'APPROVED'" not in free_block

    assert "'INTERNAL_REFERENCE_ONLY','TCGGraph'" in graph_block
    assert "'VERIFIED',$9,'PENDING'" in graph_block
    assert "'STOREFRONT_ALLOWED'" not in graph_block


def test_existing_media_must_match_exact_language_and_variant() -> None:
    source = ENRICHMENT.read_text()
    start = source.index("async def _existing_media")
    end = source.index("def _media_status_from_assets", start)
    block = source[start:end]

    assert "media_language" in block
    assert "media_variant" in block
    assert "lower(btrim(coalesce(media_language,'')))=lower(btrim($2))" in block
    assert "lower(btrim(coalesce(media_variant,'')))=lower(btrim($3))" in block
    assert "if not clean_lang" in block


def test_enrichment_reuses_existing_pricing_and_physical_photo_rules() -> None:
    source = ENRICHMENT.read_text()

    assert "apply_imported_benchmark_one" in source
    assert "EcbHistoricalFxProvider" in source
    assert "physical_photo_policy(" in source
    assert '"PHYSICAL_PHOTOS_REQUIRED"' in source
    assert '"PRICING_DATA_INSUFFICIENT"' in source
    assert '"MEDIA_REVIEW_REQUIRED"' in source
    assert '"MEDIA_UNRESOLVED"' in source


def test_enrichment_is_chunked_bounded_parallel_and_retryable() -> None:
    source = ENRICHMENT.read_text()

    assert "limit: int = Field(default=25, ge=1, le=100)" in source
    assert "retry_action_required: bool = False" in source
    assert "asyncio.Semaphore(min(6, max(1, len(rows))))" in source
    assert "await asyncio.gather" in source
    assert "overall_status=any($3::text[])" in source
    assert "attempts=attempts+1" in source


def test_recent_import_list_is_owner_scoped_and_reports_enrichment_progress() -> None:
    source = IMPORTS.read_text()
    start = source.index('@router.get("")')
    end = source.index('@router.get("/{batch_id}")', start)
    block = source[start:end]

    assert "where b.owner_id=$1" in block
    assert "enrichment_total" in block
    assert "enrichment_pending" in block
    assert "enrichment_action_required" in block
    assert "enrichment_complete" in block


def test_founder_import_ui_runs_enrichment_and_can_resume_it() -> None:
    js = UI.read_text()

    assert "Unmarked language" in js
    assert "default_language" in js
    assert "/enrichment/process" in js
    assert "runImportEnrichment" in js
    assert "Resume enrichment" in js
    assert "Retry / enrich" in js
    assert "/api/v1/imports?limit=8" in js
    assert "Action Required" in js
    assert "/api/v1/action-required/summary" in js
    assert "/api/v1/action-required?status=OPEN&limit=100" in js
