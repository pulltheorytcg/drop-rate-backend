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

## Current direction

Founder approval explicitly reopened this bounded provider-gateway slice on 1 October 2026. The common source-controlled FastAPI adapter contract is now deployed. The standalone Railway prototype remains retained for reference/diagnostics until its dependencies are checked and a deliberate retirement or rename is approved.


## 1 October 2026 gateway update

The source-controlled application now has a common grading-certificate lookup gateway at:

- `GET /api/v1/grading-certificates/status`
- `POST /api/v1/grading-certificates/lookup`

PSA is the only automated provider in this first slice because PSA documents a Public API for single-cert lookup. The main API expects a dedicated `TCG_PSA_PUBLIC_API_TOKEN`; it never falls back to `TCG_PARSE_API_KEY`.

Railway inspection also found that the service currently named `psa-cert-lookup-temp` is **not a PSA certificate service**: its deployed function is a Dragon Ball/CardTrader exact-media diagnostic. Do not delete it solely because of the name, but do not treat it as slab lookup infrastructure either. Rename/document it in a separate housekeeping slice after dependencies are checked.

The deployed `psa-fetch-batch` Railway function is the actual PSA prototype. Its currently deployed inline function still contains an old fallback to `TCG_PARSE_API_KEY`, while the repository mirror has already removed that fallback. Until its deployment is reconciled and a dedicated PSA token exists, scanner traffic should use the source-controlled FastAPI gateway contract and PSA automation must report unconfigured rather than claim verification.


## Production verification — 1 October 2026

PR #465 deployed successfully to `drop-rate-api-live` as Railway deployment `1f129392-00a6-45ae-8e06-65afd98479c5`.

- production pre-deploy: **2,225 tests passed**;
- application startup: clean;
- configured Railway readiness probe: `GET /health/ready` → **200 OK**;
- dedicated `TCG_PSA_PUBLIC_API_TOKEN`: **not currently configured**.

Therefore the gateway itself is production-live, while automated PSA provider calls remain deliberately fail-closed until the correct PSA bearer token is supplied.
