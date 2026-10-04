# Drop Rate marketing specialists v1

## Scope and release status

PR #514 is a nonpublishing first implementation of the founder's six-specialist setup. It uses the existing FastAPI/n8n/PostgreSQL architecture, not six new Railway services. The founder is recovering approved media separately; Higgsfield is excluded from this run. The eventual one-story/three-platform pilot must publish immediately (`shareNow`), not enter a future queue slot. No recurring schedule is enabled.

The implementation, migration and workflow exports are committed on the feature branch. **Production migration, deployment, workflow activation and a real model invocation have not been performed.** CI execution is not production installation. Latest terminal CI and rollout evidence belong in the PR. Preserve prior design/editorial/Buffer work in #512/#513; this PR neither merges nor replaces those drafts.

| Specialist | Implemented first-slice behaviour | Still outside v1 |
| --- | --- | --- |
| Research | Analyse supplied evidence excerpts with source IDs and timestamps | Automatic source collection and independent live verification |
| Brief | Prepare one angle, audience, objective and outline from saved research | Recurring daily selection |
| Copywriting | Produce slide text and Instagram/TikTok/YouTube variants | Final factual or asset approval |
| Design | Prepare a layout/storyboard from saved copy and stop awaiting media | Image, video or narration rendering; approved asset ingestion |
| Publishing | Deterministic BLOCKED result, no LLM and no Buffer write | Approval/publication ledger, actual Buffer publisher and delivery reconciliation |
| Social management | Analyse supplied metric snapshots and recommend experiments | Automatic metric ingestion, replies, DMs, moderation or policy changes |

`PREPARED` is an internal drafting state, not approval to publish. `AWAITING_MEDIA` is not a rendered asset. A design requiring review stays `NEEDS_REVIEW`, rather than being hidden behind the media-wait state. Valid schemas and source IDs do not independently establish truth, freshness, semantic support or reuse rights. All outputs remain unapproved. No input flag or model response can unlock the v1 publisher.

## Backend and shared state

`backend/app/marketing_specialists.py` contains separate versioned role instructions, strict contracts, minimal role-specific contexts, a bounded model adapter and replay-aware runner. `marketing_specialist_api.py` implements the signed API and PostgreSQL repository. The existing automation router includes these routes without changing its commerce commands.

Signed POST endpoints under `/api/v1/automation/commands/marketing`: `catalog`, `create`, `read`, `run`. All reuse raw-body HMAC verification and the existing 64 KiB body limit. The signed actor is checked against active platform-admin membership on every database transaction and can access only their own jobs. The command secret must never be exposed to a browser or model.

Backend feature flag `TCG_MARKETING_SPECIALISTS_ENABLED` defaults off. n8n flag `DROP_RATE_MARKETING_SPECIALISTS_ENABLED` also defaults off. Neither flag can enable the absent public publisher. The model credential is the existing backend `TCG_OPENAI_API_KEY` through Settings; it is not copied into n8n.

The pinned first-slice model is `gpt-4.1-mini-2025-04-14` through the fixed OpenAI Responses endpoint. One request per claimed stage; no tools, redirects or automatic model retries; 45-second HTTP timeout, 2,400 output-token bound and 128 KiB response bound; sanitized provider error codes; `store:false`. That flag does not mean zero provider retention. Account/model availability and live generation still require a bounded smoke test.

Per actor: at most ten new jobs and thirty claimed model stages per UTC day, with at most two RUNNING claims. These are execution limits, not a monetary spending guarantee. No real model calls were made during the implementation tests.

Canonical migration: `database/migrations/20261004133308_marketing_specialists_v1.sql`, generated with Supabase CLI. It creates only `tcg.marketing_specialist_jobs`, `tcg.marketing_specialist_runs`, associated indexes, policies and an immutability trigger. It has **not** been applied to production.

Jobs preserve immutable input snapshots and hashes. V1 permits revision 1 only; job editing/reset is absent. Future editorial/media revisions need a separately reviewed extension. Runs are unique by job/revision/stage. A per-actor transaction/advisory lock claims the run before external I/O; the transaction ends before the model request. Replays return existing results, while changed input/prompt hashes block reuse. Failed/unknown runs are not blindly retried.

On a later claim, RUNNING records older than five minutes become UNKNOWN. No background watchdog is introduced. Late completions cannot replace terminal outcomes. Inputs, outputs, prompt version/hash, model, token usage and timestamps are saved. RLS is enabled/forced, backend column grants are narrow, and anon/authenticated have no table access. The new trigger is SECURITY INVOKER. Inventory, ownership, pricing and financial history are untouched.

Missing evidence/metrics, stale inputs, unmet upstream prerequisites and the absent publisher return explicit BLOCKED reasons without consuming model claims. These precondition rejections are not stored as completed runs. Full Action Required integration, watchdog alert delivery and operator recovery UI remain unfinished; do not call them operational.

## n8n workflows and provisioning

`python automation/n8n/marketing/build_workflows.py` reproduces `workflows.json`, containing six child workflows and one preparation coordinator:

- DRMktResearchV1
- DRMktBriefV1
- DRMktCopyV1
- DRMktDesignV1
- DRMktPublishV1
- DRMktManageV1
- DRMktPrepareV1

All committed exports are inactive. Dockerfile.n8n validates the exact seven IDs and splits the reviewed aggregate into the existing provisioning directory at image-build time. On a future approved deployment, unchanged start.sh will import only absent inactive IDs and preserve persistent existing workflows. Packaging is not evidence that the production database has imported them. Never replace or delete persistent workflows as a rollback shortcut.

Children accept one job ID, actor ID, revision and immutable input hash. The fixed specialist is selected in code. They sign the exact command JSON and call the fixed backend route; caller-provided URLs or stage overrides are ignored. HTTP nodes use JSON body mode: raw-body mode in this n8n version disables JSON response decoding and broke the identity verifier. The runtime smoke independently checks HMAC against the actual transmitted bytes, so the format fix must not relax signature checks.

Responses must match all command identifiers and recognised states and retain `published:false` and `publishable:false`. HTTP retries and redirects are disabled. Execution-data saving is disabled for error, success, manual execution and progress. DR90GlobalErrorV1 is referenced, but error delivery for these new workflow identities is not verified and remains a release gate.

The coordinator runs research → brief → copywriting → design, proceeding only from PREPARED. It stops on review/failure/unknown/in-progress, and design ends awaiting media or review. Publishing and metric analysis are separate boundaries. No schedule or public webhook is included.

n8n 2.32.6 CLI execution resolves published child versions, unlike editor manual execution. Tests first import/read back exact inactive source exports, then publish those versions only inside a disposable `--network none` container with an explicitly local backend fixture. This is n8n workflow-version publishing, **not social posting**, and changes no production state. Production non-manual execution would separately require reviewed child-version activation; inactive import alone does not make the chain run.

## Verification evidence and remaining gates

Local first pass: 41 core Python tests and 15 actual Code-node checks passed with model/store doubles. Subsequent commits add the design-review regression, signed-route tests and JSON-mode regression. Use current CI for final counts rather than adding historical counts together.

GitHub preparation run 37179475775 completed successfully with pinned dependencies, targeted checks, full backend pytest, Node checks, compilation and diff checks. The later standard Backend checks run 37180388644 passed backend, dashboard UI and pinned Docker image jobs. These results cover their recorded commits, not all future changes.

Real PostgreSQL integration jobs in runs 37179939288, 37180254508 and 37180388611 passed. They applied the exact new migration to disposable PostgreSQL 17.6 and exercised actual PostgresStore calls: forced RLS, denied public grants, actor isolation, non-admin denial, immutable inputs/results, an eight-way claim race yielding one claim, replay, UNKNOWN recovery and late-result protection. Foundational auth/owner tables were fixtures; this is not a production Supabase authentication test.

Exact seven-workflow inactive import and node/connection/settings read-back passed on n8n 2.32.6. Full CLI execution then exposed two issues, recorded rather than suppressed: unpublished child versions, followed by raw-body response parsing. The CI harness now publishes only isolated test versions, and the generator/committed exports use JSON body mode with a regression test. The next terminal integration result must confirm actual ordered handoffs, review-stop behaviour and the blocked publisher against the signed local fixture. Do not report these full runtime checks as passed merely because import succeeded.

The two exact-branch preparation/repair actions wrote only generated feature-branch code/exports/docs after tests and were removed after their use. No new contents-write CI helper remains in the proposed tree. The retained integration workflow is contents-read only, with disposable PostgreSQL and network-isolated n8n tests.

Before production execution: pass current full CI and exact n8n runtime checks; verify migration preconditions and existing auth functions; apply only the reviewed additive migration through the canonical release path; deploy the existing services and observe SUCCESS/health plus actual inactive imports; verify new error routing; then run one bounded nonpublishing model smoke. Do not enable a daily schedule.

Approved media alone does not finish the later pilot. Immutable asset approval, per-channel publication claims, Buffer writes and delivery reconciliation remain to be built/tested. Keep rejected drafts untouched and never present a manual Buffer post as an n8n execution.

Rollback: disable both specialist flags and revert application code while retaining job/run history and persistent n8n data. Do not delete tables, workflows, drafts or provider content.

## Provider references

Checked 4 October 2026: official OpenAI structured-output and GPT-4.1 mini documentation; n8n Execute Sub-workflow documentation and exact 2.32.6 source for HttpRequestV3, workflow-execute-additional-data and publish:workflow; Buffer ShareMode reference. These define interfaces, not proof of account access or live delivery.

## Production migration checkpoint — 4 October 2026, 13:33 UTC

The reviewed migration is now applied as `20261004133308_marketing_specialists_v1`. Read-back verifies forced RLS and narrow grants; both new tables are empty. Earlier unapplied statements above are historical. Runtime deployment and an actual authenticated backend/model probe are still pending. A connector SET ROLE test was refused before any test insertion; do not claim it passed or broaden role membership to bypass it.
