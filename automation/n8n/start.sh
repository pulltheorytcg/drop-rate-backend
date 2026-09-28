#!/bin/sh
set -eu

WORKFLOW_DIR="/opt/drop-rate/workflows"

# DR-00 verifies HMAC signatures inside an n8n Code node. n8n 2.x blocks
# environment access in nodes by default and Code nodes deny built-in modules
# unless explicitly allowed. Fail closed before starting rather than importing a
# workflow that can never authenticate dispatcher events.
if [ "${N8N_BLOCK_ENV_ACCESS_IN_NODE:-true}" != "false" ]; then
  echo "Drop Rate n8n: N8N_BLOCK_ENV_ACCESS_IN_NODE=false is required for signed DR-00 verification." >&2
  exit 1
fi

case ",${NODE_FUNCTION_ALLOW_BUILTIN:-}," in
  ",*,"|*,crypto,*) ;;
  *)
    echo "Drop Rate n8n: NODE_FUNCTION_ALLOW_BUILTIN must include crypto." >&2
    exit 1
    ;;
esac

webhook_secret="${DROP_RATE_AUTOMATION_WEBHOOK_SECRET:-}"
if [ "${#webhook_secret}" -lt 32 ]; then
  echo "Drop Rate n8n: DROP_RATE_AUTOMATION_WEBHOOK_SECRET must be at least 32 characters." >&2
  exit 1
fi
unset webhook_secret


# The persistent volume is mounted before the application start command runs.
# Provision only version-controlled workflows whose IDs are not already present.
# Never wipe or recreate the n8n database here.
if [ -d "$WORKFLOW_DIR" ]; then
  existing_ids="$(n8n list:workflow --onlyId 2>/dev/null || true)"
  for workflow in "$WORKFLOW_DIR"/*.json; do
    [ -f "$workflow" ] || continue
    workflow_id="$(node -e 'const fs=require("fs");const w=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));if(!w.id)process.exit(2);process.stdout.write(String(w.id));' "$workflow")"
    if printf '%s\n' "$existing_ids" | grep -Fxq "$workflow_id"; then
      echo "Drop Rate n8n provisioner: workflow $workflow_id already exists; leaving persistent copy unchanged."
      continue
    fi
    echo "Drop Rate n8n provisioner: importing workflow $workflow_id."
    n8n import:workflow --input="$workflow"
  done
fi

exec n8n start
