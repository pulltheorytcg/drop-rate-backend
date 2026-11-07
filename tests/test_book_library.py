"""Catalogue -> saved copy art, legacy exact barcode repair and failed matches."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.book_artwork import reviewed_catalogue_entries, publisher_cover_url
from app.book_research import add_saved_book_artwork, publisher_source, source_cover_matches, reviewed_candidates
from scripts.seed_book_catalogue import load_seed
from test_book_catalogue import cover_book


def legacy_row(**changes):
    return dict(catalogue_id=uuid4(),inventory_id=uuid4(),provider_evidence=None,
        system_code='MARVEL_COMICS',series_title='Deadpool / Batman',issue_number='1',
        volume_identifier=None,printing_number=2,release_year=None,cover_code=None,cover_artist=None,
        barcode_gtin='75960621349800112',language='English',identity_status='NEEDS_REVIEW',
        profile_status='NEEDS_REVIEW',profile_release_date=None,
        attributes={'publisher':'Marvel','book_format':'SINGLE_ISSUE'},**changes)


@pytest.mark.asyncio
async def test_exact_saved_barcode_gets_reviewed_cover_without_identity_or_stock_changes():
    row=legacy_row(); before=deepcopy(row)
    db=AsyncMock();db.fetch.return_value=[row]
    item=dict(id=row['inventory_id'],catalogue_id=row['catalogue_id'],product_type='COMIC')
    await add_saved_book_artwork(db,[item])
    assert item['reference_image_url']=='https://images.penguinrandomhouse.com/cover/75960621349800112'
    assert item['artwork_kind']=='BARCODE_MATCHED_PUBLISHER_REFERENCE'
    assert item['reference_image_path']==f"/api/v1/owner/inventory/{item['id']}/reference-image"
    assert row==before
    db.execute.assert_not_awaited()


@pytest.mark.parametrize('changes',[
    {'barcode_gtin':None},{'barcode_gtin':'75960621349800122'},{'printing_number':3},
    {'cover_artist':'Frank Miller'},{'language':'Japanese'},{'release_year':2024},
    {'cover_code':'Virgin variant'}, {'issue_number':'2'},
    {'attributes':{'publisher':'Marvel','book_format':'HARDCOVER'}},
    {'attributes':{'publisher':'Marvel','book_format':'SINGLE_ISSUE','cover_rights_status':'REVOKED'}},
])
@pytest.mark.asyncio
async def test_legacy_art_never_guesses_a_variant_or_language(changes):
    row=legacy_row();row.update(changes)
    db=AsyncMock();db.fetch.return_value=[row]
    item=dict(id=row['inventory_id'],catalogue_id=row['catalogue_id'],product_type='COMIC')
    await add_saved_book_artwork(db,[item])
    assert 'reference_image_url' not in item


@pytest.mark.asyncio
async def test_saved_catalogue_books_get_covers_without_scanner_receipt():
    entries=reviewed_catalogue_entries()
    db=AsyncMock();items=[];rows=[]
    for entry in entries:
        id=uuid4();row={**cover_book(entry),'inventory_id':id,'language':'English','provider_evidence':None}
        rows.append(row);items.append(dict(id=id,catalogue_id=UUID(entry['id']),product_type='COMIC'))
    db.fetch.return_value=rows
    await add_saved_book_artwork(db,items)
    assert len(items)==46 and all(i['artwork_kind']=='PUBLISHER_REFERENCE' for i in items)
    db.fetch.assert_awaited_once()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize('source,image',[
    ('https://prhcomics.com/book/?isbn=75960621349800112','https://images.penguinrandomhouse.com/cover/75960621349800122'),
    ('https://prhcomics.com.evil.test/book/?isbn=75960621349800112','https://images.penguinrandomhouse.com/cover/75960621349800112'),
    ('https://prhcomics.com/book/?isbn=75960621349800112&url=evil','https://images.penguinrandomhouse.com/cover/75960621349800112'),
])
def test_distributor_art_is_bound_to_exact_public_identifier(source,image):
    assert not source_cover_matches(source,image)


def test_new_batch_is_bounded_canonical_and_available_to_scan_search():
    data=load_seed(Path(__file__).resolve().parents[1]/'backend/data/book_catalogue_expansion_20261021.json')
    assert len(data['entries'])==32
    assert sum(r['book']['system_code']=='MANGA' for r in data['entries'])==26
    for row in data['entries']:
        candidates=reviewed_candidates({**row['book'],'language':row['language']})
        assert len(candidates)==1 and candidates[0]['image_url']==row['reference']['image_url']
        assert publisher_source(row['source_url']) and publisher_cover_url(row['reference']['image_url'])
        assert not candidates[0]['cover_matches_photo']


@pytest.mark.parametrize('change',[
    {'image_url':'https://images.penguinrandomhouse.com/cover/75960621349800122'},
    {'book_identity_digest':'0'*64},{'language':'Japanese'},{'observed_width':1},
])
def test_import_rejects_invalid_or_cross_edition_reference(tmp_path,change):
    import json
    row=deepcopy(reviewed_catalogue_entries()[-1]);row['reference'].update(change)
    path=tmp_path/'invalid.json';path.write_text(json.dumps({'batch_id':'test','entries':[row]}))
    with pytest.raises(ValueError): load_seed(path)
