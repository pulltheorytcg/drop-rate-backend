# Social market evidence probe — 5 October 2026

This is a bounded, read-only research tool for the two approved Drop Rate social-content examples. It does not mutate inventory, catalogue, pricing snapshots, market observations or Shopify.

Targets:
- Umbreon VMAX 215/203, English, raw/ungraded;
- Umbreon VMAX 215/203, English, PSA 10;
- Son Goku FB01-139 official printing `_p2`, English, Super Alternate Art / SCR-double-star, raw/ungraded;
- the same Son Goku printing, PSA 10.

Identity comes from the existing reference corpus. Son Goku `_p2` is deliberately separated from the much cheaper ordinary SCR-star alternate art. Seller wording is inconsistent, so the p2 matcher requires a strong super-print marker such as "Super Alt Art", "Super Alternate Art", "God Rare/GDR", "2 Star/Double Star", or "Ghost"; "Alternate Art" by itself is insufficient.

The provider is the already-configured Trawl eBay UK sold-data API. Only exact English, single-card results are eligible. Raw buckets reject grading terms; PSA 10 buckets require both PSA and 10. Results are deduped by provider item ID and sorted newest-first.

A poster value is produced only when at least five exact comparable sold records survive. The market figure is the median of those five sale prices; shipping is retained separately and excluded from the median. Fewer than five returns `INSUFFICIENT_EVIDENCE`.

GBP is the observed market currency. USD is an auditable equivalent derived from the official ECB USD→GBP reference rate retrieved at run time; it is not a second market claim.

The operator script is `backend/scripts/social_market_evidence_probe.py`. It writes no database rows and prints only the selected evidence summary. It is intended for one-off execution through the existing API service runtime so credentials never leave Railway. Remove any temporary pre-deploy command immediately after the evidence run.
