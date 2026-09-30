# PSA certificate lookup Railway prototype

This source file mirrors the retained Railway service `psa-fetch-batch`.

## Purpose

Read-only PSA certificate verification and exact provider evidence for graded-card operations.

It does **not**:
- create or update inventory;
- decide canonical card identity;
- approve graded media;
- publish Shopify products;
- close Action Required items.

## Current PSA contract

The PSA Public API currently documents:
- base path: `https://api.psacard.com/publicapi/`;
- cert lookup: `GET cert/GetByCertNumber/{cert}`;
- authentication: `Authorization: bearer <access token>`.

The Railway service requires a dedicated `PSA_PUBLIC_API_TOKEN`.

Production audit on 30 September 2026 confirmed no PSA-specific credential is currently configured on `drop-rate-api-live`; the old prototype incorrectly referenced `TCG_PARSE_API_KEY`, which is not a PSA credential and produced HTTP 403 responses from PSA.

Do not reuse unrelated provider secrets. Until a valid PSA Public API bearer token is configured, the lookup service must return `503 PSA_PUBLIC_API_TOKEN_REQUIRED` rather than pretending certificate verification is operational.

## Endpoint

`GET /`
- no query: runs the retained diagnostic batch;
- `?cert=62398872`: runs one read-only cert lookup.

The response is normalized provider evidence. Exact catalogue matching remains a FastAPI/Postgres responsibility.

## Media rule

A successful cert lookup does not imply that PSA provides exact slab scans. If no exact front/back image URL exists, `GRADED_SLAB_MEDIA_REQUIRED` remains open.

## Future

After the storefront stability gate explicitly reopens graded-scanner work, move this provider logic into the common graded-certificate adapter contract documented in `docs/GRADED_SLAB_SCANNER_ARCHITECTURE.md` and retire the standalone Railway Function.
