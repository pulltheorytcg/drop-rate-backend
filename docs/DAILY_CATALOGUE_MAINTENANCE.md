# Daily catalogue and Shopify maintenance

The owner requested daily new cards, sets, imagery and prices, plus automatic
Shopify sync when customers add inventory. The existing API runs the jobs; no
Railway service or n8n workflow is added.

## Schedule and scope

`TCG_CATALOGUE_DAILY_REFRESH_ENABLED=true` enables a catch-up pass at startup and
daily passes due at **03:00 Europe/London**, including daylight-saving changes.
The API checks the durable receipts every five minutes. Each source has its own
receipt; a complete source is skipped until the next day. Interrupted/incomplete
sources wait one hour before retrying. Session advisory locks prevent overlap
between replicas/deployments. External calls are outside database transactions.
An explicit importer revision change starts a new attempt, preserving previous
receipts; revision 2 corrects CardTrader's live game-prefixed category labels.

The existing TCGdex, Punk Records, Bandai and Naruto importers upsert reference
sets/cards. One Piece imports now hydrate exact images from full packs. The
additional read-only CardTrader export imports sealed packaging references for
explicitly supported games/categories, including booster boxes, packs, ETBs,
decks, tins and collections. Publisher edition, contents and physical language
still require confirmation; a language option/default is not evidence. Missing
language stays `Unknown`, with a required choice during draft intake. No feed
creates inventory, verifies a canonical identity, approves media or publishes.

Reference sets and packaging artwork appear in Search. Sealed references have
separate keys and storage, cannot appear in Cards Only or graded selection, and
never inherit a loose-card valuation. Unknown-language references do not match
an English/Japanese filter. Known provider release dates remain enforced.

The daily price pass fills/refreshes up to
`TCG_CATALOGUE_PRICE_REFRESH_LIMIT` (default 20,000) due English Pokémon references
through the existing exact-variant TCGdex/Cardmarket adapter. Batches contain 40
keys; the existing six-request bound applies and a pass reuses one historical FX
download. Whole-batch provider failure stops the pass rather than making a storm
of requests. Receipts report checked, priced and failed counts separately; no
quote or exhausted capacity is not a zero valuation.

These are labelled Cardmarket reference values. Physical inventory remains on
the existing eBay UK sold-market v4 worker, which already refreshes supported
valued identities after 24 hours. Its five-sale threshold, sparse-evidence
backoff and exhausted Trawl allowance are unchanged. No subscription or paid
provider upgrade is included. Daily scheduling cannot supply unavailable data.

## Shopify projection

`TCG_SHOPIFY_AUTO_SYNC_ENABLED=true` checks every minute, requiring both the
existing publication and seller-sync switches. It selects at most ten active
owners' APPROVED, FOR_SALE items that are unlinked or have a non-test DRAFT/ERROR
link. Published, sold, personal, draft and inspection stock are not selected.

Each item uses the existing exact Inventory ID/owner/version publication service,
including deterministic handles, media, identity, price, shipping and remote
read-back gates. The current source-of-truth Store Price is used. A reference or
market-value refresh cannot change the seller's asking price. Existing Store
Price changes reconcile through the established non-test, non-pooled, unreserved
price-sync service. Orders continue through existing signed Shopify webhooks.

Failed publication receipts contain IDs, versions and safe status codes. The same
blocked version waits six hours; unfinished/failed runs wait fifteen minutes;
a changed version is eligible immediately. One idle heartbeat per hour is saved.
No test inventory is manufactured in production for acceptance checks.

## Configuration, release and rollback

Both new switches default off. `TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID` must be an
active authorized founder; it is checked again during writes. New operational
receipts have forced RLS and founder-only API access. Sealed references use the
same signed-in read/admin-write boundary as card references. Anonymous and
authenticated Supabase roles receive no table privileges.

Apply `20261009144903_catalogue_daily_maintenance.sql` after the real PostgreSQL
integration passes. The existing price-sync dependency
`20260930124000_shopify_price_reconciliation.sql` must also be present; the same
PostgreSQL job exercises its exact-version finalization and audit. Deploy, then enable the two switches on the existing live
API. Verify source receipts, price counts, sealed rows, signed-in rendering and
Shopify heartbeat. Publication acceptance uses the already-tested exact-item
pipeline; a zero-candidate production pass is not evidence of a new live sale.

Disable the two new switches to stop recurring work. Application rollback leaves
additive reference/journal tables intact. Do not delete historical receipts,
inventory, ownership, observations, Shopify links or financial records.
