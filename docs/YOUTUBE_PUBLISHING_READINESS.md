# YouTube publishing readiness — 5 October 2026

## Purpose

Instagram and TikTok delivery were proved by the completed Gunko pilot. YouTube remains deliberately unverified and must be completed as a separate approval-bound video path rather than by widening the finished image pilot.

This first step is read-only. It discovers the one connected YouTube channel inside the already-known Drop Rate Buffer organization and records only non-secret channel metadata. It does not create, edit, schedule, publish, delete, or queue content.

## Why this is separate

The completed Gunko pilot is fixed to Instagram and TikTok image publication and is retained as audit history. YouTube through Buffer is a different media contract: Buffer supports YouTube Shorts rather than long-form uploads, requires a video asset, and requires YouTube metadata including a title and category.

The future publishing pilot will therefore have its own immutable manifest, pilot ID, approval hash, video hash, channel ID, title/description/category, expiry and exact one-time permission.

## Readiness probe

`backend/scripts/buffer_youtube_readiness.py`:

- reads the existing `TCG_BUFFER_API_KEY` runtime credential without printing it;
- reuses the Buffer organization ID already committed in the completed social pilot manifest;
- performs one GraphQL channels query only;
- requires exactly one channel with `service=youtube` in that organization;
- reports channel ID, name/display name, service, allowed actions, disconnect/lock/queue state and timezone;
- reports fixed local error codes instead of provider response bodies;
- performs no mutations and writes no database state.

A channel is ready only when it is connected, unlocked, unpaused and exposes `scheduleUpdates`.

## Media gate before any live YouTube publish

No YouTube publish is authorised by this readiness probe.

The next publishable asset must be explicitly approved and must be a real narrated/captioned Drop Rate short. Do not substitute the existing static Gunko image or a silent slideshow.

For the Buffer path, the approved asset should be prepared as an H.264 MP4 with AAC audio, exact 9:16 dimensions (prefer 1080×1920), one video only, and a duration within Buffer's YouTube Shorts limit. The final hosted file must be bound by exact byte hash and byte count in the manifest before publishing is enabled.

The one-off YouTube pilot must then prove, in order:

1. exact connected channel identity;
2. exact hosted-video read-back and hash;
3. exact title, description, category and AI disclosure metadata;
4. automatic + immediate publish mode;
5. one durable intent and irreversible claim before the provider write;
6. a separate provider-status read-back;
7. an intentional duplicate trigger that replays the same provider post rather than creating a second upload;
8. cleanup of the temporary publish flag/operator command;
9. no daily/recurring publishing enabled.

## Failure policy

A timeout or ambiguous create result is UNKNOWN and must never be blindly reposted. Reconcile the provider first. Existing PostgreSQL journal and Action Required patterns remain authoritative.

No new Railway service, database schema, paid plan, inventory, ownership, pricing, settlement or recurring marketing schedule is introduced by this readiness step.


## Live readiness evidence — 5 October 2026

PR #521 introduced the read-only probe and merged as `29a089b61d123888bdd4097b32fdc93800484f2d`. A normal source deployment `f25b668f-3bbd-46b7-b937-688475273b1f` completed with 2,550 tests and readiness 200 before any live Buffer diagnostic.

A first Railway redeploy after changing the pre-deploy configuration did not provide evidence that the new diagnostic command had executed, so no Buffer conclusion was drawn from it. PR #522 added explicit output flushing and merged as `2ff4689e4d97070d9b37997593d7037c6470cdaf`. The resulting fresh GitHub-source deployment `2132c13b-d699-4afa-ad87-1d449f668146` then ran the diagnostic and completed with 2,550 tests and readiness 200.

Buffer returned exactly one YouTube channel in organization `6ac1a59ca59739d7c3e08601`:

- channel ID: `6ac1a694ea19ca0bde6c8ba3`
- service: `youtube`
- returned name/display name: `Drop Rate ` (including the provider-returned trailing space)
- timezone: `Europe/London`
- `isDisconnected=false`
- `isLocked=false`
- `isQueuePaused=false`
- `scheduleUpdates` is present in `allowedActions`

The readiness result was therefore `ready=true` with no blockers. Identity for any later pilot must bind to the immutable channel ID and organization ID, not a trimmed or human-edited display string.

No post was created, edited, queued, scheduled or deleted. The probe made only the channels read. Immediately after recording the sanitised result, the API service's original pre-deploy command was restored, its temporary timeout was cleared back to the default, and Railway reported no staged changes.

YouTube publication remains blocked on an explicitly approved narrated/captioned video plus a separate immutable video-pilot manifest and duplicate-delivery proof.
