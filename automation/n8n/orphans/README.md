# n8n orphaned workflow records

This directory is **source-control evidence only**. It is not copied into the n8n image and is not scanned by the startup provisioner.

## DR92WorkflowHeartbeatV1

- Status: inactive orphan in the production n8n persistent database.
- Origin: briefly imported by PR #381 before the duplicate heartbeat design was consolidated in PR #382.
- Canonical replacement: `DR92RuntimeHeartbeatV1`.
- Runtime authority: none. Do not activate, publish, call, or re-import this workflow.
- Business-state impact: none observed; it was imported inactive.
- Why it remains here: the deployed n8n server CLI has no supported workflow delete/archive command, no n8n API key is configured, and current Railway tooling does not expose arbitrary container exec. Direct SQLite deletion is deliberately prohibited.
- Cleanup gate: remove the persistent workflow only through an authenticated supported n8n admin/API operation. Verify its exact stable ID before deletion and confirm the canonical DR-92 remains intact.
- After supported cleanup is verified, remove this orphan JSON and this registry entry in the same PR.

Keeping the exact JSON here prevents an invisible UI-only workflow from escaping version review while avoiding accidental reprovisioning.
