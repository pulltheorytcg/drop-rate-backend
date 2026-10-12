# Scanner video regression repair — 12 October 2026

## User evidence and bounded scope

Founder tested raw Capone Bege OP11-101, clear/blue toploader Luffy OP14-013 and Zoro OP12-020, PSA Mega Charizard X ex #223 (certificate 160349012), ACE Nico Robin OP01-017 (590532), and Japanese OP17 booster. Repeated queue entries are observed; duplicate saved inventory was not established.

Root causes inspected: slab candidate search discarded name/set/language and used bare `223`; that returns SV-P-223 ahead of M2a-223 (223/193). Label-reader literal grades did not match exact picker strings. Catalogue proxy paths existed but scanner thumbnails ignored them. Manual shutter did not respect the already-captured latch. Slab catalogue lookup did not share the image request timeout, and retries could retain old slab evidence. Certificate form controls were smaller than 16px.

## Implemented repair

- Backend filters slab suggestion pages with literal number plus corroborating name/set. Wrong names, conflicting sets and untranslated names without verified aliases do not produce a suggested exact match. The broad browse remains available for deliberate human correction. Slab hints are **untrusted search constraints**, never authority; normal intake remains server-revalidated and Draft. Search is bounded to at most 80 candidates; an empty filtered page does not claim the card is absent from the full catalogue.
- Preserve original label/provider evidence. Normalize only unambiguous grade representations to existing picker values; unsupported qualifiers, impossible grades and unknown graders stay empty. Black Label/Pristine remain distinct. Cross-provider grade/number/name/certificate/language conflicts require review. No inferred certificate-digit correction.
- Missing PSA API configuration yields an explicit **unverified manual-verification** API result with an official link, not a fake verified receipt or a dead-end error. The low-level automated provider still requires its dedicated token; status still exposes configured=false. Nothing provisions a token, paid plan, scraper or provider.
- Existing authenticated catalogue image route used for One Piece/sealed references; direct approved artwork retains its fast path with run-image recovery. No owner photos become shared, no arbitrary proxy hosts or credential forwarding. Missing and failed reference artwork are distinguished; a truly absent image stays absent.
- Manual and automatic captures share the already-captured latch. Manual mode still detects removal; intentional separate physical copies remain possible. Replacement photo targets the same unfinished queue item. Saved/retrying inventory receipts are immutable. Clear old slab fields on retry; reuse existing owner-scoped idempotent save routes.
- Honest progress labels and one bounded deadline for slab reading plus catalogue lookup. Candidate language/set/variant metadata is visible, unknown grader does not default to PSA, certificate input uses 16px without disabling accessibility zoom. Asset versions updated.

## What this does NOT prove or change

No model change, new infrastructure/provider/workflow, pricing recomputation, database migration/data correction, ownership/ledger mutation or Shopify publication. No latency reduction or physical-camera accuracy improvement is claimed from mocked tests. The Charizard reference exists but has Japanese name/set and no artwork in the current source. Without verified cross-language aliases, this patch suppresses the false match rather than inventing a translated identity. PSA automation remains unconfigured. Missing valuation evidence stays unknown. Existing high-value and publication review gates remain; no 95% model-score auto-approval added.

## Verification and rollback

Run Python suite and all existing JavaScript suites in CI, plus new mocked HTTP/DOM regressions: numeric collisions and denominators, wrong set/language/name, unknown grader and qualifiers, incomplete provider response, absent credentials, duplicate shutter, manual removal, immutable save retry, image MIME/session isolation, stale retry data and shared timeout. Keep exact CI/commit/deployment evidence on the PR release comment; this document is not a claim that CI or deployment passed.

Production acceptance still needs the same physical cards/holders on iPhone, glare/blur, intentionally two identical copies, grade/cert corrections and a save/readback under the correct owner. Do not make live test inventory without recording IDs. Revert this repair commit and let the existing Railway main service build it; no schema rollback or inventory restoration is required. Never roll back unrelated later work or overwrite model settings.
