# Magic R2 signed manifest divergence — read-only production diagnosis, 9 Nov 2026

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## Why

The current protected source-only MTGJSON preflight [run 42548078345](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42548078345) stopped safely with `Unapproved real R2 source partition`. Its original immutable contract expects 153,662 English MTGJSON printing/finish records with the exact approved manifest SHA256 and maximum 110,000,000 raw source bytes / 512 parts. This generic refusal could represent a changed manifest digest, count, bytes, part count or provider scope. None is permission to overwrite the approved version.

## What / connections

Modify the *existing* signed, OIDC-protected GitHub R2-only preflight to first fetch and schema-validate the **manifest alone** through the exact authorised Railway FastAPI endpoint. It recalculates the hash of its actual manifest bytes and reports only verified counts, limits, and booleans for approved scope/source SHA. If anything differs it fails before downloading every source part. If original manifest still matches, continue the existing per-part R2 bytes/SHA proof; no guard is removed.

No D1 client, token, database, rows written or schema. No Supabase, Shopify, n8n, Market Value, price or owner/settlement data altered. Protected GitHub Actions report remains FAILURE when a newer manifest is detected. This is a diagnostic, not authorisation of a new source generation.

## Failure points

Unauthorized workflow/incorrect OIDC issuer, source redirect, 401/403, altered manifest, malformed JSON, bad byte hash, scope change, unexpected count, oversized source, too many parts or changed source revision all fail closed. Only temporary 404/503 while the Railway release starts retains its existing bounded retry behavior. Outputs never contain card identities, source part URLs, tokens, price or customer data.

## Tests / rollout / rollback

Synthetic fixtures verify fixed-source success; changed hash remains blocked; source row count, byte limit and part limit produce aggregate-only diagnostic; corrupt part and unauthorized issuer still block. CI backend/source RLS and existing approved old-game regressions must pass before merging. Protected main-branch preflight then identifies the *actual* current manifest divergence; human review is required before relaxing the exact source identity, and any accepted new generation must be immutable with full checksums.

Revert this code if the diagnostic causes an unexpected failure. It makes no data mutation and has no production API routing change. Source datasets are still private R2 and Supabase remains operations source of truth; **Supabase exit NO-GO**.
