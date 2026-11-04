# Catalogue grouping and Topps Heritage release receipt — 4 November 2026

## Verified implementation and deployment

- [PR #896](https://github.com/pulltheorytcg/drop-rate-backend/pull/896), reviewed
  head `fd697b0ae76d8251bc747180c5fa13cfa44428cd`, merged as
  `ccb72621a7a759e841450a3a2bf7fe75df101438`.
- All 12 pull-request workflows succeeded. The R2-first workflow separately
  passed native PostgreSQL 17 publication/RLS checks and the new group-query
  integration job. Local PGlite executed 96 actual group/page/set checks.
- Full local Python suite: 9,997 passed, 25 optional skipped. Full dashboard UI
  suite passed, including selection, page/context retention, reset and stale
  response tests. Railway pre-deploy repeated the Python suite successfully.
- `drop-rate-api-live` code deployment
  `18615e6d-ab33-421a-8477-a73e8ccce8e9` reached SUCCESS for the merge commit.
- `/health/ready` returned HTTP 200 with `database: connected`; `/owner`
  referenced the new `groups-20261104` assets. Public JS/CSS returned HTTP 200
  and exactly matched the merged files:
  - JS SHA-256: `dc308c8bd422ebfc75dfcb8ef46cfcaf363713e35ecda499babeb894e4d275ce`
  - CSS SHA-256: `fda965ec7b1aff850275d52e9cd8ddbfbd4d3c88cb97bd7ab55a06059f7a223f`
- An anonymous grouped catalogue GET returned HTTP 401. No authentication
  bypass, owner impersonation, intake, save, inventory or publication test write
  was used as app verification.

## Additive source activation and publication

The only runtime variable changed was `TCG_R2_FIRST_IMPORT_SOURCES`, retaining
the established and freshly logged five providers and appending Heritage:

```text
ygoprodeck,lorcast,cardcollectorcapital,reviewed_figures,mtgjson,cardcollectorcapital_heritage
```

The configured reader flag, maintenance actor, credentials and all other
variables were left unchanged. Preflight readback found five total partitions,
119,677,864 active raw bytes, no staged Railway changes and the checked code live.
The existing 12-partition / 256,000,000-byte safety limits were not changed.

Activation deployment `43c924fc-8b1d-4bf7-844e-ed285ee9b1ee` reached SUCCESS for
the same merge commit. At **12:47:32 UTC**, its normal importer recorded:

| Field | Verified result |
| --- | --- |
| Source/system/language | `cardcollectorcapital_heritage` / `SPORTS_CARDS` / English |
| State/generation | `PUBLISHED`, active, generation 1 |
| Records/released records | 100 / 100 |
| Sets | 1 |
| Normalized raw bytes | 104,647 |
| Cold R2 readback/search | Verified before publication |
| Bulk SQL catalogue rows written | 0 |
| Manifest SHA-256 | `94f4c7af3097b439dafc2826d613e78fe2e6569f757ee11078bdda8123484146` |

A separate read-only SQL query confirmed the new pointer and exact counts.
All five prior publication scopes, digests, generations, counts, bytes and
publication timestamps matched their pre-activation snapshot. The existing
Bowman source was not replaced or republished.

A later, separate eBay fix merged as `35a5dc28bf4b223f26a5216ef3a2fa7924eaaa26`,
which includes this catalogue release. Its deployment
`466c0b27-85ce-4c31-a900-339c681e5df3` reached SUCCESS at 12:49:19 UTC;
startup receipts reported all six sources CURRENT, including Heritage with the
same generation, digest and count. No unrelated changes were reverted.

Six active R2-first partitions now contain **204,208 stored source records**,
**202,159 released/search-eligible references**, and **119,782,511 raw bytes**.
These totals are reference records, not physical inventory, unique owned cards,
artwork or valued products. Existing SQL reference tables remained at 69,697
cards / 1,472 sets. No destructive cleanup or bulk SQL catalogue import occurred.

## Honest coverage boundary

- Comics: visible Marvel, DC, Indie and Other filters; Indie uses only reviewed
  Image, Dark Horse and IDW publisher facts. Unknown publishers remain Other.
- Manga: visible Shōnen, Shōjo, Seinen, Josei, Kodomo and Unclassified filters.
  Current reviewed exact-series rules classify **53 of 805** structured manga
  references: 42 Shōnen, five Shōjo and six Seinen. **752 remain Unclassified**.
  Josei and Kodomo currently have no matching catalogue records. This is the
  initial factual classification, not a completed demographic backfill.
- Sports: 100 new Topps Heritage references plus the unchanged 1,722 selected
  Bowman references. Four pre-existing canonical Topps references remain
  separate. The Panini filter exists but there is no verified Panini catalogue
  in this rollout. Selected checklists do not imply full manufacturer coverage.
- Figures: the existing four individually reviewed Funko Pop references and
  two canonical Good Smile Nendoroid references are grouped. No full Funko or
  figurine feed, new figure artwork or new figure prices were imported here.
- Riftbound remains disabled pending Drop Rate-specific Riot permission/key.
  Unapproved consumer-site extraction, mirrors and paid feeds were not enabled.
- Missing artwork and prices remain unavailable. Metadata does not approve a
  physical card's parallel/language, ownership, condition, grade or authenticity.

## Acceptance still required

Health, asset hashes and a publication receipt do **not** prove the current
signed-in reader cache or device UI. Using an ordinary authenticated account:

1. Open the four category groups, check the correct subset and empty states,
   and retain search/saved/owned refinements across pagination.
2. Browse the `cardcollectorcapital_heritage` / `2026-topps-heritage` TOPPS set:
   pages of 80 then 20 distinct references, correct next-page flags and set count
   100. Check source attribution, the #360 note and multi-player identities.
3. Confirm missing images/values stay unavailable and original saved keys work.
4. Complete real-device visual acceptance. The optional offline browser script
   was authored and syntax-checked, but Chromium installation failed; visual
   execution or screenshots are not claimed.

No app credentials were extracted and no private bucket was exposed to perform
these checks. Further manga classification and broader licensed sports/figure
coverage are follow-up work, not implied by deploying the navigation controls.
