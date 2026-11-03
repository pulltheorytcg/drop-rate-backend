# Seller Hub: charcoal, warm white and orange

## Purpose

The Seller Hub was dominated by blue surfaces, making panels and controls feel
too similar. This presentation update keeps the Hub dark while adding warm white
artwork mounts and selected financial summaries, with orange for primary actions,
links and selected controls. The approved Drop Rate logo, self-hosted Inter,
navigation structure and existing motion remain in use.

The Shopify Brand Redesign supplies the shared typography, brand and hierarchy.
Its current source uses a white/navy/blue palette; orange is the user's requested
direction for this Hub update, rather than a claimed extraction from storefront
CSS. The storefront itself is unchanged.

## Shared palette

| Role | Colour | Use |
| --- | --- | --- |
| Workspace | `#111110` | Header, sidebar, page background and mobile navigation |
| Main surface | `#1b1b19` | Panels, dialogues and sign-in |
| Raised surface | `#242421` | Secondary controls and quiet status treatment |
| Main text | `#f6f5f1` | Headings and body text on dark surfaces |
| Secondary text | `#b7b6ae` | Supporting copy on dark surfaces |
| Primary action | `#ff8a3d` | Add, continue, confirmation and listing actions |
| Action text | `#21160e` | Dark text on orange controls, 7.55:1 contrast |
| Artwork mount | `#efece5` | Collection, Search and photo-review image areas |
| Artwork placeholder | `#4a4640` | Missing-image labels on light mounts |
| Featured summary | `#f5f2ec` | Known collection value and existing featured KPIs |
| Summary text | `#25231e` / `#69645b` | Main and supporting copy on light summaries |

The existing green, amber and red status meanings remain distinct. Saved
appearance preferences still adjust quiet accent details; they do not replace
the neutral surfaces or the orange primary actions. Existing reduced-motion
settings and operating-system reduced-motion handling remain intact.

## Implementation and boundaries

`premium-hub.css` owns the shared palette and aliases used by older feature
styles. The later account, Hub, Collection, photo and collectible styles now use
the same tokens. `premium-auth.css` applies the palette to the supported `/app`
sign-in and registration entry. The legacy `/owner` login stays hidden by the
existing workspace shell and redirects to that supported entry.

Both HTML entrypoints use the charcoal browser theme colour and versioned
stylesheet URLs (`premium-orange-20261103`) to refresh cached assets. The home
Known market value card now uses the existing featured-card class. Selected
listing steps have a warm background and orange underline; light image frames
have explicitly scoped dark placeholders.

This change contains no database migration, API or JavaScript behavior change.
Ownership, optional acquisition cost, commission, physical-copy identity,
scanned-photo handoff, removal, listing rules and server authorization continue
to use their existing implementations. No production inventory or account data
is created for visual validation.

## Validation

- Existing dashboard unit/DOM suite: all 27 scripts pass, covering navigation,
  authentication recovery, scan/photos, Collection, exact-copy actions, listing,
  financial screens, imports and motion settings.
- Existing branding/static tests: 8 pass.
- Actual-source Chromium inventory browser: 320, 390, 430 and 1440 px layouts,
  guided listing, artwork failures and copy actions pass.
- Actual-source card-photo browser: 8 mobile/desktop cases pass, including photo
  retry, identification-only capture, multiple intended copies and nullable cost.
- Actual-source premium browser: 108 screen states pass with no text-contrast
  failures, page errors or horizontal overflow. Synthetic accounts and
  intercepted APIs exercise selected controls and dark native selects.
- Collection browser: six viewport journeys pass (320, 390, 430, 768 and 1440 px,
  plus the short 390 × 460 phone). Checks include list/grid, filter state,
  keyboard focus return and at least 44 px touch controls.

The first contrast pass caught “Photo not ready” and older image placeholder
copy using dark-surface muted colours on new light mounts. Those descendants now
use the artwork-ink token. The first visual pass also caught indistinguishable
listing steps; the current step now has an explicit selected treatment.

Screenshots alongside this document show actual application HTML, CSS and
JavaScript with synthetic data, not a live seller's stock or balances. Release
verification must additionally require the PR checks, Railway success for the
merged SHA, public asset byte comparison and the readiness endpoint.
