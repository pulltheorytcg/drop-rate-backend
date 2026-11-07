# Immediate prices across search, sets and inventory

The priority is to display available market evidence with the first card response,
independent of account or ownership. This release repairs delivery and matching;
it does not claim that every catalogue printing now has a source price.

## Confirmed faults and repairs

- Founder inventory already received shared prices, but its table discarded them
  for dashes and requested the same data again. The table now renders immediately
  from the authorized inventory payload. The visual grid also uses the shared
  formatter, including labelled guides and dated historical values.
- Some imported canonical cards had eligible shared market evidence while their
  equivalent provider checklist cards showed no price. Search and set browsing
  now reuse that evidence through a read-only, exact-identity resolver. Prices
  arrive in the product response. The lookup does not create an ownership,
  intake, provider mapping, condition or financial record.
- The provider spells some rarities `SuperRare`/`SecretRare`; imports use
  `SR`/`SEC`. These explicit spelling aliases are normalized in the existing
  matcher. Special/parallel rarity names remain distinct, and all existing
  source, language, finish, age and valuation eligibility checks remain.
- Value sorting includes these display references before pagination. Normal
  searches enrich only their visible missing-price page. Current catalogue
  prices retain precedence; background requests cannot erase a shared fallback.
- Complete printed-number searches now use the existing reference number index
  before joining the catalogue. Spaced/compact identifiers, legacy null keys
  and Masters parallel suffixes retain their existing matching semantics.

## Production-data evidence

Read-only production data captured on 15 October at approximately 13:37 UTC was
replayed through the actual resolver: 462 canonical card records, 1,209 bounded
reference candidates and 372 eligible shared snapshots. The live catalogue SQL
comparison identifies **27 additional blank displays**: **24 provider reference
entries** and **3 canonical entries**. These are display recoveries from existing
evidence, not 27 new prices or additional inventory copies.

The English base Capone"Gang"Bege OP11-101 reference now receives the same
**£1.32 near-mint reference** as inventory. Its alternate art and Japanese
references do not inherit it. The canonical Moltres, Vileplume and Suicune entries
receive the same labelled all-finish guide ranges already available in inventory.
The inventory coverage itself is unchanged by this pass: 340/614 current values
or labelled comparisons, including 333 eligible current physical valuations.

Two read-only production EXPLAIN ANALYZE samples for the same OP11-101 search
returned the same five rows. Database execution fell from **3,036 ms to 14 ms**
after using the existing index (planning 173 ms versus 27 ms). This is a database
sample, not a claim about total phone/network load time. The sampled set query
executed in 191 ms. No index or schema was added.

The broader source gap remains. Existing reference caches have 40,443 current
physical card values out of 67,060 physical references; the 24 shared-evidence
display recoveries are separate from those cache counts. Naruto and many exact
Japanese/parallel printings still lack usable source evidence. The eBay feed's
last recorded HTTP 429 and durable retry pause have not been bypassed. No source
subscription, paid trial or new service was activated.

## Verification and release

Local backend suite: 5,903 passed before the final indexed-query adjustment;
the affected catalogue, display, dashboard and scan regression tests also pass
after it. All dashboard JavaScript scenarios pass, including immediate founder
grid/table rendering and first-response search/set values for two accounts.

Release gates include the full backend suite, actual PostgreSQL catalogue
queries/value sorting, restricted-role shared-cache reads for both accounts,
and Chromium/WebKit checks at 320, 390 and 1440 pixels. Those browser checks
compare inventory, search and set prices and assert that no extra price request
is made. Fixtures are synthetic; no production seller login is claimed.

Final CI, merge, Railway deployment and public bundle/readiness verification
are recorded on the release PR. Rollback is a code revert on the existing
service; there is no schema or production-data rollback.
