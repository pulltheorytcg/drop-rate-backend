# Drop Rate — Live Build Status

## Read this with the full history

The complete build log through the marketing installation checkpoint is preserved unchanged in [BUILD_STATUS.history-through-20261004.md](BUILD_STATUS.history-through-20261004.md). Its Git blob is `bf3fa9436687cae18357ca2b124bbc9dff35174e`, identical to BUILD_STATUS.md at production commit `a0432bb82694868026c804d5b0af57cda9c128bd`. No historical entry was deleted or rewritten; the archive remains at repository root so its relative links keep their original meaning.

This page records current continuation checkpoints, not a replacement for the full backlog, CLAUDE.md, the master project instructions, or either operating manual. Read the historical log and relevant docs before resuming another area. Old unresolved work is not implicitly complete.

## Verified installation — PR #514, 4 October 2026

- PR #514 merged as `a0432bb82694868026c804d5b0af57cda9c128bd` after Backend checks `37206549614` and Marketing integration `37206549593` passed.
- Supabase migration `20261004133308_marketing_specialists_v1` is applied. Marketing job/run tables have forced RLS; the latest read-only check returned zero jobs and zero runs.
- API deployment `f93752ea-4f97-4d40-9bd9-2496685a177c` and n8n deployment `eb2e1e84-3c29-469e-afb5-9b877b3a37bc` reached SUCCESS. API pre-deploy passed 2,453 tests and readiness returned 200. n8n logged all seven inactive imports while preserving previous workflows.
- Installed roles: research, briefs, copywriting, design instructions, deterministic blocked publishing, and supplied-metrics analysis, plus the preparation coordinator.
- Both specialist flags remain absent/default-off. Installation is not a real model run. Research still consumes supplied evidence; design does not render finished media; social management does not collect metrics or send replies.
- Final installation evidence is on PR #514. Earlier draft/not-deployed entries in the history describe older checkpoints.

## Marketing terminal attention repair — feature branch, not yet released

- Branch: `fix/marketing-run-attention-20261004`. The prior runtime can save FAILED/UNKNOWN/NEEDS_REVIEW without a corresponding Action Required item. Stale RUNNING recovery is also silent.
- Added actor-scoped Action Required creation in the same database transaction as a terminal marketing state. Owner identity comes from verified platform-admin membership, not model output or caller metadata. The existing OWNER entity and AUTOMATION category are used; no schema change.
- A stable per-persisted-run dedupe key and ON CONFLICT DO NOTHING prevent duplicate or reopened resolved alerts. Alert text/metadata contain identifiers and fixed status only, not provider/model/source text. An alert failure rolls back the state transition.
- Added focused unit checks and extended the existing local-only PostgreSQL smoke for failure/review states, no success/media-wait alerts, actor isolation, duplicate/late results, resolved-alert replay and transactional rollback. Test and deployment results must be read from the accompanying PR before calling this repair released.
- This repair does not fix the shared accountless DR90 control route, provide external email/Slack delivery, or add a background watchdog. Abandoned runs are discovered only when the existing claim path executes. Details: [Marketing run attention](docs/MARKETING_RUN_ATTENTION.md).

## Remaining publication gates

- Run one actual authenticated preparation job and verify saved output reuse and production error visibility. The previously safety-blocked additional live-probe harness is not present and must not be recreated as a workaround.
- Recover the exact approved artwork/video and match final captions. Rejected Buffer validation drafts remain excluded. Do not invent final asset approval from concept feedback.
- Implement and test immutable asset approval, per-channel publication claims, the real Buffer write adapter, and independent delivery reconciliation. The installed publishing role has none of these and remains hard-blocked.
- The authorised pilot is one story adapted for Instagram @dropratetcg, TikTok @dropratetcg and YouTube Drop Rate, immediate shareNow, no daily activation. YouTube requires the approved narration and readable captions; no background music. Higgsfield is excluded from this run.
- Current chat discovery exposes no Buffer actions despite the earlier custom plugin. The existing Railway Buffer credential is preserved, not removed or copied. A plugin connection and runtime credential are separate clients.
- Railway's coding agent hit its existing usage limit; no increase is authorised or applied. Direct repository/infra tools are separate from that agent. No new services, public n8n endpoint, paid plan, stock, ownership, pricing, settlement or live money changes are included in this repair.

## Standing controls

PostgreSQL is authoritative; FastAPI enforces business rules; n8n coordinates. Keep authentication, signed commands, RLS, immutable history, provider terms, approval and duplicate protection. No recurring marketing release is implied. Unique unmerged work in #512/#513 is preserved; neither is silently superseded. Other frozen workstreams remain governed by the manuals and their explicit user decisions.

Rollback after a repair release is a code revert to the previous successful API build with flags disabled. Preserve marketing jobs/results, Action Required history, n8n's persistent volume and prior social content; never reset or delete them as a shortcut.
