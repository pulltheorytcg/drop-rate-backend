# Graded Card Fulfilment Research

_Last reviewed: 25 September 2026_

## Decision

Use **120g** as the conservative working shipment weight for one standard graded card.

The production `GRADED_CARD` Shopify shipping profile records this value but remains
**inactive** until a physical pack-out confirms that the selected package has enough
internal clearance and protection. Research cannot establish the internal dimensions
of the founders' actual 110 x 145 x 21mm package.

## Standard slab reference

| Grader | Working weight | Dimensions | Evidence quality |
| --- | ---: | --- | --- |
| PSA, post-2024 holder | 58.2g | 139.7 x 80.0 x 4.8mm | Third-party measured reference. PSA confirms its 2024 holder is 20% heavier than the prior holder but does not publish an absolute weight. |
| BGS | 74.8g | 130.0 x 82.5 x 6.4mm | Third-party measured reference. Beckett does not publish finished BGS holder dimensions or weight. |
| TAG | 54.0g | 133.35 x 79.38mm; third-party thickness 4.8mm | TAG officially publishes 5.25 x 3.125in width/height. Weight and thickness are third-party measurements. |
| ACE | Not reliably published | Community measurement: 134 x 80 x 8.4mm at the thickest point | Low confidence until physically measured. ACE does not publish a standard slab weight found in this review. |

Sources:

- PSA holder update: https://www.psacard.com/articles/articleview/11060/meet-the-new-standard
- Published-dimension source review: https://www.cardsurvive.com.au/psa-vs-cgc-vs-tag-vs-beckett-slab-dimensions
- TAG official slab dimensions: https://help.taggrading.com/en/articles/6747780-what-are-the-features-of-tag-s-slab
- Third-party slab measurements: https://pregradecards.com/resources/slab-taxonomy
- ACE community caliper measurement: https://www.reddit.com/r/PokemonTCG/comments/x0qqxi/ace_slab_dimensions/

## Weight calculation

The 120g profile is deliberately based on the heaviest researched standard slab:

| Component | Allowance |
| --- | ---: |
| BGS standard slab | 75g |
| Existing empty package | 27g |
| Sleeve, cushioning, label and measurement margin | 18g |
| **Configured shipment weight** | **120g** |

Do not use the 120g figure for oversized, thick-card, autograph, comic, manga or
memorabilia holders. Those require separate profiles.

## Package fit assessment

The existing 110 x 145 x 21mm external package is inside Royal Mail's Tracked 48
Large Letter maximum of 353 x 250 x 25mm and 1kg when purchased online:

https://www.royalmail.com/sending/uk/tracked-48

However, a post-2024 PSA reference length of approximately 139.7mm leaves only
5.3mm before accounting for wall thickness. That is not enough evidence of safe
impact clearance. The package therefore remains a candidate, not an approved
graded-card package.

A graded pack-out should provide an internal cavity of at least approximately
150 x 95 x 15mm. A 160 x 110 x 20-24mm external large-letter box may be a more
practical starting point, subject to supplier internal dimensions and a physical
test.

## Activation test

Before activating `GRADED_CARD`:

1. Pack one current example each from PSA, BGS, TAG and ACE.
2. Confirm no slab edge touches the external package wall under light pressure.
3. Confirm the sealed external thickness is no more than 25mm.
4. Weigh five completed examples; set the profile to the highest result rounded up by 5g.
5. Perform a controlled 1m face, edge and corner drop test with a low-value slab.
6. Re-open and inspect for cracks, chips, scuffs, label movement and card movement.
7. Record the final package SKU, unit cost, empty weight and protective-material cost.
8. Activate the profile only after all checks pass.

## Operational rule

Until activation, graded products remain blocked from Shopify publication. This is
intentional fail-closed behaviour. Raw-card fulfilment remains unchanged.
