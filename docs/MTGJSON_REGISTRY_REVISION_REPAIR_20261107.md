# MTGJSON registry revision repair

The production source registry supplied `all-printings-v5-metadata-v1` to a downloader that already requires `all-printings-v5-metadata-v2-mcm-id`. The downloader correctly rejected this descriptor before making a request. Align the registry with the existing reviewed downloader revision; retain its strict descriptor, permission, source URL, credential-free HTTP and checksum checks.

The v2 metadata contains exact Cardmarket product identifiers where supplied. These are identity join inputs, not sold evidence, price values or publication rights. No pricing timestamps, source approvals, UI, database schema, capacity safeguard or marketplace integration changes are included.

## Verification

The new regression calls the actual `fetch_source("mtgjson", ...)` registry entry with a simulated checksummed upstream response. It reproduced `SourcePermissionError` before the correction. It now proves the two fixed upstream requests, verified digest, distinct foil/nonfoil records and retained product identifiers. An additional negative case keeps the old v1 descriptor rejected before network access.

Affected R2-first, D1, Cloudflare, quote-source backup and R2 market tests pass locally. These tests use fixtures/mocks and are not proof of a successful fresh production import. CI and reviewer approval are required before merging. No deployment, import, D1 staging write or cutover was performed for this repair.

## Release verification and rollback

After a separately approved release, inspect the existing bounded importer receipt for a new checked source revision and digest, then reconcile its published source generation and downstream staged generation before activation. A successful metadata import must not be represented as restored Market Value. Never bypass the 400 MB safeguard. If unexpected behaviour appears, revert this isolated registry change through the normal reviewed release process; the strict downloader will again reject v1 before fetching. This is a code rollback procedure, not a claim that data restoration has been rehearsed.

The broader migration remains governed by [the existing R2/D1 architecture decision](CLOUDFLARE_R2_D1_MIGRATION_DECISION_20261106.md). Keep this repair independent of PRs #991, #992 and the native-wrapper draft.
