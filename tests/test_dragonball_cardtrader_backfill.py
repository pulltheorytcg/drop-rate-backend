from pathlib import Path
import ast


SCRIPT = Path(__file__).parents[1] / "backend" / "scripts" / "run_dragonball_cardtrader_backfill.py"


def test_dragonball_backfill_script_parses() -> None:
    source = SCRIPT.read_text()
    ast.parse(source)


def test_dragonball_backfill_defaults_to_probe_and_reuses_core_enrichment() -> None:
    source = SCRIPT.read_text()

    assert 'or "probe"' in source
    assert 'choices=("probe", "apply")' in source
    assert "_process_one(" in source
    assert "_seed_batch(" in source
    assert "default_language=args.default_language" in source
    assert "p.game ilike 'Dragon Ball%'" in source
    assert "sil.id is null" in source
    assert "update tcg.inventory_items" not in source.lower()


def test_dragonball_backfill_requires_founder_owner_membership_and_cardtrader_token() -> None:
    source = SCRIPT.read_text()

    assert "om.role in ('PLATFORM_ADMIN','OWNER')" in source
    assert "om.active=true" in source
    assert "TCG_CARDTRADER_API_TOKEN is not configured" in source


def test_dragonball_probe_sanitises_provider_output() -> None:
    source = SCRIPT.read_text()

    assert "_sanitise_provider_result" in source
    assert '"image_url"' in source
    assert "api_token" not in source[source.index("def _sanitise_provider_result"):source.index("async def _batch_context")]
