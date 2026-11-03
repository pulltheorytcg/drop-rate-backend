# Seller Hub: navy, white, blue actions and weekly movement

## Visual direction

The user rejected the charcoal/orange treatment and requested Drop Rate's usual
navy as the primary colour, mixed with white, blue buttons and restrained orange
accents. This revision uses the storefront's `#071b3f` navy, white summary panels
and pale blue-white artwork mounts. The main action blue is slightly darker than
the storefront accent to maintain readable white button labels.

| Role | Treatment |
| --- | --- |
| Workspace, header and navigation | Navy `#071b3f` |
| Panels and secondary controls | Layered navy `#10264a` and `#19365b` |
| Primary actions | Blue `#1768d4`, white text; 5.29:1 contrast |
| Hovered primary actions | Blue `#1a70e0`, white text; 4.73:1 contrast |
| Featured values | White panel, navy figures, blue-grey supporting copy |
| Product images | Pale `#f4f7fb`, with dark readable placeholder copy |
| Orange | Small labels, selected-navigation markers and accent rules |

Typography keeps the approved self-hosted Inter family. Hero headings use a
stronger 700 weight; a selected phrase uses italic at 550. The homepage preserves
that emphasis after overview data refreshes, including the empty collection
state. Prices, form labels, input values and body copy remain upright. No remote
font service or additional dependency is introduced. Existing layout, logo,
motion preferences and reduced-motion handling are retained.

All four public workspace/authentication entrypoints refresh their stylesheet
versions and use the navy browser theme. The two presentation scripts also have
new cache versions so refreshed pages keep the intended heading treatment.

## Why Weekly Top Movers was empty

The seller insights route still compared per-inventory `pricing_snapshots`
restricted to the legacy `LIVE_EBAY_MARKET_V1` method. Its top-value cards and
Collection had moved to the shared catalogue reference-value path. The movers
panel therefore ignored shared catalogue price history, including Cardmarket
guide observations. The old query had no qualifying comparisons for the active
accounts in the read-only production diagnostic.

The correction must use the same eligible current snapshot selected for the
physical item in Collection, then find a genuinely earlier comparable snapshot.
Matching includes catalogue identity, physical pricing basis, provider/method
and currency. It must preserve owner scope, exclude inactive inventory, avoid
counting duplicate copies as unrelated movers, and distinguish a guide-estimate
change from a verified market-value change. Evidence dates must not be fabricated
or replaced with the time a calculation happened to run.

The panel must distinguish an empty collection, missing current valuations,
insufficient comparable history, unchanged prices and genuine movement. This is
a read-only reporting correction; it must not change asking prices, ownership,
settlements, admission or publication rules.

### Verified production coverage

Read-only production evidence captured **3 November 2026, 22:53:26 UTC**, then
evaluated with the actual collection resolver and new shared history helper:

| Account scope | Active copies | Eligible current copies / profiles | Old comparable profiles | New comparable profiles | Changed / unchanged |
| --- | ---: | ---: | ---: | ---: | ---: |
| Founder collection | 509 | 328 / 297 | 0 | 95 | 52 / 43 |
| Seller review collection | 106 | 7 / 5 | 0 | 0 | 0 / 0 |
| Other active inventory (combined) | 2 | 0 / 0 | 0 | 0 | 0 / 0 |

A profile is one exact physical valuation basis. All 95 comparable founder
profiles were guide estimates, with actual evidence gaps of 6.62–6.81 days.
The earliest baseline was 25 October at 17:48 UTC and the latest current evidence
was 1 November at 13:11 UTC. The owner panel can show its top six real changes.

The seller review collection still has no genuine weekly comparison. Its four
eligible sold-market profiles have evidence dates only on 8/9 October and
1 November at 22:56–22:57 UTC. Repeated calculations created eight snapshots per
profile but did not create additional market observations. It now also has one
eligible guide profile whose nearest baseline is just outside the defined
weekly window (8 days, 2 minutes and 28 seconds): seven currently valued copies,
six copies needing details and 93 copies without an eligible current value.
The corrected UI reports coverage and the waiting state.

The current-value coverage improved during the handoff: the latest Cardmarket
valuation pass completed at 22:39:46 UTC with 244 shared snapshots and zero
provider calls. The 52 genuine weekly changes remained unchanged. These are
account-local measurements; the founder's movements are not shown as another
seller's holdings.

### Provider backoff and scheduled valuation are different steps

The last completed shared sold-market valuation job was **2 November 2026,
03:03 UTC**, with 133 valued products and 133 inserted snapshots; 1,923 catalogue
products lacked exact evidence. Bulk catalogue valuation is scheduled for Monday
03:00 Europe/London. It reads saved evidence without calling the provider.

Read-only ingestion receipts showed **13 HTTP 429 provider failures** in the
previous 14 days. The latest failure was **2 November 2026, 23:38:16 UTC**, with
backoff until **3 November 2026, 23:38:16 UTC**. This was the existing retry time
at inspection, not a promise that the provider would recover. The provider loop
runs hourly, with a 24-hour backoff after HTTP 429. The most recent 133 successful
five-sale updates were on 1 November.

A future week comparison for the four sold-market seller profiles requires
another valid provider observation and a subsequent shared catalogue pass. The
next scheduled Monday slot is 9 November; it is not a delivery date. The fresh
22:54:58 UTC capacity check measured 430,197,907 bytes: the database remains
writable but exceeds the existing 400 MB pause threshold for bulk refreshes.
Provider recovery, qualifying sold inputs and the capacity gate therefore all
matter. The separate catalogue/capacity work remains outside this UI release.

The existing R2 cleanup archives guide-cache `reference_market_history`, not
`catalogue_market_snapshots` or `market_observations`; it does not contain the
absent eBay weekly baseline. No archive was downloaded or restored.

Full comparison rules and regression rationale are recorded in
`docs/weekly-movers-shared-history-20261103.md`.

## Continuation review after the chat handoff

The pending work was recovered intact and applied to the latest main branch,
including the separately released R2 catalogue changes. Collection photo
handoff, comic intake, optional costs, removal and duplicate-save protections
remain in the regression scope.

Review found and corrected a small monetary display edge: an actual one-penny
rise or fall on an expensive item can round to `0.00%`. Founder ranking now uses
the exact integer-pence difference for direction, and both panels display the
correct arrow with `<0.01%`. An unchanged price remains excluded.

The first local full Python run uncovered a missing SOCKS library in the local
test runner and two tests pinned to the previous script cache version. The
runner-only dependency was supplied without changing application dependencies;
all 65 affected runtime cases then passed, and the two cache assertions were
updated to verify the released script version. The final affected Python set
passed 77 tests. The complete GitHub run and Railway release remain separate
verification gates.

## Verification

Actual-source browser previews use synthetic data and intercepted APIs; they are
not screenshots of a live seller's balances. The release is gated on responsive
and contrast checks, focused movement tests, existing UI tests, CI and Railway
health/readback verification. No real stock is created to validate the design.

Backend movement verification completed locally:

```sh
PYTHONPATH=backend python -m pytest -q tests/test_inventory_market_movers.py tests/test_inventory_reference_values.py tests/test_inventory_intelligence.py tests/test_owner_dashboard_insights_channels.py tests/test_owner_portal_api.py
PYTHONPATH=backend:tests python tests/inventory_market_movers_postgres.py
python -m compileall -q backend/app/inventory_market_movers.py backend/app/inventory_intelligence.py backend/app/owner_portal_api.py
git diff --check
```

The focused Python set passed **93 tests**. The disposable PostgreSQL/PGlite
fixture passed with actual shared-market migrations and exact parameter-bound
production SQL under `tcg_api`: 18 incompatible cohort/time cases, guide and sold
movement, rising/falling/unchanged values, mapping/identity/freshness rejection,
owner membership/RLS, grouped quantities, excluded sold/withdrawn items and no
read-time database mutation. Standard backend CI now runs this fixture after
installing the repository's existing pinned PGlite dependency. Live-market CI
also tracks changes to the new helper. Compilation and whitespace checks passed.

## Final responsive review

The recovered browser fixture originally covered mostly empty insight panels.
Populated testing found dark legacy price text on navy and cramped source/date
labels in small mover cards. The premium stylesheet now gives amounts and
movement indicators accessible colours, moves owner values below their metadata
on narrow phones, and stacks founder values when the card itself is narrow.
The existing browser harness now includes populated guide and sold comparisons
with long names and checks their metadata width and visible evidence labels.

All **28 UI regression suites** passed after the final JavaScript corrections.
Final local Chromium coverage passed **110 surfaces** at **320, 390, 768 and
1440 pixels**, with no horizontal overflow, contrast failures or page errors.
An additional **24 populated, waiting and tiny-change states** passed. The focused
UI contract passed **22 owner/founder cases**, including nonzero penny changes
that round below 0.01%, malicious text, grouped quantities and unavailable data.
The committed images use synthetic fixture data, not live seller balances.

The public production sign-in page was reachable during continuation. This
browser was signed out; authenticated live-session navigation has not been
claimed. Owner authorization was separately verified in disposable PostgreSQL,
and the production comparison counts came from the read-only database capture.
