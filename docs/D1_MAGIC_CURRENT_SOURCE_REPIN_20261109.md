# Magic: The Gathering — current MTGJSON source in inactive D1 follow-on writer

9 November 2026 · Supabase exit https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What and why

Live R2 publication has **153,679** MTGJSON English printing references, up 17 from the previous D1 write-candidate 153,662, with **151,609 released**. Verified active manifest SHA256 is **e3bda5f54affe0055ec64d7ffb943cb5cae23df8108e74f29e250f7ec63e662a**. The protected real-source Magic R2 preflight reported SUCCESS on main abc9d5f45a813544c8498286c74a726f69059ae7 after PR #1040 repinned its read-only source checker. The source is metadata only, not a grant of card art or Market Value data.

This PR repins the existing INACTIVE D1 follow-on Magic source to 153,679 and that manifest SHA, and updates four-source expected totals from **155,488 to 155,505** (Magic 153,679, sports 1,722, sports heritage 100, reviewed figures 4).

## Connections

Signed main-branch GitHub source→ immutable permitted R2 Magic metadata and full part/hash verification → private D1 follow-on database → exact staged prefix / whole projection SHA → isolated D1 generation activation only. Existing order of sources (sports, sports heritage, figures, Magic) and original 8,000/day write receipt remain unchanged. The entire write-capable workflow still requires maintainer-controlled **exact SHA and exact GitHub run ID** variables; no approval variables are set by this PR. No data moves automatically on merge.

## Failure and tests

Source revision, number, scope, immutable digest, release date, provider keys and R2 parts must match; a changed source or tampered existing D1 row fails closed. Tests assert new source SHA/count and the correct four-source total, existing cross-source SHA/rollback/SQL parameters, exact-run approval gate and no public release. Full Python/Postgres, n8n/dashboard and source workflow CI before merge. An older partial D1 generation must not silently be relabelled to current.

## No cutover / rollback

The separate legacy four-game D1 importer can now stage independently of Magic after PR #1041; Magic's own D1 follow-on importer still has a Yu-Gi-Oh sequencing gate to review separately. No production read route, market valuation, owner, financial, Auth, Shopify or payment changes; existing Supabase remains authoritative. Revert source pin if protected source proof/permissions change. Completing D1 shadow source is not Supabase retirement.
