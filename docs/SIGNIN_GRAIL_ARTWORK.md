# Illustrated sign-in slab pair — 3 October 2026

The user rejected the three-game photographic composition and explicitly asked
to return to the original illustrated style with two cards. The shared sign-in
now uses the previously liked Charizard PSA-style 10 and Umbreon Black Label-style
10 illustration. It is decorative generated artwork, not an exact real-card or
certificate reproduction and not an inventory, availability or ownership claim.

## Assets

- `backend/app/static/brand-assets/collector-slab-pair-labels.webp`: the current
  sign-in artwork, refined with built-in imagegen to improve the two grading
  labels. The transparent PNG was kept at its native 1254px resolution for the
  label lettering and encoded as WebP quality 90 with alpha preserved. The fresh
  asset URL avoids stale caching. The page retains the same display dimensions.
- `backend/app/static/brand-assets/collector-slab-pair.webp`: the existing built-in
  imagegen result, resized proportionally from 1254px to 1000px and encoded as
  WebP quality 88 with its real alpha channel preserved. No new creative redraw.
- `backend/app/static/brand-assets/collector-worlds-slabs.webp`: the matching
  navy/cyan/gold/red anime background, edited with built-in imagegen from the
  original `collector-worlds.webp` to remove fantasy card backs.

The approved logo remains separate. Both illustrated slabs are one transparent
image with `object-fit: contain`; responsive height rules retain the whole pair
and keep the illustration in document flow. The photographic source assets and
their positioning rules were removed. CSS references advance to v5.

## Label refinement (built-in imagegen)

The user approved the restored illustrated pair and asked for more attention to
the slab labels. The edit target was the original transparent illustration.
Previously inspected PSA Charizard and Beckett Black Label Goku reference photos
were used only for grading-label structure and print hierarchy; their card
artwork and real certificate identifiers were not used. The refined illustration
retains Charizard and Umbreon. It remains an illustrative recreation, not an
exact certificate reproduction. The generated labels were visually checked for
card details, grade placement, spelling, perspective and unobstructed print.

### Exact edit prompt

Use case: precise-object-edit.
Asset type: transparent illustrated two-slab artwork for Drop Rate's sign-in page.
Input 1 is the EDIT TARGET: the approved illustrated Charizard and Umbreon slab pair. Inputs 2 and 3 are REFERENCES FOR GRADING-LABEL DESIGN ONLY: a real PSA Charizard label and a real Beckett Black Label.
Primary request: improve ONLY the two grading labels at the tops of the slabs, giving them much more accurate structure, careful typography and convincing printed detail. Keep the approved anime illustration style. This is a label refinement, not a redesign.

LEFT CHARIZARD LABEL: red perimeter and white printed face, recognizable PSA branding at the top, crisp dark sans-serif typography, aligned compact information rows at left, separate grading column at right. Use exactly:
"1999 POKEMON GAME"
"CHARIZARD-HOLO"
"1ST EDITION"
At right: "#4", "GEM MT", and a bold prominent "10".
Match the hierarchy and professional label spacing of reference 2, adapted cleanly to the existing tilted slab. Keep the thin red frame even and tidy.

RIGHT UMBREON LABEL: rich solid black printed face, recognizable silver/white Beckett B/laurel emblem and small BECKETT lettering at left, a fine divider, restrained metallic gold lettering. Information rows:
"2021 POKEMON"
"EVOLVING SKIES"
"#215 UMBREON VMAX"
Four small aligned subgrades beneath: "CENTERING 10", "CORNERS 10", "EDGES 10", "SURFACE 10".
At right a bold prominent gold "10" with "PRISTINE" beneath.
Use the authentic Black Label print hierarchy and colors from reference 3, but retain UMBREON and do not introduce Goku or any other card.

Both labels: sharp readable letterforms, consistent baselines, tidy margins, accurate perspective, high contrast, minimal surface glare over the text, no random characters or misspellings. Preserve clear plastic lips around the labels. Do not copy or invent certification numbers or scannable barcodes. Leave certificate-number areas unobtrusive.
INVARIANTS: exactly two cards. Preserve the existing Charizard art, Umbreon/moon art, card faces, yellow borders, entire slab shapes, tilts, overlap, relative size, arrangement, fire, cyan energy, gold sparks, palette, lighting, original square framing and transparent outer background. No new objects, no scenery, no photographic pasted cards, no UI, no third card. The cards and energy outside the two label rectangles should remain as close to input 1 as possible. Render the finished illustration at high resolution with genuine alpha transparency.

## Original slab illustration prompt (built-in imagegen)

Use case: style-transfer. Asset type: transparent foreground illustration for the Drop Rate sign-in hero. The supplied image is a STYLE REFERENCE only: match its premium anime/manga cel shading, bold navy ink outlines, detailed crosshatching/halftone, cyan rim light and warm gold highlights. Create TWO recognisable collector grail trading cards in transparent grading slabs as stylised illustrated recreations, not photographs. Left/front hero: original 1999 first-edition base-set Charizard card, yellow border, orange Charizard with blue-green inner wings and fire on dark holographic card art, pale lower rules area. Clear rigid PSA-style slab, top WHITE label with RED border; label text only 'PSA', 'CHARIZARD', 'GEM MT', and a large '10'. Right/rear hero: Umbreon VMAX alternate-art Moonbreon, a black Pokemon with gold ring markings reaching up toward a big golden full moon above turquoise spired rooftops, in a clear rigid Beckett-style slab. Top BLACK label with warm gold details; label text only 'BECKETT', 'UMBREON VMAX', 'PRISTINE', and a large '10'. Do not include realistic certification numbers, barcodes or invented card rules; tiny card print may be stylised ink lines. Show the FULL exterior of both slabs, including clear thick plastic bevels and corner reflections. The Charizard is 12% larger and leans gently counterclockwise; the Umbreon leans gently clockwise and sits slightly higher, with a small natural overlap. Both label bands and both Pokemon artwork panels must remain unobstructed. A dynamic balanced two-card fan, premium and collectible, rich expressive artwork, crisp finish with depth, subtle turquoise/gold lighting integrated into the glass edges. No separate captions, no price, no UI, no hands, no tabletop, no environment. Isolate both illustrated slabs on a genuinely TRANSPARENT background, leave comfortable transparent margins all around. No background rectangle or checkerboard. Cards should fill most of a square composition.

## Background prompt (built-in imagegen)

Use case: precise-object-edit. Edit target: the supplied navy anime trading-card background. Asset type: background layer behind real slab photographs on Drop Rate sign-in. Keep the original anime/manga drawing style, midnight-navy sky, vivid cyan ocean waves and sweeping turquoise energy, gold lightning and sparks, red ribbon, distant pirate ship, shuriken and scroll, orange star orb. Remove all three floating fantasy card backs completely, reconstructing the flowing energy, night sky and waves where they were. Do not replace them with any cards or objects; real slab photos will be layered separately by the website. Reframe as a tall 2:3 portrait composition with the brightest cyan/gold energy arcing around the middle third and deep navy negative space through its center for two slab photos. Leave the upper 18% calm dark navy for an existing logo, and bottom 30% dark navy with subtle waves for an existing headline. Bold ink outlines, cel shading, manga speed lines and halftone texture. Preserve the established palette and vibe. No text, letters, numbers, logos, watermark, card shapes, card backs or UI.

## Verification and rollback

Only sign-in presentation and art change. Authentication, registration logic,
catalogue, scanner, accounts and financial behaviour are unaffected. Required
backend, dashboard and existing pinned n8n CI checks run on the correction PR.
Public-page visual inspection and asset hashes are recorded there after release.
Local visual previews are blocked by the cloud browser URL policy; no phone or
authenticated real-account visual acceptance is claimed.

To restore the last version before this artwork work, redeploy application
commit `2762e2645f4e7ab02cc5301d5d03332772e797ad`. No database, service or
configuration reversal is required. The superseded three-photo version was
PR #508, merged as `5f39851e96aa31899e27d8c26f8a9abc8d91847c`.

To undo only this label refinement, restore the image URL to
`/assets/brand-assets/collector-slab-pair.webp` or redeploy
`92b39e98a0cc025190a7f0adc7989704313837fb`. The original asset remains in the repo.
