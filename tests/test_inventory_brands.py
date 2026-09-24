from app.api import BRAND_SQL
from app.brands import KNOWN_BRANDS, brand_for_game, brand_sql


def test_known_brand_grouping() -> None:
    assert brand_for_game('One Piece') == 'One Piece'
    assert brand_for_game('Pokemon') == 'Pokemon'
    assert brand_for_game('Dragon Ball Super') == 'Dragon Ball'
    assert brand_for_game('Dragon Ball Super Fusion World') == 'Dragon Ball'
    assert brand_for_game('Naruto Kayou') == 'Naruto'
    assert brand_for_game('Riftbound: League of Legends TCG') == 'Riftbound'


def test_unknown_game_falls_back_to_exact_game() -> None:
    assert brand_for_game('Future TCG') == 'Future TCG'


def test_brand_sql_uses_catalogue_game() -> None:
    sql = brand_sql('p')
    assert 'p.game' in sql
    assert "dragon ball%" in sql
    assert BRAND_SQL == sql


def test_requested_brand_set() -> None:
    assert KNOWN_BRANDS == ('One Piece', 'Pokemon', 'Dragon Ball', 'Naruto', 'Riftbound')
