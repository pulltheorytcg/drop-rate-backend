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


@pytest.mark.parametrize('failure_point', ['before_generation', 'before_journal'])
def test_midnight_retry_preserves_one_original_reservation_and_capture_mark(setup, monkeypatch, failure_point):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    original_meta={'captured_at':'2026-11-08T23:59:00+00:00','source_snapshot':'100:102:101'}
    stage_real=replay.stage
    insert_real=replay._insert_rows
    def before_generation(*args,**kwargs):
        raise OSError('synthetic interruption before generation creation')
    def before_journal(*args,**kwargs):
        if args[2]=='ops_shadow_inventory_replay':
            raise OSError('synthetic interruption before journal')
        return insert_real(*args,**kwargs)
    monkeypatch.setattr(replay,'stage',before_generation if failure_point=='before_generation' else stage_real)
    monkeypatch.setattr(replay,'_insert_rows',before_journal if failure_point=='before_journal' else insert_real)
    with pytest.raises(OSError):
        replay.replay(db,new,schema,cat,original_meta,apply=True)
    reserved=[tuple(row) for row in db.con.execute('SELECT * FROM ops_shadow_replay_daily_budget')]
    monkeypatch.setattr(replay,'stage',stage_real)
    monkeypatch.setattr(replay,'_insert_rows',insert_real)
    r=replay.replay(db,new,schema,cat,
        {'captured_at':'2026-11-09T00:01:00+00:00','source_snapshot':'200:202:201'},apply=True)
    assert r['status']=='INVENTORY_REPLAY_SNAPSHOT_PARITY_VERIFIED'
    assert [tuple(row) for row in db.con.execute('SELECT * FROM ops_shadow_replay_daily_budget')]==reserved
    marks=db.con.execute('SELECT g.source_captured_at,c.captured_at,h.captured_at '
        'FROM ops_shadow_replay_checkpoints c JOIN ops_shadow_generations g USING(generation_id) '
        'JOIN ops_shadow_replay_head h USING(generation_id)').fetchone()
    assert tuple(marks)==(original_meta['captured_at'],)*3
    assert db.con.execute('SELECT source_snapshot FROM ops_shadow_replay_checkpoints').fetchone()[0]==original_meta['source_snapshot']
    assert db.con.execute('SELECT count(*) FROM ops_shadow_inventory_replay').fetchone()[0]==1


@pytest.mark.parametrize('problem', ['duplicate', 'stale_capture', 'wrong_count', 'wrong_day', 'wrong_parent'])
def test_invalid_original_reservation_cannot_be_replaced_by_new_day_receipt(setup, monkeypatch, problem):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    real=replay.stage
    def crash(*args,**kwargs):
        raise OSError('synthetic interruption after reserving capacity')
    monkeypatch.setattr(replay,'stage',crash)
    with pytest.raises(OSError):
        replay.replay(db,new,schema,cat,meta(),apply=True)
    monkeypatch.setattr(replay,'stage',real)
    if problem=='duplicate':
        db.con.execute("INSERT INTO ops_shadow_replay_daily_budget SELECT '2026-11-09',"
            "generation_id,parent_generation_id,'2026-11-09T12:00:00+00:00',source_snapshot,"
            "logical_rows_reserved FROM ops_shadow_replay_daily_budget")
    elif problem=='wrong_count':
        db.con.execute('UPDATE ops_shadow_replay_daily_budget SET logical_rows_reserved=1')
    elif problem=='wrong_day':
        db.con.execute("UPDATE ops_shadow_replay_daily_budget SET utc_day='2026-11-07'")
    elif problem=='wrong_parent':
        db.con.execute("UPDATE ops_shadow_replay_daily_budget SET parent_generation_id='not-the-parent'")
    before=db.con.total_changes
    day='2026-11-07' if problem=='stale_capture' else '2026-11-09'
    with pytest.raises(stage.StageGuard):
        replay.replay(db,new,schema,cat,meta(day=day),apply=True)
    assert db.con.total_changes==before
    assert db.con.execute('SELECT count(*) FROM ops_shadow_generations').fetchone()[0]==1


def test_lost_activation_acknowledgement_is_idempotent_after_midnight(setup, monkeypatch):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    batch=db.batch
    lost=False
    def lost_ack(dbid,queries):
        nonlocal lost
        result=batch(dbid,queries)
        if not lost and any('ops_shadow_replay_head' in row['sql'] for row in queries):
            lost=True
            raise OSError('synthetic acknowledgement lost after local commit')
        return result
    monkeypatch.setattr(db,'batch',lost_ack)
    with pytest.raises(OSError):
        replay.replay(db,new,schema,cat,meta(),apply=True)
    original=[tuple(row) for row in db.con.execute('SELECT * FROM ops_shadow_replay_daily_budget')]
    before=db.con.total_changes
    assert replay.replay(db,new,schema,cat,meta(day='2026-11-09'),apply=True)['status']=='INVENTORY_REPLAY_ALREADY_VERIFIED'
    assert db.con.total_changes==before
    assert [tuple(row) for row in db.con.execute('SELECT * FROM ops_shadow_replay_daily_budget')]==original


@pytest.mark.parametrize('problem', ['duplicate_budget','missing_budget','capture_mismatch','typed_projection'])
def test_already_advanced_head_does_not_hide_corrupt_legacy_retry(setup, problem):
    db,data,schema,cat=setup
    new=changed(data,version=2,market_value_minor=123)
    r=replay.replay(db,new,schema,cat,meta(),apply=True)
    generation='src-'+r['generation_sha256'][:32]
    if problem=='duplicate_budget':
        db.con.execute("INSERT INTO ops_shadow_replay_daily_budget SELECT '2026-11-09',"
            "generation_id,parent_generation_id,'2026-11-09T12:00:00+00:00',source_snapshot,"
            "logical_rows_reserved FROM ops_shadow_replay_daily_budget")
    elif problem=='missing_budget':
        db.con.execute('DELETE FROM ops_shadow_replay_daily_budget')
    elif problem=='capture_mismatch':
        db.con.execute("UPDATE ops_shadow_generations SET source_captured_at='2026-11-09T12:00:00+00:00' WHERE generation_id=?",[generation])
    else:
        db.con.execute('UPDATE ops_shadow_inventory SET market_value_minor=999 WHERE generation_id=?',[generation])
    before=db.con.total_changes
    with pytest.raises(stage.StageGuard):
        replay.replay(db,new,schema,cat,meta(day='2026-11-09'),apply=True)
    assert db.con.total_changes==before
