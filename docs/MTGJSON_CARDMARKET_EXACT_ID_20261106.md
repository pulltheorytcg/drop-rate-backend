# MTGJSON exact Cardmarket cross-reference, 6 November 2026

**Source-only identity improvement; not a live price import.**

## What, why and connection

Preserve MTGJSON's literal `identifiers.mcmId` as the R2 catalogue `details.cardmarket_product_id` for eligible English physical Magic printings. The canonical `mtgjson:<uuid>:<finish>` remains unchanged. This allows the existing read-only Cardmarket daily guide pilot (#919) to join exact provider product IDs instead of guessing names across ~153,662 MTG catalogue references.

Source data is fetched by the existing MTGJSON checksum-verified bounded streaming importer; the field is whitelisted by the R2 codec. It is NOT a Market Value, Cardmarket licence, sold-price comparison, physical inventory value, certified language/condition, or permission to change Store Prices.

## Failure modes and defences

- Missing, negative, zero, invalid, duplicate-looking or noncanonical external IDs produce **no** cross-reference on that row, never an inferred ID.
- Cardmarket IDs reused across distinct MTGJSON printings must be quarantined by the price-join adapter. IDs alone do not assert set, name, finish, language or edition correctness.
- Exact price series depends on the original finish; no foil/regular fallback, grading or visual-media substitutions.
- All payloads retain source attribution and version; release switching still passes the existing immutable R2 verification and admin-only publication checks.
- Database usage remains behind the existing capacity guard; no postgreSQL price/history/ownership columns change.

## Testing and rollout

`PYTHONPATH=backend pytest -q tests/test_r2_first_mtgjson.py tests/test_r2_first_catalogue.py`

Check canonical identity, optional ID validation, byte bound parity, R2 manifest hash/restore, no private content/price leakage and invalid ID quarantine. After CI, compare this v2 loader against a bounded real upstream set on an isolated runner and verify live partition size before authorising a full R2 metadata republish. **This PR does not activate a price refresh or publish a monetary amount.** Later source-grade Cardmarket references need separate full set/finish crosswalk testing, evidence classification and commercial use review.

## Full-catalogue read-only join bridge

`backend/app/mtg_cardmarket_r2_bridge.py` converts the existing *verified* R2 Magic partition into the exactly typed MTGJSON identity format used by the already tested public Cardmarket pilot (#919). It pages the R2 SQLite source snapshot in verified batches, never queries the 430 MB PostgreSQL database, and returns only original UUID+set+name+finish+source ID. Any conflicting same-UUID printings, duplicate finish or divergent source ID are quarantined, and any missing Cardmarket ID is not filled by guessing.

`cards_from_snapshot(snapshot)` and `cards_from_verified_r2(rows)` are explicitly non-publishing: they cannot compute or write market-value amounts. An eventual price generator will feed their output into the published daily-source corroboration selector, then require independent evidence and a separately reviewed R2 sidecar and rollback plan before publishing any `Market Value`. This adapter supports the entire R2 Magic partition, not only the 771-card Foundations sample.
