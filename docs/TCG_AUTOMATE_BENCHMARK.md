# TCG Automate Benchmark and Drop Rate Competitive Target

Status: architecture / product benchmark
Updated: 2026-09-28

## Purpose

TCG Automate is the current operational benchmark for fast TCG image-to-listing workflows. Drop Rate should match the useful parts of that workflow and exceed it in exact-printing recognition, UK-first pricing, ownership accounting, consignments, auditability, and marketplace settlement.

This document is a benchmark, not a dependency. Drop Rate must remain modular and must not copy proprietary implementation details.

## Publicly documented TCG Automate capabilities

Public product/docs pages currently describe:

- card-image recognition feeding listing-ready batches;
- direct desktop scanner capture into a live batch workflow;
- batch review/correction before publishing;
- exact-printing search/selection in quick-list workflows;
- stock-image listing support;
- managed cross-listing / quantity synchronisation on supported plans;
- scheduled repricing for connected marketplaces;
- integrations/workflows for eBay, Shopify and other marketplaces.

Sources:
- https://www.tcgautomate.com/
- https://www.tcgautomate.com/docs/desktop-app
- https://www.tcgautomate.com/features
- https://www.tcgautomate.com/docs/quick-list
- https://www.tcgautomate.com/docs/automatic-repricing

Printer connectivity is not treated as a verified TCG Automate fact here because no current public printer-specific documentation was found during this review.

## Drop Rate competitive requirements

### Recognition v2

Recognition must stop relying on one general-purpose vision model as the primary matcher.

Target pipeline:

1. capture / scan
2. deterministic image normalisation
3. exact-printing visual retrieval
4. OCR and visible-text extraction
5. game-specific evidence extraction
6. candidate generation
7. deterministic exact-printing reranking
8. AI ambiguity resolution only when needed
9. human correction for unresolved cases
10. verified-learning feedback

The canonical identity hierarchy is:

gameplay identity -> card number -> promotion/reprint family -> exact artwork/printing -> language -> finish -> physical inventory item.

A shared card number must never imply a shared collectible printing.

### Recognition benchmarks

Track independently:

- gameplay identity top-1 accuracy;
- exact-printing top-1 accuracy;
- top-3 recall;
- language accuracy;
- finish/variant accuracy;
- false auto-approval rate;
- median latency;
- P95 latency;
- mobile capture-to-result latency;
- human correction rate.

No confidence percentage may be inflated to look better. Confidence must correspond to measured evidence and calibrated evaluation data.

### UK-first pricing advantage

Drop Rate pricing should prioritise permitted UK-relevant market evidence, including eBay UK sold data and Cardmarket where permitted/available, rather than following one US-centric market source.

Pricing remains deterministic and auditable. Recognition confidence and pricing confidence are separate concepts.

### Ownership / settlement advantage

Every recognised physical item must resolve to one Inventory ID and one owner. Marketplace automation must preserve:

Order -> Order Item -> Inventory -> Owner -> Fees/Commission -> Net Proceeds -> Settlement.

This is a core Drop Rate differentiator and must not be diluted by batch/listing convenience.

## Immediate implementation order

1. promotion-aware exact-printing catalogue;
2. verified canonical image registry;
3. persistent visual fingerprints / embeddings per exact printing;
4. fast nearest-neighbour retrieval;
5. game-specific evidence adapters;
6. top-3 correction UI;
7. benchmark/evaluation harness;
8. batch scanning and desktop capture;
9. Device Bridge hardware integration.

## Non-goals

- scraping data or imagery without permission;
- allowing AI to silently create or overwrite canonical identities;
- automatically publishing uncertain/high-value cards;
- treating provider image similarity as proof of exact printing;
- coupling scanner/printer drivers to FastAPI or the browser.
