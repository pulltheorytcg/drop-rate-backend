"""Every importer must supply all parameters to the shared 18-argument SQL.

The final two slots are *optional checks* for exact provider artwork and
publisher printing identity. They must never be silently omitted when the
shared write SQL gains new guards, or the maintenance loop fails at runtime
with an asyncpg InterfaceError before pricing the next source.
"""
import ast
from pathlib import Path
import re

from app.pokewallet_one_piece_market import WRITE_SQL


def test_shared_catalogue_guide_sql_argument_count():
    placeholders = [int(value) for value in re.findall(r"\$(\d+)", WRITE_SQL)]
    assert max(placeholders) == 18
    assert set(placeholders) == set(range(1, 19))
    assert "$17::text is null" in WRITE_SQL
    assert "$18::text is null" in WRITE_SQL


def test_every_catalogue_importer_supplies_full_write_row():
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    for name in (
        "pokewallet_one_piece_market.py",
        "pokewallet_dragon_ball_market.py",
        "pokewallet_pokemon_market.py",
        "tcgcsv_market.py",
        "cardtrader_bulk_guides.py",
    ):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        values = [
            node.args[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "values"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Tuple)
        ]
        assert values, name
        assert all(len(row.elts) == 18 for row in values), name


def test_non_artwork_feeds_explicitly_leave_artwork_guards_unspecified():
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    for name in (
        "pokewallet_dragon_ball_market.py",
        "pokewallet_pokemon_market.py",
        "tcgcsv_market.py",
    ):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        candidates = [
            node.args[0] for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "values"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Tuple)
        ]
        assert len(candidates) == 1, name
        assert all(isinstance(term, ast.Constant) and term.value is None
                   for term in candidates[0].elts[-2:]), name
