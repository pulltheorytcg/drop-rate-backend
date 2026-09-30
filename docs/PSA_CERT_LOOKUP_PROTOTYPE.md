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

The Railway service reads `PSA_PUBLIC_API_TOKEN` if introduced later and falls back to the legacy existing secret name `TCG_PARSE_API_KEY` so the compatibility repair can be deployed without exposing or copying the token.

## Endpoint

`GET /`
- no query: runs the retained diagnostic batch;
- `?cert=62398872`: runs one read-only cert lookup.

The response is normalized provider evidence. Exact catalogue matching remains a FastAPI/Postgres responsibility.

## Media rule

A successful cert lookup does not imply that PSA provides exact slab scans. If no exact front/back image URL exists, `GRADED_SLAB_MEDIA_REQUIRED` remains open.

## Future

After the storefront stability gate explicitly reopens graded-scanner work, move this provider logic into the common graded-certificate adapter contract documented in `docs/GRADED_SLAB_SCANNER_ARCHITECTURE.md` and retire the standalone Railway Function.
