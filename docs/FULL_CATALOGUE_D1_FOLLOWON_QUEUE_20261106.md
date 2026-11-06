# Full catalogue: following Yu-Gi-Oh! with Sports, Figures and Magic D1 staging

## Purpose and architecture

**6 Nov 2026 — implementation stage, not a completed production migration.** The original R2-first source records are content-addressed, checksum verified and remain the source of truth. This work enables a *single additional private D1 read-model database* to stage the remaining R2-first sources in deterministic order, without financial or storefront changes.

### Exactly authorised sources

1. Sports cards `cardcollectorcapital / SPORTS_CARDS / English` **1,722** source references, pinned SHA256 `025043fb2594a98f18c070ecbdcdfa682b25a3447839ebca1cdfb84d33bdae1f`.
2. Sports heritage `cardcollectorcapital_heritage / SPORTS_CARDS / English` **100** references, SHA256 `94f4c7af3097b439dafc2826d613e78fe2e6569f757ee11078bdda8123484146`.
3. Reviewed figures `reviewed_figures / FIGURES / Not applicable` **4** references, SHA256 `8bafa9e80735482c62dbb201ad26c21fa6c157c941d4e5c6edfc81a09f092d72`.
4. Magic `mtgjson / MAGIC_THE_GATHERING / English` **153,662** references, SHA256 `be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28`. All 308 original R2 parts already passed full source-integrity audit on 6 Nov.

These four sources total **155,488** R2-first *reference records*, and not verified Market Values.

## Security/connectivity

- Railway FastAPI supplies only the fixed source registry via a dedicated `/api/v1/internal/d1-shadow/followon/{source}` route. Short-lived GitHub OIDC must match the exact repo IDs, main branch, workflow `d1-followon-r2-shadow.yml`, signed event, host and audience. Unknown source names cannot select another provider, R2 key or DB.
- The existing maintenance-admin PostgreSQL RLS lookup remains read-only. All R2 object bytes and SHA256/source IDs are checked before any D1 action. The GitHub workflow's D1-scoped API token never reaches Railway.
- The follow-on workflow runs on a trusted main-branch push and **03:49 UTC daily**, independently from Yu-Gi-Oh! at 03:17 UTC. Pull requests run offline tests only, with no cloud credentials.
- Before creating **one** additional D1 database, the importer reads the existing Yu-Gi-Oh! database and requires **45,418 exact source rows and its active immutable pointer**, and requires its last write receipt day to precede the current UTC day.
- Preserve at least one database slot for the future financial/operational ledger. Existing D1 DBs and their tables are inspected; any unexpected table or ambiguous name fails closed. The shared shadow is capped at a conservative **390,000,000 bytes** (500MB D1 Free limit).
- One **8,000-new-reference-row** budget receipt per UTC day in the *entire follow-on D1*, not per source. A crash leaves the receipt intact and requires another day's verified resume; no same-day repeated writes. D1's own account metrics and source-of-truth quota enforcement still apply.
- Each source is independently staged in immutable `shadow_generations` + `shadow_cards`, with exact prefix readback and original source-identity SHA256; a single D1 pointer activates only after the whole source passes parity, and the active source is reverified. No D1 data is automatically served to customers.

## Failures and tests

Wrong printing/variant/language, changed manifest generation, missing or corrupt R2 part, mismatched D1 prefix, duplicate staged rows, unknown database, Free DB capacity, YGO unfinished or YGO completion day, wrong OIDC workflow, account ID mismatch, expired token, D1 API quota failure and unsafe disk-size evidence must all fail closed. Full tests simulate multiple UTC days and sequential source activation, source tampering, repeat run, account saturation and denial of unrelated R2 endpoints. On failure, the old live catalogue and full owner/financial ledger remain unaffected.

This does **not** include the existing legacy owner-free R2 snapshot (**69,697 Pokémon/One Piece/Dragon Ball/Naruto card rows, 1,472 sets, 3,893 sealed products, 2,062 catalogue products including comics/manga and 2,062 profiles**). Its separate source preflight is in `d1-legacy-r2-preflight.yml`; it requires a distinct, typed D1 staging adapter after source parity and shared capacity checks. Nor does this include storage migration of images, real-time pricing observations, auth or order/settlement records.

Cloudflare Free ceilings: https://developers.cloudflare.com/d1/platform/limits/ and https://developers.cloudflare.com/d1/platform/pricing/. No upgrade or deletion has been authorised.
