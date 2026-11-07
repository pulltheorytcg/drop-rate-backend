# Approved Gunko image publishing pilot — 4 October 2026

## Scope

The founder approved the latest posters for a one-off n8n publishing test, retaining the earlier immediate-publish instruction. Start with the approved Gunko Release Radar on Instagram and TikTok. This proves the publishing leg using supplied approved creative, not the six-agent research/design system. Do not enable the daily schedule, use Higgsfield, or substitute a silent video for the approved narrated YouTube format.

The latest Gunko snapshot is file_00000000acc081f49f4c89102c586b3d, SHA256 4781fb9bfa37084421e7854cf5004df592dd113858a18b2ec235d67cebfa78a1. Its 948x1659 poster is kept whole: Instagram receives a 1080x1350 navy-padded JPEG; TikTok receives a same-ratio JPEG. These are format conversions, not regenerated artwork. Both were uploaded to the verified Drop Rate Shopify Files CDN without modifying products or themes. The immutable manifest has exact asset URLs, byte counts, hashes, captions, original approval provenance and channel IDs.

Manifest SHA256 (sorted UTF-8 JSON, compact separators): `2b056042371fbb245ff26dd5582a46f6bcc4ff8463362cb50e31932e67dc7fde`.
Pilot ID: `6d3c3d1e-0ec0-4fc8-b5fb-5f9d4eeb925a`.

The caption labels chase status as opinion, the artwork as AI-assisted fan illustration, and release dates as planned/subject to change. Dates are corroborated by dated reporting, not claimed as directly fetched Bandai pages. This is not a stock/preorder announcement. References are in the manifest. The other two price posters need separate price/FX verification; they are not quietly included. YouTube needs an actual narrated/captioned video and is excluded from this image-only command contract.

## Implementation

`POST /api/v1/automation/commands/approved-social-pilot/execute` reuses the existing exact-body HMAC verifier and current active-founder authorization. It accepts only the exact manifest identity/hash, two known channels, and check/publish/status. It takes no arbitrary URL, caption, provider query or media from the caller. Check is read-only; publish additionally requires the exact hash in TCG_APPROVED_SOCIAL_PILOT and an unexpired manifest. Existing specialist flags remain off.

FastAPI uses the existing BUFFER_API_KEY via a Railway runtime reference in TCG_BUFFER_API_KEY; no key is read into chat or committed. The fixed Buffer endpoint and Shopify asset URLs reject redirects. Preflight verifies the exact connected/unlocked/unpaused channel and scheduling permission, and byte-checks the final hosted image. Submission is shareNow + automatic, never a notification/draft/queue fallback. No music is added.

The existing tcg.automation_runs table is the append-only journal, using its current SELECT/INSERT grants and owner-scoped authenticated transactions. Stable keys derive from the one approved pilot ID and channel, not each attempt. A full immutable intent and a unique irreversible claim commit before any Buffer write. The provider outcome is a separate immutable submission record; later read-backs append observations. Eight competing callers may produce only one claim. A retry with a claim only reconciles; it never creates a replacement post. No schema, RLS or finance change is required.

A timeout or malformed/error create response is UNKNOWN. A claim without a result is UNKNOWN, not permission to resubmit. The operator must reconcile Buffer before any recovery. Saved failure/unknown states insert a deduplicated Action Required under the verified owner's existing permissions. Unclaimed preflight/transport failures remain visible in the explicit operator result and logs; this is not a background watchdog or a repair of the shared DR90 route.

## Actual n8n, without altering persistent workflows

The source-controlled DRApprovedSocialPilotV1 export has a manual trigger, exact command signer, HTTP call to FastAPI and an identity-checked summary. It has no schedule or public webhook, retries are disabled, and execution-data persistence is disabled.

The explicit `node /opt/drop-rate/pilot/run-approved-pilot.cjs` command imports and executes that exact workflow using real n8n 2.32.6. It uses its own temporary SQLite database, deletes inherited DB_* settings, and generates an encryption key only for that disposable database. It never resets or writes the production n8n volume. PostgreSQL remains the durable publication journal. Ordinary start.sh never invokes it; it is packaged separately from automatic persistent provisioning.

The operator chooses check, then publish only after readiness passes, then status. It can be run through a bounded temporary pre-deploy command on the existing n8n service after source and API deployment verification. Read the resulting DROP_RATE_APPROVED_PILOT_RESULT and database journal. Remove the temporary command and disable the publish hash after the test. Do not leave a social publishing command attached to future deployments. Successful container deployment is not delivery proof.

## Tests and acceptance

Adapter/command tests cover exact approval, media hashes, wrong identities, nonautomatic modes, expiry/default-off, partial/provider errors, signature tampering, non-admin access, duplicate races, and timeout-after-write with no repost. Existing disposable PostgreSQL tests are extended to test the actual Journal's append-only grants, actor isolation, eight-way claim race, immutable intent/results, observations and transactional alert rollback. Actual n8n tests run the exact packaged runner in a network-isolated container against a local HMAC-checking fixture for check/publish/status. Fixtures make no real social/model request.

Live acceptance requires the real preflight result, one real submission per ready platform, durable provider IDs and a separate status read. DELIVERED means Buffer reports sent with a valid timestamp; public visibility is a separate check, never inferred from accepted/scheduled. A partial success must be preserved while the other channel is investigated. No delete/reset/repost shortcut.

## Provider references checked

- https://developers.buffer.com/types/CreatePostInput.html
- https://developers.buffer.com/types/ShareMode.html
- https://developers.buffer.com/types/SchedulingType.html
- https://developers.buffer.com/types/PostStatus.html
- https://developers.buffer.com/types/InstagramPostMetadataInput.html
- https://developers.buffer.com/types/TikTokPostMetadataInput.html
- https://developers.buffer.com/guides/hosting-media.html
- https://support.buffer.com/en-us/articles/adding-music-stickers-and-other-effects-to-instagram-and-tiktok-posts-G5QrWfQL4k

## Release status and rollback

At initial commit this is prepared code and hosted media, not a deployment or public post. Current-head CI and the accompanying PR's later execution evidence determine the actual result. The local first-pass adapter suite passed 27 tests using explicit dependency shims; authenticated and real database/n8n tests are CI gates, not claimed as locally completed.

No extra Railway service, subscription, limit increase, model call, inventory/ownership/price/settlement change or generic agent activation is included. The earlier prohibited broad probe/source-export helpers are not recreated. This explicit newly approved publishing command is narrowly scoped to the supplied creative and normal current service credentials.

Rollback: disable TCG_APPROVED_SOCIAL_PILOT, remove temporary n8n pre-deploy commands, and restore the previous API build if needed. Keep hosted media, public posts, PostgreSQL journal and persistent n8n history. Software rollback does not retract a public post; deletion would require a separate instruction.
