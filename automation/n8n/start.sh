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

command_secret="${DROP_RATE_AUTOMATION_COMMAND_SECRET:-}"
if [ "${#command_secret}" -lt 32 ]; then
  echo "Drop Rate n8n: DROP_RATE_AUTOMATION_COMMAND_SECRET must be at least 32 characters." >&2
  exit 1
fi
unset command_secret

control_url="${DROP_RATE_API_AUTOMATION_CONTROL_URL:-}"
case "$control_url" in
  https://*/api/v1/automation/control/receipt|http://*.railway.internal:*/api/v1/automation/control/receipt)
    ;;
  *)
    echo "Drop Rate n8n: DROP_RATE_API_AUTOMATION_CONTROL_URL must target the governed automation receipt endpoint over HTTPS or Railway private HTTP." >&2
    exit 1
    ;;
esac
unset control_url

# The persistent volume is mounted before the application start command runs.
# Create a one-time pre-provision database backup before any workflow import.
# This is a rollback snapshot for the source/provisioning cutover; it is not a
# substitute for normal platform-level backups.
N8N_STATE_DIR="${N8N_USER_FOLDER:-/home/node/.n8n}"
N8N_DB="$N8N_STATE_DIR/database.sqlite"
N8N_PREPROVISION_BACKUP="$N8N_STATE_DIR/database.sqlite.pre-drop-rate-provision-v1.bak"
if [ -f "$N8N_DB" ] && [ ! -f "$N8N_PREPROVISION_BACKUP" ]; then
  echo "Drop Rate n8n provisioner: creating one-time pre-provision database backup."
  cp "$N8N_DB" "$N8N_PREPROVISION_BACKUP"
  chmod 0600 "$N8N_PREPROVISION_BACKUP"
  if [ ! -s "$N8N_PREPROVISION_BACKUP" ]; then
    echo "Drop Rate n8n provisioner: database backup verification failed." >&2
    exit 1
  fi
fi

# Provision only version-controlled workflows whose stable IDs are absent.
# Never wipe/recreate the n8n database and never overwrite an existing workflow.
if [ -d "$WORKFLOW_DIR" ]; then
  existing_ids="$(n8n list:workflow --onlyId 2>/dev/null || true)"
  expected_ids=""
  for workflow in "$WORKFLOW_DIR"/*.json; do
    [ -f "$workflow" ] || continue
    workflow_id="$(node -e 'const fs=require("fs");const w=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));if(!w.id)process.exit(2);if(w.active!==false)process.exit(3);process.stdout.write(String(w.id));' "$workflow")"
    expected_ids="$expected_ids
$workflow_id"
    if printf '%s\n' "$existing_ids" | grep -Fxq "$workflow_id"; then
      echo "Drop Rate n8n provisioner: workflow $workflow_id already exists; leaving persistent copy unchanged."
      continue
    fi
    echo "Drop Rate n8n provisioner: importing inactive workflow $workflow_id."
    n8n import:workflow --input="$workflow"
  done

  installed_ids="$(n8n list:workflow --onlyId 2>/dev/null || true)"
  printf '%s\n' "$expected_ids" | while IFS= read -r workflow_id; do
    [ -n "$workflow_id" ] || continue
    if ! printf '%s\n' "$installed_ids" | grep -Fxq "$workflow_id"; then
      echo "Drop Rate n8n provisioner: workflow verification failed for $workflow_id." >&2
      exit 1
    fi
  done
fi

exec n8n start
