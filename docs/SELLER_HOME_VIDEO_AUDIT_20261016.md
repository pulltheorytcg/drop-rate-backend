# Seller Hub video audit — 16 October 2026

## Scope and recording evidence

The founder supplied a **124.93-second**, 512×1112 iPhone Safari recording of the live Drop Rate Seller Hub, approximately 14:50 London time on 16 October. We reviewed the whole clip at 4-second intervals plus full-resolution key frames. The recording is sufficient to verify **displayed states**, not to independently infer source-market prices or whether product images have redistribution rights.

| Approximate recording position | Observed state | Interpretation |
|---|---|---|
| 8–14s | Home: **104** physical items; market **£0.03**, **1 valued / 103 awaiting**, **1 Cardmarket guide estimate**. Automatic retail recommendation **£1**, **1/104 priced**; tiny line says two saved asking prices **£20**. | Two independent aggregates. One 3p estimate is not the whole collection; £1 automatic suggestion is not the existing £20 Store Value. |
| 15–20s | Pipeline **102 Draft / 0 Inspection / 2 Approved / 0 Reserved**. Portfolio leader shows just a 3p Dragon Ball card; weekly movers lack sufficient history. | Incomplete pricing coverage makes leader rankings nonrepresentative. Owner stock exists. |
| 24–76s | Search lists One Piece with mixed-language Cardmarket guide amounts such as £0.04 and many **Price unavailable**, plus publisher-provided SAMPLE-marked official reference images. A product detail sheet has its GBP value and detailed source basis visually jammed together; transient blank artwork. | Search provider references have a separate eligibility/identity requirement. Guide numbers are not condition-adjusted UK sold prices; copyright watermarks should not be stripped. |
| 76–88s | Two similar Dragon Ball category images, one Masters and one Fusion World; official Kayou Naruto sealed packages display verified-product / packaging-photo-pending placeholders with **Price unavailable**. | Two legitimate Dragon Ball systems need clearer disambiguation; 4 Kayou SKUs are correctly indexed without assumed image rights or fabricated prices. |
| 88–124s | Seller inventory shows 104 physical items grouped by exact copy identity, two approved plus drafts, most **No exact market evidence**, some labelled historical references, empty Store Prices, several image unavailable/loading placeholders. | Valid unpriced state isn't £0. Newly imported canonical printings need verified references; image failures require source-specific repair. |

## Independent Supabase readback (not inferred from the video)

Read-only exact-owner audit found:

- **104 total physical items**: 91 One Piece raw singles, 8 Pokémon raw singles, 2 Dragon Ball singles, 3 One Piece sealed packs.
- **102 Draft**, **2 Approved**; the two approved Japanese One Piece sealed packs each have **£10 saved Store Price**. £20 is an actual saved asking-price subtotal of only 2/104 items, not a recommended total for the entire collection.
- **One** eligible active shared market reference: **£0.03** for a Dragon Ball Common, Cardmarket estimate across conditions/languages (automatic minimum retail recommendation £1.00). Other **103 have no eligible current exact-physical reference**, not necessarily no historical guide or no source number.
- Existing personal raw stored value for one One Piece pack is **£8.66**; that value is not a currently eligible shared portfolio quote. Historical, raw cached, source guide, Store Price and verified current snapshot are different categories and must not silently merge.
- **Zero** verified source provider/market mapping records for all 104 canonical cards. Roughly 10 physical copies reference a canonical card with any shared market snapshot (seven distinct canonical identities), but only one currently meets the rules.
- Of **82** distinct Japanese One Piece canonical raw identities, 60 have a reference using the same **card number**; only 16 of those have any priced candidate; **zero priced candidates share the exact literal canonical English name and Japanese source name**. Japanese translation and printing are unresolved; a number-only reference would be a potentially false price. Do not auto-link those 16.
- Global library contains **1,424/4,480** direct positively priced Japanese One Piece source reference cards, while global credible coverage across all games is **40,443/67,060**. These cannot be assumed to apply to every owner's specific printing/condition.
- Supabase Free DB ~**405.5MB**, **50,378** unarchived genuine price observations (~77MB relation), >400MB bulk-source safety pause. The daily verified Drive archive hasn't yet completed a new export/restoration. **No unverified history deletion or forced repricing is authorised.**

## What this bounded UI release does

1. **Market value · partial** when some of an owner's items lack eligible current evidence. Include explicit *valued / active count* and missing count; a small GBP total is not presented as the entire collection's worth.
2. **Saved Store Value** as the main retail card number, calculated **only** from existing persisted owner asking prices (in this recording £20 across 2 copies). Display automatic recommendations independently in secondary text (in this recording £1 for 1 copy). No overwrite of any Store Price; no unpriced card assigned £0, £1 or an arbitrary AI value.
3. Correct **physical inventory items**, not only cards, since the count includes sealed packages.
4. Rename misleading **Top valued cards** to **Currently valued cards**, with an explicit message that missing quotes aren't £0 or fully ranked.
5. In Search, show clear badges for the two genuine **Dragon Ball Super Masters / Fusion World** games even with similar logos. In product details, display the GBP price and detailed guide provenance on separate block lines to prevent jammed source labels.
6. Bump Safari JS/CSS asset versions. No pricing engine/provider/database schema/source ownership/Shopify/settlement changes.

## Why prices are still missing and acceptance plan

The core problem is not solved by visual labels: the 104-card cohort requires exact sourced market references and verified Japanese card name/release/printing translations. Price authority remains PostgreSQL and deterministic FastAPI, not AI. Tracking: [issue #667](https://github.com/pulltheorytcg/drop-rate-backend/issues/667), global coverage #653, safe archive #651, image coverage #657.

Check required results: source identity proof and price coverage per game; no duplicated founder inventory; original Store Prices retained; no cross-account value leak; honest stale-source and 30-day/mixed-region guide labelling; no marked "current" when source evidence has expired. The **400MB** guard must remain active until a complete typed-restore, correct private Drop Rate Google Drive upload/download SHA-256 and atomic history archival allow ordinary bulk pricing again.

**Tests:** owner overview JSDOM covers the exact 104/1/103/£0.03/£1.00/£20 case, no valued items and empty inventory; browser DOM tests check the duplicated-looking Dragon Ball identities and separate detail-source/value elements; baseline PostgreSQL, Safari/Chromium, owner isolation, display, stock and Railway readiness CI must pass before calling deployment complete.
