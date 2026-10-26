# Popular-card price gaps, 26 October 2026

The user prioritised real missing values on popular cards. Current physical
reference coverage is 42,482/67,065 (63.34%), not 90%. A value is never copied
from a different printing merely because its name matches.

## Hidden Fates Shiny Vault

All 94 `sma` references have no current supported value. The existing bridge
looks for a separate Shiny Vault expansion, while CardTrader publishes the
explicit SV-numbered cards in its parent Hidden Fates expansion. This patch
allows only the exact `sma` / `Hidden Fates Shiny Vault` pair, SV1–SV94, and the
exact parent title in the CardTrader number-based bridge. The name-only bulk
matcher is unchanged. Existing exact card/blueprint/Cardmarket names, collector
numbers, singleton IDs and collision checks remain mandatory. Source facts are
recorded as provenance; missing canonical rarity is not invented.

Primary identity examples:
- https://www.cardtrader.com/en-EU/cards/121421-charizard-gx-shiny-rare-sv49-sv94-hidden-fates
- https://www.cardmarket.com/en/Pokemon/Products/Singles/Hidden-Fates/Charizard-GX-HIFSV49

Bounded read-only scripts probe six exact popular Pokémon and the parent
CardTrader expansion. Live evidence must be reviewed before running the existing
price-writing pipeline. No coverage increase is claimed by the code change alone.

## Observed legacy Pikachu display

One imported Base Set (Unlimited) Pikachu uses number `58`, while the reference
identity uses `58/102` and the parent title Base Set. The observed exact identity
gets a bounded lookup alias. Only the explicit `Normal · unlimited` quote is
eligible; the distinct Poketour treatment (£313.18 in the inspection) and first
edition are excluded. The inspected unlimited quote was £11.40, dated 25 October.
The result is a dated catalogue guide, never a physical-copy value or recommendation.

Tests cover edition collisions, wrong identity/language, source and FX rejection,
and unknown or duplicate printing evidence. Inventory ownership and stored money
are unchanged. The separate reviewed book operator uses the already configured
maintenance administrator and existing RLS; it creates no privileges.

Live repair/import/price receipts will be recorded after execution.
