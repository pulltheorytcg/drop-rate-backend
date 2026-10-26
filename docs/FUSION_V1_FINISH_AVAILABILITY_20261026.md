# Reviewed Fusion V1 finish availability

The already-reviewed SB01/ST01 Cardmarket products can return two explicit
price records, normal and foil, while the normal trend is null or zero. The
previous selector treated the presence of the normal record as sufficient to
exclude the foil quote, even when only the foil had a positive value.

For these exact reviewed V1 products only, the selector now requires at most one
normal and one foil record and rejects unknown finish records. It prefers a
valid positive normal trend, then accepts a valid positive sole foil trend if
the normal quote is absent or unusable. Duplicate normal or foil records fail
closed even if one record has a price. Invalid/nonfinite/boolean/zero values
are never stored.

A foil quote is explicitly labelled Holofoil, keeps the same independently
proved V1 Cardmarket product and EUR trend/FX evidence, and remains an indicative
catalogue guide with physical_valuation_eligible=false. No TCGplayer fallback,
new release aliases, schedule, quota, inventory or storefront-price changes.

The existing SB01/ST01 operator remains dry-run by default with the same
eight-request and 90-second bounds. Preview rows now show finish and source_field;
quote_finish_counts and no_quote_reasons distinguish usable foil guides from
missing or ambiguous quotes. Review a fresh preview before applying any new
guides. Prior positive guides remain protected by the existing write guards.

Regression fixtures use the observed normal/foil list shape with synthetic
values (including null/zero normal and positive foil); they do not claim that
the test prices are live source values.
