import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('exit_inventory',Path(__file__).resolve().parents[1]/'tools/supabase_exit_inventory.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_reports_locations_without_secret_values_and_does_not_claim_cutover(tmp_path):
    (tmp_path/'app.py').write_text('SUPABASE_KEY="private-secret"\nimport asyncpg\n')
    result=m.inventory(tmp_path,['app.py'])
    assert result['dependency_candidates']==2
    assert 'private-secret' not in str(result)
    assert result['live_dependency_total'] is None
    assert result['production_cutover_authorized'] is False

def test_history_tests_and_operations_are_not_counted_as_runtime(tmp_path):
    for name in ['docs/old.md','tests/test_auth.py','.github/workflows/test.yml','backend/app/auth.py']:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('supabase')
    r=m.inventory(tmp_path,['docs/old.md','tests/test_auth.py','.github/workflows/test.yml','backend/app/auth.py'])
    assert r['by_scope']=={'historical_or_schema':1,'tests':1,'migration_or_operations':1,'runtime_or_configuration':1}

def test_skips_symlink_and_binary_and_deduplicates_paths(tmp_path):
    (tmp_path/'data').write_bytes(b'\xffsupabase')
    (tmp_path/'link').symlink_to('/etc/passwd')
    (tmp_path/'app.py').write_text('supabase\nsupabase')
    r=m.inventory(tmp_path,['app.py','app.py','data','link'])
    assert r['dependency_candidates']==1
    assert r['findings'][0]['lines']==[1,2]
    assert r['unread_files']==['data','link']
