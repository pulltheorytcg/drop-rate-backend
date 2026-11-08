## 7 November 2026 — Collection media batch isolation (not deployed)

- Fix shared Collection mapping reusing the last asset’s certificate eligibility for unrelated items. Re-evaluate against each selected item/asset; preserve actual slab priority, private reference labels and SQL owner/rights guards.
- Reproduced four grader failures before repair; 126 targeted tests pass afterwards. No UI, image bytes, production records, pricing or marketplace changes. CI and live/device acceptance pending.
- See [regression evidence, scope and next five actions](docs/COLLECTION_MEDIA_BATCH_ISOLATION_20261107.md).


These original implementation notes are retained separately to avoid shared build-log merge conflicts. Current CI/deployment evidence must be checked independently.
