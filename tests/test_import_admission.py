from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.import_admission import exact_admission, meets_threshold, identity_fingerprint, manual_admission_valid
from app.owner_auto_imports import ConfirmImportCandidate


@pytest.mark.parametrize('value,expected',[(.95,True),('0.95',True),(Decimal('0.95'),True),(.949999,False),(1,True),(1.01,False),(-1,False),(None,False),('NaN',False),('Infinity',False),('95%',False)])
def test_inclusive_threshold(value,expected):
    assert meets_threshold(value)==expected


def records():
    source={'product_type':'CARD','game':'Pokemon','name':'Known Card','set_name':'Synthetic Set','card_number':'001','variant':'Normal','rarity':'C','language':'English'}
    return source,dict(source,id=uuid4())


def test_exact_complete_unique_identity_has_rule_evidence_not_fake_calibration():
    source,catalogue=records()
    result=exact_admission(source,catalogue,unique=True)
    assert result['method']=='EXACT_CATALOGUE_IDENTITY'
    assert meets_threshold(result['rule_confidence'])
    assert result['calibrated_probability'] is None
    assert result['identity_fingerprint']==identity_fingerprint(catalogue)
    assert exact_admission(source,catalogue,unique=False) is None


@pytest.mark.parametrize('field',['game','name','set_name','card_number','variant','language'])
def test_conflicts_and_missing_facts_cannot_be_hidden_by_a_high_csv_score(field):
    source,catalogue=records()
    source['confidence']=1.0
    source[field]='Different'
    assert exact_admission(source,catalogue,unique=True) is None
    source[field]=''
    assert exact_admission(source,catalogue,unique=True) is None


def test_manual_evidence_is_bound_to_selected_unchanged_identity():
    source,catalogue=records()
    source['import_identity_confirmation']={'method':'MANUAL','catalogue_id':str(catalogue['id']),'identity_fingerprint':identity_fingerprint(catalogue)}
    assert manual_admission_valid(source,catalogue)
    catalogue['language']='Japanese'
    assert not manual_admission_valid(source,catalogue)


def test_wrong_or_unpaired_grade_stays_review():
    source,catalogue=records()
    source['grade']='10'
    assert exact_admission(source,catalogue,unique=True) is None


def test_explicit_manual_language_is_validated():
    for invalid in ('not-a-language','', '<script>'):
        with pytest.raises(ValidationError):
            ConfirmImportCandidate(version=1,catalogue_id=uuid4(),language=invalid)
    assert ConfirmImportCandidate(version=1,catalogue_id=uuid4(),language='EN').language=='English'


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity','-1'])
def test_invalid_costs_go_to_review_not_server_error(value):
    from app.collectr_snapshot import collectr_cost_minor
    from app.imports import _money_minor
    assert collectr_cost_minor(value)==(None,['invalid_purchase_cost'])
    assert _money_minor(value,'GBP')==(None,['invalid_purchase_cost'])


def test_source_receipt_never_masks_changed_physical_identity():
    from app.collectr_snapshot import collectr_snapshot_key, collectr_source_snapshot_key
    source,_=records()
    original=collectr_snapshot_key(source)
    source['_collectr_source_identity']=list(original)
    changed=dict(source,language='Japanese',grade='10',grading_company='PSA')
    assert collectr_snapshot_key(changed)!=original
    assert collectr_source_snapshot_key(changed)==original
