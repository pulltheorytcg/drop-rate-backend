from pathlib import Path

from app.schemas import ManualCatalogueCreate


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260927180056_collectible_identity_foundation.sql"
)
API = ROOT / "backend" / "app" / "collectible_identity.py"
MAIN = ROOT / "backend" / "app" / "main.py"
SCHEMAS = ROOT / "backend" / "app" / "schemas.py"
DOCS = ROOT / "docs" / "COLLECTIBLE_IDENTITY.md"


def test_collectible_identity_migration_is_additive_to_physical_inventory() -> None:
    sql = MIGRATION.read_text()

    assert "create table tcg.collectible_systems" in sql
    assert "create table tcg.catalogue_product_profiles" in sql
    assert "create table tcg.card_gameplay_identities" in sql
    assert "create table tcg.card_printings" in sql
    assert "create table tcg.sealed_product_details" in sql
    assert "create table tcg.comic_printing_details" in sql
    assert "create table tcg.provider_catalogue_mappings" in sql

    # Physical inventory remains the existing source of truth.
    assert "alter table tcg.inventory_items" not in sql.casefold()
    assert "update tcg.inventory_items" not in sql.casefold()
    assert "delete from tcg.inventory_items" not in sql.casefold()


def test_collectible_taxonomy_supports_multiple_values_and_fail_closed_unknown() -> None:
    sql = MIGRATION.read_text()

    assert "cardinality in ('SINGLE','MULTI')" in sql
    assert (
        "case when code='RIFTBOUND' then 'MULTI' else 'SINGLE' end"
        in sql
    )
    assert "'UNKNOWN','Unknown / unresolved'" in sql
    assert """'{"fail_closed":true}'::jsonb""" in sql
    assert "Taxonomy dimension permits only one value" in sql


def test_foundation_has_game_specific_and_future_collectible_systems() -> None:
    sql = MIGRATION.read_text()

    for code in (
        "POKEMON_TCG",
        "ONE_PIECE_CARD_GAME",
        "DRAGON_BALL_SUPER_MASTERS",
        "DRAGON_BALL_SUPER_FUSION_WORLD",
        "DISNEY_LORCANA",
        "RIFTBOUND",
        "NARUTO_BANDAI",
        "MARVEL_COMICS",
        "DC_COMICS",
    ):
        assert code in sql

    # Future Naruto support is registered without inventing unsupported taxonomy.
    assert (
        "('NARUTO_BANDAI','Naruto Bandai Card Game','Naruto','TCG',"
        "'Bandai','ANNOUNCED',null"
    ) in sql


def test_one_piece_taxonomy_separates_type_rarity_art_and_finish() -> None:
    sql = MIGRATION.read_text()

    for card_type in ("LEADER", "CHARACTER", "EVENT", "STAGE", "DON"):
        assert (
            f"'ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','{card_type}'"
            in sql
        )
    for rarity in ("C", "UC", "R", "SR", "SEC", "L"):
        assert (
            f"'ONE_PIECE_CARD_GAME','CARD','RARITY','{rarity}'"
            in sql
        )
    for art in ("BASE", "PARALLEL", "ALTERNATE_ART", "MANGA", "SUPER_PARALLEL"):
        assert (
            f"'ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','{art}'"
            in sql
        )
    assert "'ONE_PIECE_CARD_GAME','CARD','SPECIAL_CLASSIFICATION','SP'" in sql
    assert "'ONE_PIECE_CARD_GAME','CARD','FINISH','FOIL'" in sql


def test_other_tcg_taxonomies_are_not_forced_into_one_piece_vocabulary() -> None:
    sql = MIGRATION.read_text()

    assert "'POKEMON_TCG','CARD','RARITY','ILLUSTRATION_RARE'" in sql
    assert "'POKEMON_TCG','CARD','RARITY','SPECIAL_ILLUSTRATION_RARE'" in sql
    assert "'POKEMON_TCG','CARD','FINISH','REVERSE_HOLOFOIL'" in sql

    assert "'DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','Z_LEADER'" in sql
    assert (
        "'DRAGON_BALL_SUPER_FUSION_WORLD','CARD','CARD_TYPE','ENERGY_MARKER'"
        in sql
    )

    assert "'DISNEY_LORCANA','CARD','CARD_TYPE','LOCATION'" in sql
    assert "'DISNEY_LORCANA','CARD','RARITY','ICONIC'" in sql

    assert "'RIFTBOUND','CARD','CARD_TYPE','BATTLEFIELD'" in sql
    assert "'RIFTBOUND','CARD','ART_TREATMENT','OVERNUMBER'" in sql


def test_sealed_and_comic_models_are_first_class() -> None:
    sql = MIGRATION.read_text()

    assert "'POKEMON_TCG','SEALED','SEALED_TYPE','ELITE_TRAINER_BOX'" in sql
    assert "'ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','STARTER_DECK'" in sql
    assert "manufacturer_sku text" in sql
    assert "barcode_gtin text" in sql

    assert "series_title text not null" in sql
    assert "issue_number text not null" in sql
    assert "cover_code text" in sql
    assert "cover_artist text" in sql
    assert "'MARVEL_COMICS','COMIC','COMIC_PRINTING_CLASS','FIRST_PRINT'" in sql
    assert "'DC_COMICS','COMIC','COMIC_PRINTING_CLASS','REPRINT'" in sql


def test_ai_suggestions_cannot_become_verified_provider_identity() -> None:
    sql = MIGRATION.read_text()

    assert (
        "verification_basis in "
        "('LEGACY_IMPORT','DETERMINISTIC_EXACT','HUMAN','AI_SUGGESTED')"
        in sql
    )
    assert (
        "verification_basis <> 'AI_SUGGESTED'\n"
        "        or match_status <> 'VERIFIED'"
        in sql
    )
    assert (
        "verification_basis in ('DETERMINISTIC_EXACT','HUMAN')"
        in sql
    )


def test_new_identity_tables_are_rls_protected_and_admin_mutated() -> None:
    sql = MIGRATION.read_text().casefold()

    for table in (
        "collectible_systems",
        "taxonomy_schemas",
        "taxonomy_values",
        "catalogue_product_profiles",
        "catalogue_taxonomy_assignments",
        "card_gameplay_identities",
        "card_printings",
        "sealed_product_details",
        "comic_printing_details",
        "provider_catalogue_mappings",
    ):
        assert f"alter table tcg.{table} enable row level security" in sql
        assert f"alter table tcg.{table} force row level security" in sql

    assert "with check (tcg.is_platform_admin())" in sql
    assert "from public, anon, authenticated" in sql
    assert "revoke delete on" in sql


def test_legacy_backfill_never_claims_exact_verification() -> None:
    sql = MIGRATION.read_text()

    assert "'LEGACY_UNREVIEWED'" in sql
    assert "'MIGRATED_UNVERIFIED'" in sql
    assert "'NEEDS_REVIEW'" in sql
    assert "media approval does not silently promote" in sql
    assert "'REVIEW'," in sql
    assert "'DETERMINISTIC_EXACT'," in sql


def test_collectible_identity_api_is_read_only_and_platform_admin_guarded() -> None:
    source = API.read_text()
    main = MAIN.read_text()

    assert '@router.get("/systems")' in source
    assert '@router.get("/taxonomy/{system_code}")' in source
    assert '@router.get("/identity/{catalogue_id}")' in source
    assert "@router.post(" not in source
    assert "@router.put(" not in source
    assert "@router.patch(" not in source
    assert "@router.delete(" not in source

    assert "collectible_identity_router" in main
    assert (
        "app.include_router(collectible_identity_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
        in main
    )


def test_collectible_identity_api_exposes_exact_printing_and_physical_inventory() -> None:
    source = API.read_text()

    for token in (
        "catalogue_product",
        "profile",
        "card_printing",
        "gameplay_identity_id",
        "sealed_product",
        "comic_printing",
        "taxonomy",
        "provider_mappings",
        "physical_inventory",
        "inventory_code",
        "owner_name",
        "store_price_minor",
        "market_value_minor",
    ):
        assert token in source


def test_catalogue_schema_accepts_future_collectible_types_without_breaking_cards() -> None:
    schemas = SCHEMAS.read_text()
    assert (
        'CatalogueProductType = Literal["CARD", "SEALED", "COLLECTION", '
        '"COMIC", "ACCESSORY"]'
        in schemas
    )

    card = ManualCatalogueCreate(
        product_type="CARD",
        game="One Piece",
        name="Test",
        set_name="Test Set",
        card_number="OP00-001",
    )
    comic = ManualCatalogueCreate(
        product_type="COMIC",
        game="Marvel",
        name="Test Comic",
        set_name="Test Series",
    )
    assert card.product_type == "CARD"
    assert comic.product_type == "COMIC"


def test_collectible_identity_architecture_is_documented() -> None:
    docs = DOCS.read_text()

    assert "gameplay identity" in docs
    assert "exact card printing" in docs.casefold()
    assert "AI_SUGGESTED" in docs
    assert "An AI confidence score alone is never sufficient." in docs
    assert "Elite Trainer Boxes (ETBs)" in docs
    assert "Marvel Comics" in docs
    assert "DC Comics" in docs


def test_cross_system_identity_mismatches_are_database_rejected() -> None:
    sql = MIGRATION.read_text()

    assert "Card/sealed products require a TCG collectible system" in sql
    assert "Comic products require a comics collectible system" in sql
    assert "Subtype identity does not match catalogue product profile" in sql
    assert "Card printing and gameplay identity systems do not match" in sql
    assert "Provider mapping does not match catalogue product identity" in sql
    assert "create trigger card_printings_validate" in sql
    assert "create trigger provider_catalogue_mappings_validate" in sql


def test_collectible_identity_migration_has_valid_plpgsql_dollar_quoting_shape() -> None:
    sql = MIGRATION.read_text()
    assert "\nas $\n" not in sql
    assert "\n$;\n" not in sql
    assert sql.count("as $$") == sql.count("$$;")
