# Graded Slab Scanner Architecture

_Status: provider gateway implementation reopened by explicit founder approval on 1 October 2026. Scanner UI/canonical commit flow remains separately gated._

## Goal

Add a grader-aware intake mode to both Founder HQ and the future Seller Hub/mobile app so a user can choose what they are scanning:

- **Raw Card**
- **Graded Slab**

Raw Card keeps the existing recognition flow.

Graded Slab becomes a separate verification pipeline designed around the slab label/certificate rather than trying to identify the encapsulated artwork as if it were a raw card.

## Target user flow

1. User opens scanner.
2. User chooses **Raw Card** or **Graded Slab**.
3. If Graded Slab:
   - capture slab front;
   - optionally capture slab back / QR;
   - detect grading company;
   - OCR/read certificate number;
   - normalise the certificate number;
   - route to the relevant provider adapter;
   - verify the certificate with the grading provider where permitted;
   - retrieve provider identity data;
   - match that identity deterministically to the Drop Rate canonical catalogue;
   - show one confirmation screen containing card, set, number, language, variant, grader, grade and cert;
   - user confirms;
   - create/update the physical Inventory Item;
   - store grader + grade + certificate number directly on that Inventory Item;
   - register exact official slab media when the provider exposes it and Drop Rate has a permitted right to use it;
   - otherwise retain first-party slab captures and/or raise Action Required.

The system must never infer or overwrite a different physical card solely because the slab artwork looks visually similar.



## Language recognition

Language detection is part of the scanner identity pipeline for both **Raw Card** and **Graded Slab** modes.

Initial supported languages:
- English (`EN`);
- Japanese (`JA`);
- Chinese (`ZH`);
- Korean (`KO`).

The scanner must not determine language from artwork alone. It should combine:
- OCR/script evidence from the physical card or slab label;
- Unicode/script classification (Latin, Japanese kana/kanji, Hangul, Chinese Han text);
- card/set/collector-number conventions;
- provider/canonical catalogue evidence;
- grading-provider certificate language/printing fields when available;
- known language availability for the exact printing.

For Chinese, the data model should preserve room for script/market detail such as Simplified vs Traditional Chinese (for example `ZH-HANS` / `ZH-HANT`) even if the initial UI displays simply **Chinese**.

Suggested normalized result:

`language_detection = { language, script_variant, confidence, evidence[] }`

Rules:
- **HIGH confidence + canonical compatibility** → preselect language for confirmation;
- **MEDIUM confidence** → show language prominently for human confirmation;
- **LOW confidence / conflicting evidence** → Action Required; do not silently assign language;
- a provider response may corroborate language but must not overwrite contradictory first-party physical evidence without review.

For graded slabs, provider cert data and slab-label OCR should be compared. A mismatch (for example provider says English while the physical slab/card appears Japanese) must fail closed.

The confirmed language is stored on the **physical Inventory Item** and participates in:
- exact canonical printing matching;
- recognition;
- market-data/pricing selection;
- Shopify title/metafields/filters;
- duplicate/pooling eligibility;
- future cross-channel publication.

Two otherwise identical cards in different languages must never be pooled together.

## Provider adapter contract

Each grader implements the same interface conceptually:

`lookup_certificate(cert_number) -> GradedCertificateResult`

The normalized result should contain, where available:

- grader;
- certificate number;
- verification status;
- card/game/category;
- year;
- set/brand/title;
- card name/subject;
- collector/card number;
- language;
- variant/parallel;
- overall grade;
- subgrades where applicable;
- label type;
- provider record URL/reference;
- provider image URLs;
- provider warnings/notes;
- fetched timestamp;
- raw provider payload/provenance where permitted.

The adapter only returns provider evidence. Canonical matching and all inventory mutations remain deterministic FastAPI/Postgres logic.

## Provider plan

### PSA

**Target: fully automated provider verification.**

PSA exposes an official Public API with cert lookup by certificate number. This should become the first production-grade adapter.

Planned path:
- read cert from slab;
- call PSA official cert endpoint;
- parse exact identity + grade;
- deterministically match canonical card;
- store cert/grade on Inventory Item;
- attach exact official PSA slab media when supplied and permitted;
- fail closed when cert is valid but PSA has no exact slab scan.

The source-controlled FastAPI gateway now owns the production adapter contract. The retained Railway `psa-fetch-batch` service remains a diagnostic/prototype path and must not be treated as canonical business logic. Its production deployment still requires a dedicated PSA token; unrelated provider credentials must never be reused.

### ACE

**Target: automated verification only after permitted machine-access method is confirmed.**

ACE's public certificate pages expose useful structured identity including cert, card name, set, number, language, variant and grade, and exact slab imagery has already been verified for cert 590532.

Planned path is the same provider-adapter contract as PSA.

Do not assume scraping is permitted. Before production automation, confirm an official/permitted machine interface or explicit permission. Until then:
- scanner may OCR grader/cert;
- link the operator to the exact ACE cert record;
- allow human-confirmed provider evidence;
- store the cert and exact first-party/operator-approved slab media;
- keep missing official sides as Action Required.

### CGC

**Target: automated verification if a permitted integration/API is available; otherwise QR/cert-assisted human verification.**

CGC's public Verify Certification tool confirms the card description and grade and can expose images of the holdered card. CGC also places a QR code on the slab label for quick verification.

Scanner should therefore support:
- CGC slab detection;
- cert OCR;
- QR capture where present;
- provider lookup through a permitted adapter;
- exact identity/grade/media confirmation;
- storing CGC certification number directly on the Inventory Item.

Do not bypass provider rate limits or build an undocumented scraper if CGC does not provide permitted machine access.

### TAG

**Target: cert/QR-first verification with rich digital grading evidence.**

TAG is especially well suited to Graded Slab mode because every TAG slab can expose its DIG (Digital Image & Grading) Report by certificate number or QR code. TAG documents certificate search, QR access and digital reports containing card identification, industry-standard grade, TAG Score where applicable, detailed grading metrics/defects and high-resolution imaging.

Scanner support should include:
- detect TAG slab/label;
- read the TAG certificate number;
- scan the slab QR code when available;
- resolve the corresponding DIG report through a permitted provider path;
- ingest exact card identity, standard grade and TAG Score where present;
- preserve detailed TAG grading metrics as provider evidence rather than flattening them into Drop Rate's core grade field;
- store the TAG certificate number directly on the physical Inventory Item;
- attach exact TAG slab/card media only where permitted;
- retain the DIG/provider reference for audit and customer/admin verification.

TAG also supports Proof™ anti-counterfeit authentication on slabs. This should be treated as a separate authenticity signal from ordinary certificate lookup and should not be silently equated with canonical card identity.

Do not assume the public certificate-search/DIG pages constitute an unrestricted scraping API. Prefer a documented/approved machine integration or partnership route before enabling automated server-side extraction.

### BGS / Beckett

**Target: adapter-ready but fail-closed for automation until permitted machine access is available.**

Beckett currently exposes public BGS/BVG/BCCG certificate verification by serial number, but the public lookup is protected by reCAPTCHA and no documented public cert API is currently part of this architecture.

Therefore:
- scanner detects BGS/BVG/BCCG;
- reads serial number and subgrades/label text from the physical slab;
- stores candidate data only;
- opens the Beckett verification record for human confirmation where needed;
- does not automate around reCAPTCHA;
- only enables automatic provider verification if Beckett later supplies or approves machine access.

BGS half grades and subgrades must be preserved exactly. The schema/UI must support grades such as 9.5 and Black Label 10 rather than coercing them to whole numbers.

## Canonical matching rules

A provider response is not sufficient on its own to mutate identity unless the deterministic matcher can establish one exact Drop Rate canonical printing.

Hard gates should include as applicable:
- grader + cert exactness;
- card name;
- card/collector number;
- set/brand;
- game;
- language;
- variant/parallel;
- year/printing;
- provider-specific label data.

Outcomes:

- **EXACT** → one confirmation screen; user can commit.
- **AMBIGUOUS** → Action Required / human selection.
- **NO MATCH** → create intake draft only; no canonical identity guessed.
- **PROVIDER UNAVAILABLE** → retain capture/cert candidate and allow retry; do not invent verification.

## Inventory data model

Every physical graded item keeps:
- unique Inventory ID;
- canonical Card ID;
- owner;
- grader;
- grade;
- certificate number;
- language;
- acquisition cost;
- location;
- market/store pricing;
- physical status;
- media provenance.

Certificate number belongs to the physical Inventory Item, not the canonical Card.

A unique constraint/check should prevent the same grader + certificate number from being silently assigned to two active physical items unless an explicit audited exception exists.

## Media rules

Provider media must remain separate from identity evidence.

- exact provider certificate match is required;
- use only exact slab media for that certificate;
- retain source/provider/rights/provenance;
- do not substitute another slab;
- if only a front exists, store the front and leave the missing-back exception open;
- first-party slab photos remain valid and may be preferred where provider media rights are unclear.

## UX

### Scanner entry
Two large choices:
- Raw Card
- Graded Slab

### Graded result
Show:
- grader logo/name;
- verified / needs review state;
- grader-specific score where relevant (for example TAG Score);
- card image/slab image;
- card name;
- set;
- collector number;
- language;
- variant;
- grade;
- subgrades when relevant;
- certificate number;
- provider verification source;
- confidence / exact-match status.

Primary action: **Confirm graded card**.

The user should not have to manually retype card name, set, grade and cert after successful verification.

## Security and audit

Log:
- cert lookup request/result;
- provider used;
- exact canonical match decision;
- user confirmation;
- grader/grade/cert mutations;
- provider-media import;
- manual overrides;
- duplicate-cert exceptions.

Never store provider account passwords in application data. Provider credentials/tokens belong in secret storage.

## Phase 2 gate

The founder explicitly reopened the grading-certificate provider gateway on 1 October 2026.

The bounded implementation permitted now is:
- one authenticated FastAPI lookup contract;
- PSA automation through the official Public API when its dedicated token is configured;
- ACE / CGC / Beckett routed to official human-verification pages until permitted machine access exists;
- no automatic canonical identity mutation;
- no automatic inventory creation/publishing;
- no scraping around provider controls.

Scanner UI, OCR/QR capture, deterministic catalogue matching and inventory commit remain separate bounded slices and must retain their normal tests/review gates.


## Implemented scanner slice — 1 October 2026

Founder approval reopened the scanner integration after the provider gateway was deployed.

### Seller Hub modes

The scanner now separates:
- **Raw Card** — existing recognition flow, unchanged.
- **Graded Slab** — QR/certificate/label evidence flow.

### Graded Slab evidence order

1. Attempt native QR detection in the browser where supported.
2. Accept only a supported official grader domain, or a numeric QR with an explicit grader hint.
3. Normalise grader + certificate.
4. Call the common grading-certificate gateway.
5. If QR/provider lookup cannot establish card identity, capture the full slab and run label OCR.
6. Compare visible grade/card-number evidence against verified provider data when available.
7. Block on conflicts.
8. Seed canonical catalogue search from provider card number first, then visible label card number/name.
9. Require the user to confirm the exact catalogue card.
10. Re-run provider verification server-side on graded inventory intake.
11. Create only a seller-owned DRAFT item with `identity_confirmed=false`.

### QR browser compatibility

The browser QR path uses the platform Barcode Detection API only as progressive enhancement. It is not the sole scanner path because browser support is not universal. When unavailable, the same camera/upload workflow falls back to slab-label OCR and manual certificate entry.

### Physical-slab uniqueness

A grading certificate represents a single physical encapsulated item. The graded scanner slice introduces a unique database index on normalized grader + certificate number. Existing production read-back before the migration found 8 certificate-bearing graded items and no duplicates.

### PSA credential requirement

PSA's Public API requires an account-generated bearer token. The production application variable is `TCG_PSA_PUBLIC_API_TOKEN`. The application does not generate, scrape, infer or reuse a different provider secret for this value.

Until that token is configured:
- PSA QR/cert parsing still works;
- slab-label OCR still works;
- canonical catalogue confirmation still works;
- automated PSA provider verification reports unavailable and the item remains review-gated.
