"""Disposable SQLite simulations: no real D1/PG data or credentials."""
import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import d1_operational_source_stage as stage
import d1_operational_snapshot_replay as replay
from test_d1_operational_source_stage import FakeCloudflareD1, fixtures, job as fixture_job

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(stage,'FLOORS',{t:1 for t in stage.TABLES})
    monkeypatch.setattr(fixture_job,'FLOORS',{t:1 for t in stage.TABLES})
    db=FakeCloudflareD1();data=fixtures()
    # Replay needs the original per-table schema, not arbitrary fixture metadata.
    schema={name:[{'column':k,'type':'fixture'} for k in rows[0][1]] for name,rows in data.items()}
    catalogue={'c1':'a'*64}
    stage.stage(db,data,schema,catalogue)
    return db,data,schema,catalogue

def changed(data,**fields):
    data=copy.deepcopy(data);obj=data['inventory_items'][0][1];obj.update(fields)
    raw=json.dumps(obj,separators=(',',':'))
    data['inventory_items']=[(obj['id'],obj,raw,stage.sha(raw))]
    return data

def meta(day='2026-11-08',time='12:00:00'):
    return {'captured_at':day+'T'+time+'+00:00','source_snapshot':'100:102:101'}

def test_append_exact_parity_idempotency_and_original_preservation(setup):
    db,data,schema,cat=setup
    original=db.con.execute('SELECT * FROM ops_shadow_inventory').fetchall()
    new=changed(data,version=2,market_value_minor=123)
    r=replay.replay(db,new,schema,cat,meta(),apply=True)
    assert r['post_replay_snapshot_differences']==0
    assert r['classification_counts']=={'PRICING_FIELD_UPDATE':1}
    assert r['unexplained_differences']==0
    assert len(db.con.execute('SELECT * FROM ops_shadow_inventory').fetchall())==2
    assert tuple(db.con.execute('SELECT * FROM ops_shadow_inventory WHERE generation_id=?',[original[0]['generation_id']]).fetchone())==tuple(original[0])
    assert replay.replay(db,new,schema,cat,meta(time='13:00:00'),apply=True)['status']=='INVENTORY_REPLAY_ALREADY_VERIFIED'
    assert db.con.execute('SELECT COUNT(*) FROM ops_shadow_inventory_replay').fetchone()[0]==1
    values=db.con.execute('SELECT store_price_minor,owner_id FROM ops_shadow_inventory').fetchall()
    assert all(tuple(v)==(500,'o1') for v in values)
    assert 'i1' not in json.dumps(r)

def test_new_update_reverified_next_window_and_same_day_budget_is_not_bypassed(setup):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    replay.replay(db,new,schema,cat,meta(),apply=True)
    later=changed(new,version=3,market_value_minor=124)
    assert replay.replay(db,later,schema,cat,meta(time='13:00:00'),apply=True)['status']=='INVENTORY_REPLAY_DEFERRED_DAILY_BUDGET'
    r=replay.replay(db,later,schema,cat,meta(day='2026-11-09'),apply=True)
    assert r['post_replay_snapshot_differences']==0
    assert db.con.execute('SELECT COUNT(*) FROM ops_shadow_replay_checkpoints').fetchone()[0]==2

@pytest.mark.parametrize('fields',[
    {'version':0}, {'version':1,'market_value_minor':123},
    {'version':2,'owner_id':'foreign'}, {'version':2,'store_price_minor':100},
    {'version':2,'acquisition_cost_minor':200}, {'version':2,'unknown_private_field':'secret'},
])
def test_protected_or_unexplained_changes_block_without_target_writes(setup,fields):
    db,data,schema,cat=setup
    before=db.con.total_changes
    with pytest.raises((stage.StageGuard,replay.SnapshotDriftGuard)):
        replay.replay(db,changed(data,**fields),schema,cat,meta(),apply=True)
    assert db.con.total_changes==before

def test_financial_drift_blocks_inventory_replay(setup):
    db,data,schema,cat=setup
    obj=data['financial_ledger_entries'][0][1];obj['amount_minor']=999
    raw=json.dumps(obj)
    data['financial_ledger_entries']=[(obj['id'],obj,raw,stage.sha(raw))]
    with pytest.raises(stage.StageGuard,match='Non-inventory'):
        replay.replay(db,data,schema,cat,meta(),apply=True)

def test_partial_stage_resumes_without_overwriting_old_snapshot(setup,monkeypatch):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    real=replay._insert_rows;failed=False
    def fail(*args,**kw):
        nonlocal failed
        if args[2]=='ops_shadow_inventory_replay' and not failed:
            failed=True;raise OSError('simulated lost acknowledgement')
        return real(*args,**kw)
    monkeypatch.setattr(replay,'_insert_rows',fail)
    with pytest.raises(OSError):replay.replay(db,new,schema,cat,meta(),apply=True)
    assert db.con.execute("SELECT COUNT(*) FROM ops_shadow_generations WHERE state='REJECTED'").fetchone()[0]==1
    assert replay.replay(db,new,schema,cat,meta(time='12:01:00'),apply=True)['post_replay_snapshot_differences']==0
    assert db.con.execute('SELECT COUNT(*) FROM ops_shadow_inventory_replay').fetchone()[0]==1

def test_stale_capture_time_cannot_replace_newer_checkpoint(setup):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    replay.replay(db,new,schema,cat,meta(),apply=True)
    with pytest.raises(stage.StageGuard,match='Stale'):
        replay.replay(db,changed(new,version=3,market_value_minor=125),schema,cat,meta(day='2026-11-07'),apply=True)

def test_dry_run_performs_no_ddl_or_data_writes(setup):
    db,data,schema,cat=setup;before=db.con.total_changes
    r=replay.replay(db,changed(data,version=2,market_value_minor=123),schema,cat,meta())
    assert r['status']=='INVENTORY_REPLAY_DRY_RUN_VALIDATED'
    assert db.con.total_changes==before

@pytest.mark.parametrize('fields,category',[
    ({'version':2},'VERSION_INCREMENT'),
    ({'version':2,'condition':'LP'},'LEGITIMATE_INVENTORY_UPDATE'),
    ({'updated_at':'2026-11-08T12:00:00Z'},'TIMESTAMP_ONLY_CHANGE'),
])
def test_classifies_each_record_exactly_once(setup,fields,category):
    db,data,schema,cat=setup
    # Establish a baseline with a timestamp using a separate fixture database.
    data=changed(data,updated_at='2026-11-07T12:00:00Z')
    db=FakeCloudflareD1()
    schema['inventory_items'].append({'column':'updated_at','type':'fixture'})
    stage.stage(db,data,schema,cat)
    r=replay.replay(db,changed(data,**fields),schema,cat,meta())
    assert r['classification_counts']=={category:1}

def test_typed_projection_corruption_is_not_hidden_by_a_correct_hash(setup):
    db,data,schema,cat=setup
    db.con.execute('UPDATE ops_shadow_inventory SET market_value_minor=999')
    with pytest.raises(stage.StageGuard,match='typed-field'):
        stage.stage(db,data,schema,cat)

def test_reader_ignores_quarantined_partial_generation(setup):
    from d1_operational_source_delta_watch import verify_shadow
    db,data,schema,cat=setup
    newer=changed(data,version=2,market_value_minor=123)
    stage.stage(db,newer,schema,cat,initial_state='REJECTED')
    r=verify_shadow(db,data,cat)
    assert r['changed_or_missing_record_count']==0
