import { readFile, writeFile } from 'node:fs/promises';
import {
  BUFFER_ORGANIZATION_ID, BUFFER_CHANNELS, summarizeBufferConnection,
} from './buffer-connection.mjs';
import {
  BUFFER_QUEUE_QUERY, BUFFER_QUEUE_PAGE_SIZE, queueFailure, validateQueuePage,
  summarizeQueue, summarizeQueueFirstPage,
} from './buffer-queue.mjs';

const workflow = JSON.parse(await readFile(new URL('./workflows/dr-32-buffer-connection-check.json', import.meta.url)));
workflow.id = 'DR32BufferQueueCheckV1';
workflow.name = 'DR-32 Buffer Queue Check (read-only, bounded)';
workflow.nodes[0].id = 'dr32-queue-trigger';
workflow.nodes[1].id = 'dr32-queue-request';
workflow.nodes[2].id = 'dr32-queue-summary';
// Reuse fixed-endpoint/auth/timeout settings, with no dynamic input or pagination URL.
workflow.nodes[1].parameters.jsonBody = JSON.stringify({ query: BUFFER_QUEUE_QUERY, variables: { after: null } });
workflow.nodes[2].parameters.jsCode = [
  summarizeBufferConnection, queueFailure, validateQueuePage, summarizeQueue, summarizeQueueFirstPage,
].map(fn => fn.toString().replace(/\r\n/g, '\n')).join('\n') + `
const response = $input.first().json || {};
return [{json:summarizeQueueFirstPage(Number(response.statusCode), response.body,
  ${JSON.stringify(BUFFER_ORGANIZATION_ID)}, ${JSON.stringify(BUFFER_CHANNELS)},
  ${BUFFER_QUEUE_PAGE_SIZE}, new Date().toISOString())}];`;
const names = ['Check Buffer Queue', 'Read Drop Rate Buffer Queue', 'Summarize Queue Observation'];
workflow.nodes.forEach((node, index) => { node.name = names[index]; });
workflow.connections = {
  [names[0]]: { main: [[{ node: names[1], type: 'main', index: 0 }]] },
  [names[1]]: { main: [[{ node: names[2], type: 'main', index: 0 }]] },
};
workflow.meta.dropRate.role = 'buffer-read-only-queue-check';
workflow.meta.dropRate.scope = 'Expected three channels and non-sent posts only; more than one page is unverified. No posting or scheduling authority.';
await writeFile(new URL('./workflows/dr-32-buffer-queue-check.json', import.meta.url), JSON.stringify(workflow, null, 2) + '\n');
