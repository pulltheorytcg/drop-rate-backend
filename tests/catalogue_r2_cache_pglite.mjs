// Test-only local PostgreSQL transport. In-memory PGlite, never a remote DSN.
// Uses the repository's existing pinned dependency, not an application dependency.
import { PGlite } from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import readline from 'node:readline';

const db = new PGlite();
await db.waitReady;
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  let message;
  try {
    message = JSON.parse(line);
    if (message.operation === 'close') {
      await db.close();
      process.stdout.write('{"ok":true,"rows":[]}\n');
      break;
    }
    if (message.operation === 'execute' && message.arguments.length === 0) {
      await db.exec(message.sql);
      process.stdout.write('{"ok":true,"rows":[]}\n');
    } else {
      const result = await db.query(message.sql, message.arguments);
      process.stdout.write(JSON.stringify({ ok: true, rows: result.rows }) + '\n');
    }
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, code: error.code, message: error.message }) + '\n');
  }
}
