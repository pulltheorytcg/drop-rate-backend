# Hidden Fates Shiny Vault targeted price fill

This operator path repairs one measured gap: all 94 canonical English `sma`
references had no current supported price. It does not raise a coverage percentage
by changing its denominator or value other printings by name alone.

## Verified source identity

The live read-only probe at 2026-10-26 22:04 UTC returned CardTrader expansion
1615 (Hidden Fates), 190 blueprints and Pokémon single category 73. Base Charizard
009 maps to blueprint 121245 / Cardmarket 394737. Shiny Vault SV49 is separately
blueprint 121421 / Cardmarket 381243, SV59 is 121431 / 396937, and SV69 is
121441 / 396982. Each has an explicit SV numerator and one marketplace ID.
TCGdex returned exact matching identities for those three cards but no underlying
marketplace IDs or quotes, confirming that a repeated direct refresh cannot fill
this gap alone. The probe reads identity data only; prices come from the existing
permitted dated Cardmarket exports and official ECB currency conversion.

## Preview and apply

In the existing deployed runtime:

```sh
PYTHONPATH=backend python backend/scripts/refresh_hidden_fates_prices.py --from-settings --max-seconds 120
```

Review the per-card preview, source IDs, observation dates, EUR/GBP values, actual
matched/priced totals, failures and conflicts. Then use the same command with
`--apply` to persist only positive proven values. An incomplete source, lock
conflict, changed checklist or unsafe capacity stops the operation. The fixed
scope must contain exactly SV1–SV94 with the expected full identity.

The operator uses the configured maintenance administrator, the existing
maintenance advisory lock, existing conditional price writes and append-only
history trigger. It never changes inventory, owner balances or store prices.
It rejects outside-scope cached claims and competing CardTrader IDs across the
complete parent export, including unpriced or multi-ID blueprints. Failed or
missing quotes never erase existing values in this targeted fill.

Apply creates a durable `reference_sync_runs` receipt with source
`hidden_fates_catalogue_prices`. Timeout/commit uncertainty is explicit and
requires database readback before retrying. Successful execution alone is not
proof that all 94 have prices; use the actual receipt and exact source readback.

The scheduled catalogue adapter retains its default full-library behavior. The
new scope and dry-run switches are internal operator options, not user request
parameters or a new public API. No schema or service was added.

## Validation

Tests cover the full and incomplete checklist, identity changes, dry-run no-write
behavior, positive-only scope, admin/capacity/lock rejection, timeout/failure
reporting, and competing Cardmarket claims from unpriced base cards. Existing
persistence tests continue to exercise the shared write/history contract. Live
results will be recorded after the reviewed preview and application.
