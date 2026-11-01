# Catalogue cold-session and value-sort follow-up — 1 November 2026

## What the first live tests proved

PRs #847 and #848 deployed successfully as `d5336ee2` at 00:17 UTC.
The API readiness endpoint returned HTTP 200, and signed-in catalogue games
returned in 359 ms. A subsequent One Piece `sort=newest` request returned
200 in 908 ms, proving the new static-filter browse path works when warm.

However, the first two Pokémon `sort=newest` requests returned 500 after
roughly 10–11 seconds. The application logged
`CATALOGUE_R2_INDEXED_BROWSE_FALLBACK type=InterfaceError` and then retried
live SQL on the same unusable connection. Supabase PostgreSQL logs independently
recorded FATAL `25P03`, **terminating connection due to idle-in-transaction
timeout**, on `tcg_api` sessions from the running `drop-rate-api` process.
This is a read-only session-lifetime failure, not evidence of lost catalogue
records or incorrectly scoped prices.

The other remaining slowdown is explicit value sorting. The route still sends
`sort=value_desc` to the expensive whole-catalogue live value computation.
Signed-in One Piece, Dragon Ball and comics value-sort requests did return
200, but several took 4–21 seconds. These are not solved by the newest-first
static page fix.

## Changes in this follow-up

1. When a verified R2 catalogue generation loads, its immutable identity
   browse index is built in a background thread outside all account SQL
   transactions. Live releases/date changes remain immutable cache keys.
2. A catalogue product GET now retries at most **once** on a broken database
   interface/connection. It reacquires a fresh owner-authorized, RLS-scoped
   read transaction, never reuses the closed transaction, and does not retry
   invalid SQL, authorization failures or cancellations. R2 lookup likewise
   stops falling back through the *same* broken connection.
3. For dynamic value sorts with an exact game-system restriction, use **all**
   matching shared R2 identities, not a newest-first subset, to perform the
   full owner- and price-scoped sort in PostgreSQL. The R2 transport contains
   no owner or price facts. If the query shape is unsupported, verified mapping
   aliases exist, or more than 60,000 candidates match, retain the original
   SQL route rather than guessing identities.

No RLS, `tcg_api` privilege, database timeout, published catalogue, price,
ownership, fee, media or financial ledger data is changed by this PR.

## Validation gates

- Unit tests: exact filter and both value-sort directions, unavailable DB
  retry exhaustion, unauthorized/non-connection failure, cold R2 warm-up.
- Real PostgreSQL parity: filtered value sort against original live SQL for
  **two owners** and both price directions, with prices/ownership intact.
- GitHub CI and Railway pre-deploy finance/tests green.
- Active Railway deployment status `SUCCESS`, `/health/ready` 200.
- Actual signed-in newest + highest/lowest-value requests (Pokémon, One Piece,
  comics/manga and sealed) without 500s, target first page under 5 seconds.
- Image-load and source-artwork gaps are separate; successful SQL does not
  imply every printing has an eligible image.

Do not call the catalogue fully restored until signed-in mobile tests pass.
