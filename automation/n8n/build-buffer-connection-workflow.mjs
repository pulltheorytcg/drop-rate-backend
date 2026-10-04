import { writeFile } from 'node:fs/promises';
import {
  BUFFER_ENDPOINT, BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS,
  BUFFER_CONNECTION_QUERY, summarizeBufferConnection,
} from './buffer-connection.mjs';

const workflow = {
  id: 'DR32BufferConnectionCheckV1',
  name: 'DR-32 Buffer Connection Check (read-only)',
  active: false,
  settings: {
    executionOrder: 'v1', executionTimeout: 30,
    saveDataErrorExecution: 'none', saveDataSuccessExecution: 'none',
    saveManualExecutions: false, saveExecutionProgress: false,
  },
  nodes: [
    {
      id: 'dr32-buffer-trigger', name: 'Check Buffer Connection',
      type: 'n8n-nodes-base.executeWorkflowTrigger', typeVersion: 1.1,
      position: [-520, 0], parameters: { workflowInputs: { values: [] } },
    },
    {
      id: 'dr32-buffer-request', name: 'Read Drop Rate Buffer Channels',
      type: 'n8n-nodes-base.httpRequest', typeVersion: 4.2,
      position: [-240, 0],
      parameters: {
        method: 'POST', url: BUFFER_ENDPOINT,
        sendHeaders: true,
        headerParameters: { parameters: [{
          name: 'Authorization',
          value: "={{ (() => { const key = $env.BUFFER_API_KEY; if (typeof key !== 'string' || !key || /\\s/.test(key)) throw new Error('buffer_key_missing_or_invalid'); return 'Bearer ' + key; })() }}",
        }] },
        sendBody: true, contentType: 'raw', rawContentType: 'application/json',
        body: JSON.stringify({ query: BUFFER_CONNECTION_QUERY }),
        options: {
          timeout: 15000,
          redirect: { redirect: { followRedirects: false } },
          response: { response: { fullResponse: true, neverError: true, responseFormat: 'json' } },
        },
      },
    },
    {
      id: 'dr32-buffer-verify', name: 'Summarize Connection Only',
      type: 'n8n-nodes-base.code', typeVersion: 2, position: [40, 0],
      parameters: { jsCode: `${summarizeBufferConnection.toString()}\nconst response = $input.first().json || {};\nreturn [{json:summarizeBufferConnection(Number(response.statusCode), response.body, ${JSON.stringify(BUFFER_ORGANIZATION_ID)}, ${JSON.stringify(BUFFER_CHANNELS)})}];` },
    },
  ],
  connections: {
    'Check Buffer Connection': { main: [[{ node: 'Read Drop Rate Buffer Channels', type: 'main', index: 0 }]] },
    'Read Drop Rate Buffer Channels': { main: [[{ node: 'Summarize Connection Only', type: 'main', index: 0 }]] },
  },
  pinData: {},
  meta: { dropRate: {
    contract: 'DR-32', version: 1, role: 'buffer-read-only-connection-check',
    publishingEnabled: false,
    scope: 'Channel access only. No scheduler, posts, credentials import, media upload or financial writes.',
  } },
};

await writeFile(new URL('./workflows/dr-32-buffer-connection-check.json', import.meta.url), JSON.stringify(workflow, null, 2) + '\n');
