# Drop Rate — Live Build Status

## Read this with the full history

The complete build log through the marketing installation checkpoint is preserved unchanged in [BUILD_STATUS.history-through-20261004.md](BUILD_STATUS.history-through-20261004.md). Its Git blob is `bf3fa9436687cae18357ca2b124bbc9dff35174e`, identical to BUILD_STATUS.md at production commit `a0432bb82694868026c804d5b0af57cda9c128bd`. No historical entry was deleted or rewritten; the archive remains at repository root so its relative links keep their original meaning.

This page records current continuation checkpoints, not a replacement for the full backlog, CLAUDE.md, the master project instructions, or either operating manual. Read the historical log and relevant docs before resuming another area. Old unresolved work is not implicitly complete.

## 5 October 2026 — Gunko post metrics baseline (read-only)

- PR #525 merged as `14722ade1f93667a1730275206087b07e168c4f7` and added a strictly read-only Buffer metrics reader for the two already-delivered Gunko pilot posts. It has no post mutation, schedule, database write or recurring analytics job.
- Fresh API deployment `505da5fb-2ae6-4594-902a-d5ad059ead2b` passed **2,560 tests** and readiness 200. Its bounded live probe read the exact Instagram/TikTok post IDs and channel identities already recorded by the publishing pilot.
- Instagram metrics were available with `metricsUpdatedAt=2026-10-05T00:03:34.559Z`; Buffer reported Reactions 0, Comments 0, Engagement Rate 0, Views 0, Shares 0, Saves 0, Follows 0 and Reach 0.
- TikTok metrics were available with `metricsUpdatedAt=2026-10-05T00:06:35.657Z`; Buffer reported Reactions 0, Comments 0, Engagement Rate 0, Video Views 0, Shares 0 and Reach 0, plus provider values **Watch Time (min) 0.02** and **Avg. Watch Time (sec) 1.89**. Preserve those provider labels/units as returned; do not derive extra conclusions from the early baseline.
- The temporary metrics diagnostic was removed after the read. The live API pre-deploy command is back to the normal compile/test/Stripe self-test chain, with no staged Railway changes. Recurring metrics collection/analysis remains off.

## 5 October 2026 — YouTube video pilot contract prepared (not live)

- PR #526 merged as `06886af5bb812619d5c818bd5417484fd95d2f38`; API deployment `03005678-d39f-4b6c-9a58-29d655d5e12b` reached SUCCESS after **2,589 tests** and readiness 200. The release emitted no Buffer readiness/metrics/publish diagnostic lines; the contract is inactive validation code only.\n- Added a separate fail-closed contract for the future YouTube Shorts pilot after channel readiness was verified. It is intentionally **not** a FastAPI route and contains no Buffer credential or GraphQL mutation, so it cannot publish.
- The future approved asset must be one HTTPS Shopify Files `video/mp4`, exact 9:16, at most three minutes, with exact SHA-256/byte count plus affirmative approved-audio/narration/caption declarations. The contract binds the verified Buffer organization/channel IDs and founder approval metadata.
- Added pure construction of the future immediate/automatic Buffer YouTube input and deterministic channel/post validation. Subscriber notifications are disabled for the bounded pilot; public/not-for-kids and AI-disclosure fields are explicit rather than provider defaults.
- Media preflight streams the file without redirects, caps the pilot at 512 MiB, requires exact MIME/length/hash and an MP4 `ftyp` marker. It does not pretend to infer narration/caption quality from bytes; the exact hash binds runtime bytes to the human-approved media revision.
- Tests cover strict manifest parsing, approval/URL/aspect/duration/audio/caption gates, exact provider input, channel binding, media integrity and YouTube delivery URLs, plus an explicit no-route/no-Buffer-mutation assertion. See [YouTube video pilot contract](docs/YOUTUBE_VIDEO_PILOT_CONTRACT.md).
- Still blocked: no approved narrated/captioned MP4 has been supplied. Do not add/activate the live route or n8n YouTube publishing workflow until that exact asset and its title/description/category are approved.

## 5 October 2026 — Buffer YouTube channel readiness verified

- PR #521 merged as `29a089b61d123888bdd4097b32fdc93800484f2d` with a read-only Buffer YouTube readiness probe. Clean API deployment `f25b668f-3bbd-46b7-b937-688475273b1f` passed **2,550 tests** and readiness 200 before the live diagnostic.
- The first config-only redeploy did not prove that the newly configured probe executed, so no readiness claim was made from it. PR #522 merged as `2ff4689e4d97070d9b37997593d7037c6470cdaf` to flush operator evidence; fresh source deployment `2132c13b-d699-4afa-ad87-1d449f668146` then passed **2,550 tests**, ran the read-only Buffer channels query and returned readiness 200.
- Buffer returned exactly one YouTube channel for organization `6ac1a59ca59739d7c3e08601`: channel `6ac1a694ea19ca0bde6c8ba3`, service `youtube`, provider-returned name/display name `Drop Rate ` (trailing space preserved), timezone `Europe/London`. It is not disconnected, locked or queue-paused, and `scheduleUpdates` is allowed. The readiness result is **READY** with no blockers.
- No Buffer mutation occurred: no post was created, edited, queued, scheduled or deleted, and no database write or recurring n8n schedule was introduced. Future YouTube identity must bind to the exact channel ID/organization ID rather than the mutable display name.
- Immediately after evidence capture, the temporary diagnostic was removed from Railway: the original API pre-deploy command was restored, the temporary timeout was cleared to the default, and no staged changes remain.
- YouTube delivery is **not** yet proven. Publishing remains blocked until an explicitly approved narrated/captioned video is bound to a separate immutable YouTube pilot manifest and the live path passes provider delivery read-back plus intentional duplicate-trigger replay without a second upload. See [YouTube publishing readiness](docs/YOUTUBE_PUBLISHING_READINESS.md).

## 4 October 2026 — Gunko social publishing pilot completed

- PR #519 merged as `5191cba757382618ae8ed2335a1997f371f2625d`. The subsequent bounded live Gunko pilot completed through the real n8n → signed FastAPI → Buffer path for Instagram and TikTok. This is execution evidence for the explicitly approved one-off pilot, not activation of the general six-agent or recurring marketing system.
- API deployment `e79cb45d-ed35-420f-8667-caf81fa60102` reached SUCCESS after **2,539 tests** and readiness 200. Read-only n8n deployment `4fc66826-3262-4c92-87a0-6211e71c5372` then returned `READY` for both intended Buffer accounts, including the hosted-image validation that had previously blocked publication.
- Real publish deployment `4a4d523b-6e37-442a-8bf5-273614363eb3` submitted the approved manifest `880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d`. Instagram @dropratetcg produced Buffer post `6ac29d1f6ae9cbb01a564d9f`; TikTok @dropratetcg produced Buffer post `6ac29d1ffe1389e4133cde22`. A separate real status read-back on n8n deployment `603f2c64-2164-41cf-b1b2-deaa4b9fe004` returned `DELIVERED` for both with platform URLs.
- Idempotency is live-verified for this pilot. Intentional repeat publish deployment `85abd755-81d2-4355-9a4e-8a907c4e2f4f` returned `DELIVERED`, `replayed: true` and the **same post IDs/URLs**. PostgreSQL then still contained exactly **2 intents, 2 claims, 2 submissions and 2 observations**—one per channel—with **0 Action Required** items for this pilot. No duplicate provider submissions or journal records were created.
- Cleanup is complete. n8n's temporary pre-deploy command was removed and its timeout restored; `TCG_APPROVED_SOCIAL_PILOT` was cleared after the replay. Cleanup API deployment `4bc47f07-0379-49b0-b6fd-ddf2bccc32b3` reached SUCCESS, again passed 2,539 tests and returned readiness 200. Daily/recurring publishing and the generic preparation specialists remain off.
- Verification boundary: delivery was re-read from Buffer and recorded in PostgreSQL, but independent public visual/audio inspection of the returned social URLs was not completed, so `public_visibility_verified` remains false. The Umbreon/Goku price posters remain pending source/FX checks, and YouTube still requires the approved narrated/captioned video. This pilot does **not** prove general campaign intake, autonomous content production, arbitrary-post approval or daily scheduling.

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
