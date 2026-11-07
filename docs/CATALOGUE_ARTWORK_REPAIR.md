# Catalogue artwork repair — 9 October 2026

## Cause and observed coverage

The One Piece importer read Punk Records' lightweight `cards_by_id.json` index, which has no artwork. The full per-pack records include `img_full_url` for each exact language and printing, including parallel suffixes. The old upsert also erased an existing URL when a sparse source omitted it.

Read-only production inspection found 3,981 missing Japanese One Piece image links across 26 packs. All 26 full provider packs were fetched and validated before release. The baseline contains 68,151 reference rows; the sorted provider/system/language/printing/set/name/number/source identity fingerprint is `e2d1e266e6f7758bd6788d03133fbf3b`.

Signed-in desktop inspection loaded Pokémon and Dragon Ball artwork successfully. It did not reproduce every image failing on iPhone. The old placeholder remained in the accessibility tree even after successful image loading. Some Pokémon references genuinely have no provider artwork: card-detail responses for `30th-c-001` and `30th-c-027` returned no image. Missing source artwork must not be substituted from another printing or language.

The subsequent signed-in One Piece check reproduced an empty English OP16 grid. Its image URLs returned valid PNG files but included `Cross-Origin-Resource-Policy: same-site`, preventing direct embedding on Drop Rate. This separate transport failure affects existing image links and must be repaired alongside the import gap.

## Changes

- Hydrate future One Piece imports from the existing provider's full pack records. Accept only official language-specific HTTPS artwork hosts and exact printing/name matches within the same pack.
- Keep known image URLs and their provenance when a later sparse import has the same identity. A changed name or pack cannot inherit the previous artwork.
- Supply a bounded, admin-only, dry-run-by-default repair script. `--apply` fills only currently empty reference image URLs, leaving identities, existing images, physical inventory and media approvals intact. Each update retains pack source, SHA-256, actor, check time and a reference-sync run ID. Replays cannot overwrite an existing image.
- Hide the loading placeholder after success, report unavailable artwork accurately, load the opened detail image eagerly, and advance the catalogue script cache version in both app shells.
- On a direct image failure, use authenticated same-origin image transport for exact One Piece references. The server resolves the provider/system/language/printing primary key from existing released records; it does not accept a client URL. Reuse the scanner's trusted-host, raster-validation, 2 MB size limit and bounded byte cache. Limit fetches to four, release database transactions before HTTP, retain catalogue access checks and fall back to an existing approved same-product image on failure. Discard stale/account-changed responses, abort work on navigation and revoke browser object URLs on cleanup. Both shells load the updated scanner transport.

This is reference display repair, not verified recognition evidence or approval of customer-facing inventory photos. It has no new provider, recurring job, public write route or schema migration.

## Release and verification

Focused Python tests cover identity, language, parallel, invalid source, future-import behaviour and authenticated exact-reference image delivery. UI checks cover loaded, failed, unavailable and fallback states, bounded fetching and account-change cleanup. A disposable PostgreSQL CI job exercises the actual repair and upsert SQL, including replay protection and provenance retention. The full existing backend/UI gates remain required.

After current-head CI succeeds, run the script once in the existing API deployment environment using the authorised platform-admin actor:

```sh
PYTHONPATH=backend python backend/scripts/repair_reference_artwork.py --actor-user-id 6e8291db-0975-4acf-9ce4-f2f25a87d88d --apply
```

Append it temporarily to the existing Railway pre-deploy chain after all original checks; retain the original checks and timeout. Restore the original configuration after the one execution. Do not install a startup repair hook. Inspect the `REFERENCE_ARTWORK_REPAIR` report, run journal and resulting image coverage; verify reference identity and inventory/media fingerprints, deployment readiness, the delivered script version and signed-in image rendering.

This checkpoint records implementation and preflight evidence, not a claim that the backfill or release already completed. Append release results to the pull request and build log after verification.

## Recovery

Reverting the code restores prior importer/display behaviour. Correct reference URLs can remain in place. Any specific incorrect artwork must be corrected by exact identity and recorded run provenance; do not broadly clear images or delete run history. A failed deployment leaves the previous application active. An interrupted repair can be rerun explicitly because each pack commits separately and existing images are never overwritten.
