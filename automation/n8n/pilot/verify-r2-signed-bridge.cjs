// Explicit one-shot n8n -> live FastAPI HMAC/R2 integration diagnostic.
// Runs only when opted in at boot. Never prints a secret, signature or URL.
const crypto = require('node:crypto');

async function main() {
  const secret = String(process.env.DROP_RATE_AUTOMATION_COMMAND_SECRET || '').trim();
  const receipt = String(process.env.DROP_RATE_API_AUTOMATION_CONTROL_URL || '').trim();
  if (secret.length < 32 || !/^https:\/\/[^/]+\/api\/v1\/automation\/control\/receipt$/.test(receipt)
      && !/^http:\/\/[^/]+\.railway\.internal:\d+\/api\/v1\/automation\/control\/receipt$/.test(receipt)) {
    throw new Error('bridge_configuration_invalid');
  }
  const endpoint = receipt.replace('/control/receipt', '/commands/storage/mirror-approved-media');
  const body = JSON.stringify({
    schema_version: 1,
    action: 'MIRROR_APPROVED_CANONICAL_MEDIA',
    execution_id: `n8n-r2-bridge-test-${Date.now()}`,
    occurred_at: new Date().toISOString(),
    limit: 1,
  });
  const timestamp = String(Math.floor(Date.now() / 1000));
  const signature = 'sha256=' + crypto.createHmac('sha256', secret)
    .update(`${timestamp}.${body}`, 'utf8').digest('hex');
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Drop-Rate-Timestamp': timestamp,
      'X-Drop-Rate-Signature': signature,
    },
    body,
    signal: AbortSignal.timeout(60000),
  });
  const receiptBody = await response.json();
  if (!response.ok || receiptBody.accepted !== true || receiptBody.failed !== 0
      || !Number.isInteger(receiptBody.mirrored)) {
    throw new Error(`bridge_receipt_invalid_http_${response.status}`);
  }
  console.log(`R2_SIGNED_BRIDGE_PASS mirrored=${receiptBody.mirrored} examined=${receiptBody.examined}`);
}

main().catch(error => {
  console.error(`R2_SIGNED_BRIDGE_FAIL ${error.name || 'Error'}:${error.message}`);
  process.exitCode = 1;
});
