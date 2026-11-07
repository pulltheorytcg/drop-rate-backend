# Reviewed Japanese Black Bolt numbering correction

The live TCGdex API still labels the official SV11B count as 174. Pokémon's
printed cards use the denominator 086, including the secret cards above 086.
The set contains 174 distinct reference identities; that total must not change.

Primary evidence:
- https://www.pokemon-card.com/card-search/details.php/card/47537/regu/XY (001/086)
- https://www.pokemon-card.com/card-search/details.php/card/47911/regu/XY (087/086)
- https://www.pokemon-card.com/card-search/details.php/card/47998 (174/086)
- https://github.com/tcgdex/cards-database/commit/d09f7844f36b6cd69444650260372af490e9dbb7

## Changes and boundaries

The importer has one reviewed exception for Japanese SV11B. It accepts known
upstream metadata values 174 and 86, formats the printed denominator as 086,
and rejects unexpected local IDs, provider IDs or official counts. It retains
the total of 174 and adds the source proof without assigning a physical finish.

The operator SQL is separate from automatic migrations and startup. Deploy
the importer guard first so a later sync cannot restore the known error.
Run `repair_sv11b_preflight.sql`, review its snapshot SHA256, and substitute
that digest plus the verified platform administrator UUID into
`repair_sv11b_numbers.sql`. A privileged operator executes the transaction;
no extra audit-table privileges are granted to the application.

The transaction locks the maintenance scope and exact set/cards, rechecks all
174 IDs and the reviewed snapshot, and updates only card_number, number_key and
the appended collector_number_reference proof. Artwork, existing provenance,
timestamps, finish, rarity and identity are preserved. Full old/new records
are appended to immutable audit events with actor, request and repair run ID.
A changed snapshot, missing identity, audit failure, occupied lock, lack of
administrator authority, or database size at/above 400,000,000 bytes aborts.
An already-correct set is a no-op and creates no duplicate audit or receipt.

Historical prices, physical inventory, ownership, store prices and settlements
are outside this operation. This correction alone does not add prices.

## Scoped price verification

`refresh_pokewallet_pokemon(..., reference_set_id="SV11B")` uses a bound,
case-sensitive exact reference-set filter. The default remains the existing
round-robin behavior. Malformed filters fail before I/O; unknown IDs do not
widen the query. Whole-source-set pagination and duplicate-printing rejection,
free endpoints, quota safeguards and the seven-request ceiling remain intact.

After the guarded correction, run a small dry run using the existing
administrator, maintenance lock, capacity guard and durable job receipt.
Review complete pagination and accepted guide evidence before applying the
same scoped refresh. The source currently exposes 326 rows; multiple source
printings can share one collector fraction, so 174 corrected references must
never be reported as 174 new prices. Guides remain labelled mixed-language
Cardmarket references and are not exact physical-card sold valuations.

## Validation and failure recovery

Focused importer/filter tests cover the reviewed denominator, scope isolation,
unknown IDs, malformed input, unchanged total and unresolved finish.
The disposable PostgreSQL workflow exercises actual SQL, complete audit and
idempotency, metadata/image preservation, stale snapshots, identity failures,
administrator and advisory-lock checks, and a mid-transaction audit failure.
A failed transaction rolls back every update, audit and run receipt.
After a committed repair, use its old/new audit evidence for any separately
reviewed compensating correction; never erase historical audit records.

## Live result — 28 October 2026, 23:32 UTC

PR #776 merged as `89ed3d11e501364e2cede8f26e1d4d04dee478d2`.
All four applicable CI workflows passed, including 8,147 backend tests
(18 skipped), the source-artwork contract and the new real PostgreSQL repair
contract. Railway deployment `99674702-1871-4958-999c-fcd6c3f26c0d` succeeded;
readiness returned HTTP 200 with the database connected.

The reviewed preflight digest was
`20d87065c5ed51b297dc61e76d48ea31b0499658bc683a5b0bf90f4e2a1f74a8`.
Repair run `375b1efc-e66a-4148-a937-f7601048c804` corrected exactly 174
references and appended 174 full old/new audit records. All 174 read back with
the /086 denominator. Existing artwork and metadata were preserved.

Dry-run receipt `ffe7396d-63a1-47cb-891f-77f09a474520` used five free requests,
fully checked 326 cards from 332 search results across four pages, and found
94 unique printings. Eighty fractions had ambiguous source printings; two
otherwise unique cards lacked Cardmarket guides. The accepted set was 92.

Apply receipt `c3d77de0-55b1-435d-a060-6f0bada165a7` repeated the same five-request
scope with zero provider failures and wrote 92 guides. Database readback
confirms 92 positive, current, identity-matching guides, all explicitly marked
as neither sold comparables nor physical-card valuations. Their GBP values
range from £0.13 to £199.12. Historical observations were retained by the
existing catalogue-guide history trigger.

Full coverage changed from **43,362/67,065 (64.66%)** to
**43,454/67,065 (64.79%)**, a net gain of **92**. There are zero asking-price
estimates. The 89% threshold remains 59,688, leaving **16,234** to recover.
The before/after snapshot of all 616 physical inventory records remained
`4e76edca42d35f28dffcacb289e6653a`; ownership, costs, selling prices and statuses
were unchanged by this operation.

## Remaining constraints

The eBay retrieval fix recovered listings, but the three bounded pilots
(30 Browse requests) accepted no estimates. Titles often lacked explicit
language or exact printing evidence; ambiguous parallels remain excluded.
A second ten-query Pokémon sample also encountered legacy promo numbering
and graded listings. Do not relax evidence rules to meet a percentage.

Additional reviewed numbering issues include Legendary Treasures Radiant
Collection fractions and Wizards Black Star Promo numbering. They require
their own exact-scope source proof and audit before correction. Larger gaps
remain in unresolved variants and games/languages without permitted exact
sources. This pass does not meet the 89% target, and its 500/day eBay ceiling
with three-day expiry cannot sustainably fill the remaining gap alone.
