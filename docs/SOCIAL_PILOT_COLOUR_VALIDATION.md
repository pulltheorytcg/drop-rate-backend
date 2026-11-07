# Pilot colour-profile validation

PR #518's actual read-only n8n execution reached the CDN but returned PILOT_MEDIA_COLOUR_METADATA_CHANGED for both images. The first validator rejected any ICC/EXIF presence, so a valid profile or harmless metadata could stop publication before the exact pixel comparison. No public post was attempted.

This repair does not skip colour handling. It accepts valid bounded ICC data only by using Pillow's existing LittleCMS-backed ImageCms conversion to sRGB, then requiring the SHA-256 of every resulting RGB8 pixel to equal the approved value. An ICC description saying sRGB is not trusted as proof. Invalid or oversized profiles fail; any transformed pixel difference fails. Without ICC, nonstandard gamma remains rejected. EXIF may contain harmless encoder metadata, but orientation must be absent or identity; there is no silent rotation. Existing PNG, dimension, byte, frame and opacity guards remain.

The chosen original PNG has no ICC/EXIF metadata, and the prepared Instagram source JPEG has only JFIF metadata. Local sRGB-to-sRGB conversion preserved every pixel of both full publication copies. The manifest, captions, media URLs, accounts, approval hash and pilot identity are unchanged by this repair.

Six additional tests cover standard sRGB, harmless EXIF, changed orientation, post-transform pixel differences, oversized profiles and unsupported gamma. The prior invalid-profile, one-pixel, alpha, animation, format, bounds and exact approval tests remain. Full Backend checks and the existing real PostgreSQL/actual n8n integration checks must pass before merge. Fixtures are not live social delivery.

API release of #518 reached SUCCESS on deployment 08fe2c4e-b248-412f-9c38-ce2e36839223, with 2,533 pre-deploy tests and readiness 200. n8n check deployment a5291b63-49ef-4db7-b133-2f7f6e2c1e9a completed with the metadata block. The next check must be read after this repair is deployed; only READY permits the separately enabled, immediately published pilot.

Pillow primary reference: https://pillow.readthedocs.io/en/stable/reference/ImageCms.html

No new dependency, migration, service, RLS change, secret change, daily schedule, model generation, price post or YouTube replacement. Restore the preceding API build to roll back; preserve all n8n and publication history. Remove temporary operator commands and disable publishing after the test.
