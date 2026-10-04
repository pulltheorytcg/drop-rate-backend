"""Generate inactive specialist exports; no provider/model secrets in workflow JSON."""
import json
from pathlib import Path

STAGES = {
    'research': 'DRMktResearchV1', 'brief': 'DRMktBriefV1',
    'copywriting': 'DRMktCopyV1', 'design': 'DRMktDesignV1',
    'publishing': 'DRMktPublishV1', 'social_management': 'DRMktManageV1',
}
SETTINGS = {
    'executionOrder': 'v1', 'errorWorkflow': 'DR90GlobalErrorV1',
    'saveDataErrorExecution': 'none', 'saveDataSuccessExecution': 'none',
    'saveManualExecutions': False, 'saveExecutionProgress': False, 'executionTimeout': 180,
}
SIGNER = r"""const crypto = require('crypto');
if (String($env.DROP_RATE_MARKETING_SPECIALISTS_ENABLED || '').toLowerCase() !== 'true') throw new Error('marketing_specialists_disabled');
if ($input.all().length !== 1) throw new Error('marketing_single_job_required');
const input = $input.first().json;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
if (!uuid.test(String(input.job_id || '')) || !uuid.test(String(input.actor_user_id || '')) || input.revision !== 1 || !/^[0-9a-f]{64}$/.test(String(input.expected_input_sha256 || ''))) throw new Error('marketing_input_invalid');
const command = {job_id: input.job_id, actor_user_id: input.actor_user_id, revision: 1, stage: '__STAGE__', expected_input_sha256: input.expected_input_sha256};
const secret = String($env.DROP_RATE_AUTOMATION_COMMAND_SECRET || '').trim();
const receipt = String($env.DROP_RATE_API_AUTOMATION_CONTROL_URL || '').trim();
const publicUrl = 'https://drop-rate-api-live-production.up.railway.app/api/v1/automation/control/receipt';
const privateUrl = /^http:\/\/drop-rate-api-live\.railway\.internal:[0-9]{1,5}\/api\/v1\/automation\/control\/receipt$/;
if (secret.length < 32) throw new Error('marketing_signature_not_configured');
if (receipt !== publicUrl && !privateUrl.test(receipt)) throw new Error('marketing_backend_url_invalid');
const body = JSON.stringify(command);
const timestamp = String(Math.floor(Date.now()/1000));
const signature = 'sha256=' + crypto.createHmac('sha256', secret).update(timestamp + '.' + body, 'utf8').digest('hex');
return [{json:{command_url:receipt.replace('/automation/control/receipt','/automation/commands/marketing/run'),command_body:body,command_timestamp:timestamp,command_signature:signature,command}}];"""
VERIFY = r"""const r = $input.first().json || {};
const status = Number(r.statusCode || 0);
if (status !== 200) throw new Error('marketing_backend_http_' + status);
const b = r.body || {};
const c = $('Sign Command').first().json.command;
for (const key of ['job_id','actor_user_id','revision','stage','expected_input_sha256']) {
  if (b[key] !== c[key]) throw new Error('marketing_response_identity_mismatch');
}
if (!['PREPARED','NEEDS_REVIEW','AWAITING_MEDIA','BLOCKED','RUNNING','FAILED','UNKNOWN'].includes(b.state) || b.publishable !== false || b.published !== false) throw new Error('marketing_response_contract_invalid');
return [{json:b}];"""
GATE = "const b = $input.first().json; if (b.state !== 'PREPARED') throw new Error('marketing_handoff_stopped_' + String(b.state)); return [{json:b}];"


def node(name, kind, parameters, x=0):
    return {'id': name.lower().replace(' ', '-'), 'name': name, 'type': 'n8n-nodes-base.' + kind,
            'typeVersion': {'code': 2, 'httpRequest': 4.2, 'executeWorkflow': 1.2}.get(kind, 1),
            'position': [x, 0], 'parameters': parameters}


def connections(nodes):
    return {left['name']: {'main': [[{'node': right['name'], 'type': 'main', 'index': 0}]]}
            for left, right in zip(nodes, nodes[1:])}


def workflow(wid, name, nodes):
    return {'id': wid, 'name': name, 'active': False, 'settings': dict(SETTINGS),
            'nodes': nodes, 'connections': connections(nodes), 'pinData': {},
            'meta': {'dropRate': {'version': 1, 'status': 'BUILT_INACTIVE_UNVERIFIED_RUNTIME',
                                'publishable': False, 'higgsfield': False}}}


def exports():
    result = []
    for stage, wid in STAGES.items():
        request = node('Run via FastAPI', 'httpRequest', {
            'method': 'POST', 'url': '={{ $json.command_url }}', 'sendHeaders': True,
            'headerParameters': {'parameters': [
                {'name': 'X-Drop-Rate-Timestamp', 'value': '={{ $json.command_timestamp }}'},
                {'name': 'X-Drop-Rate-Signature', 'value': '={{ $json.command_signature }}'},
            ]}, 'sendBody': True, 'contentType': 'raw', 'rawContentType': 'application/json',
            'body': '={{ $json.command_body }}', 'options': {
                'timeout': 120000, 'redirect': {'redirect': {'followRedirects': False}},
                'response': {'response': {'fullResponse': True, 'neverError': True, 'responseFormat': 'json'}},
            },
        }, 240)
        request['retryOnFail'] = False
        nodes = [node('Specialist Input', 'executeWorkflowTrigger', {}, -240),
                 node('Sign Command', 'code', {'jsCode': SIGNER.replace('__STAGE__', stage)}),
                 request, node('Verify Result', 'code', {'jsCode': VERIFY}, 480)]
        result.append(workflow(wid, 'Drop Rate Marketing | ' + stage.replace('_', ' ').title() + ' V1', nodes))
    nodes = [node('Existing Job Input', 'executeWorkflowTrigger', {}, -240)]
    for index, stage in enumerate(['research', 'brief', 'copywriting', 'design']):
        nodes.append(node('Run ' + stage.title(), 'executeWorkflow', {
            'workflowId': {'__rl': True, 'value': STAGES[stage], 'mode': 'id'},
            'mode': 'each', 'options': {'waitForSubWorkflow': True},
        }, index * 480))
        if stage != 'design':
            nodes.append(node(stage.title() + ' Prepared', 'code', {'jsCode': GATE}, index * 480 + 240))
    parent = workflow('DRMktPrepareV1', 'Drop Rate Marketing | Preparation Coordinator V1', nodes)
    parent['meta']['dropRate']['stopsAt'] = 'AWAITING_MEDIA_OR_NEEDS_REVIEW'
    result.append(parent)
    return result


if __name__ == '__main__':
    Path(__file__).with_name('workflows.json').write_text(json.dumps(exports(), indent=2) + '\n')
