"""Pure mapping tests. Database-trigger and HTTP tests run separately in CI."""
from copy import deepcopy

import pytest

from app.import_inventory import physical_inventory_condition
from app.collectr_snapshot import collectr_source_snapshot_key


@pytest.mark.parametrize('company,grade', [('PSA', '10'), ('BGS', '9.5'), ('CGC', '10'), ('ACE', '9')])
@pytest.mark.parametrize('condition', ['Near Mint', 'Lightly Played', None])
def test_graded_projection_preserves_import_source_and_grade(company, grade, condition):
    record = {'product_type': 'CARD', 'game': 'Pokemon', 'name': 'Synthetic card',
              'set_name': 'Synthetic set', 'card_number': '001', 'variant': 'Normal',
              'language': 'English', 'condition': condition,
              'grading_company': company, 'grade': grade, 'certificate_number': 'SYNTHETIC-001'}
    original = deepcopy(record)
    source_key = collectr_source_snapshot_key(record)
    assert physical_inventory_condition(record) is None
    assert record == original
    assert collectr_source_snapshot_key(record) == source_key


@pytest.mark.parametrize('condition', ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged', None])
def test_raw_condition_is_not_lost(condition):
    assert physical_inventory_condition({'product_type': 'CARD', 'condition': condition}) == condition


@pytest.mark.parametrize('record', [
    {'product_type': 'CARD', 'grade': '10', 'condition': 'Near Mint'},
    {'product_type': 'CARD', 'grading_company': 'PSA', 'condition': 'Near Mint'},
    {'product_type': 'BOX', 'grading_company': 'PSA', 'grade': '10', 'condition': 'Near Mint'},
])
def test_projection_is_not_a_blanket_bypass_for_invalid_physical_data(record):
    assert physical_inventory_condition(record) == 'Near Mint'


def test_sealed_state_is_separate_and_unmodified():
    record = {'product_type': 'BOX', 'seal_status': 'SEALED', 'condition': None}
    original = deepcopy(record)
    assert physical_inventory_condition(record) is None
    assert record == original
