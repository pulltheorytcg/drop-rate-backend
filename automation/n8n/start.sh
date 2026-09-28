#!/bin/sh
set -eu

WORKFLOW_DIR="/opt/drop-rate/workflows"

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
