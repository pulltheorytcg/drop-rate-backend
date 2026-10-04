# Lossless publication media and exact visible approval

## Actual failure

The real n8n check reached authenticated production FastAPI and verified both expected Buffer channels on 4 October 2026. Both then returned PILOT_MEDIA_CHANGED under the earlier encoded-JPEG length/SHA check. No publish operation or posting claim was created. A file-format mismatch must not be solved by deleting approval checks.

## Format-only repair

The selected Gunko poster is unchanged. The prepared 1080x1350 Instagram canvas is decoded once from the user-visible test pack and saved as opaque RGB PNG. TikTok uses an opaque RGB PNG of the original selected 948x1659 poster. No resizing beyond the previously selected Instagram layout, cropping, repainting, logo generation or caption change occurs here. The new publication copies are hosted using Shopify Files on the verified Drop Rate store; products and themes are untouched.

New manifest revision: `880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d`.
Pilot ID remains `6d3c3d1e-0ec0-4fc8-b5fb-5f9d4eeb925a`. Existing claims are never overwritten; the journal was empty before this format revision.

| Channel | Dimensions | SHA-256 of row-major RGB8 pixels |
| --- | --- | --- |
| Instagram | 1080x1350 | 184856efc33e384b0cc3d878a6c0d724e0ba8573d27ba077c9f8bfc2115733d6 |
| TikTok | 948x1659 | 5cb56b61b635a55463def50d4d65c889eb2b4a573355c898824b92c14660cb2f |

The manifest retains source encoded checksums and upload-file lengths/hashes as provenance. Runtime integrity instead binds exact decoded RGB values and dimensions, so valid lossless compression or harmless text metadata changes do not look like new creative. This has **zero pixel tolerance**: one changed channel value is rejected. No image similarity model or perceptual score is used.

The fixed HTTPS CDN URL is still allowlisted; redirects are refused. Downloads request PNG and enforce an 8 MiB limit. The validator bounds dimensions before loading, restricts the decoder to PNG, rejects multiple frames/animation, colour-profile/EXIF changes, nonstandard gamma and nonopaque alpha, and hashes the exact RGB bytes. Unsupported or malformed responses fail closed with fixed errors. Pillow is already a pinned project dependency.

## Diagnostic correction

n8n CLI error output can contain its complete workflow source, including all error guard strings. Scanning that whole output incorrectly labels any failure as the first guard found. The classifier now parses bounded execution JSON and reads only data.resultData.error fields. Truncated JSON containing code stays unknown. Diagnostics still emit constants only, never captured output, signatures, provider errors or secrets. The earlier HASH_NOT_CONFIGURED result is therefore not conclusive proof of that cause.

## Tests

Exact pixel tests cover different valid PNG encodings/text metadata, one-pixel change, different dimensions, opaque RGBA, unexpected transparency, animation, ICC, wrong format, malformed images, byte limits and invalid approval fields. The actual Buffer preflight mock decodes a real fixture PNG. The approval digest is checked against the committed manifest. Regression tests ensure embedded guard code cannot override the actual runtime error.

Existing signed-route, immutable journal, eight-way claim race, timeout-after-write, owner isolation and actual n8n fixture checks remain. CI has no production credentials or public social requests. Current-head CI must pass before release. Live pixel equality and eventual provider delivery must be read separately; these tests do not claim either result.

## Operation and rollback

Use the new hash in the temporary check-only n8n operator command. Align only that disposable process with its tested crypto/env settings and the existing API URL; never expose or reset private n8n. Wait for READY on each intended channel before enabling the exact API publication hash. Immediate publish still uses shareNow/automatic and no write retries. Separate status/replay calls must preserve the same claims and returned IDs. Remove the operator command and disable publishing after the pilot.

Old manifest/assets remain in Git/provider history. Reverting application code does not authorize another public post or discard an existing claim. Preserve every journal and Action Required item. No migration, new service, recurring schedule, model/Higgsfield call, price post or YouTube substitute is included.

This section supersedes the encoded-JPEG hashes described in the earlier pilot document. Its source/deployment checkpoints remain historical evidence; the accompanying repair PR records current-head tests and final live outcomes.
