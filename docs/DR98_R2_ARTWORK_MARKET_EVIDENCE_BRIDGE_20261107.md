# DR-98 — Continuous private R2 artwork and Market Value evidence enrichment bridge

**7 November 2026 — guarded implementation, staged pending CI and production activation.**

## 1. What is being built, and why

DR-96's six game-specific release scouts already publish verified immutable catalogue generations to Cloudflare R2. App rows for these newer catalogues correctly show `image_url = null` and `market_value_minor = null` until an exact printing and legitimate market evidence can be demonstrated. For most new games, an approved per-print commercial image source and UK **sold** comparable evidence are not yet connected. DR-97 keeps the original Pokémon/One Piece/Naruto/Dragon Ball feeds running, but its SQL bulk imports currently defer above the existing 400 MB Supabase safety threshold. Riftbound additionally requires Riot official API approval.

DR-98 is a **real, persistent evidence/worklist stage**, not a claim that pending images or prices have magically been resolved. Every 15 minutes, six separate signed n8n workflows ask Railway FastAPI to prepare bounded, private R2 candidate batches for the currently published provider generation. The backend validates source identity against the authorised PostgreSQL manifest pointer, verified R2 content SHA-256 and the source permission record, derives each exact stable reference key, and writes content-addressed, fully readback-verified **private worklists** with card number, set, finish, language, release date and necessary independent proofs. No bulk SQL data or new ownership/market price writes are needed.

## 2. Connections and exact outputs

`DR96 source check → source's immutable R2 snapshot + tiny authenticated SQL manifest pointer → DR98 signed n8n 15-minute schedule → FastAPI catalogue_enrichment.run_batch → checked R2 source shards → immutable private R2 evidence worklists → future vetted artwork/UK sold-data workers → separately approved D1/public image and value projections`.

The existing app already reads the DR96 verified catalogue metadata. DR98 does **not** rewrite canonical cards, conditions or founder-owned inventory.

Each output worklist record has a canonical exact-source `reference_key`, source `provider_id`, product type, set, card number, language, finish, rarity and release date, plus explicit `identity_state`, `artwork_state=NEEDS_EXACT_PRINT_AND_COMMERCIAL_RIGHTS_PROOF`, and `market_state=NEEDS_EXACT_UK_SOLD_EVIDENCE`. Every output is tied to the current immutable source manifest digest and exact source part ordinal/hash. Source permission reference is **metadata access provenance, not artwork reproduction permission**. Raw/graded photos are never substituted for each other.

DR98 processes **up to 6 source shards per invocation** (up to 3,000 cards) per game; by iterating deterministically through a 15-minute UTC slot it eventually covers all shards without n8n mutable cursor state or SQL tables. For MTG's ~154k existing metadata records, this yields a full cycle in roughly 13 hours if scheduled runs and provider/R2 integrity checks succeed. Duplicate deliveries produce the same content SHA-256; older generations remain immutable and harmless. A publication change mid-run suppresses any live success receipt. Only content hashes and bounded counts go back to n8n (not card records, images or private owner data).

## 3. Existing image and pricing pipelines

- **Artwork:** DR-94 remains the sole already-active publisher for previously rights-approved canonical media mirrors; DR-95 is a separate inactive delegating control. DR-98 never downloads YGOPRODeck/Lorcana/MTG/sports artwork or guesses which alt-print a source image represents. The Cloudflare artwork D1/Worker implementation from PR #968 remains **private staging only** and Worker public deployment is not verified. Exact-print image rights, per-image SHA-256, published rights attestations and real slab photographs are required before a live image may be shown.
- **Market Value:** The existing deterministic pricing engine remains authoritative for data-backed UK sold prices. No marketplace asking, retail price/RRP, provider `set_price` or unsupported guessed "guide" is promoted as Market Value. DR-98 prepares **the missing-evidence queue**; it doesn't query a new market data provider, invent sold observations or set `market_value_minor`. Independent, approved sold-data adapters still need to be connected for the new games.
- **Legacy four games:** DR-97 continues using original source adapters. PostgreSQL capacity was last 430,484,627 bytes, above the 400 MB bulk-refresh pause; DR-98 cannot bypass that guard. Full legacy R2/D1 catalogue and price migration is a separate controlled task.
- **Riftbound:** DR-97 is active as approval readiness only. Riot needs an approved app-specific API key or written licence; DR-98 does not generate Riftbound metadata or art without that approval. See [Riot's official policy](https://developer.riotgames.com/docs/riftbound).

## 4. Failure points and test gates

1. **Spoofed n8n command** → existing HMAC body verifier rejects request; strict source enumeration, no arbitrary URL or path.
2. **Wrong source manifest, unapproved provider, partial R2 shard or SHA error** → no accepted worklist receipt; existing publication stays untouched.
3. **R2 write/readback fails** → 503/retry, no metadata/image/price publication; already staged private objects stay content-addressed.
4. **Source switches generations during a batch** → `STALE_GENERATION_PRIVATE_ONLY`, no accepted current batch. Safe to replay after the next slot.
5. **Missing set/card number or figure edition** → `IDENTITY_REVIEW_REQUIRED`; never claim exact print matching or use a raw image for an actual slab.
6. **Missing commercial image rights or verified sold evidence** → explicit pending states, **not** a guessed placeholder or guide price.
7. **n8n activation version/backup/DR90 drift** → separate fail-closed `guarded-enrichment-publish.cjs` with six exact workflow hashes, offline persistent SQLite backup, complete readback and idempotent retries. DR90–97 existing workflows remain untouched.

Local/CI: `PYTHONPATH=backend pytest -q tests/test_dr98_enrichment.py tests/test_dr96_release_scout.py tests/test_n8n_workflow_registry.py`, whole backend suite, production predeploy suite; pinned `n8n:2.32.6` offline activation smoke via `tests/n8n_enrichment_publish_smoke.cjs`.

## 5. Deployment, next gates and rollback

Merge only if full CI green; Railway API must deploy healthy before switching on n8n. Add six inactive DR98 definitions to the existing additive n8n importer, then explicitly set `DROP_RATE_N8N_ENRICHMENT_PUBLISH_ON_BOOT=true` on the n8n service, verify backup/readback/published state, and reset the flag to false without unpublishing the six schedules. Observe at least one **real signed live** `PRIVATE_ENRICHMENT_WORKLIST_VERIFIED` receipt with R2 digests; otherwise treat this as activated schedules but not a verified completed batch.

**Remaining to fulfil the owner's full requirement:** deploy the private Cloudflare D1 artwork Worker with scoped bindings/credential and source rights approval, build per-print image licence/identity attestations, connect verified UK sold observations and a deterministic pricing decision worker for these R2-first cards, then expose reviewed media + eligible Market Value to signed-in app users. Never call a task complete because a pending-evidence worklist exists.

No Shopify auto-creation of a new reference card. Only an approved, owner-linked physical Inventory ID with actual photographs can become a sellable product.
