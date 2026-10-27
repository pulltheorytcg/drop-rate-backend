# Drop Rate live auction buying scanner — proposal

**Status: DESIGN AND RESEARCH ONLY — NOT IMPLEMENTED.**

Prepared 27 October 2026. This document proposes a buyer companion for identifying an item while watching a live auction and consulting Drop Rate's existing, dated price evidence. It does not authorize or implement capture, a browser extension, a native overlay, an auction integration, automated bidding, or changes to production. Any later implementation needs a separately agreed scope and the prerequisites below.

## Recommendation

Develop the concept first around **a desktop Chrome companion on explicitly permitted streams**, with an optional paired phone showing the result. A user-activated tab capture and a small in-page panel offer the clearest technical route to the requested experience. Start validation with Drop Rate's own or otherwise authorized test footage. Do not connect continuous capture to Whatnot or eBay until the relevant platform has confirmed permission for the proposed use.

On iPhone, the practical initial alternative is **share a permitted screenshot to Drop Rate for one-shot identification**, or watch on a laptop/tablet while keeping the buying result open on the phone. These are different experiences from an always-on popup over the Whatnot app. They still require permission to use the underlying content; taking a screenshot is not a workaround for platform terms. Android is the stronger candidate for a later true cross-app floating panel, subject to permissions, platform restrictions and device testing.

The first supported recognition cohort should be a curated set of **raw English Pokémon singles with verified exact identity, accessible artwork and suitable price evidence**. The design accommodates sealed products, slabs, comics and manga, but their valuation readiness is a separate gate. An attractive popup cannot fix a missing or wrong printing match.

## 1. What the supplied image establishes

The supplied `IMG_5034.jpeg` shows a black rounded panel at the top of a Whatnot screen. It names Rapidash and Temporal Forces, includes a small reference image, and presents USD values across NM, LP, MP, HP and DMG columns. Normal, JPN and reverse-holo entries appear as rows, with PalletTrade branding below.

That demonstrates a useful information layout. It **does not establish how the panel was produced**: it could be composed into the seller's broadcast video, added by a broadcast tool, or displayed by a buyer-side tool. A still screenshot cannot prove automatic recognition, latency, the source of the values, or an iPhone system-overlay capability. It also cannot prove that its Rapidash result refers to the item currently being handled. Keeping an old result visible during an item change is a specific failure our design must prevent.

Use the compact hierarchy as inspiration, while creating an original Drop Rate design. Keep language separate from finish: Japanese is a language, whereas normal and reverse holo describe printing/finish distinctions. Never carry one row's price into another identity.

## 2. Platform feasibility and permission boundary

| Surface | Supported technical route to investigate | Material constraint | Proposed role |
| --- | --- | --- | --- |
| Desktop Chrome | User invokes the extension on the selected auction tab; `tabCapture` supplies its stream. A content script can render the result in the page, or an extension panel can sit beside it. | This works inside a browser, not over a phone's native app. Site permission, browser permission and content rights remain separate. Cross-origin/protected video and changed page layouts require actual tests. | First technical pilot, using authorized footage/sites. |
| iPhone/iPad with the iOS 26 support baseline | Legacy ReplayKit broadcasting through a Broadcast Upload Extension and an explicit system broadcast choice is a compatibility route to investigate on supported older OS versions; current Apple docs deprecate the broadcast sample handler. | Capture permission is not permission to place an arbitrary interactive price panel over another app. Extension/background limits and the target app's protected playback require device tests. | Screenshot/share flow or a second-screen companion first; continuous capture is a later feasibility project. |
| Newer Apple API track | Apple's current ScreenCaptureKit iOS sample describes a system content picker and background screen capture on **iOS 27 or later**. | The retrieved sample is labelled **beta**. Do not treat it as an available production capability on iOS 26, or assume it solves result presentation over another app. Recheck final SDK availability before implementation. | Track as a future capture option, without making the initial product depend on it. |
| Android | User-approved `MediaProjection` capture, preferably restricted to the chosen app, plus a separately permitted `TYPE_APPLICATION_OVERLAY` panel. | Capture consent is required for each session. Overlay permission is separate; apps may block overlays and secure surfaces may appear blank. The app must handle revocation and foreground-service requirements. | Later native floating-panel pilot if a phone overlay is essential. |

Chrome documents both the user-invocation requirement for tab capture and content scripts' ability to change page DOM. Request video only for recognition and verify that the auction remains audible: Chrome's documentation warns that obtaining a tab audio stream changes local audio playback behavior. Do not request broad access to unrelated tabs. [Chrome capture](https://developer.chrome.com/docs/extensions/reference/api/tabCapture), [content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts).

Apple documents consent and the extension boundary in ReplayKit, and its picker lets the user choose the broadcast provider. However, its current [RPBroadcastSampleHandler documentation](https://developer.apple.com/documentation/replaykit/rpbroadcastsamplehandler) marks that API deprecated/no longer supported, and [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit) is described as its replacement. ReplayKit is therefore a legacy compatibility investigation, not the default architecture for a new iPhone implementation; verify actual SDK/OS availability on supported devices. The current iOS ScreenCaptureKit sample explicitly states iOS 27+ and carries a beta notice. This proposal treats those as separate deployment tracks. [ReplayKit security](https://support.apple.com/guide/security/replaykit-security-seca5fc039dd/web), [broadcast picker](https://developer.apple.com/documentation/replaykit/rpsystembroadcastpickerview), [iOS ScreenCaptureKit sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-on-ios).

**iPhone result display:** Live Activities expose system-controlled surfaces such as Dynamic Island and the Lock Screen; they are not a freely positioned price table. A compact “item found / open result” status could be evaluated later. Apple's PiP APIs are for video playback and video calls; the video-call PiP view does not receive ordinary touch events for custom buttons. Do not promise that rendering a price card as video creates an approved general-purpose overlay. This is a product feasibility conclusion from the documented surfaces, not a claim that Apple has reviewed this concept. [Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities), [PiP](https://developer.apple.com/documentation/avkit/avpictureinpicturecontroller), [video-call PiP](https://developer.apple.com/documentation/avkit/adopting-picture-in-picture-for-video-calls).

Apple requires recording consent and a clear indication, and restricts background services to their intended purpose. These are design requirements for any subsequent native submission, not a reason to emulate calls or audio playback just to stay active. [App Review Guidelines, 2.5.4 and 2.5.14](https://developer.apple.com/app-store/review/guidelines/).

Android documents per-session MediaProjection consent, selected-app capture and stop callbacks. `TYPE_APPLICATION_OVERLAY` requires `SYSTEM_ALERT_WINDOW`; its placement and visibility can be changed by the system. `FLAG_SECURE` can prevent capture, while `HIDE_OVERLAY_WINDOWS` allows apps to block overlays. Respect a blank/protected stream and stop; do not attempt to bypass it. [MediaProjection](https://developer.android.com/media/grow/media-projection), [overlay/secure window reference](https://developer.android.com/reference/android/view/WindowManager.LayoutParams), [overlay protection](https://developer.android.com/security/fraud-prevention/activities).

### Whatnot and eBay

Whatnot's current terms restrict automated use and unauthorized monitoring or copying, including specified manual copying. eBay UK's agreement restricts automated access/data extraction without prior express permission. **Neither OS consent nor seller consent by itself establishes permission from the platform.** The launch prerequisite is a documented platform-approved integration/use case or other verified permission covering the planned processing and display. This proposal does not establish that such permission exists and does not make a legal determination about a hypothetical implementation. [Whatnot terms](https://legal.whatnot.com/), [eBay UK agreement, Using eBay](https://www.ebay.co.uk/help/policies/member-behaviour-policies/user-agreement?id=4259).

## 3. Buyer experience and original wireframe specification

The buyer starts one session, selects the permitted tab/app and draws or confirms the product region. The companion watches that region, proposes the item once it has stable evidence, and presents the best available **labelled** reference. The buyer may pause, change the crop, correct the item, or stop at any time. It never presses Bid or changes a bid amount.

| Panel area | Proposed content and behavior |
| --- | --- |
| Collapsed badge | Drop Rate icon; `Watching`, `Checking item`, `Check version`, or `Paused`; one expand action. It never covers the auction bid button. |
| Header | Small verified reference thumbnail; item name; set and collector number, or series/issue/volume; clear close and pause controls. |
| Identity line | English · reverse holo · raw, for example. Each attribute is an observed or explicitly selected value; unknowns remain visible. |
| Main value | `Value: £…` when eligible; otherwise `Regional guide: £…`, `Last known: £…`, or `No supported value`. Price type and evidence date remain adjacent. |
| Evidence line | Provider/source, source currency, last evidence date, market region and condition basis. Separate identity confidence from pricing quality. |
| Optional detail | A condition grid only where the source actually contains condition-specific observations for the same exact identity. Missing cells show an em dash. No synthetic NM-to-LP discounts. |
| Buying section | User-entered current bid, additional shipping and known buyer charges; calculated all-in cost; optional personal maximum/budget. |
| Actions | `Check version`, `Edit costs`, `Save result`. Inventory intake remains a separate explicit action after purchase. |

Desktop specification: a roughly 340–400 px wide movable card, using Drop Rate's existing type and color tokens; start compact, expand downward, with a maximum height that preserves auction controls. Android specification: a small movable edge badge expands to a similarly concise sheet. iPhone screenshot result: the same information hierarchy inside Drop Rate, with an explicit return-to-auction affordance where supported. These are wireframe requirements, not built screens.

Do not reproduce the image's dense grid by default. A confident item identity, one honest value/basis, and the buyer's costs are the useful first glance. Price should never turn green merely because the current bid is below a general guide.

## 4. Identification, item transitions and value eligibility

**Recognition scope by item type:**

| Type | Required identity evidence | Reasons to withhold an exact value |
| --- | --- | --- |
| Raw card | Game, set, collector number, language, artwork/variant and finish where material. | Same art across editions; reverse-holo ambiguity; sleeve glare; reprints; tiny unreadable text; condition unknown. |
| Graded card | Exact card plus grading company and readable grade; certificate evidence where available. | Slab label unclear; wrong company; raw price mistaken for graded value; no eligible grade-specific comparables. Never infer authenticity from the image. |
| Sealed product | Game, set, product format, language, pack/box/case count, edition and region where material. | A booster pack is not a booster box; a display is not a sealed case; outer wrap and contents cannot be authenticated from one frame. |
| Comic | Series, issue, publisher, publication year, cover variant, printing, language and raw/graded state. | Reprinted cover art, variant covers, newsstand/direct variants, unreadable barcode suffix, restoration/grade uncertainty. |
| Manga | Series, volume, publisher/imprint, language, edition/format and ISBN where visible; printing when price-sensitive. | Omnibus versus single volume, different languages, same-cover reprints, missing edition identifiers. ISBN alone may not prove a valuable first printing. |

**Temporal behavior:** sample locally at an initial budget of about two frames per second, reject blurred/occluded candidates, and run recognition only for a meaningful changed crop. Require a stable identity across a short evidence window (initial candidate: three agreeing observations out of four over approximately 1–2 seconds). These are tuning hypotheses to validate, not guaranteed accuracy.

The lock key includes canonical identity, language, finish, product type, grade where applicable and the current scene/session. A price is attached only after the identity gate passes; having a price must not influence which identity wins. Deduplicate repeated frames while the same item remains visible, but allow the same card to appear again in a later lot. Where no reliable lot identifier exists, require a clear scene transition or the buyer's `New item` action.

On a scene change, immediately mark the old result as `Previous item` or hide its buying value. Never show a delayed response as the current item: compare request generation/session IDs before painting a result. A hand, giveaway animation or seller's existing price overlay must not become the recognized product. Use a product crop and physical-object evidence; do not trust captions, chat text or an on-screen price table as identity authority. With multiple items visible, ask the buyer to select the target region.

Present distinct states: **identified + supported value**, **identified + guide**, **identified + stale evidence**, **check version**, **no match**, **no supported value**, **capture stopped**. Scores must be calibrated against held-out examples before showing numeric confidence. No high-confidence label from an uncalibrated model score; no guessed condition, invented price, minimum-price floor masquerading as evidence, or automatic auction action.

## 5. Reuse of the existing Drop Rate architecture

Local review found the following existing components. File references describe inspected code, not new implementation.

| Existing component | Reuse proposal and boundary |
| --- | --- |
| `backend/app/recognition_engine.py` | Reuse identity/printing evidence, candidate ranking and exact-match gates. It already separates identity confidence from printing confidence. |
| `recognition_reference_index.py` and `recognition_provider_reference_index.py` | Reuse reference visual indexes for fast candidate hints. Index readiness and rights remain explicit gates. |
| `recognition_pipeline.py` | Reuse cancellation-safe parallel evidence collection. Add no detached unbounded work in a future live loop. |
| `recognition.py` | The current authenticated `/api/v1/recognition/resolve` creates recognition-run receipts and can perform provider discovery. **Do not call this whole route for every frame.** A later implementation should reuse its domain logic behind a bounded buyer-session path, with provider research disabled by default. |
| `recognition_sealed.py` | Reuse product-code, format and language checks; do not relax them to make boxes appear instantly recognized. |
| `book_recognition.py` | Reuse book evidence and review states. Current research can take longer and its route has per-owner limits; it is not an existing real-time auction engine. |
| `catalogue_display_prices.py`, `inventory_reference_values.py`, `reference_applicability.py` | Read existing shared exact-identity prices and their eligibility, source, date and condition basis. Preserve guide-versus-physical-valuation distinctions. |
| `catalogue_coverage.py` | Reuse reproducible physical-card denominators and missing-evidence reasons. Current coverage includes explicitly labelled mixed-language guides, not only exact UK sold values. |
| `mobile/README.md` | Current mobile delivery wraps the web hubs. A ReplayKit extension, Android capture service or cross-app panel would require native work; it is not unlocked by changing the web scanner alone. |

Supabase remains the source of truth; FastAPI applies deterministic eligibility and cost calculations; R2 serves authorized catalogue artwork and archived data. A short-lived session cache connects stable recognition results to those existing records. A future companion must not write ownership, inventory, Shopify products or settlements merely because a buyer watched an item.

Pricing reads come from Drop Rate's existing cache. **No per-frame market-provider requests.** Existing background import jobs continue to refresh their allowed sources. If an exact match has no eligible price, report that and optionally enqueue a deduplicated refresh under the established rate limits; do not block the auction UI waiting for an external provider or borrow a neighboring variant's value.

## 6. Privacy and latency budgets

Use explicit session start/stop, visible capture state and immediate revocation handling. Crop to the product region on-device before any upload. Avoid chat, usernames, notifications, addresses, checkout details and unrelated application content. Do not capture audio. Keep frames in a bounded memory buffer; do not retain screenshots, video or audio by default. Retain only minimal operational metadata under a declared retention policy. Any optional diagnostic image submission requires a separate explicit action and its own retention notice; it must not silently enter the learning store.

Local cropping reduces disclosure but is not a guarantee that a crop contains no personal information. Before allowing cloud recognition, assess the selected model provider's processing/retention configuration and disclose that cropped images are transmitted. A source image hash is still derived data and should not be treated as equivalent to collecting nothing.

| Stage | Initial engineering budget to test |
| --- | --- |
| Stable usable crop | Approximately 0.5–1.5 s from a clearly presented item; slower or impossible for moving/hidden products. |
| Local preprocessing, lookup and network overhead | Target 0.1–0.4 s, device/network dependent. |
| Cached/index-supported recognition plus price read | Target under 1 s after a stable crop when the supported path succeeds. |
| End-to-end supported result | Target median under 2 s and p95 under 4 s on a defined device/network/test corpus. |
| Slow or ambiguous path | Show `Checking`/`Check version`; never imply the live auction paused. A model/research fallback may exceed the budget and must be cancellable. |

These are **acceptance targets, not measured current performance**. The existing photo workflow, especially book research, has not been proven to meet them. Test battery, heat, dropped frames, interrupted sessions and a 30-minute continuous watch as well as short happy-path scans.

## 7. Buying calculations

The useful deterministic calculation is:

`All-in cost = chosen bid + incremental shipping + known buyer fees + applicable import/tax costs + any user-entered immediate costs`.

Show unknown charges as unknown. Do not subtract a guessed amount or assume shipping is free because previous purchases may bundle. A personal maximum bid can be calculated from a user-set all-in budget after the known costs; if charges depend on the bid, solve using the relevant verified formula. A resale-oriented target may additionally use explicit user-entered sale-price, fee, shipping and margin assumptions, clearly labelled as a scenario. It is not a market forecast or promised profit. Never copy an estimated target into the auction's bid box automatically.

## 8. Readiness gates and proposed delivery sequence

The latest checked project receipt, `docs/CATALOGUE_CONTINUATION_20261027.md`, records **38,819 / 67,065 physical references (57.88%)** with basic identity fields, an artwork URL and a current supported value/labelled guide on the **same record**. English Pokémon's equivalent subset is **19,886 / 21,290 (93.41%)**. These are data-presence measures, not proof that every image loads, every variant is exact, or every guide is an eligible valuation of the auctioned copy.

The same receipt records **37 comic and 58 manga editions**, with **zero** positive book market snapshots even on the weaker historical-positive test, and **zero** records complete with identity, cover and supported value. Both exact-printing verification fields are not jointly verified for any of those books. Therefore this proposal must not promise universal card coverage or live buying valuations for comics/manga today.

1. **Now: proposal only.** Finish the current catalogue work and retain this specification. No feature code, permission prompts, store submission or integration is created by this document.
2. **Permission and data gate.** Obtain a documented permissible capture/integration route and source-display rights. Define the first supported identity cohort; verify its artwork, exact printing, value basis and freshness. Keep unsupported identities visibly unsupported.
3. **Authorized footage experiment.** Benchmark a proposed bounded session resolver against clear/blurred cards, sleeves, mirrored footage, variants, multiple items, scene switches and no-match cases. Include low-value cards and high-value lookalikes. Measure wrong-version confidence, abstention, stale-result leakage, latency and provider-call count.
4. **Desktop pilot.** Only after an implementation request, build user-selected capture plus original result panel for the permitted surface. Validate permission revocation, black frames, cancellation and untouched auction controls. No automatic bids or purchasing.
5. **Phone paths.** Evaluate the screenshot/share and paired-phone experience first. Test Android native capture/overlay separately. Treat iPhone continuous capture and result presentation as separate feasibility tests, including supported SDK/OS, background lifecycle and App Review acceptance.
6. **Expand supported product types from evidence.** Sealed/slab support requires its own identity and source tests. Comic/manga identification can be piloted with honest no-value states; book buying valuations wait for verified edition/printing and permitted sale evidence.

Proposed release criteria include no cross-lot stale value shown as current, no inventory/ownership writes, no automated auction action, no per-frame price-source calls, successful stop/revocation, accurate source/date/condition presentation and measured recognition quality on a held-out corpus. Set a high precision target for exact matches and publish abstention separately; neither a tiny perfect sample nor catalogue percentages alone demonstrate production accuracy.

**Proposed future scope:** a narrow desktop pilot on authorized footage plus a phone-friendly result view, after the catalogue priorities and integration permissions are resolved. This remains a design proposal; no implementation is requested now. The floating panel in the reference image does not establish a buyer-side iPhone overlay capability.
