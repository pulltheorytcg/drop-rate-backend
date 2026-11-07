# Market-value coverage backlog: verified source-access and exact-mapping blockers
12 October 2026

## Business requirement
Every owner sees the same canonical GBP reference or the same unpriced reason for the same exact card, printing, language, condition and grade. Store Price, acquisition cost and owner proceeds are separate. This release does not invent GBP values or silently substitute another language, rarity or grade.

## Verified state
- Supabase global library: **69,538 card references**; 31,537 have a current cached positive GBP value or explicitly labelled mixed-language/condition guide (**45.35%**); **38,001** have no eligible current value/guide. Those 31,537 **are not all exact-sold quotations**.
- Sealed references: **3,879**, of which **2,726** have current positive guides and **1,153** do not.
- **14,873** of the missing card references are in categories with no connected/licensed exact GBP source: Japanese One Piece (**4,480**), Japanese Dragon Ball Fusion World (**3,227**), Naruto Bandai Legacy (**4,487**), Naruto Kayou (**2,679**). Naruto catalogue language is `Unknown`, so it requires source identity/language verification as well.
- Other missing cards require exact printing/product mapping or a supported eligible price/quote in their source. Even real market data cannot guarantee a trading history or market value for every print.
- The existing 12 October daily reference job completed with zero declared provider failures, so this is not simply a stalled scheduler. Historical eBay ingestion includes blocked insufficient-exact-sales cases and temporary provider errors, which must not become guessed prices.

## Scope of this release
The existing authenticated catalogue coverage endpoint now includes global `missing_by_reason` ordered by descending affected reference count, `by_status` and per-game `status_counts`. `SOURCE_ACCESS_REQUIRED` separates source-license gaps from fixable provider-ID mappings. Strictly positive fresh GBP quotes count as coverage; zero, stale, US-only or unverified sources cannot count. Every action describes a requirement, not an automated buying decision. It reuses existing scheduled coverage receipts and existing owner-independent read paths. No migration, provider integration, paid subscription, bulk mutation, materialisation, new background service, n8n workflow or Shopify publishing change.

## Source roadmap, subject to commercial permission
1. **Existing Cardmarket daily public downloads**: focus on uniquely matched English Pokémon, One Piece and Dragon Ball product+release+variant identifiers; prevent a parallel/promo/reprint from inheriting a base-card guide. Source publication permission and commercial display rights need review before any expansion beyond the already-operating internal reference process.
2. **CardTrader**: the existing token supports supported identity/marketplace workflows. CardTrader's own terms say broader market-data API access, availability and pricing can be made available **upon request**. Do not repurpose a shopping/checkout endpoint as an unrestricted commercial pricing feed. Contact the provider for permission/terms before full market ingestion.
3. **TCGGraph**: published commercial API covers Pokémon, One Piece and Dragon Ball with granular language/grade pricing, but does **not** list Naruto. It is a separate paid API; do not open an account, incur fees or trigger background calls without account owner consent and a confirmed coverage/licensing pilot. Match on provider printing identity, game, set, variant and language, never card number alone.
4. **Naruto**: obtain a legitimate provider/contract covering both Bandai and Kayou and verified language/printings; otherwise return an honest missing-value state. eBay active listings can be context only; missing exact sold observations cannot silently become confirmed market value.

## Acceptance
- Every account sees identical quote, timestamp, evidence tier and missing reason for identical identity/profile; no owner-dependent cache as primary source.
- Current quote vs mixed-language guide vs US-only vs stale vs unmapped vs source-access required remain distinguishable.
- Non-positive values are not reported as priced; aggregate source-coverage total equals the provider catalogue denominator.
- Wrong language/finish/grade never inherits price, and no API failure overwrites historical observations.
- Run full Python/dashboard CI and actual read-only live coverage query; separate real signed-in account and phone checks from automated test evidence.
- Any new source adapter requires terms/permission, a budget decision, deterministic parsing, versioned migration if necessary, replay tests, idempotency, provenance, timeouts/rate limits and an explicit new PR.
