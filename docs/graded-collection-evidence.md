# Graded collection images and market values

Graded copies previously inherited raw catalogue artwork when their physical
photo was absent or failed to load. Collection images now require an eligible
INVENTORY_ITEM asset belonging to that owner and exact inventory ID, with
capture_context GRADED_SLAB. Any grading company, grade or certificate makes
the copy graded for image selection, including incomplete records. The shared
image endpoint, reference endpoint and browser fallback all enforce this rule.
Raw catalogue artwork remains available to raw items. Missing slab media is
shown as “Slab photo required”; a failed assigned slab is shown as unavailable.
Photos and certificate numbers are never copied between inventory records.

Graded market values require five distinct exact-profile sold comparisons with
the current UK location and sale-price normalization evidence. Legacy cached
search amounts lacking this proof are unavailable until revalidated; they are
not relabelled retail or raw guide prices. The existing v4 price calculation,
identity matching and freshness rules remain in place. Historical snapshots,
ownership, acquisition cost, selling prices and listing state are unchanged.
This may reduce visible graded valuation coverage while older evidence is
rechecked. Raw pricing policy is unchanged by this repair.

Validation includes missing and failed slab images, raw/canonical rejection,
certificate-only records, other-owner isolation, normalized versus legacy sold
evidence, accepted price bases, duplicate sales and unchanged financial fields.
The PostgreSQL integration fixtures exercise real media queries and authenticated
routes; the owner UI tests exercise the actual image loader and failure events.

For a bounded read-only provider check, use `PYTHONPATH=backend python
backend/scripts/check_graded_market_evidence.py <inventory UUID> [second UUID]`
in the configured backend environment. It allows at most two explicit records,
requires the configured platform-admin actor, logs only diagnostic price/count
information, and does not persist prices or change inventory.
