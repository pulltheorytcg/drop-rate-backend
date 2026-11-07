import json
import subprocess
from pathlib import Path


def test_committed_pilot_export_and_code_syntax():
    root=Path(__file__).resolve().parents[1]
    file=root/'automation/n8n/pilot/approved-social-pilot.json'
    workflow=json.loads(file.read_text())
    assert workflow['id']=='DRApprovedSocialPilotV1'
    assert workflow['active'] is False
    assert workflow['settings']['saveDataSuccessExecution']=='none'
    assert workflow['settings']['saveDataErrorExecution']=='none'
    assert not any('scheduleTrigger' in n['type'] or 'webhook' in n['type'] for n in workflow['nodes'])
    for node in workflow['nodes']:
        if node['type']=='n8n-nodes-base.httpRequest':
            assert node['retryOnFail'] is False
            assert node['parameters']['contentType']=='json'
        if node['type']=='n8n-nodes-base.code':
            result=subprocess.run(['node','-e','new Function(process.argv[1]);',node['parameters']['jsCode']],capture_output=True,text=True,timeout=10)
            assert result.returncode==0,result.stderr
