# Drop Rate Tier 1 market value refresh — read-only preflight (10 Nov 2026)

**STATE: REQUIRES SOURCE RIGHTS AND NEW EVIDENCE — NO PRICE WRITES AUTHORISED.**

## What was verified
Connected Supabase production `ozrxenrdladkooixutmm`, read-only SQL, 10 Nov 2026. The eligibility query is in `docs/audits/2026-11-10_tier1_pro_sold_dryrun_select.sql`. This is an **evidence and upsert-classification preview**, not an execution of FastAPI's robust-statistics pricing engine, not a Shopify update, and not an approved upsert dry run with verified source rights.

- Tier 1 physical CARD/SEALED copies: **505**.
- All recorded `EBAY/SOLD` observations: **1,083**, of which **168** positive UK GBP observations were within the last 14 days at query time, across 76 canonical identities. All reported `access_method=TRAWL_API` (not official eBay Browse sold data).
- Matching the exact internal catalogue ID, source country GB, language, raw condition or graded company/grade, and price recency: **98** physical copies had any recent sold evidence; **33** had 3+ matching sales; **407** had zero.
- **0** missing positive-value copies had 3+ such sales; **0** stale positive-value copies had 3+ such sales.
- Screening classification: **INSERT candidates 0 / UPDATE candidates 0 / SKIP 505** under the narrow 14-day GBP/variant-like-for-like test. This deliberately prevents inventing values for the unpriced items. Source-rights/terms are not revalidated, and every candidate would require the deterministic backend outlier/liquidity logic before a real financial or display change.
- Earlier production coverage audit #1048 found 234 fresh stored values, seven stale, 264 missing within the same 505-item cohort; values are not proof of sold evidence.
- eBay sold source has 32 recorded failed ingestion runs (latest 10 Nov HTTP 429), so do not brute-force retries or present Browse API active listings as sold evidence.
- Real backup verified via Actions run 42873462449. A database **restore test remains outstanding**, and no R2 backup is included.

## Twenty examples selected for review (public-safe fields only)
Each below is **SKIP_MISSING_SOLD_EVIDENCE**, with zero matching recent sales. These are catalogue labels, **not** owner IDs, acquisition costs, physical inventory identifiers, or permission to change a listing.

| # | Game | Card / product | Number | Language |
|---:|---|---|---|---|
| 1 | One Piece | It's My Student's Farewell. I Want It to Be Proper. | EB04-009 | Japanese |
| 2 | Pokémon | Grimsley's Move | 090/094 | English |
| 3 | Pokémon | Baltoy | 046/083 | Japanese |
| 4 | One Piece | Basil Hawkins | OP07-029 | Japanese |
| 5 | One Piece | Hitokiri Kamazo | EB04-035 | Japanese |
| 6 | Pokémon | Seel | 021/094 | English |
| 7 | One Piece | Kaido | EB04-030 | Japanese |
| 8 | One Piece | Benevolent King of the Waves | OP16-071 | Japanese |
| 9 | One Piece | Ground Death | OP14-096 | Japanese |
| 10 | Pokémon | Darumaka | 015/094 | English |
| 11 | One Piece | Pacifista | EB04-056 | Japanese |
| 12 | One Piece | Eustass Captain Kid (Online Regional 2024 Vol. 2) [Participant] | P-003 | English |
| 13 | Pokémon | Misdreavus | 035/094 | English |
| 14 | One Piece | Cavendish (Reprint) | EB01-012 | English |
| 15 | One Piece | Sengoku | OP16-060 | Japanese |
| 16 | Dragon Ball Super | Trunks, Thwarting the Dark Empire | BT13-131 | English |
| 17 | Pokémon | Krookodile | 066/094 | English |
| 18 | Pokémon | Cresselia | 039/094 | English |
| 19 | Pokémon | Darmanitan | 016/094 | English |
| 20 | Pokémon | Granbull | 038/094 | English |

## Next release gate
1. Validate a commercially permitted fresh source for sold comparables (and Cardmarket/third-party terms for supplementary non-sold context), provenance, condition/grade/finish/printing and robust outliers. Do not use retail/guide prices as Market Value.
2. Run the existing deterministic FastAPI engine in a **bounded non-writing preview** once there are qualifying comparable observations. Return precise INSERT/UPDATE/SKIP action counts, changed-price calculations, 20 identity/variant checks, and source rights receipts.
3. Obtain a typed restore test in an isolated project and explicit separate approval for any production mutation.
4. After authorised writes, verify SQL readback, R2 publication/cache parity, app Market Value and image display, and graded slab image correctness on live mobile and desktop.
