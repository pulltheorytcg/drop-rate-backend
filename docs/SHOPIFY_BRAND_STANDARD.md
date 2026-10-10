# Drop Rate Shopify listing standard

The seller explicitly requires Shopify images and copy to remain consistent with the existing Drop Rate catalogue. This is a publication requirement, including seller-held stock. The current live product conventions are the baseline; a new product is not permission to introduce a new visual style or launch a theme redesign.

## Copy

- Use the shared product-type renderer in `backend/app/shopify_completeness.py`. Sealed titles use the verified product name followed by the existing middle-dot language suffix, for example `Booster Pack: World's Strongest Warriors [OP-17] · JP`. Card titles retain the established name, language, number, set, variant and condition structure. Pooled-card descriptions retain their explicit pooled-copy wording.
- Keep the existing factual description structure and consistent field labels for each product type. Use verified catalogue and inventory facts. Do not import supplier marketing text or add one-off AI sales copy, unsupported rarity/value promises, guaranteed pulls, invented contents, condition or provenance.
- Generate SEO and metadata from the same verified fields. Future wording improvements must be reviewed as a shared template change against representative existing listings, rather than changing one new listing's voice in isolation.

## Images

- Use the exact approved catalogue product image or the physical photos required by the item's media policy. The game, product, language, printing and packaging must match; a box, English release or similar-looking pack is not a substitute for a Japanese single pack.
- Match the existing product-led presentation: centred artwork or product photography, full product visible, readable packaging and a clean white or transparent background. Preserve aspect ratio and let the established theme frame the image. Do not add promotional badges, decorative scenes or extra logos, crop identifying details, remove publisher sample marks, or generate replacement product artwork.
- Preserve the distinction between official reference artwork and photographs of the seller's physical copy. Canonical art does not replace required slab/condition evidence. Media source, rights, exact identity, approval and READY Shopify file checks still apply.
- The Shopify gallery must match the approved media selection exactly. Missing or unexpected media blocks publication; do not silently delete unexpected Shopify files to make the check pass.

## Enforcement and review

The normal publisher writes a draft from the shared plan, reads it back and verifies title, description, SEO, tags, product type, theme template and exact media IDs before publication. It checks the final active product again and returns it to draft on mismatch. These are deterministic checks, not an automated claim that any newly approved image has passed visual brand review. Compare new image treatments with existing products during approval.

On 10 October 2026 the OP-17 draft was compared with live Japanese Premium Card Collection -6 assort vol.1- and Tin Pack Set Vol.2 Portgas.D.Ace listings. All three use the same sealed copy renderer and language suffix. Their source images were inspected: the existing products use white/transparent backgrounds and product-led framing; OP-17 uses the complete official pack on transparency. Existing card samples also retain the shared title conventions. This is a representative consistency review, not a claim to have visually audited the entire store.

Regression coverage rejects changed titles, descriptions, SEO and missing/additional media. Publication-service tests require a matching draft and final readback. The [seller-held publication evidence](SELLER_HELD_SEALED_PUBLICATION.md) records the live stock and release checks separately.
