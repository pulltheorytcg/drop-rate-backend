# Founder Business area — first read-only release

## Purpose
Use Seller Hub's clean visual language for useful founder oversight, rather than copying Founder HQ or creating another stock database. First slice: Overview, Sellers, Stock ownership, and recorded Sales & payouts. Entry is **More → Business** (or the desktop Business shortcut) using an existing verified founder login. The internal legacy `accounts` view/hash and account APIs remain compatible. Existing own-stock tools are linked, not duplicated or reimplemented.

## Access contract
Only the existing three `founder_app_accounts` roster entries may qualify. `/access/me` returns `business_allowed` only for a valid platform-admin membership, FOUNDER owner type, valid founder slot 1–3 and the database's existing verified roster predicate. The predicate checks roster/membership/owner activity and a single active membership on every request. The directory/inventory/activity APIs all call `require_business_founder` before querying business records.

Names, emails, JWT user metadata, owner type alone, a hidden menu, or a generic admin role without roster enrollment do not grant access. No roster, owner, authentication, RLS or grant is changed. No extra membership is added. The separate consignor account stays restricted until a later authorised consolidation.

## What is visible
Active owner accounts can be found by display name, username or account ID. Selecting one filters the existing owner-oversight inventory API. A product can also be searched across active accounts by name, set, card number, Inventory ID, owner name/username or certificate. Each physical row shows its actual owner and Inventory ID, grade/condition/language/variant, recorded location, valuation, store price and Shopify link state. Missing prices are not converted to zero.

Overview shows active accounts, approved-for-sale copies, Draft records and active records awaiting valuation. These are **record counts**, not a reconciled portfolio valuation. Known overlapping imports remain unreconciled and may still appear in these records; they are never silently counted as proven extra stock. No company portfolio value or profit total is invented. Existing value and finance records are only read. Inactive accounts remain outside the existing API/RLS scope and are explicitly not advertised as supported by this first version.

Sales and payout-request history uses the existing read-only account API and labels order status; an order-line price is not presented as settled income. The linked legacy financial tools retain their existing own-owner scope.

## Safety and failure behavior
No mutation endpoint/button exists here. Looking up a seller never impersonates that seller, switches ownership, duplicates a physical card, publishes to Shopify, changes commissions, pays anyone or reconciles the overlapping Collectr file. Login identities and inventories are not merged. Account and item details are rendered as text, not HTML; no private data is saved to browser storage. Stale responses are generation/account-bound. Logout, permission failure and restored browser history clear/recheck private content. Ordinary sellers have no Business entry and cannot read the underlying endpoints directly.

## Tests / verification boundaries
- Pure and mocked HTTP tests: three valid slots, owner/consignor, unregistered admin, invalid slot, absent roster, and deny before a business data query.
- Real PostgreSQL + signed JWT/JWKS HTTP: use the actual committed founder-roster migration and a relevant-schema fixture whose SELECT policies were compared with production. Check all three founders, other sellers, forged claims, invalid/expired tokens, roster revocation, ambiguous memberships, same-card copies across owners, filtered search/pagination, and unchanged data snapshots. This is a local ephemeral issuer, not production Supabase sign-in, and not a replay of the complete production migration chain.
- JSDOM: capability-hidden entry, directory search, escaped names, exact owner selection, pending valuations, stale responses, logout/revocation cleanup and no POST/PATCH/DELETE. APIs mocked.
- Chromium/WebKit: actual shell CSS/Business module at 320–1440px, with mocked responses; overview/directory/stock layouts and logout. Not a physical phone.
- Exact-head CI, actual deployment and live readback must be recorded separately in the PR release comment. No live founder login or production data writes are performed merely to manufacture acceptance proof.

## Deployment and rollback
No database migration, new Railway service, secret, external provider or n8n workflow. Deploy the reviewed existing API/static assets normally. Reverting this application release restores the earlier Accounts UI without touching inventory, ownership, financial or authentication history. Existing Founder HQ remains available; additional editing/admin capabilities and eventual shared login consolidation are separate bounded changes.
