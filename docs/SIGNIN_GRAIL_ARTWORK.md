# Sign-in grail artwork — 3 October 2026

The requested left-hand sign-in artwork keeps the established navy, cyan, gold
and red anime scene and introduces one real graded reference from each game:

| Game | Card shown | Source label |
| --- | --- | --- |
| Pokémon | 1999 first-edition Base Set Charizard #4 | PSA GEM MT 10, 16426238 |
| One Piece | Japanese manga Monkey D. Luffy OP05-119 | PSA GEM MT 10, 123649883 |
| Dragon Ball Super | Son Goku, The Awakened Power TB1-097 | Beckett Black Label Pristine 10, 0016574034 |

The user first requested stylised recreations, then refined that to these three
games with exact real PSA/Black Label references. To retain exact card artwork,
edition, lettering and grading details, the foreground uses source-image layers
instead of AI-redrawn card faces or labels. CSS supplies the angled composition,
ink-coloured edging and cyan/gold rim lighting. The generated illustration is
the surrounding background only. This is a hybrid illustrated scene, not a
claim of pixel-identical AI recreation.

The source image bytes were converted to WebP; the large Luffy scan was also
resized to 780px wide. No card/label content or watermark was repainted, erased
or replaced. CSS clips only the plain scene outside the Goku holder. Sources,
source hashes, derivative hashes and conversion details are recorded in
`backend/app/static/slab-art/sources.json`. The source listings identify the
grades; this work does not independently authenticate the objects, claim
ownership/availability, or introduce them into inventory or pricing.

`backend/app/static/brand-assets/collector-worlds-slabs.webp` was edited from the
existing `collector-worlds.webp` using the built-in imagegen tool, then encoded
as WebP. The approved Seller Hub logo remains a separate image.

## Background prompt

Use case: precise-object-edit. Edit target: the supplied navy anime trading-card background. Asset type: background layer behind real slab photographs on Drop Rate sign-in. Keep the original anime/manga drawing style, midnight-navy sky, vivid cyan ocean waves and sweeping turquoise energy, gold lightning and sparks, red ribbon, distant pirate ship, shuriken and scroll, orange star orb. Remove all three floating fantasy card backs completely, reconstructing the flowing energy, night sky and waves where they were. Do not replace them with any cards or objects; real slab photos will be layered separately by the website. Reframe as a tall 2:3 portrait composition with the brightest cyan/gold energy arcing around the middle third and deep navy negative space through its center for two slab photos. Leave the upper 18% calm dark navy for an existing logo, and bottom 30% dark navy with subtle waves for an existing headline. Bold ink outlines, cel shading, manga speed lines and halftone texture. Preserve the established palette and vibe. No text, letters, numbers, logos, watermark, card shapes, card backs or UI.

## Scope and verification

The changes are limited to shared sign-in markup, its scoped CSS, artwork and
CSS version references. The registration page retains its existing artwork.
The authenticated home retains its exact ungraded catalogue references. No
authentication, catalogue, scanner, account, inventory or financial behaviour
is changed.

All existing dashboard interaction suites pass locally. `git diff --check`
passes. Required backend, dashboard and existing pinned n8n build CI gates run
on the release PR. The cloud browser cannot open local previews, so local
responsive visual acceptance is not claimed; public-page visual and asset
verification are recorded on the PR after deployment. No physical-device or
real-account testing is claimed.

Application rollback: redeploy commit
`2762e2645f4e7ab02cc5301d5d03332772e797ad`, or revert this artwork PR. No database,
configuration or external service changes need reversal.
