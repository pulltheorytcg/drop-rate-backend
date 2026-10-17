"""The real-provider release check accepts only the known print edition/art."""
import json
from pathlib import Path

import pytest

from scripts.book_research_smoketest import fixture_record, fixture_cover

ENTRY = json.loads((Path(__file__).resolve().parents[1] /
    'backend/data/book_catalogue_starter_20261016.json').read_text())['entries'][0]


def candidate(**updates):
    return dict(source_url=ENTRY['source_url'], fields=ENTRY['book'],
                image_url=ENTRY['cover_source_url'], cover_matches_photo=True, **updates)


@pytest.mark.parametrize('suffix', ['', '/paperback'])
def test_known_publisher_print_aliases_require_exact_isbn_and_visual_art(suffix):
    row = candidate(); row['source_url'] += suffix
    assert fixture_record(row, ENTRY) and fixture_cover(row, ENTRY)
    row['fields'] = {**row['fields'], 'barcode_gtin': '9781591160571'}
    assert not fixture_record(row, ENTRY) and not fixture_cover(row, ENTRY)


@pytest.mark.parametrize('source', [
    ENTRY['source_url'] + '/digital', ENTRY['source_url'] + '?format=paperback',
    ENTRY['source_url'].replace('/139', '/140'),
    ENTRY['source_url'].replace('www.viz.com', 'www.viz.com.evil.test')])
def test_other_records_formats_and_hosts_fail(source):
    row = candidate(); row['source_url'] = source
    assert not fixture_record(row, ENTRY) and not fixture_cover(row, ENTRY)


def test_missing_different_or_visually_unmatched_cover_fails():
    row = candidate(); row['image_url'] = None
    assert fixture_record(row, ENTRY) and not fixture_cover(row, ENTRY)
    row['image_url'] = 'https://dw9to29mmj727.cloudfront.net/products/159116057X.jpg'
    assert not fixture_cover(row, ENTRY)
    row['image_url'] = ENTRY['cover_source_url']; row['cover_matches_photo'] = False
    assert not fixture_cover(row, ENTRY)
