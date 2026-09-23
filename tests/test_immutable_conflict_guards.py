from pathlib import Path


ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "backend" / "app"


def test_storage_assignment_rejects_sold_inventory_before_update() -> None:
    source = (BACKEND / "storage_locations.py").read_text()
    assert "select id, version, status" in source
    assert "Sold inventory cannot be moved; use the refund/return workflow" in source


def test_database_immutability_guard_is_translated_to_safe_conflict() -> None:
    source = (BACKEND / "main.py").read_text()
    assert "except asyncpg.PostgresError as exc" in source
    assert 'exc.sqlstate == "55000"' in source
    assert "Operation conflicts with an immutable or historical record state" in source
    assert "status_code=409" in source


def test_database_error_response_never_exposes_raw_database_error() -> None:
    source = (BACKEND / "main.py").read_text()
    block = source.split("def _database_error_response", 1)[1].split("def create_app", 1)[0]
    assert "str(exc)" not in block
    assert "exc.args" not in block
