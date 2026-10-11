from copy import deepcopy

import pytest

from app.import_inventory import inventory_condition_for_copy
from app.collectr_snapshot import collectr_snapshot_key, collectr_source_snapshot_key


@pytest.mark.parametrize('company,grade', [('PSA','10'),('BGS','9.5'),('CGC','10'),('ACE','9')])
def test_graded_projection_keeps_receipt_identity_unchanged(company, grade):
    source={'product_type':'CARD','game':'Pokemon','name':'Synthetic Card','set_name':'Synthetic Set',
            'card_number':'001','variant':'Holofoil','language':'English','condition':'Near Mint',
            'grading_company':company,'grade':grade,'certificate_number':'synthetic-cert'}
    source['_collectr_source_identity']=list(collectr_snapshot_key(source))
    before=deepcopy(source)
    key=collectr_source_snapshot_key(source)
    assert inventory_condition_for_copy(source) is None
    assert source==before
    assert collectr_source_snapshot_key(source)==key
    assert source['condition']=='Near Mint'


@pytest.mark.parametrize('condition', [None,'Near Mint','Lightly Played','Damaged'])
def test_raw_condition_is_not_discarded(condition):
    assert inventory_condition_for_copy({'product_type':'CARD','condition':condition})==condition


@pytest.mark.parametrize('source', [
    {'product_type':'CARD','grade':'10','condition':'Near Mint'},
    {'product_type':'CARD','grading_company':'PSA','condition':'Near Mint'},
    {'product_type':'CARD','grading_company':' ','grade':'10','condition':'Near Mint'},
    {'product_type':'SEALED','grading_company':'PSA','grade':'10','condition':'Near Mint'},
])
def test_unresolved_shape_is_not_silently_repaired(source):
    # These must still be rejected by review/database validation, not silently
    # converted into a different physical product by this narrow projection.
    assert inventory_condition_for_copy(source)=='Near Mint'


def test_sealed_state_is_not_converted_to_condition():
    assert inventory_condition_for_copy({'product_type':'SEALED','seal_status':'SEALED','condition':None}) is None
