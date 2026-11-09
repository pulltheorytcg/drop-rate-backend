# 9 November 2026 — Verify the *current* original-game and Magic R2 catalogues

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## 1. What is built and why

Read-only source proof is refreshed for all four original TCG families — **Pokémon, One Piece, Dragon Ball Super Masters/Fusion World, and Naruto Bandai Legacy/Kayou** — as well as **Magic: The Gathering**. These games were already present in the live catalogue, but the migration's static source pins were stale.

Verified on 9 Nov by read-only queries of live Supabase: `tcg.reference_cards` totals **69,867** records across exactly these four game families: Pokémon 37,068, One Piece 9,007, Dragon Ball (Masters 9,031; Fusion World 7,595) 16,626, Naruto (Bandai 4,487; Kayou 2,679) 7,166. Counts are **reference cards**, not unique physical inventory items, graded variants, Shopify listings, market prices or proof of licence to reproduce images.

The current `tcg_private.live_catalogue_r2_publication` independently reports a published, immutable R2 generation **122674**, with five owner-free relation counts: `reference_cards=69867`, `reference_sets=1473`, `reference_sealed_products=3893`, `catalogue_products=2062`, `catalogue_product_profiles=2062`: **79,357 typed rows**, **161 parts**, **29,886,526 raw bytes**. The exact compact JSON (alphabetical key order) manifest SHA256 computed from its registry metadata is `977c9d114cf1aa96225e14bf5f76144cfd60ad2d85dffd82987e1197fdd4ef35`. This is registry evidence only; independent readback of **all original R2 object bytes and per-relation row SHA** is still required.

The previous D1 importer and preflight expect generation 122500 with **69,697 cards, 1,472 sets and 79,186 typed rows** — **170 card records and one set behind** the current live R2 source. The first proof step must not pretend this older import is complete. This PR updates **only the signed, read-only exporter and source preflight**, not the D1 write/import constants or Cloudflare database.

Magic: active `mtgjson/English` R2 generation 2 contains **153,679 reference records**, **151,609 released**, **98,902,731 raw bytes**, immutable manifest SHA `e3bda5f54affe0055ec64d7ffb943cb5cae23df8108e74f29e250f7ec63e662a`. The old read-only importer/preflight expected 153,662 and old SHA `be5af...`. This PR repins only the Magic **source verification job**, while the follow-on D1 writer stays pinned to its older approved SHA until full R2 evidence verifies the refresh and staged source generation design is reviewed.

## 2. Connections

Authenticated protected GitHub main-branch OIDC → existing exact read-only FastAPI private R2 export → R2 snapshot manifests, **every** 161 legacy part + Magic source part → payload/hash/identity validation → count-only and hash-only CI artifacts/commit receipts. Existing Supabase publication registry still controls approved source; no new secrets, public routes, R2 keys, market valuation or owner data exposure.

## 3. Failure points

Changed legacy manifest/generation/count/bytes/part SHA, missing R2 part, changed identity, duplicate source rows, insufficient OIDC signature/RLS, Magic source SHA mismatch, unreleased Magic printing, or unapproved provider/licence must fail closed. Existing protected read-only jobs must print evidence only after real R2 bytes are verified; **no protected D1 token** is present in source-preflight workflows. Do not repin live D1 financial/customer/inventory code or install a new catalogue serving path.

## 4. Testing

Tests require exact legacy generation and source SHA even in synthetic mock transport, blocked corruption and forged claims. The existing Magic source SHA/scope tests remain. All backend/PostgreSQL, n8n/dashboard, Magic and legacy offline CI must pass; only protected main-run R2 audit proves the exact current object bytes. This is a **two-stage** migration change: after source CI passes, use its independently verified five relation digests to repin the write-capable legacy D1 importer **in a separate reviewed PR**. D1 import must have protected release SHA/run approval and all required immutability/parity/rollback protections; it must not be blocked solely because an unrelated Magic queue is incomplete. The Magic follow-on writer also requires a separate source-verified current-generation review.

## Extra release protection

The original `d1-legacy-r2-shadow.yml` and `d1-followon-r2-shadow.yml` workflows could previously run their write-capable D1 jobs from ordinary main pushes or schedules once their preceding source guards cleared. Both now additionally require a *separately managed GitHub Actions repository variable pair* matching the exact current commit and **the exact GitHub run ID**: `DR_D1_LEGACY_IMPORT_APPROVED_SHA`/`DR_D1_LEGACY_IMPORT_APPROVED_RUN_ID`, and `DR_D1_FOLLOWON_IMPORT_APPROVED_SHA`/`DR_D1_FOLLOWON_IMPORT_APPROVED_RUN_ID`. None is set by this change. A merged preflight update will **not** stage any D1 rows automatically. Read-only audit jobs still run.

## 5. Safety and rollback

No Supabase mutation, source deletion, owner/financial/Shopify writes, Cloudflare plan change, D1 import, web path cutover or settlement. If source proof fails or a publication advances again, keep existing Supabase/R2 serving and do not stage D1. Revert these read-only pins if necessary. Retirement gates A–H remain **NO-GO**.
