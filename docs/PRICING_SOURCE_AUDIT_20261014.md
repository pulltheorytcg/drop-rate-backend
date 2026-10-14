# Missing-price source audit — 14 October 2026

This pass researched real unpriced catalogue identities and provider access. **Zero new production prices were imported.** A fresh read-only coverage query still returns **40,423 priced references and 26,635 missing physical references (39.72%)**. The previous 745-record recovery remains live; it is not a gain from this research pass.

Of the remaining physical gap, **17,257** records need new source evidence or eligible regional quotes: 13,062 source-access cases, 4,182 exact-quote cases and 13 US-context-only cases. The separate 9,378 mapping cases still need exact printing resolution. Provider catalogue membership does not establish quote availability.

## What was verified

| Source | Evidence from this audit | Decision |
|---|---|---|
| Existing Trawl UK sold feed | Already integrated. The 9 October receipt measured exhaustion of the free 250-credit allowance. The latest provider-failure journal read in this audit records HTTP 429 on 13 October at 09:47 UTC, with a 24-hour pause. This is the latest recorded failure, not a new balance measurement. | Best candidate for a small approved access trial. Actual coverage of the missing catalogue remains unproven. |
| PriceCharting | Public Japanese product pages exist for the missing Gogeta:BR FB09-001, Krieg OP15-001 and Ivysaur Web #001, with distinct alternate/edition pages. | Potential identity/guide coverage. API/CSV redistribution to Seller Hub requires a separate commercial agreement; the $49/month Legendary subscription alone is insufficient. Standard API/CSV provides current values, not historical sale records. |
| Flipzi | Public playground found Japanese Pokémon Web Ivysaur #001, but its RAW price response had empty prices/finishes and its Japanese eBay UK response had empty grades. Name searches found Gogeta FB09-001 printings and Krieg #001; their Japanese quote coverage was not verified. | Do not buy on catalogue size alone. Free access is evaluation-only; paid display rights do not establish exact UK sold evidence. |
| TCGGraph | Existing client available, but no configured production key. Public explorer examples did not verify these missing Japanese/Naruto records. Documentation explicitly distinguishes own-language prices from English/localised twins and describes some language-level fields as asking-price statistics. | No subscription recommended until exact missing-card samples succeed. Never use an English twin as Japanese evidence. |
| Naruto Card Game Archive | Its price index reports active US eBay asks, including 1,669 legacy and 759 Kayou cards. The database's Naruto identities also retain unknown language/edition/finish flags. | Not eligible UK sold evidence. Do not convert these asks into GBP market values or count them as recoveries. |
| Other public sites | Scouter has the Japanese Gogeta printings, but blends asks, guides and sold inputs. The inspected Limitless Japanese Krieg page links to an English Cardmarket product. | Useful leads only. No licensed exact UK quote was established. |

The latest access checks inspected configuration names only; no runtime credentials were exported. No provider subscription, new service, schema, stock publication, inventory price or source matching rule changed.

## Exact sample results

| Existing unpriced identity | External identity found | Remaining blocker |
|---|---|---|
| Bandai Official / Japanese / 584009:FB09-001, _p1, _p2 | PriceCharting Japanese Dual Evolution base, alternate art and super alternate art pages; Flipzi FB09-001 catalogue printings | Commercial permission and eligible regional evidence; independently prove artwork/finish mapping. Suffix order is not proof. |
| Punk Records / Japanese / OP15-001, OP15-001_p1 | PriceCharting Japanese Adventure on Kami's Island base and alternate art pages; Flipzi Krieg #001 | Same language/printing and commercial/regional checks; no English-price substitution. |
| TCGdex / Japanese / web1-001 | PriceCharting Japanese Web Ivysaur #1; Flipzi 01a13a23-43af-7bda-996e-a963247e7e02 | Edition/finish unresolved; Flipzi exact tested quote responses empty. |
| Naruto archive / the-path-to-hokage:n020-sasuke-uchiha | Archive legacy-game identity | Language, edition, finish and recent exact UK sold records unresolved. |
| Naruto archive / kayou-t4-w4:bp-019-hiruzen-sarutobi | Archive BP-019 / T4W4 identity | Do not substitute English/NA Kayou or the newer Naruto game. Language and physical printing remain unresolved. |

Flipzi's number-only searches returned zero, while name searches found catalogue entries. This is a search limitation, not evidence that those cards are absent. Subsequent detail/UK-market requests returned HTTP 403; no Japanese quote conclusion is drawn from those blocked requests. Public playground data was not imported.

## Prepared access trial

[The 100-candidate manifest](PRICING_SOURCE_PILOT_20261014.json) contains real, currently unpriced references, their original source URLs and unresolved identity flags. [The read-only selection query](PRICING_SOURCE_PILOT_20261014.sql) preserves revision-22 coverage rules and spreads candidates across sets using deterministic hash order.

The sample contains 18 each from legacy Naruto, Kayou, Japanese One Piece, Japanese Fusion World and Japanese Pokémon, plus eight English Pokémon exact-quote gaps and two US-context-only gaps. These are discovery targets, not approved matches or a statistically representative forecast. The sample was captured at **2026-10-14 11:28:36 UTC**.

Proposed next access: **Trawl Basic, USD $20/month, 3,000 credits/month, automatically renewing until cancelled**. This is a limited coverage trial, not a claim that this tier can continuously price the whole catalogue. The provider permits use within a customer's product and hard-stops at the plan cap. Its pricing and detailed credit documentation differ on full-detail page charging, so budget conservatively at up to two credits per page and record the returned usage headers.

Trial bounds:

- At most **100 queries, one page each, 200 credits total**, with equivalent searches deduplicated. No automatic retry after 401, 403 or 429.
- Coordinate with the existing hourly inventory worker and its durable provider pause before consuming the shared allowance. Never bypass that pause or let another probe invisibly exhaust the trial allocation.
- Recheck current coverage and identity before querying. Confirm actual printed numbers; some Japanese catalogue numbers are local indexes. Preserve unknown language, edition and finish until independently evidenced.
- Record exact source IDs, sold dates, currency, prices, language, condition, printing and rejection reasons. Reject asks, lots, unrelated games, wrong languages and unsupported grades.
- Discovery writes **zero production prices**. Only a separately verified ingestion change may promote qualifying evidence through existing pricing rules. Five distinct recent exact regional sales remain necessary for sold-based automatic eligibility.
- Report queried, no-result, ambiguous, insufficient-comparable and eligible counts per family, plus actual credit use. Do not forecast all-card recovery from a small convenience sample.

**Execution status: prepared, not run.** The existing sold worker services owned inventory; this manifest does not implement or schedule global catalogue ingestion. Source approval and a source-specific evidence bridge would still be needed for successful new catalogue samples.

Section 0.4 of the attached Phase 2 Operating Manual requires Daiyan's explicit sign-off for commercial dependencies. No new spend was authorized in this request. Complete the low-cost trial before considering any larger subscription or commercial licence.

## Commercial enquiry draft — prepared, not sent

If Japanese guide coverage is pursued with PriceCharting, request: commercial permission to display dated derived guides in Drop Rate Seller Hub; exact Japanese Pokémon, One Piece and Fusion World coverage against the attached sample; reliable product/printing/edition IDs; source-region and currency semantics; available API fields and historical-sale access; caching, attribution, retention/deletion obligations; and the full recurring price. A subscription or a positive public-page match is not approval to redistribute data. No third party was contacted.

## Sources checked on 14 October 2026

- Trawl: [pricing](https://trawl.dev/pricing), [terms](https://trawl.dev/terms), [credit/API documentation](https://trawl.dev/docs).
- PriceCharting: [API usage and commercial permission](https://www.pricecharting.com/api-documentation), [subscription pricing](https://www.pricecharting.com/pricecharting-pro), [Japanese Gogeta base](https://www.pricecharting.com/game/dragon-ball-japanese-fusion-world-dual-evolution/gogeta-br-fb09-001), [Japanese Krieg base](https://www.pricecharting.com/game/one-piece-japanese-adventure-on-kami%27s-island/krieg-op15-001), [Japanese Web Ivysaur](https://www.pricecharting.com/game/pokemon-japanese-web/ivysaur-1).
- Flipzi: [public playground](https://flipzi.io/api/playground/), [licensing](https://flipzi.io/docs/data/guides/caching-and-licensing/), [plans](https://flipzi.io/api/pricing/).
- TCGGraph: [pricing](https://tcggraph.com/pricing), [price semantics](https://tcggraph.com/docs/prices), [explorer](https://tcggraph.com/explorer).
- Other leads: [Naruto asking-price index](https://narutocardgame.gg/prices), [Scouter methodology](https://dbscouter.com/pricing-methodology), [Limitless Japanese Krieg](https://onepiece.limitlesstcg.com/cards/jp/OP15-001).
- Project evidence: [verified live recovery](PRICING_RECOVERY_LIVE_RESULTS_20261014.md), [source-integrity rules](PRICING_SOURCE_INTEGRITY_20261013.md), [existing sold-feed quota history](LIVE_EBAY_MARKET_REFRESH.md).

