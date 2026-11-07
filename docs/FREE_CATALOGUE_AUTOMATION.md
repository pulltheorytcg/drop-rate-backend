# Free catalogue automation

27 October 2026. The Railway API's existing maintenance worker performs real
imports; the independent ChatGPT watch checks progress and researches sources.
The watch does not itself trigger deployments or duplicate provider requests.

## Running schedule and evidence

| Work | Cadence / limit | Evidence |
| --- | --- | --- |
| PokéWallet missing-price backfill | Each UTC hour: 10 One Piece, 18 Dragon Ball, 7 Pokémon requests; at most 840/day under normal scheduling | `tcg.catalogue_job_runs`, three `POKEWALLET_*` jobs, persisted cursors, requests and writes |
| Official/community reference discovery | Daily after 03:00 Europe/London | `tcg.reference_sync_runs`: TCGdex, Punk Records, official Bandai and Naruto archive feeds |
| TCGCSV Dragon Ball bulk guides — disabled pending source permission | Prepared cadence: once per rolling 24 hours, maximum 100 release groups / 204 requests; 250ms pacing | No production activation; prepared receipts use `tcg.reference_sync_runs.source='tcgcsv_dragon_ball'` and verified R2 evidence |
| Existing broad Cardmarket guide refresh | Weekly, with incomplete batches resumed | `REFERENCE_PRICES` and existing valuation receipts |
| R2 history archival | Existing hourly maintenance check | Verified archive registry; existing archive watch retained |
| Independent catalogue/source watch | Hourly | ChatGPT **Drop Rate Catalogue Watch**, enabled 27 October |

The five-minute maintenance loop checks what is due; it does not request every
source every five minutes. The same database advisory lock and capacity guard
protect all catalogue imports. Hourly price work now precedes daily metadata,
sealed imports and weekly bulk work. Provider failures produce INCOMPLETE
hourly receipts rather than incorrectly recording COMPLETE.

Daily reference receipts now include `new_sets` and up to 30 exact
`new_set_samples` with provider, language, set ID, source URL and release date.
These mean **new to this database**, not necessarily newly published releases.
Upcoming dates remain upcoming; unknown dates remain unknown. The hourly watch
also searches primary publisher announcements for releases not yet in a feed.

## TCGCSV source rules

Sources: <https://tcgcsv.com/docs>, <https://tcgcsv.com/faq>,
<https://tcgcsv.com/tcgplayer/categories>.

**Production rights hold, reviewed 27 October 2026:** TCGCSV permits access to
its exports and says their contents come directly from TCGplayer's API. That
does not establish downstream commercial rights for Drop Rate. TCGplayer's
[API Terms and Conditions](https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions),
under "Use" and "Restricted Activities", restrict obtaining its API data from
third parties, combining pricing sources and commercial/competitive reuse
without written permission. No permission covering this use has been verified.
Keep `TCG_TCGCSV_FREE_ENABLED=false`. Passing technical checks, free access and
successful R2 readback do not clear this hold. Existing approved-source jobs
and the independent scheduling/receipt fixes can continue separately.

The free backend export refreshes daily. Read `last-updated.txt`, skip an
unchanged completed build, use an identifying User-Agent, respect pacing and
never fetch through the customer browser. Current importer endpoints are
restricted to Dragon Ball Masters category 27 and Fusion World category 80.
No subscription, API key or paid endpoint is used.

Before a guide is accepted, require an exact release title and abbreviation,
English publisher reference, printed card number, card name, complete source
product collection, unique product for the number, released/non-presale status,
and product-ID-bound TCGplayer URL. Unpriced alternatives still cause ambiguity.
Do not infer parallel art, foil equivalence, Japanese identity, condition or grade.
Only a positive `marketPrice` with an explicit, unambiguous finish is usable.

Amounts retain their USD original, source observation date, ECB conversion and
exact reference identity. The interface labels these **TCGplayer US guides
converted to GBP**, not UK sold prices. They do not change inventory, ownership,
Store Prices or Shopify. Another provider's positive catalogue guide is preserved.

Before any price write, a minimal factual evidence snapshot is compressed,
uploaded privately to R2 under the existing `exports` category, downloaded by
the storage verifier, and SHA-256 checked. The receipt records key, hash and
size. Source response hashes are included; descriptions and artwork are not.
An upload alone is not verification. A source-build change, failed readback,
ambiguous identity or quota error prevents the affected import from completing.
The worker records RUNNING before its first provider request; restarts, failures
and interruptions wait 24 hours before retrying this daily-only source.

`TCG_TCGCSV_FREE_ENABLED` defaults to false and must remain false until explicit
upstream permission for Drop Rate's intended use is verified and recorded here.
No schema migration or extra Railway service is needed. If permission is later
established, use the existing R2 configuration and maintenance administrator,
then verify committed counts independently from attempted writes.

## Other free sources and limits

| Source | Useful data | Current boundary |
| --- | --- | --- |
| TCGdex | Pokémon checklists, artwork references, provider prices | Existing import; cache bulk requests, do not invent absent artwork |
| Official Bandai checklists | One Piece / Dragon Ball cards and release identities | Existing daily import; checklist metadata alone is not a market quote |
| PokéWallet free API | Current per-card marketplace guides across supported games | Shared allowance: 100/hour and 1,000/day; paid analytics not called |
| TCGCSV | Daily TCGplayer product/price exports | Prepared Dragon Ball integration remains disabled: upstream commercial permission unresolved |
| Open Library monthly dumps | Comic/manga edition metadata and ISBNs | Existing 95-edition catalogue; full monthly-dump automation is **not yet deployed** |
| Grand Comics Database | Comic publication/issue facts | Candidate source; verify export access and attribution before expanding |

Open Library asks bulk consumers to use monthly dumps rather than harvest its
live APIs: <https://openlibrary.org/developers/api> and
<https://openlibrary.org/developers/dumps>. Metadata does not supply market values
or blanket cover-reproduction permission. The old bounded-prefix pilot cannot
be represented as a scalable complete-dump importer.

TCGCSV's current Naruto category 93 is **Naruto Card Game**, not proof of legacy
Bandai or Kayou price coverage. The current narutocardgame.gg price page describes
active eBay asking prices, not sold comparables. Neither is a basis for filling
the 7,166 missing legacy/Kayou values automatically.

## Verification and monitoring

PR #749 was deployed successfully on 27 October. All 6,924 backend tests and all
eight GitHub workflows passed; live readiness returned HTTP 200. TCGCSV remains
disabled, with zero source-tagged price rows. See the [production checkpoint](CATALOGUE_CONTINUATION_20261027.md)
for dated database readback, remaining gaps and the separate one-off preview's
approval outcome.

Before this change, at 27 October 08:52 UTC, coverage was **43,033 / 67,065
physical references (64.17%)**, leaving **17,326** additional supported guides
to reach 90%. This is a baseline, not a promise of completion from automation.
The existing 2,480 digital Pocket references remain excluded.

Tests cover incomplete collections, duplicate/unpriced variants, wrong game or
release, presales, future dates, invalid finishes, source changes, quota failure,
24-hour restart suppression and verified R2 evidence before database writes.
Read-only checks of actual TCGCSV exports against 503 live reference records
found 115 unique Awakened Pulse matches, 121 Blazing Aura matches and six Manga
Booster 01 matches. One Awakened Pulse match lacked a current value and had a
positive source quote; the rest were already covered or excluded as ambiguous.

Only after the source-permission hold is resolved and activation is authorised,
verify the actual source receipt, committed source-tagged row count and
API readiness. Inspect `report.reason` on INCOMPLETE; never claim scheduled
imports added data without database readback. The independent watch alerts on
hourly imports stale for over three hours, daily imports stale for over 30 hours,
repeated failures, capacity blocks and newly verified free source opportunities.
