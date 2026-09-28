# Founder HQ Mobile V2

## Purpose

Founder HQ mobile is a first-class operating surface, not a compressed desktop dashboard. A founder should be able to scan, find, inspect, price and act on a card with one hand while standing beside physical stock.

This work changes presentation and navigation only. Supabase remains the source of truth and FastAPI remains the authority for ownership, pricing, approval, Shopify and finance rules.

## Current UX problems found in the implementation

1. The same eight desktop sections are rendered into a horizontal `seller-nav` on small screens.
2. Mobile inventory falls back from a wide table into generic two-column rows instead of a card-native collection surface.
3. Dashboard hero, operational panels, utility drawers and finance modules retain desktop information hierarchy.
4. Important mobile actions compete equally with secondary/admin functions.
5. Scan/media is a normal tab even though capture is one of the highest-frequency mobile workflows.
6. Search and filters consume vertical space instead of behaving like a persistent collection control.
7. Desktop dialogs are reused for editing; mobile needs bottom-sheet/full-screen task surfaces with safe-area support.
8. There is no explicit thumb-zone or 44px minimum target contract.

## Mobile information architecture

Persistent bottom navigation (max five destinations):

- Home
- Inventory
- Scan (primary centre action)
- Sales
- More

`More` contains Verify, Media library, Reports, Balance and Settings. Deep links/hash routes remain compatible so desktop and existing links do not break.

The bottom bar must respect `env(safe-area-inset-bottom)` and never cover pagination, forms or dialog actions.

## Core workflows

### Scan -> identify -> confirm -> inventory

1. Tap Scan from anywhere.
2. Camera/capture opens directly.
3. Recognition shows best match plus meaningful runner-ups.
4. Evidence is grouped by card number, set, artwork/printing, language, rarity/type and provider evidence.
5. Exact-print ambiguity blocks silent confirmation.
6. Founder confirms or chooses a candidate.
7. Physical inventory fields are captured separately: owner, cost, condition/grade, location.
8. Save returns to a compact card detail view with next actions.

Target: no dashboard detour and no unnecessary page reload.

### Find -> inspect -> act

1. Inventory opens to visual collection.
2. Search is immediately available.
3. Filter button opens a sheet; active filters render as removable chips.
4. Cards show image, name, set/card number, language/variant, market/store value and status.
5. Tap card -> detail sheet/page.
6. Primary actions depend on deterministic state: edit, verify, price, approve, Shopify status.

### Home

Above the fold:
- inventory market value
- sellable/store value
- action-required count
- sales snapshot
- prominent Scan/Add action

Below:
- action queue
- top-value stock
- weekly movers
- Shopify blockers

Do not put configuration/admin controls on Home.

## Inventory density

### Phone
- 2-column visual grid by default.
- Card image uses stable aspect ratio; missing images use compact branded placeholder.
- Text limited to two primary lines plus compact metadata/value row.
- No giant empty media boxes.
- List view remains optional for operational scanning.

### Tablet
- 3-4 columns based on available width.

### Desktop
- retain dense 5-7 card target where viewport permits.
- table remains available for bulk operations.

## Interaction contract

- minimum interactive target: 44x44 CSS px.
- no horizontal page scrolling.
- no action dependent on hover.
- forms use correct mobile input modes.
- destructive actions require explicit confirmation.
- primary save/action remains reachable above keyboard where practical.
- focus is moved into opened sheets/dialogs and restored on close.
- loading, empty, error and offline/network-failure states are designed, not blank.
- skeletons may be used for card collections; do not shift layout when data arrives.

## Visual direction

Drop Rate should feel collectible-first and premium rather than enterprise-admin:
- card artwork does the visual work;
- dark neutral shell with restrained brand accent;
- typography hierarchy stronger than borders;
- fewer nested boxes;
- status conveyed with text + shape, never colour alone;
- motion is brief and functional;
- no decorative animation that compromises scrolling or scan performance.

We can learn interaction principles from Collectr/Pulse-style collection apps without cloning their artwork, branding or proprietary UI.

## Performance targets

- avoid rendering thousands of DOM cards at once; paginate/virtualise.
- lazy-load card images and provide fixed dimensions.
- no layout shift from missing/late images.
- mobile navigation interaction should not trigger network work unless destination data is actually needed.
- camera flow must not preload dashboard-heavy modules.

## Accessibility

- semantic nav and labelled controls.
- visible focus states.
- screen-reader labels for icon-only actions.
- status not colour-only.
- respect reduced-motion.
- modal/sheet focus trap and Escape support on hardware keyboards.

## Rollout

### Phase A — shell
Bottom navigation, safe areas, mobile header, More sheet, routing compatibility.

### Phase B — inventory
2-column card collection, sticky search/filter control, filter sheet, compact card detail.

### Phase C — scan
Make Scan a first-class centre action and streamline capture -> recognition -> confirmation.

### Phase D — Home and finance
Recompose dashboard/sales for mobile information hierarchy.

### Phase E — polish
Accessibility, performance profiling, device matrix and visual regression.

## Device acceptance matrix

At minimum verify:
- 320px narrow viewport
- 375/390px iPhone class
- 430px large iPhone class
- 768px tablet portrait
- desktop >= 1280px

Test with long card names, missing images, Japanese text, graded/raw cards, large GBP values, empty collections and 5,000+ inventory pagination.

## Release gates

A mobile phase cannot merge merely because it "looks responsive." It must pass:
- existing backend/unit suite;
- navigation keyboard/accessibility checks;
- no horizontal overflow at acceptance widths;
- 44px target checks for primary controls;
- scan/add/find/edit critical-path smoke tests;
- desktop regression check;
- screenshots at 390px and 1440px reviewed before production.
