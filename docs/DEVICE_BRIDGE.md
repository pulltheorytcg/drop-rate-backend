# Drop Rate Device Bridge

Status: architecture contract
Updated: 2026-09-28

## What we are building

A local companion application called the Drop Rate Device Bridge.

The bridge is the only component allowed to talk directly to local scanners and printers. The web dashboard and FastAPI backend create deterministic jobs and consume results; they do not contain USB/TWAIN/printer-driver logic.

Initial hardware scope:

- document/card scanner capture;
- thermal inventory-label printing;
- ordinary system-printer fallback for PDF labels.

Later scope:

- shipping/pick-pack labels;
- receipt printers if operationally useful;
- additional scanner SDKs / feeder integrations.

## Why it belongs

Fast intake is only valuable if the physical card can be tracked after recognition.

A printed inventory label can bind:

physical card -> Inventory ID -> owner -> storage location -> Shopify listing -> sale -> settlement.

This reduces picking errors and is especially important once inventory reaches thousands of cards.

## Architecture

### FastAPI / PostgreSQL

FastAPI owns deterministic print-job rules.

PostgreSQL stores auditable job state and never stores unnecessary device secrets.

Proposed entities:

- device_registrations
- print_profiles
- print_jobs
- print_job_attempts

Print-job lifecycle:

QUEUED -> CLAIMED -> PRINTED

Failure path:

QUEUED/CLAIMED -> FAILED -> RETRY_QUEUED

Explicit operator action is required for a duplicate/reprint after a job has reached PRINTED.

### Device Bridge

The bridge runs locally on the workstation connected to hardware.

Responsibilities:

- discover supported local printers/scanners;
- expose only safe device metadata to Drop Rate;
- claim jobs scoped to its authorised location;
- render/send printer-native output;
- capture scanner frames/files;
- report deterministic success/failure telemetry;
- operate safely through intermittent internet connectivity.

The bridge must never contain pricing, ownership, settlement or catalogue business rules.

### Browser

The dashboard can:

- choose an approved printer profile;
- preview a label;
- queue a print;
- show printer/bridge status;
- request an explicit reprint.

The browser must not speak directly to local printers as the primary architecture. Browser-only USB APIs are too inconsistent across desktop/mobile browsers for a core operational workflow.

## Printer strategy

Use a driver abstraction.

Initial adapters should support:

- ZPL-capable thermal printers via raw/system queues where available;
- Brother-style raster/system-printer paths;
- generic PDF/system-printer fallback.

Printer brands and command languages must remain adapters so hardware can be replaced independently.

Do not assume one vendor.

## Inventory label v1

Minimum label payload:

- Drop Rate logo / short brand mark where label size permits;
- Inventory ID / inventory code;
- scannable QR or Code 128 representation of Inventory ID;
- card name;
- card number;
- language;
- condition;
- owner-safe short identifier if operationally required;
- optional storage location.

Do not print acquisition cost, settlement data, personal consignor data, secrets, or unnecessary financial information.

## Security

- bridge registration requires authenticated platform-admin approval;
- device credentials are scoped and revocable;
- jobs are scoped to an owner/location/profile;
- server generates immutable payload hashes;
- claim/complete calls are idempotent;
- the bridge cannot alter inventory ownership or prices;
- every reprint is auditable;
- secrets are never embedded in label payloads.

## Failure points

Required handling:

- printer offline;
- printer renamed/removed;
- wrong paper/profile;
- bridge disconnected;
- job claimed then workstation crashes;
- duplicate network delivery;
- operator double-click;
- printer reports success but paper jams;
- reprint requested after successful print;
- device assigned to wrong location.

A claimed job must lease for a bounded period and return to retryable state if the bridge disappears before completion.

## Testing

Before live hardware use:

- unit tests for label payload generation;
- idempotency tests;
- duplicate-print prevention tests;
- claim lease expiry tests;
- role/location isolation tests;
- explicit reprint audit tests;
- offline/retry simulations;
- snapshot tests for ZPL/PDF output;
- scan printed barcode/QR back into Drop Rate and verify the exact Inventory ID;
- hardware smoke tests on at least two different printer families.

## Build order

1. backend print-job domain and audit trail;
2. label preview/rendering;
3. desktop bridge authentication and heartbeat;
4. one thermal-printer adapter plus PDF fallback;
5. inventory intake -> optional auto-queue label;
6. scanner capture in the same bridge;
7. batch workflows;
8. shipping/pick-pack labels.

No automatic printing should be enabled until duplicate prevention and reprint audit are proven.
