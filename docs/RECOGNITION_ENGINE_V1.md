# Recognition Engine v1

Drop Rate Recognition Engine v1 is a multi-signal card-identification pipeline for exact collectible printings.

## Scope

Initial supported games:

- One Piece Card Game
- Pokémon TCG

The engine is intentionally provider- and model-modular so Dragon Ball, Lorcana, Riftbound, Naruto and future collectible categories can be added without changing the inventory/ownership model.

## Safety model

The AI vision provider is an observation layer only.

It may extract:

- game
- language
- card name guess
- set name guess
- collector/card number
- rarity text
- card type/category
- artwork treatment
- finish/treatment
- visible markers/OCR text
- image quality
- possible print/layout concerns

It does not choose whether an inventory record may be approved.

The deterministic resolver independently compares those observations against:

- Drop Rate catalogue products
- structured collectible taxonomy
- current inventory language evidence
- TCGdex / Punk Records provider data
- existing provider catalogue mappings
- local canonical reference images
- local perceptual image fingerprints
- runner-up candidate score and margin
- high-value / graded / existing-identity risk gates

## Decisions

Recognition produces one of:

- EXACT_CANDIDATE
- NEEDS_REVIEW
- NO_MATCH
- FAILED

EXACT_CANDIDATE means the exact-printing evidence cleared the resolver gates. It does not change inventory by itself.

NEEDS_REVIEW is used whenever evidence is insufficient, ambiguous or risky.

## Same-number variant protection

A shared printed card number is not enough for an exact-printing decision.

If multiple viable local printings share the same card number, the engine requires at least one unique printing discriminator:

- uniquely matching art-treatment evidence
- unique exact provider identity/evidence
- strong visual reference similarity with a meaningful lead

Otherwise the run is forced to NEEDS_REVIEW with AMBIGUOUS_PRINTING.

This is designed for cases such as:

- One Piece Base vs Parallel vs Alternate Art vs Manga
- Pokémon Normal vs Holo vs Reverse Holo and art variants
- future promo/reprint/stamped treatment distinctions

## Hard gates

The resolver cannot silently pass:

- wrong game
- wrong card number
- wrong language
- low-confidence card number
- low-confidence language
- poor image quality
- possible counterfeit/layout concern
- high-value item threshold
- graded inventory
- current inventory identity conflict
- insufficient top-vs-runner margin
- unresolved same-number printing ambiguity
- provider evidence conflict

## Image handling

The API accepts JPEG, PNG and WebP card images.

The original source image is not stored in PostgreSQL by Recognition Engine v1.

Stored source facts are limited to:

- SHA-256
- MIME type
- byte size

For deterministic visual matching, the service computes local perceptual fingerprints in memory. Trusted provider reference images are fetched only from allow-listed card-image hosts.

## Audit model

Every run is recorded in `tcg.recognition_runs`.

Every ranked candidate is recorded immutably in `tcg.recognition_candidates`.

The candidate evidence includes:

- score
- rank
- hard-rejection state
- rejection reasons
- per-signal evidence
- candidate snapshot

Recognition candidate evidence cannot be updated or deleted through the application role.

## Human truth / training data

Founder review is stored separately in append-only `tcg.recognition_feedback`.

Outcomes:

- CONFIRMED_TOP
- CORRECTED_TO_CANDIDATE
- REJECTED_ALL

A correction must select a viable candidate from the actual recognition run.

Feedback records can supersede prior feedback but are immutable themselves. This preserves the complete audit chain.

This human-labelled dataset is the future source for:

- recognition evaluation
- confusion-pair analysis
- threshold calibration
- model/provider benchmarking
- supervised training where permitted
- regression tests

Unreviewed AI output is never treated as training ground truth.

## Founder HQ

The Verify tab includes a Scan a card panel.

The user can:

1. take/upload a card photo
2. run recognition
3. view top candidate
4. view runner-up
5. inspect evidence score and margin
6. inspect extracted game/language/number/rarity/type/art/finish
7. see safety blockers
8. confirm top candidate as a human label
9. mark runner-up as the correct human label
10. reject all candidates

Those feedback actions do not edit inventory or Shopify.

## OpenAI configuration

Vision uses an OpenAI multimodal model through the Responses API.

Required production variable:

`TCG_OPENAI_API_KEY`

Optional variables:

- `TCG_RECOGNITION_MODEL`
- `TCG_RECOGNITION_EXACT_THRESHOLD_BPS`
- `TCG_RECOGNITION_MIN_MARGIN_BPS`
- `TCG_RECOGNITION_HIGH_VALUE_REVIEW_MINOR`
- `TCG_RECOGNITION_MAX_IMAGE_BYTES`

The current default is `gpt-5.6-sol`; it is configurable rather than hard-wired. The model is replaceable, and deterministic resolution, audit history and human feedback remain independent of the AI provider.

## Production rollout

Recognition Engine v1 should be deployed fail-closed:

1. migrate schema
2. deploy application/UI
3. configure the vision API key
4. validate with known One Piece and Pokémon cards
5. build a reviewed benchmark set
6. measure exact-printing precision and review rate
7. calibrate thresholds only from reviewed evidence
8. do not auto-change inventory identity until benchmark evidence justifies a separate guarded approval phase


## Live mobile camera

Founder HQ Verify includes a browser-native live camera mode.

On a supported HTTPS mobile browser:

1. the user taps **Open live camera**
2. the browser requests camera permission
3. Drop Rate requests the rear-facing camera by default
4. the live stream remains local to the browser
5. the user aligns the physical card inside a 5:7 card guide
6. **Capture & recognise** takes one centre-cropped JPEG still
7. the camera stream is stopped immediately
8. only the captured still image is sent to the Recognition Engine
9. the Recognition Engine returns exact-printing evidence and review gates

The application does not continuously upload or record the camera stream.

Camera permissions are restricted to the first-party Drop Rate origin with:

`Permissions-Policy: camera=(self), microphone=(), geolocation=()`

Microphone and geolocation remain disabled.

If live camera access is unavailable or denied, the existing JPEG/PNG/WebP upload flow remains available.

Where the device/browser exposes torch control, Founder HQ can toggle it. The feature also provides front/rear camera switching, but the rear camera is preferred for card recognition quality.

Leaving Verify, hiding the page, closing/navigating away from the page, or pressing Close stops all active video tracks.


## Gameplay fingerprint recovery

A readable collector number remains the strongest identity anchor, but Recognition Engine v1 does not give up when glare, a sleeve or a rigid holder obscures the tiny printed ID.

For One Piece, the vision stage also extracts:

- cost
- power
- colour
- card type
- attribute
- traits
- effect text

Drop Rate compares those observations against language-specific Punk Records provider data. English and Japanese One Piece provider indices are supported.

A provider-derived card ID is accepted as an identity anchor only when multiple independent gameplay fields strongly agree. The recovered ID is recorded separately from direct OCR and is never represented as though the model read the printed number.

Exact printing remains a separate decision. If a recovered identity has multiple provider printings such as base, parallel or reprint variants, Drop Rate requires sufficiently discriminating artwork evidence before it may return EXACT_CANDIDATE. Otherwise it returns the correct durable card identity with NEEDS_REVIEW for the printing.

Catalogue fallback name matching is punctuation-insensitive so imported names such as `Monkey.D.Luffy (118)` can match vision text such as `Monkey D. Luffy`.


## Identity confidence vs printing confidence

Recognition Engine v1.2 separates two different questions:

- **Identity confidence**: which durable card identity is this?
- **Printing confidence**: which exact artwork / parallel / reprint / finish is this?

Identity confidence is based on independent evidence such as game, language, name,
collector number or recovered provider ID, card type and provider/gameplay
fingerprints. One Piece fingerprints can include cost, power, colour, attribute,
traits and effect text.

Printing confidence is based on evidence such as art-treatment interpretation,
finish, canonical reference-image similarity and exact provider-print mapping.

A card may therefore have very high identity confidence while still remaining
NEEDS_REVIEW for exact printing. That is intentional.

### OCR conflict handling

A printed collector number from vision is not treated as infallible.

If OCR produces a number that strongly conflicts with independent facts such as
name, cost, power, colour, type, traits, effect text and provider data, the engine
can recover the durable identity from the stronger multi-signal fingerprint.

The conflict is preserved as `OCR_CARD_NUMBER_CONFLICT` and prevents silent
exact-printing approval. The UI shows both the OCR value and the recovered card ID.

Provider and catalogue candidate retrieval is deliberately soft. A single wrong OCR
field cannot remove the correct card from the candidate set.
