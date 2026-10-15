# Missing inventory market references — 15 October 2026

The mobile layout repair did not fix pricing. A read-only live audit at 11:57 UTC
found **620 inventory copies**: **333** with eligible shared physical-basis
values, **282** unavailable and **5** needing details. The global catalogue had
**40,443 priced physical references of 67,060**; its separate 2,480 digital
records are not resale products. These are different denominators.

## Confirmed display faults

Inventory consulted only `catalogue_market_snapshots`. It never consulted the
newer card-reference caches used by catalogue browsing. Thus an explicitly
selected catalogue printing could show a price in search and none in inventory.
The screenshot's unfinished Capone copies also hid the shared £1.32 near-mint
comparison because their own condition was not recorded. Assigning condition or
copy value automatically would be incorrect.

The repair adds a **display-only `catalogue_reference`** beside the unchanged
physical `reference_value` contract. Exact selected references and uniquely
matched ordinary imports can show fresh, source-dated Cardmarket guides/ranges.
Unknown-condition raw copies can show a labelled near-mint comparison. Slabs,
rejected/review mappings, wrong languages, conflicting printings, expired guides,
US-only quotes and invalid currency conversions cannot supply a current guide.
Regional Japanese guides retain their explicit mixed-region limitation; English
quotes are never a Japanese fallback.

The shared UI formatter is used by seller cards/details and the founder column.
It now retains dated **Last known** evidence when a physical snapshot expires;
that historical amount remains outside current totals and retail recommendations.
No condition, identity, owner, Store Price, valuation snapshot, publishing or
financial record is written by this change.

## Measured replay

Running the actual resolver against the captured live products, cache quotes and
eligible snapshots restores **7 previously blank copy displays**:

- Capone"Gang"Bege: two unfinished copies, **£1.32 · Near-mint reference**.
- Monkey.D.Luffy: one unfinished copy, **£1.44 · Near-mint reference**.
- Heat Rotom, Moltres, Suicune and Vileplume: four fresh catalogue guide ranges.

That is **340/620 copies with a visible current value or labelled comparison**;
only the original **333** remain eligible for the existing current-value totals.
The remaining **280** do not acquire invented prices. The global catalogue price
coverage is unchanged. Replayed values are not a claim of an authenticated live
seller session; release evidence must separately confirm CI and deployed code.

## Remaining source and identity gaps

The 15 October daily catalogue/reference jobs completed. Supabase is writable.
Many Japanese imports have unresolved provider mappings or no eligible quote for
their particular release; the 61 REVIEW mappings originated from unverified media
references and cannot simply be promoted. Existing eBay ingestion last recorded
HTTP 429 on 14 October, with its durable retry pause. No paid provider access or
additional spend has been authorised. This repair does **not** establish all-card
pricing or restore upstream sold-feed capacity.

## Verification and rollback

Full local backend suite: **5,883 passed**. Focused tests cover ranges, source age,
identity collisions, region isolation, conversion validation, account-independent
display and exclusion from financial totals. Restricted-Postgres integration adds
real cache reads through both signed account HTTP routes, ownership isolation,
rejected mappings and immutable state. Browser checks exercise the same formatter
for founder/seller at mobile and desktop sizes, including new reference states and
dated historical values. CI/deployment outcomes are recorded on the release PR.

Rollback is a code revert on the existing Railway service. No schema migration or
production data rollback is needed.
