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



def test_public_set_diff_never_logs_owner_balances():
    from app.catalogue_r2_live import public_set_parity_diff
    a=[{"system_code":"POKEMON_TCG","set_id":"30th",
        "set_name":"30th Celebration","language":"English",
        "provider":"TCGdex","game":"Pokemon","release_date":"2026-09-16",
        "indexed_count":161,"card_count":161,"total_count":884,
        "owned_count":2,"owned_value_minor":987654321,
        "private_notes":"DO_NOT_LOG"}]
    b=[{**a[0],"set_name":"30th CELEBRATION","owned_count":1,
        "owned_value_minor":765432101,"private_notes":"NEVER"}]
    result=public_set_parity_diff(a,b)
    assert result["differences"][0]["fields"]["set_name"]=={
        "sql":"30th Celebration","r2":"30th CELEBRATION"}
    assert result["differences"][0]["fields"]["owner_aggregates"]=="DIFFERENT"
    assert "987654321" not in str(result)
    assert "765432101" not in str(result)
    assert "DO_NOT_LOG" not in str(result)
    assert "NEVER" not in str(result)
