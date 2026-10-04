// Emits a shell command containing only reviewed code and a read-only workflow.
// No credentials are read locally or embedded. Intended for one bounded Railway
// pre-deploy run with a disposable DB. Clear the pre-deploy command afterwards.
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const source=readFileSync(new URL('./runtime-smoke.mjs',import.meta.url),'utf8');
const workflow=JSON.parse(readFileSync(new URL('./workflows/dr-32-buffer-queue-check.json',import.meta.url),'utf8'));
const json=JSON.stringify(workflow);
const hash=createHash('sha256').update(json).digest('hex');
const program=source+`\nrunSmoke(JSON.parse(Buffer.from('${Buffer.from(json).toString('base64')}','base64').toString()),'${hash}');\n`;
console.log(`node --input-type=module -e "await import('data:text/javascript;base64,${Buffer.from(program).toString('base64')}')"`);
