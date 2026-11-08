# Supabase exit tracker — evidence baseline

Live tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

Target: **zero operational Supabase dependence**, using existing Railway/FastAPI, D1, R2, Workers, Shopify and n8n. UI unchanged. This tracker records evidence, not completion percentages. Updated 8 November 2026.

## Dependency and cutover matrix

| Area | Verified evidence / current state | Remaining gate |
|---|---|---|
| Source inventory | Existing register: 148 relations (107 app, 6 private, 27 Auth, 8 Storage); historical audit: 128 functions, 156 triggers, 272 RLS policies | Refresh schema drift; enumerate deployed consumers. Relation count is not total operational dependency count |
| Dependencies eliminated | R2 catalogue/source backups and artwork Worker exist | No complete service exit proven by this audit; total live dependencies and eliminated count remain unverified |
| Operational data | Nine-table snapshot: 1,184 source rows, 469 catalogue links, 6 identity mappings without credentials | Staging only, not authoritative. Latest drift watch reports **94 changed inventory records**, zero added/missing; copied ledger/orders/refunds unchanged |
| Catalogue | Lorcana prior receipt 3,505; latest YGO receipt **24,000 / 45,418** | YGO incomplete; follow-on workflow waiting; legacy **0 / 79,186 relation rows**. Full category parity not achieved |
| Ownership and settlements | Original snapshot hash/ledger parity verified | Current inventory drift, remaining tables, server-side owner isolation, concurrent orders, duplicate webhooks/refunds and full penny reconciliation |
| Authentication | Inactive OIDC verifier exists; six legacy identity mappings | Supabase Auth still live. Hosted replacement, controlled reauthentication, recovery, revocation and independent access tests required |
| Artwork and routes | Existing private artwork Worker release successful; R2 source/data objects exist | Release success does not prove switched application routes. Full byte/mapping/rights parity and route readback required |
| Current pricing | Latest saved production proof: 59,693 market rows, zero unexpired; 87,369 price rows and 69,697 reference rows freshly backed up/restored in R2 | Current eligible D1 projection, atomic generation pointer, refresh jobs and live display proof; no Store Price changes |
| Railway | Latest saved release b6d6fa842dc6199845c46596246db51f66dc024d, ready/database connected | No service proven Supabase-independent; enumerate actual service env-variable names and consumers without secret values |
| n8n and Shopify | Existing integrations retained | Reconcile deployed workflows, signed API consumers, webhook inbox/outbox/replay; never dual financial writers |
| Capacity/cost | D1 account receipt: 7 visible databases, 35,799,040 total bytes, largest 27,422,720 | Account tier/daily rows not measured by receipt. Measure reads/writes, growth, p50/p95 search and financial latency, R2 usage and recovery cost before activation |
| Cutover/rollback | NO-GO for operational and authentication cutover | Complete snapshot + replay, zero unexplained drift, restore drills, concurrency/permissions tests and reviewed reversible plan |

## Exact evidence

- Architecture/inventory/checkpoints/shadow/drift/artwork PRs #922, #942, #944, #946, #948, #958, #968, #978, #980, #981 are merged (GitHub API rechecked today). #979 is eBay first-party photograph safety, not Worker deployment.
- [Operational stage receipt](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42472600872): staging only, no production read switch.
- [Drift watch](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42495600532): `READ_ONLY_OPERATIONAL_D1_SNAPSHOT_STALE`, 94 inventory hashes differ. Guard is functioning; do not suppress failure or overwrite the snapshot to conceal drift.
- [YGO](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42470784492), [follow-on](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42472930142), [legacy](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42484923787), [capacity](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42474400288). Artifacts inspected, not inferred from green checks.
- [Artwork Worker release](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42388563768). Runtime application cutover still needs separate proof.

## Ordered completion work

- [ ] A: Explain 94 changed inventory hashes using restricted source comparison; preserve old generation. Expand consistent snapshots to all applicable registered relations; classify Auth secrets for controlled reauthentication, not bulk copying. Implement validated catch-up/replay with stable event keys and high-water mark.
- [ ] A: Complete existing quota-controlled catalogue imports and reconcile exact keys/hashes. Do not rerun to evade daily budget.
- [ ] B: Switch catalogue/artwork reads only after parity, signed access, latency and rollback tests.
- [ ] C: Publish eligible current pricing projection from immutable permitted evidence; retain source classification and expiry. No manufactured freshness or fixed sold-comparison shortcut.
- [ ] D: Complete reviewed Railway/Cloudflare-hosted identity replacement and recovery; test every founder/consignor boundary independently.
- [ ] E: One operational D1 financial transaction boundary; unique inbox/outbox events, concurrent physical-item reservation, mixed-owner allocation, refunds and exact ledger reconciliation. Freeze/buffer source writes for reversible cutover; never two authoritative writers.
- [ ] F: Switch remaining Railway/n8n/Shopify/background consumers; replay verification.
- [ ] G: Prove zero runtime Supabase calls/secrets/client dependencies across deployed services, not merely absence of string matches.
- [ ] H: Stability period and restoration drills, then explicit approval before irreversible retirement.

## Maintenance and resource policy

Previously approved bounded compaction completed: 51,027,968 bytes reclaimed, unchanged row counts/full-row hashes, final saved database size 379,473,043 bytes, healthy readiness. Temporary lock setting reset. This is stabilisation, **not a dependency eliminated**. 400,000,000-byte safeguard unchanged.

Cloudflare documentation rechecked 8 November: Free D1 500 MB/database, 5 GB/account, 5 million reads/day and 100,000 writes/day; paid 10 GB/database. Per-database throughput depends on query duration. Actual account tier and workload are unverified; no purchase authorised or made. Historical data stays R2. Cost projection requires measured workload, not invented figures.

Sources: https://developers.cloudflare.com/d1/platform/limits/ and https://developers.cloudflare.com/d1/platform/pricing/.

No production cutover, source deletion, ownership/settlement mutation, UI change or plan change performed by this audit. PR #991/#992 and native wrapper #511 remain independent.

## Repeatable dependency inventory

`python tools/supabase_exit_inventory.py` emits tracked file/category/line locations without source values. At baseline main `b6d6fa842dc6199845c46596246db51f66dc024d`: 1,129 lexical candidates across 792 files; 248 runtime/configuration, 105 operations/migration, 344 test and 432 historical/schema pairs. This deliberately broad screen requires manual classification. It cannot detect dynamically configured external services or prove absence of dependencies. Production totals remain unknown until deployment/configuration and network audits finish. New inventory tooling can itself add lexical candidates; compare like-for-like commit scopes.

Local validation: 29 tests passed for inventory, existing relation register and drift guards on Python 3.9. Existing OIDC test collection requires the repository Python 3.12 environment (3.9 lacks dataclass slots); no OIDC pass is claimed locally. CI inventory job uses Python 3.12.

## Drift explanation implementation

The existing read-only drift watch now accepts `--explain-drift`. For changed tables it validates the immutable D1 generation's original JSON hashes against the original source identities and reports only source-schema column names and affected counts. No values or item IDs are emitted. Missing/null, JSON type and serialization-only changes remain distinguished; all original hash differences still block cutover. The protected existing workflow enables this diagnostic; it does not replay changes or create a new snapshot. 33 local inventory/register/drift tests pass, including privacy, corrupt JSON/hash rejection and the integrated read-only path. CI and the protected production diagnostic run remain separate evidence gates.
