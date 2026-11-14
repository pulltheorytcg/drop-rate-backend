from datetime import datetime,timezone,timedelta
import pytest

from app.cardmarket_public_pilot import PilotError
from scripts.audit_cardmarket_metadata_fields import field_coverage

NOW=datetime(2026,11,14,22,tzinfo=timezone.utc)


def export(rows,*,stamp=None):
    return {"createdAt":(stamp or NOW).isoformat(),"products":rows}


def test_explicit_metadata_and_image_fields_counted_without_linking_cards():
    rows=[
        {"idProduct":1,"idExpansion":5,"name":"Card 1","number":"001","rarity":"Rare","image":"https://example.test/1.png"},
        {"idProduct":2,"idExpansion":5,"name":"Card 2"},
    ]
    report=field_coverage(export(rows),game="pokemon",now=NOW)
    assert report["product_rows"]==2
    assert report["populated_fields"]["idExpansion"]==2
    assert report["populated_fields"]["number"]==1
    assert report["has_card_number_and_image"]==1
    assert report["has_card_number_and_rarity"]==1
    assert report["crosswalk_publishable_from_name_only"] is False
    assert report["db_writes"]==0


@pytest.mark.parametrize("rows",[
    [{"idProduct":1,"name":"A"},{"idProduct":1,"name":"B"}],
    [{"idProduct":0,"name":"A"}],
    [{"idProduct":True,"name":"A"}]
])
def test_unsupported_product_identity_fails_closed(rows):
    with pytest.raises(PilotError):
        field_coverage(export(rows),game="pokemon",now=NOW)


def test_stale_file_and_unknown_game_rejected():
    with pytest.raises(PilotError):
        field_coverage(export([{"idProduct":1}],stamp=NOW-timedelta(days=4)),game="pokemon",now=NOW)
    with pytest.raises(PilotError):
        field_coverage(export([{"idProduct":1}]),game="naruto",now=NOW)
