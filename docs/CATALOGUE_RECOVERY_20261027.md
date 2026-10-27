# Catalogue recovery checkpoint — 27 October 2026

## Card fixes deployed

PR [#752](https://github.com/pulltheorytcg/drop-rate-backend/pull/752) merged as `7f98b9c803daec7bad8a404000f0ed2cac8e6f89`. All **four current-head workflows passed**, including **6,985 backend tests**, dashboard/browser checks and real PostgreSQL artwork/reference persistence checks.

Railway deployment `ad845201-ebaf-4d56-aa9c-1953742c2ea8` is **SUCCESS**. Its normal predeploy suite also passed all **6,985 tests**. Application startup completed; the new runtime logged `GET /health/ready` **200 OK at 12:15:22 UTC**. This is runtime/hosted healthcheck evidence. The web-fetch helper could not access this API host, so a separate external HTTP probe is not claimed.

No Railway configuration, provider quota, daily scheduler revision or one-off operator was changed. The social evidence probe reported SKIPPED under its existing configuration. The original book work remains in draft PR #751 pending recovery of its final local code and data.

## Verified live data

Read directly from Supabase at **12:03–12:04 UTC (UK time)** after the workspace interruption. All three production run receipts remain COMPLETE. These changes are already committed; they do not depend on the pending code release.

| Measure | Verified state |
| --- | ---: |
| Physical card references | 67,065 |
| Supported values or labelled guides | 43,135 / 67,065 — **64.32%** |
| Basic identity, artwork URL and supported value/guide on the same card | 38,919 / 67,065 — **58.03%** |
| Physical card artwork URLs | 60,283 / 67,065 — **89.89%** |
| Missing physical card artwork URLs | 6,782 |
| Additional priced references required for the user's 90% goal | 17,224 |
| Comic editions | **785**, previously 37 |
| Manga editions | **805**, previously 58 |
| Total comic/manga editions | **1,590**, previously 95 |
| Book editions with any positive shared market snapshot | **0** |
| Book profile identities marked VERIFIED | **0** |
| Inventory rows | **616** |
| Database size | **370,625,683 bytes**, writable; guard remains 400,000,000 |

Card coverage reuses production source, identity and seven-day recency joins. The 2,480 digital Pocket references are excluded by exact set-ID/title pairs. This includes explicitly labelled guides, not only condition-specific UK sold comparables. An artwork URL is not a fresh successful fetch of every image. The 58.03% intersection is a basic data-presence measure, not proof that every variant and physical copy is fully verified.

The comic/manga numbers are imported editions, not a percentage of every book ever published. Metadata growth does not supply cover rights, exact printing verification or market values. Therefore complete identity + artwork + supported value coverage remains **0%** for imported comics and manga.

## Completed production changes

### 92 Japanese Pokémon M1S artwork repairs

Run `7cae446f-9f7b-4c22-ad42-037b53e60275` completed at **11:11:25 UTC**. All 92 reviewed images were fetched, decoded, identified and checked against their pinned SHA-256 digests before the conditional repair. The 56 same-number assignments and 36 explicit shifted-asset assignments are separate reviewed manifests; no blanket number offset is inferred.

The independent 11:11 readback confirmed all 92 provider identities and image/digest pairs, with no blank M1S URL remaining. Inventory remained 616 rows with the same full-row checksum `9ce22ee09a38670d505253da278d1b68`. The repeat receipt read at 12:03 confirms the durable COMPLETE record. See [artwork review](POKEMON_ARTWORK_REVIEW_20261027.md).

### One exact publisher manga cover

Run `0a14df93-ddb0-4120-b5b7-220d4fe9fb34` completed at **11:34:07 UTC**. Boys Over Flowers Volume 22, ISBN 9781421509853, now has the image from its exact [VIZ physical edition page](https://www.viz.com/manga-books/manga/boys-over-flowers-volume-22-0/product/897). The original Open Library source mapping was preserved. This adds a publisher reference cover, not approved R2 media, a verified printing or a price.

### 1,495 comic/manga editions imported

Run `fb47fea2-ff75-4e46-b468-468288d6de17` completed at **11:41:20 UTC**. All 30 batches committed and their independent readbacks matched the reviewed source IDs and normalized digests. The new cohort is 748 comics and 747 manga. No market values or approved media were added.

The source processing covered 56,827,250 records in the complete Open Library September edition dump. The reviewed import snapshot digest is `dc10814daac57325fa766b730c92567b4da5454487e67ef8fe5cdf9802d5def3`; its normalized digest is `d2829f0d62ff504ef30885aed87a20067e3ac1fd218053eb904f3b80104ba54d`. The final review held 117 quality candidates, including 57 individually recorded ISBN holds. Another 909 novel records remain staged for further review; they are not imported.

The import receipt records the same 616-row inventory checksum before and after. New editions remain STRUCTURED; source mappings remain REVIEW with no invented printing number, cover code, image, price or source approval.

## Release recovery and the actual blocker

The coding workspace became unavailable while the final book pipeline changes and review datasets were being copied into GitHub. The last backed-up combined branch is `codex/catalogue-recovery-20261027`, commit `8944b736ded8fb14c2669039e50a1519b64d2d27`, PR [#751](https://github.com/pulltheorytcg/drop-rate-backend/pull/751). Its six workflows passed, including 7,018 backend tests, but those results precede the final local subject-preservation and exact-hold-registry changes.

**Do not merge that older full book pipeline as though it were the final reviewed code.** Restore the workspace, recover its final code/data/evidence and check them against the recorded immutable manifests before the remaining book release. The 1,495 production records are already committed and must not be blindly reimported. The durable database receipt and this readback survive the workspace interruption.

The independently reviewed card-fix subset can be released from the exact backed-up blobs without those book dependencies. It contains:

- Preservation of the 92 reviewed M1S assignments through later provider refreshes and normalization of blank image values.
- Bounded full-number Dragon Ball searches after a structurally valid provider result explicitly reports truncation. Partial/truncated responses never provide prices; all variant competitors and pages still participate in matching.
- Existing request caps, shared quota reserve, daily scheduler revision and source permissions remain unchanged.
- Real PostgreSQL artwork persistence checks and relevant regressions.

The isolated release passed its own current-head CI and normal Railway deployment verification and is **live**, as recorded above. It introduces no new source, one-off price import or new pricing coverage claim. The original book PR remains available as a draft backup.

## Remaining catalogue blockers

1. **Price evidence and exact mappings.** 23,930 physical references still have no eligible current value/guide. The 7,166 Naruto references have no verified permitted feed for the intended use; even full coverage of all other physical references is only 89.31%. At least 460 Naruto references would therefore need coverage even if every other reference were priced.
2. **Artwork and printing evidence.** 6,782 physical card URLs remain missing. Book cover/printing work is separate from the newly imported edition metadata. The last accepted publisher-cover audit was 47 references after the VIZ repair; it is not a claim of 47 newly approved media assets.
3. **Free-source capacity.** Existing approved hourly jobs continue within the established 35-request hourly allocation and shared quota reserve. Refresh/write counts must not be described as newly covered cards.
4. **R2 scope.** The previous verified checkpoint has 401 approved-media mirrors and zero eligible backlog, while broad reference-image mirroring remains source-permission gated. Current prices remain authoritative in Supabase. Adding R2 capacity alone does not create missing values, exact mappings or reproduction rights.
5. **Workspace availability.** The final unuploaded book import safeguards and supporting datasets cannot be released until that execution workspace is recovered. GitHub, Supabase and Railway connections remain available.

TCGCSV remains disabled. The separate earlier Railway one-off preview was declined and has not been retried or bypassed. There is no need for new paid-feed authorization to release the reviewed card fixes.

## Live auction scanner

**Design and research only; no scanner feature code is implemented.** The [proposal](LIVE_AUCTION_SCANNER_PROPOSAL.md) records a compact buyer price panel, exact variant matching, clear source/date/condition labels, stale-item protection and cached price lookups.

Its proposed median-under-2-second and p95-under-4-second timings are targets, not measured performance. Desktop permitted-footage capture is the clearest first experiment; an iPhone screenshot/share or second-screen path and an Android overlay need separate testing. The supplied screenshot does not establish a buyer-side iPhone overlay. Continuous use with Whatnot/eBay still requires a verified permitted integration route.

## Resume

Read the next normal hourly pricing receipts after this release; attempted refreshes are not new covered references. Recover final book files without repeating applied batches. Then continue exact-source mapping, publisher cover review and book valuation evidence. Keep the scanner as a proposal until the user requests implementation.

Machine-readable production checkpoint: [catalogue-recovery-readback-20261027.json](evidence/catalogue-recovery-readback-20261027.json).
