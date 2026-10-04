import json
import subprocess
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'automation/n8n/pilot/safe-diagnostics.cjs'


def classify(stdout):
    code="const {classify}=require(process.argv[1]);const stdout=require('fs').readFileSync(0,'utf8');console.log(JSON.stringify(classify({stdout},'EXECUTE')));"
    result=subprocess.run(['node','-e',code,str(MODULE)],input=stdout,capture_output=True,text=True,check=True,timeout=5)
    assert 'PRIVATE' not in result.stdout and not result.stderr
    return json.loads(result.stdout)['reason']


def test_actual_error_wins_over_workflow_guard_source():
    run={'workflowData':{'nodes':[{'parameters':{'jsCode':"throw new Error('approved_pilot_hash_not_configured'); // PRIVATE"}}]},
         'data':{'resultData':{'error':{'message':'access to env vars denied','description':'PRIVATE'}}}}
    assert classify('Execution failed\n'+json.dumps(run,indent=2)+'\nEnd')=='N8N_ENV_ACCESS_DENIED'


def test_truncated_execution_stays_unknown():
    raw='{"workflowData":{"nodes":[{"jsCode":"approved_pilot_hash_not_configured PRIVATE"}]},"data":'
    assert classify(raw)=='PILOT_RUNTIME_UNVERIFIED'


def test_successful_execution_dump_cannot_imply_guard_failure():
    run={'workflowData':{'nodes':[{'parameters':{'jsCode':'approved_pilot_hash_not_configured'}}]},
         'data':{'resultData':{'runData':{},'error':None}}}
    assert classify(json.dumps(run))=='PILOT_RUNTIME_UNVERIFIED'
