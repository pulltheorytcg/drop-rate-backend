# Seller Hub display repair — 8 October 2026

## Findings and scope

The browser image policy omitted `www.dbs-cardgame.com` and `narutocardgame.gg`, despite both supplying existing catalogue artwork. It also omitted `cardtrader.com` and its `www` redirect used by approved inventory media. Read-only checks returned HTTP 200 image responses from all three providers. The narrow image-host additions leave script, connection, framing and media approval rules intact.

Catalogue results now return a same-product approved canonical image as a fallback when provider artwork fails. Empty provider URLs also fall back correctly. The UI tries each distinct allowed URL once, then shows the existing image placeholder. No unverified artwork is approved or promoted to a storefront.

Market data is a separate coverage limitation. Existing canonical products return saved reference prices through the current query, while unmapped reference printings have no verified price link. The inspected unvalued seller item has no saved market observations or media; its absence is real. Names/card numbers alone cannot safely link parallel artwork or valuations. This repair does not invent prices, reuse a box price for a pack, merge inventory, or mark those mappings verified.

The owner overview now reports valued and unvalued active-item counts. A wholly unvalued collection says “Value pending” instead of £0. Partial totals explicitly report missing coverage; an empty collection still totals £0. Inventory and product details explain pending values. Stored prices, pricing rules, ownership, RLS, history and publication gates are unchanged.

## Verification and rollback

- Targeted Python checks passed (70 cases); the full browser interaction suite passed, including distinct image fallback, unsafe URL rejection, pending versus priced details and empty/partial/unvalued overview cases.
- Read-only production query verification returned existing market values and approved images without modifying data. Three source image downloads returned HTTP 200 and image content types.
- CI, release and authenticated device validation remain separate gates; this document does not claim them before completion.
- Revert this PR to restore the previous response/UI/header behaviour. No migration or data rollback is needed.
