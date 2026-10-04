# Drop Rate — Live Build Status

## Read this with the full history

The complete build log through the marketing installation checkpoint is preserved unchanged in [BUILD_STATUS.history-through-20261004.md](BUILD_STATUS.history-through-20261004.md). Its Git blob is `bf3fa9436687cae18357ca2b124bbc9dff35174e`, identical to BUILD_STATUS.md at production commit `a0432bb82694868026c804d5b0af57cda9c128bd`. No historical entry was deleted or rewritten; the archive remains at repository root so its relative links keep their original meaning.

This page records current continuation checkpoints, not a replacement for the full backlog, CLAUDE.md, the master project instructions, or either operating manual. Read the historical log and relevant docs before resuming another area. Old unresolved work is not implicitly complete.

## 4 October 2026 — Colour metadata compatibility (live-test repair)

- PR #518 merged as `d21706869daff13e5974fd29127ccb61b5e563d8`; Backend `37222469633` and Marketing integration `37222469535` passed. API deployment `08fe2c4e-b248-412f-9c38-ce2e36839223` reached SUCCESS after 2,533 tests and readiness 200.
- The actual n8n check on deployment `a5291b63-49ef-4db7-b133-2f7f6e2c1e9a` then returned PILOT_MEDIA_COLOUR_METADATA_CHANGED for both channels. It did not publish. The conservative validator rejected colour/EXIF metadata before reaching pixel comparison; no claim of exact live pixel verification yet.
- Replace blanket ICC/EXIF rejection with bounded real colour management: valid embedded profiles are converted to sRGB and the resulting pixels must equal the exact approved SHA-256. Harmless EXIF with identity orientation is allowed; changed orientation, invalid/oversized profiles, nonstandard unprofiled gamma, altered pixels and prior size/format/alpha/frame checks still fail closed. No name-only profile trust or pixel tolerance.
- The selected source PNG contains no colour profile, and local sRGB-to-sRGB conversion preserves every pixel of both publication copies. Added six metadata/transform regressions. Manifest hash, media, caption, accounts and approval are unchanged. Current-head CI and next live check remain separate gates. See [Colour-profile validation](docs/SOCIAL_PILOT_COLOUR_VALIDATION.md).

## 4 October 2026 — Live connection reached; lossless media repair

- PR #517 merged as `fbf4033ffacb2857cf6d72c50bdbe45bed3c7c6c`. The actual n8n runner now reaches signed production FastAPI commands and Buffer's two expected accounts. On deployment `6cad92a0-8a72-4279-92c6-6c200ae4e00e`, the check returned BLOCKED / PILOT_MEDIA_CHANGED for Instagram and TikTok. This is evidence that channel validation passed, not successful publication. No publish operation was selected and prior journal reads contained no claims.
- Aligned the disposable operator process with its tested env-access/crypto settings and the existing public HTTPS API URL. Persistent n8n configuration/workflows and the volume are unchanged. Multiple settings were aligned together; do not infer a single root cause from the old generic diagnostic.
- The prior JPEG file-byte fingerprints did not match the CDN response. Added lossless PNG copies with exact dimensions and SHA-256 of every decoded RGB8 pixel. Compression/text metadata can differ; even a one-value pixel change is rejected. ICC/EXIF changes, unexpected transparency, animation, excessive dimensions/bytes and invalid images fail closed. No perceptual tolerance or skipped approval check.
- Same selected Gunko design, same caption/accounts/pilot ID, new format-only manifest revision: `880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d`. Previous `2b0560...` revision is retained in Git history, not silently accepted. No existing publication intent/claim is overwritten. Both PNGs are hosted on the existing verified Drop Rate Shopify Files CDN, without product/theme changes.
- Fixed diagnostic classification to read actual n8n resultData.error, not guard strings embedded in the dumped workflow source. Earlier HASH_NOT_CONFIGURED classification is not conclusive root-cause evidence.
- Code, exact workflow revision, adapter/media tests, actual n8n CI fixture, docs and status are in the same repair PR. Deployment, exact live pixel read-back and delivery still require execution. See [Lossless pilot media](docs/SOCIAL_PILOT_LOSSLESS_MEDIA.md). Keep publishing/daily schedules off until the read-only check reports READY; remove the temporary operator command after the pilot.

## 4 October 2026 — Pilot runtime diagnosis (continuation)

- PR #516 merged as `dc57859c84d5e947121004161f6bd6fa07eabb12` after Backend checks `37219010958` and Marketing integration `37219010950` passed. Existing API deployment `f2bbf92c-3c2b-4da8-8725-ad390cc0e403` and n8n deployment `79c9d5cf-9b60-4ca6-8d05-cf2b891956b5` reached SUCCESS. API pre-deploy passed 2,501 tests and readiness returned 200.
- Read-only live check first failed before runner output with shell-style assignments in the Docker exec command. Using explicit `env NAME=value ... node ...` started the runner, but it returned RUN_UNVERIFIED. No successful live preflight or social delivery is claimed by those results; no publish operation was selected.
- Added fixed phase and allowlisted failure categories to the existing pilot runner. Raw stdout/stderr, environment values, signatures, provider messages and URLs remain excluded from diagnostic output. This does not change the approved manifest, HMAC, submission, duplicate protection, or production n8n database.
- Tests exercise the actual JavaScript classifier, known failures, unknown input, and redaction. Existing actual n8n check/submit/status fixture remains the integration gate. Live retry is check-only until verified readiness; inspect the durable journal before any publishing recovery.
- See [Pilot runtime diagnostics](docs/SOCIAL_PILOT_RUNTIME_DIAGNOSTICS.md). Current-head CI/deployment and the next actual run are separate gates. Preserve the earlier healthy deployment, remove temporary operator commands after testing, and leave daily scheduling off.

## 4 October 2026 — Approved Gunko publishing pilot (implementation checkpoint)

- The founder approved the latest posters for an immediate one-off n8n publishing test. Start with the Gunko story on Instagram and TikTok. The price posters still need separate source/FX checks; YouTube needs the approved narrated/captioned video, not a substituted silent slideshow. No daily activation.
- Recovered exact latest Gunko image, preserved the whole design in Instagram's 4:5 navy-padded JPEG and TikTok's same-ratio JPEG, and hosted both on the verified Drop Rate Shopify Files CDN. No product/theme changes. The manifest stores original and hosted hashes, exact captions, channel identities and approval source.
- Added a narrow signed FastAPI command with check/publish/status, exact manifest binding and expiry. It verifies actual channels and media bytes, then uses immediate automatic Buffer submission. Existing PostgreSQL automation_runs provides append-only intent/claim/submission/observation records; no new migration, database or service.
- Stable unique claims prevent duplicate/ambiguous retries. Provider failures become UNKNOWN and require reconciliation; failed records create owner-scoped Action Required. No caller-supplied media/copy/provider URLs and no broad publishing permission.
- Committed the actual inactive manual n8n export and explicit temporary-database runner. It is packaged separately, never invoked by normal startup, and does not alter persistent n8n workflows or enable the six preparation agents. This tests the publishing leg using approved assets, not autonomous research/design.
- Added adapter, signed-route, real PostgreSQL journal and network-isolated actual n8n fixture tests. Initial local adapter tests passed 27 cases; current-head CI, deployment, live preflight, real submission and separate delivered/public-visibility evidence remain required. The accompanying PR must record actual results rather than infer them from source or deployment success.
- Technical/approval details, sources, operating sequence and rollback: [Approved social pilot](docs/APPROVED_SOCIAL_PILOT.md). Remove any temporary n8n operator command and disable its API publication flag after the test. Preserve all journal/history and provider content.

## Verified installation — PR #514, 4 October 2026

- PR #514 merged as `a0432bb82694868026c804d5b0af57cda9c128bd` after Backend checks `37206549614` and Marketing integration `37206549593` passed.
- Supabase migration `20261004133308_marketing_specialists_v1` is applied. Marketing job/run tables have forced RLS; the latest read-only check returned zero jobs and zero runs.
- API deployment `f93752ea-4f97-4d40-9bd9-2496685a177c` and n8n deployment `eb2e1e84-3c29-469e-afb5-9b877b3a37bc` reached SUCCESS. API pre-deploy passed 2,453 tests and readiness returned 200. n8n logged all seven inactive imports while preserving previous workflows.
- Installed roles: research, briefs, copywriting, design instructions, deterministic blocked publishing, and supplied-metrics analysis, plus the preparation coordinator.
- Both specialist flags remain absent/default-off. Installation is not a real model run. Research still consumes supplied evidence; design does not render finished media; social management does not collect metrics or send replies.
- Final installation evidence is on PR #514. Earlier draft/not-deployed entries in the history describe older checkpoints.

## Marketing terminal attention repair — released PR #515

- PR #515 merged as `bd9be18373a42343bb0fadec8046bcc6f9ef660a`. API deployment `6a412a5c-7898-48e1-9917-b64158072b97` and n8n deployment `c6968707-c2d6-417d-8bef-d39a8380970f` succeeded; API pre-deploy passed 2,465 tests and readiness returned 200. Final evidence is on PR #515.
- Branch: `fix/marketing-run-attention-20261004`. The prior runtime could save FAILED/UNKNOWN/NEEDS_REVIEW without a corresponding Action Required item. Stale RUNNING recovery was also silent.
- Added actor-scoped Action Required creation in the same database transaction as a terminal marketing state. Owner identity comes from verified platform-admin membership, not model output or caller metadata. The existing OWNER entity and AUTOMATION category are used; no schema change.
- A stable per-persisted-run dedupe key and ON CONFLICT DO NOTHING prevent duplicate or reopened resolved alerts. Alert text/metadata contain identifiers and fixed status only, not provider/model/source text. An alert failure rolls back the state transition.
- Added focused unit checks and extended the existing local-only PostgreSQL smoke for failure/review states, no success/media-wait alerts, actor isolation, duplicate/late results, resolved-alert replay and transactional rollback. Those isolated checks passed; no production marketing job was implied.
- This repair does not fix the shared accountless DR90 control route, provide external email/Slack delivery, or add a background watchdog. Abandoned runs are discovered only when the existing claim path executes. Details: [Marketing run attention](docs/MARKETING_RUN_ATTENTION.md).

## Remaining general marketing gates

- The six-agent preparation chain still needs one actual authenticated job, saved-output reuse and live error visibility. The previously safety-blocked broad live-probe harness is not present and must not be recreated as a workaround.
- The approved single-image pilot above is a distinct, manually initiated publishing test. It does not complete generic asset revision approval, automatic content creation, arbitrary campaigns, recurring scheduling or YouTube production.
- Rejected Buffer validation drafts remain excluded. Never substitute them for the approved media. Earlier design feedback alone was not final publication approval.
- Current chat discovery exposes no Buffer actions despite the earlier custom plugin. The existing Railway Buffer credential is preserved; unattended backend access uses a runtime reference, not a key copied to chat. The pilot does not depend on the chat plugin.
- Railway's coding agent hit its existing usage limit; no increase is authorised or applied. Direct repository/infra tools are separate from that agent. No new services, public n8n endpoint, paid plan, stock, ownership, pricing, settlement or live money changes are included.

## Standing controls

PostgreSQL is authoritative; FastAPI enforces business rules; n8n coordinates. Keep authentication, signed commands, RLS, immutable history, provider terms, approval and duplicate protection. No recurring marketing release is implied. Unique unmerged work in #512/#513 is preserved; neither is silently superseded. Other frozen workstreams remain governed by the manuals and their explicit user decisions.

Rollback after a repair release is a code revert to the previous successful API build with flags disabled. Preserve marketing jobs/results, Action Required history, n8n's persistent volume and prior social content; never reset or delete them as a shortcut.
