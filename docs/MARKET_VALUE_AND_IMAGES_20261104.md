# One market-value display and reliable inventory images

## Display contract

Collectors see one Market value for an item. Existing source precedence,
freshness and exact-match checks still choose the amount. Cardmarket trend
prices and eligible computed market estimates remain source evidence; changing
the heading does not turn a retail recommendation into market evidence.

Valuation, scanner and overview views do not show a second guide amount or an
automatic retail recommendation. Source, estimate status and evidence dates
remain available in the details. Historical or missing values remain explicit.
No historical value or retail-only recommendation may populate a new selling
price. Where no saved price or draft exists, an eligible current market value
can prefill the explicit selling-price field. Existing saved prices and drafts
remain under their owner's control.

The previous retail value was a separately calculated selling recommendation,
not manufacturer RRP. The previous guide label described Cardmarket-derived
market evidence. Those competing labels were the reported display problem.

## Inventory image delivery

The authenticated inventory image route retains ownership and media-approval
checks and the existing asset preference order. It can read a verified R2
mirror of the exact approved source before trying the original provider.
Stored image reads are bounded and checked against the expected byte count and
content hash. Missing, failed, mismatched or corrupt mirrors cannot silently
replace an eligible source image.

This does not create artwork, change card identities, relax rights checks or
attach a different physical copy's photograph. The inspected Luffy 25th
Anniversary P-001 record lacks an approved media asset, verified reference
mapping and saved reference image. Its image cannot be repaired by guessing a
printing. Several other inspected cards retain their approved source assets
and verified mirrors; no source-image deletion was found in the pricing release.

## Verification

UI tests cover a single value, source precedence, expired and missing evidence,
retail-only values excluded from selling prefill, and preservation of saved
prices. Image tests cover approved exact mirrors, corrupt or unavailable stored
bytes, original-provider fallback and access restrictions. Full backend,
browser and database-contract CI must pass before deployment. Actual release
and live-check results are recorded in the pull request.
