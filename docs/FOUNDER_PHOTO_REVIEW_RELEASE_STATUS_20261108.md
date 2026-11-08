## 7 November 2026 — Founder physical-photo review routing (not deployed)

- Fixed the shared review scope excluding `FOUNDER_UPLOAD`. Active founder/source and consignor/source pairs now enter the same existing admin-only queue and review lookup. Owner/Inventory ID joins, first-party provenance, identity and approval gates remain intact. No UI, schema, RLS, integrations or production data changes.
- Regression reproduced before the fix: `Founder upload vanished from review queue`. Disposable PGlite/API integration passes afterward, including actual founder front/back uploads, seller denial, explicit approval, complete slab resolution, incomplete front-only rejection, revoked admin denial and retained own-photo access. Shopify transport is mocked; this is not production/device proof.
- 89 affected upload/media unit tests pass. Existing CI already runs the extended integration harness. CI and review remain required before merge/deployment. Independent of PRs #991, #992 and #998.


These original implementation notes are retained separately to avoid shared build-log merge conflicts. Current CI/deployment evidence must be checked independently.
