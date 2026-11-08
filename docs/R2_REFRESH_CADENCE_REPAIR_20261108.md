# R2 metadata refresh cadence repair

The background worker previously slept 172800 seconds after every pass even
when Lorcast or MTGJSON was configured for a daily refresh. It now sleeps for
the shortest configured source interval: daily for Lorcast/MTGJSON, two days
for YGOPRODeck, weekly for the reviewed sports/figures feeds. An empty or invalid
configuration retains the two-day fallback; invalid sources cannot start a pass.

`import_source` still checks each publication's cooldown before provider access.
Mixed daily/two-day feeds therefore do not download a successfully published
two-day feed early. Failed feeds are attempted on the next scheduled pass, never
in an immediate retry loop. This is not a persistent per-attempt checkpoint or
Retry-After implementation: publication timestamps govern the existing cooldown.
An unchanged source still retains its original publication timestamp.

The 30-second database-lock contention retry remains limited to the exact
ALREADY_RUNNING sentinel, which means no provider request occurred. Cancellation
propagates. Failures retain the normal configured interval, and do not erase a
verified publication or prevent independent sources from being processed.

No UI, source approval, data schema, pricing TTL, market-value algorithm, database
capacity safeguard, inventory or financial record is changed. In particular,
metadata refresh does not make historical prices fresh or recover SQL capacity.
The separate MTG descriptor correction in PR #994 is still needed for MTG imports.

## Validation and release

Run the R2 import/source/catalogue/service tests and database capacity guard tests.
The cadence tests use a simulated clock/sleep and mocked provider/database I/O;
they are not live refresh proof. Existing publication tests cover verified R2
readback, compare-and-swap, rollback and permissions using local fixtures.
The normal CI PostgreSQL suite remains required before release.

After review and deployment, inspect `R2_FIRST_IMPORT` logs across a daily interval,
confirm due sources are attempted and younger two-day/weekly publications remain
CURRENT without downloads. A provider refusal must preserve its previous manifest.
Verify published hashes/counts through the existing readback before claiming fresh
catalogue coverage. Rollback is a code revert/redeploy; no data migration is needed.
