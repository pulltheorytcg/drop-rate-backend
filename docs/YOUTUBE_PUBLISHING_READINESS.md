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
