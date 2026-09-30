# Graded Slab Scanner Architecture

_Status: approved backlog design, deferred behind the Phase 2 storefront launch/stability gate._

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

The current Railway PSA prototypes prove the capability but should eventually be consolidated into a parameterised, source-controlled adapter rather than hardcoded one-off services.

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

This architecture is approved and recorded now so it is not forgotten.

Implementation remains deferred until Brand Redesign is live and the Phase 2 stability threshold explicitly reopens recognition/Seller Hub work. The only exception is a bug/security fix required for already-supported graded inventory.
