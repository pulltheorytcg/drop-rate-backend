## 7 November 2026 — Fail closed on incomplete reference-review evidence (not deployed)

- Issue #670 audit found SQL three-valued logic could allow a display-only reference through a pending source review when required proof fields were NULL. The media-only exception now requires an explicitly true complete predicate. Financial valuation, identity, ownership, UI and publication paths remain unchanged.
- New disposable PostgreSQL/PGlite regression fails before the fix on missing `verification_basis`, then passes with null/missing/conflicting identity and media evidence, valid media-only review and unresolved market review cases. CI runs this real-SQL harness. This is synthetic local proof, not live coverage recovery.
- 153 affected reference/valuation unit tests pass; no production mutation, migration or deployment. Full CI and review required. Issue #670 remains open for production acceptance and actual eligible-source coverage.


These original implementation notes are retained separately to avoid shared build-log merge conflicts. Current CI/deployment evidence must be checked independently.
