# Dragon Ball storefront media quality

_Last reviewed: 30 September 2026_

## Goal

Drop Rate should not treat a low-resolution thumbnail as a finished storefront asset merely because the card identity is correct.

For Dragon Ball Super Masters and Dragon Ball Super Fusion World, the replacement target is a **measured long edge of at least 2160 pixels**. This is the project's practical 4K-quality gate for portrait card imagery.

A file that has merely been enlarged to 2160 pixels does not gain real detail. Generative or AI redraw/upscaling must not be used to invent card text, collector numbers, stamps, foil details or artwork.

## Current production snapshot

- 25 unique Dragon Ball Shopify products are currently published.
- They represent 27 physical inventory units.
- All 25 currently rely on CardTrader canonical URLs whose filenames are `preview_...`.
- Direct Shopify Admin read-back confirms **all 25 are below the 2160px target**.
- Current Shopify image dimensions range from **251×350px** at the low end to **1279×1782px** at the high end; common Dawn of the Z-Legends assets are about **313×437px**.
- Eight additional FOR_SALE Dragon Ball items are identity-confirmed, English, Near Mint and priced but remain unpublished because exact-print media is unresolved.
- Six of those eight are Masters pre-release copies.
- The other two are Fusion World tournament variants:
  - Nappa FP-046 — Tournament Pack 07;
  - Vegeta FB05-039 — Tournament Pack Winner 06.

The current images stay live until a verified replacement is ready. The quality migration is replacement-first; it must not create an image outage.

## Non-negotiable order of checks

1. Exact game line.
2. Exact card identity / collector number.
3. Exact language.
4. Exact printing / variant / stamp / tournament version.
5. Storefront rights / permitted use.
6. Human exact-print approval where required.
7. Shopify read-back.
8. Measured image dimensions.

A high-resolution image of the wrong printing is still wrong and must fail closed.

## Quality states

Media assets gain three source-quality states:

- `UNMEASURED` — legacy or not yet verified. Existing live assets remain backward-compatible in this state.
- `BELOW_TARGET` — measured long edge is below 2160 px.
- `TARGET_MET` — measured long edge is at least 2160 px.

For Dragon Ball, a measured `BELOW_TARGET` asset cannot become the preferred storefront replacement. `UNMEASURED` remains temporarily eligible so the current catalogue is not broken during migration.

Shopify File read-back is used to record width and height. This keeps the quality decision deterministic and auditable rather than inferred from a filename such as `large`.

## Source strategy

### 1. First-party capture — guaranteed 4K fallback

Use the existing founder media intake flow and upload the original camera/scanner JPEG, PNG or WebP.

For exact promo, pre-release and winner copies where no permitted provider exposes the exact high-resolution printing, first-party capture is the preferred resolution because it proves the physical stamp/version and can comfortably exceed 2160 px.

Capture requirements:

- original camera/scanner file, not a screenshot;
- card fills the frame but all four corners remain visible;
- square-on;
- even diffuse light;
- no glare hiding foil/stamp/collector number;
- no beauty filters, generative fill or AI reconstruction;
- retain enough native resolution to exceed the 2160px long-edge gate.

### 2. TCGGraph — exact external candidate when configured

The existing TCGGraph adapter already understands Dragon Ball Masters vs Fusion World and uses exact collector number, name, language, line and printing/finish gates.

When a TCGGraph API key is configured:
- request the exact printing;
- prefer its documented `large` image candidate;
- keep it PENDING until exact-print human approval;
- sync it to Shopify Files;
- measure the Shopify read-back dimensions;
- accept it only when it reaches `TARGET_MET`.

Do not assume an image named `large` is 4K; the system measures it.

Production currently has no `TCG_TCGGRAPH_API_KEY` configured.

### 3. CardTrader

CardTrader remains useful for exact identity/media evidence, but a Dragon Ball image whose delivered filename is a `preview...` derivative no longer short-circuits higher-quality resolution.

The enrichment pipeline may continue to TCGGraph when available. Without another exact high-resolution provider, it returns Action Required and asks for first-party capture rather than silently accepting a low-resolution replacement.

### 4. Bandai official website

Bandai's official website is useful as identity/reference evidence, but its current website notice states that unauthorised reproduction/reprinting of its images is prohibited. Drop Rate therefore does **not** treat Bandai site artwork as an automatic Shopify storefront source.

## Eight unresolved cards

These stay fail-closed until exact media evidence is available:

| Game | Card | Printing |
| --- | --- | --- |
| Masters | Trunks, Thwarting the Dark Empire BT13-131 | Supreme Rivalry Pre-Release |
| Masters | Mijorin, North Galaxy Warrior BT18-043 | Dawn of the Z-Legends Pre-Release |
| Masters | Rage Shenron, Impenetrable Evil BT18-025 | Dawn of the Z-Legends Pre-Release |
| Masters | Sarta, North Galaxy Warrior BT18-044 | Dawn of the Z-Legends Pre-Release |
| Masters | Omega Shenron, Merciless Negativity BT18-004 | Dawn of the Z-Legends Pre-Release |
| Masters | Vegeta, Lone Saiyan Warrior BT18-018 | Dawn of the Z-Legends Pre-Release |
| Fusion World | Nappa FP-046 | Tournament Pack 07 |
| Fusion World | Vegeta FB05-039 | Tournament Pack Winner 06 |

Do not substitute:
- base-set art for a stamped pre-release printing;
- Nappa Winner 07 for ordinary Tournament Pack 07;
- ordinary Vegeta Tournament Pack 06 for Winner 06.

## Replacement procedure for the 25 live products

For each current Dragon Ball product:

1. identify the exact current catalogue printing;
2. acquire an exact high-resolution permitted candidate or founder capture;
3. register it as a new media asset — never overwrite historical evidence;
4. approve exact identity/rights;
5. sync to Shopify Files;
6. read back width/height;
7. require `TARGET_MET`;
8. attach/switch the verified media on the exact Shopify product;
9. visually verify the PDP;
10. only then revoke/retire the legacy CardTrader preview asset.

No bulk deletion precedes successful replacement.

## Testing

Required coverage:

- 2160px threshold in both portrait and landscape orientation;
- invalid/missing dimensions remain `UNMEASURED`;
- Dragon Ball `BELOW_TARGET` canonical media is rejected;
- existing Dragon Ball `UNMEASURED` media remains temporarily backward-compatible;
- `TARGET_MET` media is selected;
- low-resolution first-party Dragon Ball media cannot satisfy a mandatory physical-photo gate;
- CardTrader preview derivatives fall through to the next exact provider rather than winning by provider order;
- Shopify File queries return width and height;
- quality measurement cannot delete/unpublish products;
- exact printing/variant rules remain unchanged.
