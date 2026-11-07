# YouTube video pilot contract — prepared, not live

## What this adds

The Buffer YouTube channel is verified and ready, but no approved video has been supplied yet. This module prepares the deterministic contract for the future one-off YouTube Shorts test without exposing a route or creating any provider-write capability.

`backend/app/youtube_pilot_contract.py` binds a future pilot to:

- one immutable pilot ID and founder actor;
- Buffer organization `6ac1a59ca59739d7c3e08601`;
- the verified YouTube channel ID `6ac1a694ea19ca0bde6c8ba3`;
- one HTTPS Shopify Files MP4;
- exact SHA-256 and exact byte count;
- exact 9:16 dimensions, a maximum three-minute duration declaration, audio, approved narration and approved captions;
- founder-approved title, description and YouTube category;
- public/not-for-kids pilot metadata with subscriber notifications disabled;
- an explicit founder approval reference and expiry.

The module contains no FastAPI router, no Buffer credential handling and no GraphQL mutation. It cannot publish.

## Exact media rule

The future live adapter must call `verify_approved_video` before any provider write. The function streams the approved Shopify Files URL without redirects, requires `video/mp4`, enforces the approved byte count, checks the MP4 `ftyp` marker, and requires an exact SHA-256 match. The 512 MiB internal cap is intentionally much smaller than Buffer's platform maximum because this is a bounded short-form pilot, not a generic upload service.

Codec, audio content, narration quality and burned-in caption quality are human/creative-pipeline approval facts rather than values inferred by this backend. Exact file hashing ensures the bytes checked at publish time are the same bytes that were approved.

## Buffer payload

The pure `buffer_create_input` builder prepares, but does not send, the future `CreatePostInput`:

- one video asset;
- `mode=shareNow`;
- `schedulingType=automatic`;
- no draft and no approval-queue fallback;
- YouTube title/category and explicit disclosure/privacy settings.

This input is not callable from HTTP today. A separate reviewed adapter/route and inactive version-controlled n8n export are still required after the actual media is approved.

## Failure policy

Wrong organization/channel/service, disconnected/locked/paused state, missing scheduling permission, changed URL/MIME/container/length/hash, invalid approval metadata, unsafe delivery URL or unknown provider state all fail closed.

A later create timeout or ambiguous provider result must remain UNKNOWN and reconciliation-only. Never issue a second YouTube upload simply because the first response was uncertain.

## Tests

The contract tests cover strict manifest parsing, immutable revision hashing, URL/aspect/duration/audio/narration/caption gates, exact Buffer input, ID-based channel binding, stream/hash verification, content-type and redirect rejection, delivery normalization and an explicit assertion that the module exposes no router or Buffer mutation.

## Remaining gate

Do not add the live YouTube route or n8n publish workflow until the founder has approved the exact narrated/captioned MP4 and its title/description/category. At that point, bind those values into an immutable manifest, add the adapter/journal path, run check-only, enable the exact revision temporarily, publish once, re-read delivery, intentionally replay the same event, then disable and clean up.
