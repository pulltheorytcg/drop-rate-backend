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
