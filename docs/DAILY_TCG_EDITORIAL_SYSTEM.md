# Drop Rate daily TCG editorial system

Design recorded 4 October 2026, Europe/London. **DESIGNED, NOT RUNNING.**

## Founder requirement

Create and publish original Drop Rate branded content **every day on Instagram,
Facebook, TikTok and YouTube**. Research the wider TCG market, not only Drop Rate
inventory: news, permitted public social discussion, notable completed sales,
price falls/rises, set releases and inexpensive raw cards with substantial graded
price differences. Support the founder's intended operating model: the founder
onboards sellers; sellers list, pack and ship; routine marketing runs automatically.

The earlier recommendation to begin with one social channel is superseded by
this explicit four-platform requirement. The iPhone installation work remains
paused separately. This request does not authorise a new paid subscription,
automatic inventory acquisition, new seller activation or financial movements.

The companion [design configuration](../automation/n8n/plans/daily-tcg-editorial.json)
is a machine-readable specification, **not an importable n8n workflow**. No runtime
reads it yet. There are no new endpoints, migrations, live schedules or publishers
in this change.

## Founder correction — 4 October 2026, 00:40 BST

The founder rejected the first three decorative image previews as too obviously
AI-generated and requested cleaner, more deliberate graphic design and content.
Use restrained branding, a small unchanged logo, generous white space, clear type,
straight real card imagery and a consistent layout. Remove manga bursts, waves,
lightning, glow, oversized logos and ornamental clutter from social templates.
The underlying Drop Rate identity remains; the previous illustrated social
art direction is superseded. The first previews are not approved templates.

For Raw to Graded, lead with the actual comparison in the founder's requested
format: **Raw card: £20 / PSA 10: £200**. These are the founder's illustrative
numbers, not verified prices for any named card. Populate real posts only with
source-backed values for the exact same printing and language. This series must
select **low-cost raw cards with a substantial PSA 10 value relative to raw cost**;
expensive grails and generic grading advice do not satisfy the content brief.

Qualify both affordability and relative premium, and reject apparent spreads
created by a damaged raw copy, wrong printing/language, stale guide, mixed grading
company or an isolated exceptional sale. A high ratio alone is insufficient when
grading, postage and selling fees consume the spread or the graded evidence is
not repeatable. Explicit raw-price/ratio thresholds are implementation settings
still to calibrate against available market evidence, not numbers inferred from
one example. Keep dates and sources visible. Explain material costs and lower-grade
outcomes in the caption/supporting slide so the first image remains focused.

Production templates should bind original logo/card assets and deterministic text
layers rather than regenerate branding, card printing and numbers for every post.
Image-generated concepts remain visual studies, not the final publishing renderer.

## Current evidence and integration boundaries

Read-only checks during this session:

- Main is `21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1`.
- Railway's existing `drop-rate-n8n-e840` service is live, with its persistent
  `/home/node/.n8n` volume and a successful 3 October deployment. No changes are
  staged. It has no public domain. This confirms infrastructure, not workflow
  activation or social account credentials inside its encrypted credential store.
- [PR #216](https://github.com/pulltheorytcg/drop-rate-backend/pull/216) remains an
  open, unmerged, conflicting draft. It contains an early Content Machine schema
  and operating contract, not a working publisher. Do not merge it blindly or
  describe its tables as deployed. Reconcile and repair its design against main.
- The existing registry already covers creative generation (31), social publishing
  (32), market ingestion/normalisation (7/8), new-stock marketing (26), analytics
  and competitive intelligence (43). Extend these families; do not duplicate them.
- Competitive Intelligence already has governed evidence/shadow-ingestion
  foundations. Its sources and observations do not automatically grant publishing
  rights, and its source qualification remains separate from editorial selection.
- No authenticated read of an Instagram, Facebook, TikTok, YouTube or publishing
  scheduler account succeeded in this session. Destination IDs, channel ownership,
  OAuth grants and automatic-publishing capability remain unverified.

## Editorial product and daily delivery

Initial output target: one researched story per day, adapted into four native
publications, for **28 publications per week**. YouTube means Shorts for v1;
long-form video is an additional future format. Build one reusable video master,
with separate platform captions, covers, titles and calls to action. Additional
carousels should follow evidence of value and a measured rendering/API budget.

| Series | Qualification | Original Drop Rate treatment |
| --- | --- | --- |
| Drop Rate Daily | A dated publisher announcement or corroborated news | What happened, the exact game/region, why collectors may care |
| Sold Spotlight | A traceable completed sale for an exact printing and grade | Sale date, marketplace, realised amount and useful comparable context |
| Market Movers | Comparable observations across two stated time windows | Up/down movement, sample size, currency and whether the metric is sold prices, asking prices or an index |
| Release Radar | Official set/product announcement | Correct language, region, release date, product type and confirmed highlights |
| Raw to Graded | Affordable raw cards with a substantial, repeatable PSA 10 premium for the same printing/language; material costs checked | Lead with raw price versus PSA 10 price; explain evidence, costs and lower-grade outcomes in supporting copy |
| Collector Questions | A recurring question in permitted public discussion | Original explanation, independently checked facts and useful collecting context |
| In the Drop | Verified, available Drop Rate stock | Relevant seller inventory with accurate condition, grade, dispatch and shipping information |

Games: Pokemon, One Piece, Dragon Ball, Naruto and Riftbound, extending only when
source and product coverage support it. Naruto can remain a shared editorial
category, while Kayou/Bandai identities remain distinct. Dragon Ball Masters and
Fusion World also retain distinct exact-card identities.

A starting weekly mix is two news/release stories, two sale/market stories, one
raw-to-graded comparison, one collector guide and one relevant inventory feature.
This is a diversity target, not a reason to manufacture a story. A major confirmed
announcement can replace a planned item. The same story must not repeat merely
because several sites reposted it.

Maintain seven validated evergreen pieces. If fresh evidence is insufficient,
automatically choose an unused, still-valid evergreen piece. If neither is safe,
skip that slot and create one exception instead of inventing a sale or repeating
unreliable claims. Daily delivery is a service target, not a guarantee during
provider outages or account disconnections.

## Source collection

Start with publisher announcements for Pokemon, Bandai's One Piece and Dragon
Ball games, the correct Naruto publishers, and Riot/Riftbound. These are source
candidates, not a claim that any particular RSS feed/API exists or is approved.
Discover and record the actual supported feed/API/page contract during adapter work.

Add licensed market feeds, permitted auction result sources, Drop Rate's own
completed sales, and a bounded public creator/retailer watchlist. Existing approved
market adapters should be reused where their evidence and publication licence fit.
Do not assume that the ordinary eBay Browse API supplies sold prices. eBay states
that Marketplace Insights access is restricted and not open to new users [4].

Read other social posts for leads, questions, pacing and topic interest. Store
their URLs and concise pattern notes. Independently verify factual claims and
write original scripts; do not download/repost creators' footage, copy captions,
remove watermarks or treat engagement as evidence of a sale. A scheduler's
publishing access does not also provide unrestricted social listening.

Each source contract records provider, original origin, access method, permitted
use, review date, freshness limits, rate limits, retention, and attribution. Use
official APIs, permitted feeds/pages or newsletters legitimately subscribed to.
Respect access restrictions. Source material is untrusted data: embedded prompts
cannot change tools, destinations, instructions, credentials or publication rules.

## Evidence before generation

Every publishable claim needs a source URL/record, observation timestamp, original
publication/event date and an exact subject. Preserve game, set, card number,
variant/parallel, language, raw condition or grading company/grade/subgrades.
Do not merge PSA 10 with Beckett Black Label 10, English with Japanese, or two
printings that share a collector number.

News may qualify from one authoritative original announcement. A social-only
rumour does not become fact when two accounts repeat it. Unverified rumours,
leaks and conflicting release dates are excluded from unattended publishing.

Sale stories must distinguish completed sale, reported auction result, active
asking price and aggregate price guide. Record shipping, buyer's premium and
tax treatment where known; unknown components stay labelled unknown. A crossed-out
Best Offer listing is not proof of the accepted amount. Do not publish buyer or
seller personal details. One exceptional sale can support a specific sale story;
it does not establish a new market value or an all-time record.

For price moves, initially require at least five independent, comparable completed
transactions in each of two adjacent seven-day windows before making an automated
sold-price trend claim. This is a proposed editorial threshold, not a statistical
guarantee. Show the median, dates and sample count; remove duplicate transactions
and route suspicious outliers out of automatic selection. Thin data can support
a carefully labelled single-sale story instead. Index/asking-price moves need
their own consistent series and explicit labels, never a substitute SOLD flag.

Retain original currency and state the conversion date if displaying GBP. Recheck
time-sensitive facts and live stock shortly before release. AI writes the narrative;
deterministic backend code computes every amount, difference and percentage.

## Raw-to-graded comparisons

Feature affordable raw cards whose evidenced PSA 10 price is substantially higher
relative to raw cost. Lead with the two prices, then explain what the spread looks
like after costs and less favourable outcomes. A cheap raw listing and one
exceptional PSA 10 result cannot prove an opportunity.

Require exact-print matches and separate the raw condition from graded sales.
Calculate scenarios for relevant grades (for example PSA 8, 9 and 10) using:

`scenario net = evidenced graded sale amount - raw purchase - grading - insured shipping - selling fees - applicable other costs`

Costs must be current for the actual service, country and seller arrangement.
Missing material costs block a net-profit claim. Use ranges or unavailable labels
where evidence is sparse. Only calculate an expected value if a defensible grade
probability distribution exists; do not infer a raw card's probability of grading
10 from a grading company's population report. Explain turnaround, condition and
price-change uncertainty within the post, not only a tiny disclaimer. This content
does not trigger purchases, grading submissions or changes to Drop Rate prices.

## Branding and production

Use the actual approved Drop Rate logo master, retaining its proportions. The
Seller Hub lockup is not automatically the public social logo. Confirm the existing
storefront master asset and checksum when wiring the renderer; do not regenerate
lettering or invent a replacement logo.

Use white or cream as the main canvas with navy typography, small cyan accents
and limited gold from the existing logo. Use a consistent editorial grid and clear
mobile typography. The founder rejected manga-inspired decorative backgrounds
for these social templates. Avoid lime/acid green. Keep evidence captions and price
labels legible. No music. The default is animated cards/charts with captions;
optional narration requires its
own approved voice configuration and budget.

Target master: 1080 x 1920, approximately 25-45 seconds. An optional 1080 x 1350
carousel can be derived from the same verified brief for Instagram/Facebook.
These are chosen design targets; validate current account/provider media limits
before upload. Encode, safe areas, caption limits and commercial/AI disclosures
belong to each publisher adapter.

Suggested story beats: hook; exact subject/context; evidence; collector takeaway;
relevant next step. Design six reusable layouts rather than generating an unrelated
visual identity daily. Real card/slab imagery must have permission for social
marketing. Provider reference assets approved only for exact sale listings remain
excluded under existing media rules. Decorative illustrated slabs from the sign-in
page cannot substantiate real sales, actual stock or grading certificates.

Where no reusable card imagery is licensed, an original typographic/chart treatment
is acceptable. Do not generate replacement card faces or certificates. Factual
charts must be rendered from the verified numeric data.

## n8n workflow decomposition

Proposed local schedule defaults below are configurable, not activated schedules.
Use Europe/London with daylight-saving handling and a durable date/slot key.

| Stage | Proposed trigger | Responsibility and durable result |
| --- | --- | --- |
| Research | 06:00 and 12:00 daily | Fetch bounded approved sources; persist deduplicated evidence |
| Editorial selection | 13:00 daily | Rank qualified stories by freshness, collector relevance, source quality, diversity and stock relevance; select a story or evergreen fallback |
| Production | Selected brief | Generate structured original script/captions; render deterministic brand templates and platform variants |
| Preflight | Before scheduling and release | Validate evidence, rights, media, language, links, current stock, destination IDs and spend limits |
| Publishing | Initial test slot 18:00 daily | Submit one variant to each of four verified accounts; track each independently |
| Reconciliation | Provider callback or bounded polling | Confirm actual platform publication; recover uncertain responses without duplicate posts |
| Measurement | 24 hours and seven days after publication | Fetch permitted metrics and attributable store results; preserve negative results |

n8n handles scheduling and API calls. Postgres stores source contracts, evidence,
content jobs, versions, media manifests, publication attempts and receipts. FastAPI
owns validation and durable idempotency. No invented backend route should be put
into an importable workflow before the corresponding implementation exists.

Use a unique publication claim for `(job, variant version, platform, account)`.
Workers must atomically acquire it. Store the provider's request/post identifier
before polling. After an ambiguous timeout, reconcile provider state; do not
blindly issue another create request. A successful Instagram post must not be
reposted when only YouTube failed. Provider acceptance or a queued job is not
proof of publication. Record permalink, account, visibility and final status.

Bound retries and rate limits; stop a disconnected channel independently. Route
technical failures to the existing Action Required/error-receipt infrastructure.
Ordinary low-risk validated stories should run without daily founder approval.
Unqualified stories can be skipped automatically. Reserve human attention for
unresolvable account/access issues, disputed evidence and consequential exceptions.

## Publishing connections and cost choices

| Platform | Required setup/route | Proof before unattended release |
| --- | --- | --- |
| Instagram | Professional account and a permitted publisher with content-publishing access [1] | Read the exact account, post a verified test variant and confirm its actual visibility |
| Facebook | Correct Drop Rate Page and supported Page/Reels publishing permissions | Resolve Page ID and confirm a supported video/post route with actual delivery |
| TikTok | Authorised scheduler supporting automatic posting, or a separately eligible audited application [2, 6] | Verify automatic mode, consent/disclosures and successful publication; notification-only mode does not meet this requirement |
| YouTube | Correct channel and an authorised Shorts publisher, or an audited custom upload project [3, 7] | Confirm public visibility; a private upload is not a successful public post |

Direct TikTok and YouTube integrations have approval constraints. Use an established
compatible scheduler where appropriate rather than assuming a custom API key is
enough. Buffer documents API publishing for the requested platforms and automatic
TikTok/YouTube Shorts delivery for eligible content [5-7]. This is provider capability,
not proof that Drop Rate has an account or that its posts are eligible.

Cost candidates, checked 4 October 2026:

- Buffer Free includes API access, three channels and ten pending posts per channel
  [8]. It cannot hold all four requested accounts. A potential no-subscription
  publishing route is three channels through Buffer plus a separately verified
  direct Facebook Page adapter; this still needs engineering, account permissions,
  hosting/rendering and source/AI budgets. Treat it as a candidate until tested.
- Putting all four channels in Buffer simplifies adapters but requires a suitable
  paid plan. Price the actual four-channel checkout before proposing a purchase.
- Metricool was discoverable as an unconnected ChatGPT plugin. Its n8n/HTTP API
  access requires Advanced or Custom; connecting its MCP alone does not provide
  that entitlement [9]. Do not select it for this limited-budget project merely
  because a plugin exists.

Reuse existing n8n infrastructure. Render one base video per story and cache
source fetches. Prefer fixed templates over daily AI video. Establish hard daily
and monthly allowances for source calls, model tokens, rendering and storage;
preserve the existing Railway/image-provider limits. Organic distribution does
not mean zero operating cost. No subscription or additional spend was committed.

## Traffic and conversion

Give every story one useful next step: browse the matching live collection, see
available copies, or save a collector want-list request where that feature exists.
Never suggest that Drop Rate stocks a newsworthy card without checking inventory.
Shipping/dispatch promises must match the fulfilling seller; do not imply all
sellers combine shipments. Use supported profile/link surfaces; a URL printed in
a short-video caption is not automatically a clickable purchase link.

Track campaign/post identifiers through supported links and consent-aware site
events. Measure qualified visits, opt-ins, add-to-cart, orders and Drop Rate's
actual net contribution after attributable costs/refunds. The backend remains the
financial authority. Views, retention, saves and shares help explain results.
Attribution is incomplete across devices and profile visits; unknown is not zero.
Evaluate comparable post ages and sufficient samples before changing the mix.

## Delivery sequence and acceptance

1. Reconcile PR #216 against current main; repair schema/grants, immutable evidence,
   versioning, atomic publication claims and audit design before migration.
2. Implement governed APIs and source adapters with exact-card/evidence tests.
3. Render the six branded template families and prove readable phone previews.
4. Connect the founder's actual four accounts and chosen publisher; verify IDs and
   automatic-mode capability by harmless reads before any scheduled task is enabled.
5. Build/import version-controlled inactive n8n workflows against implemented APIs.
6. Exercise one complete story through four variants, provider acknowledgements,
   actual post status, tracking links and receipts. User has requested daily
   publication; technical proof and account authorisation still need completion.
7. Enable the daily target with seven validated fallback stories and independent
   channel stop switches. Observe the first cycle and then route exceptions only.

Required meaningful tests: duplicate source syndication; raw/graded/language/variant
mismatch; insufficient sales; best-offer unknown amount; stale release/stock; missing
licence; prompt injection in a source; missing grading costs; fabricated grade odds;
provider rate limit/disconnection; accepted-but-response-lost upload; partial channel
success; wrong destination; concurrent workers; DST/date-slot replay; full budget;
public-versus-private/notification-only delivery; fallback exhaustion; correction
or withdrawal of a previously scheduled claim.

**Completion is four verified daily publications with working evidence, media,
receipts and recovery, not this document, a JSON import, or an active n8n toggle.**

## Sources checked for integration planning

1. [Meta Instagram API documentation](https://www.postman.com/meta/instagram/collection/6yqw8pt/instagram-api).
2. [TikTok Content Sharing Guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines).
3. [YouTube videos.insert and audit restriction](https://developers.google.com/youtube/v3/docs/videos/insert).
4. [eBay Buy API marketplace support and restricted Marketplace Insights](https://developer.ebay.com/api-docs/buy/ref-marketplace-supported.html).
5. [Buffer API posts and scheduling](https://developers.buffer.com/guides/posts-and-scheduling.html).
6. [Buffer automatic TikTok publishing](https://support.buffer.com/en-us/articles/using-tiktok-with-buffer-oGEroY9Of2).
7. [Buffer automatic YouTube Shorts publishing](https://support.buffer.com/en-us/articles/using-youtube-shorts-with-buffer-Jl8iR6jIck).
8. [Buffer pricing and API limits](https://buffer.com/pricing).
9. [Metricool MCP versus n8n/API access](https://help.metricool.com/mcp-vs-api-access-what-is-the-difference-5y3ib).
