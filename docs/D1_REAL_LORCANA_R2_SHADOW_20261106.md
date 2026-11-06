# Stage A.2 — verified production Lorcana R2 → isolated Cloudflare D1 shadow (6 Nov 2026)

**What:** first **real, checksum-verified** private R2 catalogue transfer to a NEW, unconnected Cloudflare D1 shadow database. The scope is the active `lorcast / DISNEY_LORCANA / English` R2 partition (3,505 references on 6 Nov 2026). This does not change live catalogue reads, finance, ownership, R2 source, Shopify, Postgres data, production pricing or Supabase Auth.

**Why:** proves full source-data parity over a real partition before any 45k Yu-Gi-Oh! or 153k Magic import; avoids exceeding the Cloudflare D1 Free plan's 100k daily writes. No new R2 credential is exposed, copied to GitHub or introduced.

## Connections

- GitHub Actions **push on trusted main only** can mint a short-lived GitHub OIDC RS256 JWT (audience `drop-rate-readonly-r2-d1-shadow-20261106`).
- Railway FastAPI verifies issuer-signing JWKS, signature, audience, expiration, ref, full repository ID, exact workflow ref, runner environment and event; unauthorised or pull-request tokens cannot export source bytes. Endpoint is **disabled by default** unless `TCG_R2_D1_SHADOW_EXPORT_ENABLED=true`. The endpoint returns *only* the current published Lorcana R2 manifest and its exact indexed reference shards, never arbitrary R2 keys or prices; no write endpoints exist.
- The active Supabase PostgreSQL `r2_first_catalogue_publications` row is a **temporary read-only source-trust pointer**. Its manifest digest, counts, revision, permission reference and original content hash are compared to every retrieved R2 object. This is not a migration of the PostgreSQL ownership master.
- A GitHub runner, using the previously verified D1-scoped `CLOUDFARE_D1_PILOT_TOKEN`, creates one **new** database prefixed `drop-rate-d1-real-lorcast-shadow-`, builds the Stage A schema, writes only the verified reference records, and reads back **every** row to re-compute the expected SHA256 projection digest. Only after complete byte/row parity does it activate this *isolated* D1 partition pointer.
- Production D1 catalogue **does not exist yet** as a connected serving path; the database created here has no public Worker binding, so this release does not accidentally change customers' search results. No Market Value price fields exist in this projection.

## Failure and security gates

1. OIDC JWT must be signed by GitHub; exact `repository_id=1382317534`, `refs/heads/main`, `.github/workflows/d1-real-r2-to-d1.yml`, expected `aud`, 2-minute freshness, GitHub-hosted runner and `push` event. Do not log JWT/token or payloads. Any mismatch is 401/403. **Do not remove these checks to fix a run.**
2. R2 URL scope is fixed inside the backend; ordinal can only select shards of the **current active manifest**, and every shard is SHA256 checked. A publisher refresh during the import must cause a safe failure rather than mixed generations.
3. D1 runs with existing GitHub-scoped token only. No R2 S3 secrets are passed to GitHub, and no D1 token is passed to Railway. Existing operational database resources are never targeted; a previous real Lorcana shadow blocks duplicate creation.
4. R2 active manifest hard bound 1,000–8,000 rows, ≤8 MB bytes and ≤25 parts. D1 statements use ≤100 bound parameters, ≤12 statements per batch, no raw interpolated card values. Daily database write and account storage limits are checked conservatively.
5. A D1 checksum mismatch, missing row, bad source key, denied auth, cost limit, network interruption or failed query **never sets an active pointer**; previous D1/Shopify/PostgreSQL records are untouched.
6. Do not enable this pipeline for Magic, Yu-Gi-Oh! or private financial records without a separate cost/migration review; their sizes, variant and security constraints are different.

## Tests and result definition

`PYTHONPATH=backend:tools pytest -q tests/test_d1_r2_shadow_export.py tests/test_d1_r2_real_shadow.py tests/test_d1_shadow_catalogue.py`

The tests exercise real RS256 verification (mocked fixed JWKS), wrong repository/branch/workflow claims, disabled endpoints, unavailable R2, duplicate database protection, signed exact manifest, byte tampering, 1002-row full D1 readback using SQLite API double, explicit source checksum parity, immutable source IDs, and zero customer/price/owner writes.

GitHub workflow: `.github/workflows/d1-real-r2-to-d1.yml`. Pull-request tests have no secrets. On merged main push only, trusted code requests GitHub OIDC and uses existing D1 token. Remote report: `d1-lorcana-real-shadow-report.json`, artifact retained for 30 days. **Accept the migration step only if the remote job reports `REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED`, equal source and D1 row counts, matching SHA256 and no production writes.** A green local test alone is not completion.

Source/billing references: https://developers.cloudflare.com/d1/platform/limits/ , https://developers.cloudflare.com/d1/platform/pricing/ , https://docs.github.com/en/actions/reference/security/oidc .

## Next steps after remote verification

Extend a reviewed credential-free R2 shadow channel to Yu-Gi-Oh! (45,418 published on 6 Nov), Magic (153,662) in quota-safe increments, then remaining PostgreSQL reference sources (69,697). Build low-cost delta refresh, signed Worker read APIs, prices/evidence separation, exact grade/finish/language validation and a complete storefront shadow read parity benchmark. Ownership, consignment, finances, webhooks and replacement authentication remain a separately tested D1 cutover; do **not** retire Supabase until all are verified.
