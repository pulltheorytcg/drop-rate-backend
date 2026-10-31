# Japanese Pokémon artwork mirror permission repair — 31 October 2026

## Production observation (read-only)

- 3,065 Japanese `TCGdex` reference cards now have exact, individually verified
  `www.pokemon-card.com` source image URLs. They were recovered without changing
  physical inventory or approving listing photography; see
  [the source verification](POKEMON_OFFICIAL_ARTWORK_RECOVERY.md).
- At 22:54 UTC, 3,008 of these source images lacked a verified private-R2
  mirror. A further 2,907 Japanese Pokémon reference cards still had no source
  image URL, which **this permission repair cannot supply**.
- The live background worker was processing batches of 20 but reporting
  `failed: 20, mirrored: 0`, with `InsufficientPrivilegeError` both for the
  mirror receipt and its retry receipt. Existing `tcg_api` table grants are
  present. The forced-RLS `WITH CHECK` on `tcg.reference_image_mirrors`
  omitted the new official host, despite the backend's strict URL allowlist.
- A read-only SQL pattern check found all 3,065 recovered source URLs match
  the proposed anchored official-image pattern, with zero exceptions.

## Smallest safe change

Migration `20261031230000_r2_pokemon_official_reference_images.sql` extends
the existing **INSERT and UPDATE** mirror policies for exactly the
`TCGdex` / `POKEMON_TCG` / `Japanese` source identity and the official
`https://www.pokemon-card.com/assets/images/card_images/large/` path shape.
The current reference's provider, system, language, ID and source URL must
all match at receipt time. The other provider hosts and permissions remain
unchanged. Forced RLS remains in force; no media is upgraded to approved
inventory or storefront imagery, and no pricing or owned stock is touched.

## Release and verification gates

1. Run the targeted tests and the migration/security suites in CI, review the
   policy diff and apply the version-controlled migration through the normal
   controlled Supabase deployment path. Never disable RLS to make the worker pass.
2. Check `pg_policies` for both updated exact-source policies, and confirm
   neither `anon` nor `authenticated` received table privileges.
3. Observe new `CATALOGUE_R2_REFERENCE_MEDIA_BATCH` logs. Successful batches
   should have nonzero `mirrored`; classify any `SOURCE_UNAVAILABLE` or R2
   failures separately. The worker already bounds throughput, validates image
   bytes and uses per-source retry backoff.
4. Recount VERIFIED mirror records where the current Japanese TCGdex image URL
   is on the official host. Monitor the number missing; do not claim the 3,008
   backlog is cleared until live readback confirms it. Test a representative
   signed image in a signed-in catalogue browser and the provider fallback.
5. Confirm inventory ownership, store prices, financial history, rights state
   and current card identities are unchanged. Record the actual release result
   in `BUILD_STATUS.md`.

Rollback, if necessary, is to restore the previous two `ALTER POLICY`
definitions from `20261030142942_r2_cardtrader_image_filenames.sql` via a new
versioned migration. Existing R2 objects and mirror rows are not deleted.
