# Cardmarket public source snapshots

The existing pilot now optionally saves the exact public download response bytes
into the existing private R2 exports namespace. Default CI remains read-only.
Run `PYTHONPATH=backend python backend/scripts/pilot_cardmarket_public_daily_mtg.py --archive-r2`
only in the existing backend environment with configured object storage.

All three bounded files are validated and hashed before any upload. Existing
content-addressed storage verifies downloaded bytes after upload, refuses to
overwrite a corrupted object, and supports idempotent retries. A final verified
manifest links source URLs, hashes, retrieval time, source observation timestamps,
ECB conversion provenance, coverage counts and source permission references.
Interrupted uploads cannot publish a Market Value; retrying reuses verified
objects. Rollback is to stop invoking the optional flag, with no deletions needed.
No database writes, API routes, worker schedules, UI, pricing acceptance rules,
Store Prices, ownership or financial records change.

Cardmarket's published public-file announcement explicitly permits use for
websites/apps without account API approval:
https://insight.cardmarket.com/en/Articles/the-state-of-cardmarket-2024
This applies to the public guide/catalogue files, not third-party photographs or
unrestricted use of the account API. MTGJSON's MIT notice is retained in the
snapshot manifest: https://mtgjson.com/license/.

Coverage diagnostics distinguish unique accepted product IDs from finish-specific
candidates. Collector number and source set code remain attached to MTGJSON
printing identities. A reference's English identity does not establish English
language, near-mint condition or any slab grade for an aggregate source guide.
Those guide dimensions are explicitly unspecified/not grade-specific. Numeric
expansion cohorts remain pilot corroboration, not a globally reconciled catalogue
crosswalk. No candidate is automatically promoted to physical Market Value.

Validation: 86 affected offline tests passed, covering ambiguity, exact finish,
source precision, stale exports, corrupted local and remote snapshots, symlinks,
missing source files, zero preflight upload on error, and manifest provenance.
The existing public-source CI also executes a bounded live download pilot.
