"""Do not leak owner data while diagnosing unpublished R2 game mismatches."""
from app.catalogue_r2_live import public_game_parity_diff


def test_game_parity_report_ignores_all_private_fields():
    expected=[
        {"system_code":"POKEMON_TCG","game":"Pokemon","languages":["English"],
         "products":100,"sets":10,
         "private_notes":"DO_NOT_LOG","owner_id":"PRIVATE_OWNER"},
        {"system_code":"ONE_PIECE_CARD_GAME","game":"One Piece",
         "languages":["English"],"products":90,"sets":4},
    ]
    actual=[
        {"system_code":"POKEMON_TCG","game":"Pokemon","languages":["English"],
         "products":99,"sets":10,"customer_secret":"NEVER"},
        {"system_code":"ONE_PIECE_CARD_GAME","game":"One Piece",
         "languages":["English"],"products":90,"sets":4},
    ]
    result=public_game_parity_diff(expected,actual)
    assert result["differences"]==[{
        "system_code":"POKEMON_TCG",
        "fields":{"products":{"sql":100,"r2":99}}
    }]
    assert result["sql_order"]==["POKEMON_TCG","ONE_PIECE_CARD_GAME"]
    assert result["r2_order"]==["POKEMON_TCG","ONE_PIECE_CARD_GAME"]
    assert "DO_NOT_LOG" not in str(result)
    assert "PRIVATE_OWNER" not in str(result)
    assert "NEVER" not in str(result)


def test_game_parity_report_can_distinguish_only_order_difference():
    original=[
        {"system_code":"POKEMON_TCG","game":"Pokemon","products":2,"sets":1},
        {"system_code":"MANGA","game":"Manga","products":4,"sets":2},
    ]
    cached=list(reversed(original))
    report=public_game_parity_diff(original,cached)
    assert report["differences"]==[]
    assert report["sql_order"]!=report["r2_order"]
