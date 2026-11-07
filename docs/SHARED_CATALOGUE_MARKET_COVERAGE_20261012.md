# Shared market value and reference coverage — 12 October 2026

## Requirement and audited baseline

Every signed-in account should read one shared GBP market reference for the **same exact printing, language, condition, grade and sealed profile** at the same valuation timestamp. Asking prices, acquisition costs, profit, fees, ownership and physical-copy photographs remain owner-specific. A guarantee to provide a verified exact value where no permitted market evidence exists is not possible.

Read-only production audit: **69,538** card references, **613** physical inventory items and **464** canonical products. **31,537 / 69,538 (45.35%)** have a positive current cached reference or guide, but this includes mixed-language/condition estimates. **38,001** card references have no positive GBP reference/guide in the existing price stores. Therefore exact-sold evidence coverage is even lower.

| Reference card family | Positive guide / card references |
| --- | ---: |
| Pokémon English | 16,524 / 23,770 |
| Pokémon Japanese | 9,449 / 13,006 |
| One Piece English | 2,037 / 4,527 |
| One Piece Japanese | 0 / 4,480 |
| Dragon Ball Super Masters English | 2,797 / 9,002 |
| Dragon Ball Fusion World English | 730 / 4,360 |
| Dragon Ball Fusion World Japanese | 0 / 3,227 |
| Naruto Bandai Legacy (unknown reference language) | 0 / 4,487 |
| Naruto Kayou (unknown reference language) | 0 / 2,679 |

Existing daily REFERENCE_PRICES, CARDMARKET_VALUES, CATALOGUE_VALUES and CATALOGUE_COVERAGE jobs ran on 12 October. 35 previous unmapped provider recognition candidates have reference market data that the scanner did not previously read.

## Narrow implementation and connections

FastAPI now uses the owner-independent canonical catalogue function `tcg.catalogue_reference_value_v2` and, for unmapped provider card candidates, eligible reference quotes from `tcg.reference_market_prices` or `tcg.reference_catalogue_prices`. Exact provider, system, printing, language, set, source, identity-provenance and seven-day freshness checks prevent adjacent artwork, language or variants borrowing prices. A non-condition-specific quote is visibly **Market guide (GBP)**, never presented as a confirmed exact-condition sale or automatically made the seller's retail price.

Authenticated `/api/v1/catalogue-browser/coverage` retains its existing fields and adds a global summary by game/language and CARD/SEALED, with priced versus missing counts. Missing, stale and US-context-only evidence never counts as a GBP price.

Supabase remains authoritative for catalogue prices. FastAPI owns deterministic selection. Founder HQ, Seller Hub and scanner consume the same catalogue reference; n8n cannot calculate prices. No new service, provider, n8n flow, database migration or change to ownership, pricing rule, Shopify or payments.

## Failure points and acceptance

- Missing/licence-restricted data: retain null, report mapping/provider gap, never create £1, £0 or guessed values.
- Ambiguous printing, grade, language or sealed variant: fail closed rather than copying from an adjacent card.
- Expired or provider rate-limited evidence: mark stale, retain historical records, do not silently treat as current.
- Guide estimates: distinguish guide from exact market value, display currency and checked date.
- Two owners with identical exact profile: same market reference independent of their asking prices.
- Provider record without canonical product: expose the eligible global guide without automatically materialising, confirming or publishing it.
- Low confidence/high-value: keep manual identity/publication review.

Tests cover guide/source distinction, unmapped provider candidate, owner-independent breakdown and missing/US-only controls, alongside existing scanner/security/collection tests. Production acceptance still requires two authenticated seller accounts reading the same exact print/grade/language and obtaining the same amount/source/timestamp, as well as readback of unpriced, invalid and stale examples and no owner/financial/Shopify mutations.

**Limitations:** 100% true exact-price coverage requires licensed condition-/printing-specific observations across Pokémon, One Piece, Dragon Ball and Naruto, including Japanese cards and graded variants. Existing feeds do not cover entire JP/Naruto collections. Bulk mixed-language references cannot be silently relabelled as JP exact values. Do not scrape without permission, invent prices or use seller listing prices as the authoritative market benchmark.

**Rollback:** revert this code PR through the existing main → Railway pipeline, with no schema/data rollback.