# Free pricing-source evaluation — 14 October 2026

The user approved free testing only. **No subscription, paid trial, account or API key was created. No production prices or source rules changed.** The latest verified catalogue position remains the earlier 40,423 priced / 26,635 unpriced physical references; this evaluation is not a new coverage measurement or recovery.

## Public playground results

Used Flipzi's visible, no-signup playground, including its permitted paid-endpoint demonstrations. **Five additional unpriced catalogue identities received UK marketplace checks.** Three also received current-price checks. All eight requests returned HTTP 200.

| Exact catalogue candidate | UK marketplace result | Current-price result |
|---|---|---|
| Japanese Gogeta:BR FB09-001 / Bandai 584009:FB09-001 | Empty grades | Not tested in this follow-up |
| Japanese Krieg OP15-001 | Empty grades | Not tested in this follow-up |
| English Hex Maniac xy7-75a | Empty grades | Positive Cardmarket-attributed current quote and guide fields |
| Japanese Lt. Surge's Jolteon PMCG5-042 | Empty grades | Empty prices and finishes |
| English Team Flare Grunt g1-73a | Empty grades | Positive Cardmarket-attributed current quote, guide fields and a reverse-holo finish entry |

Every marketplace request specified RAW, the candidate language and ebay_uk. The returned filter also stated **finish=standard**; the playground did not expose a finish selector. Empty responses therefore do **not** prove an absence of quotes for every finish, language, grade or provider product. An alternate-art card cannot inherit its base printing's quote, and a returned reverse-holo entry is not independent proof that the target alternate print has that finish.

The two positive current-price responses are **evaluation leads**, not verified GBP values or evidence of five sold transactions. Their top-level quotes use market_priority semantics; each also has separately labelled Cardmarket guide fields. Do not treat all these fields as sales, mix them together, or copy evaluation data into Seller Hub. Source mapping, finish, language, condition, region and permitted production use remain gates.

The earlier Japanese Web Ivysaur test is recorded in [the source audit](PRICING_SOURCE_AUDIT_20261014.md) and is not counted among these five follow-up identities. Naruto is absent from the observed provider game list. No Naruto quote request was sent to a different game.

Japanese-name search for Lt. Surge's Jolteon returned no results; its English alias found the correct Japanese set/#042. Zygarde-EX's autocomplete displayed only eight results and omitted the target #54a; this does not establish catalogue absence. Manual search results and autocomplete can differ in filtering and page length.

The playground remained within its displayed allowance, ending with **one general call and one premium call remaining**. No quota reset, extra account, paid upgrade or automated retry was used.

## Free-account setup and remaining user step

The official [pricing page](https://flipzi.io/api/pricing/) provides a **500-unit/month free API key with no payment card**, for development/evaluation of catalogue and current prices. It excludes sold comps, graded prices and history; those can only be sampled through the limited public playground without a paid plan.

Followed the page's **Get a free API key** link and verified the registration page at https://flipzi.io/account/register?product=data. It requires work email, a new password, name and company, followed by email verification. The browser's authentication guidance requires the user to complete new-account/password creation manually. No fields were entered and no account creation was submitted.

[Registration screen prepared for the user](assets/flipzi-free-signup-20261014.jpg). After the user completes this free signup in the handed-off browser, verify the displayed Free plan and allowance before further tests. Keep any eventual API key out of chat, logs, source control and client code. The 100-candidate manifest remains discovery-only; no full 100-card trial has run.

A separate first-invoice-free SWITCH promotion was visible on the pricing page. It requires a payment card, first-purchase eligibility and identifying an API being switched from, then renews at the chosen plan's normal price. **It was not selected or activated**, since the user authorized the no-cost, no-card evaluation rather than a recurring paid commitment.

## Trawl

The console playground redirected to sign-in; no new account or subscription was created and no additional API calls were made. The earlier production receipt measured the free allowance as exhausted. Trawl's current documentation gives 250 credits/month and resets free accounts on the first of each month UTC; next scheduled reset is **1 November 2026**. The login page is not a fresh account-balance check. No background reminder or retry job was created.

## Receipt

Captured at 2026-10-14T11:48:28.626Z. [Machine-readable outcomes](PRICING_FREE_EVALUATION_20261014.json) record public product IDs, filters and provider request IDs without copying price amounts or credentials. [Official playground](https://flipzi.io/api/playground/), [free-plan details](https://flipzi.io/api/pricing/), [Trawl credits](https://trawl.dev/docs).

