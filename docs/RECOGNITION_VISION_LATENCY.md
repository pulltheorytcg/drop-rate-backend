# Recognition vision transport and latency telemetry

## Purpose

Live recognition timing showed that deterministic candidate resolution is already fast while the external vision stage dominates scan latency. This slice removes avoidable HTTP connection setup and improves measurement without changing recognition semantics.

## What changes

- The API worker reuses one bounded `httpx.AsyncClient` for OpenAI recognition requests, allowing HTTP keep-alive connection reuse across scans.
- The shared client is closed during FastAPI shutdown.
- Successful Responses API calls record non-image telemetry:
  - provider request duration;
  - response ID/model;
  - input/output/total tokens where supplied;
  - cached input tokens where supplied;
  - reasoning tokens where supplied.
- Recognition persists that telemetry inside the existing `provider_evidence` JSON alongside stage timings.

No raw source image is persisted by this telemetry.

## What does not change

This release deliberately does **not** change:

- recognition model;
- prompt/instructions;
- structured output schema;
- image detail (remains `high`);
- output-token ceiling;
- recognition engine version;
- candidate weights;
- exact-match threshold;
- runner-up margin;
- language/card-number/finish/art hard gates;
- human-review behavior;
- TRAIN / VALIDATION / HOLDOUT rules.

The Responses request also does not add a reasoning-effort override. Any future model/detail/reasoning change must be measured against human-labelled evaluation evidence first.

## Failure handling

Transport reuse is process-local only. It contains no recognition result cache, so one card can never receive another card's observation through this optimization.

A closed shared client is replaced on the next request. Provider timeout, network, rate-limit and HTTP failure handling remains unchanged.

## Measurement

Use the existing recognition run `provider_evidence.timings_ms` plus the new `vision_telemetry` object to distinguish:

- end-to-end vision stage time;
- provider HTTP time;
- local parsing/validation overhead;
- token usage/cached-token behavior.

This provides the evidence required before attempting more aggressive latency changes such as prompt/output reduction, reasoning-effort changes or image-detail changes.

## 1 October 2026: measured critical path and overlapping image checks

Read-only production sample: 11 runs with stage timings averaged 23.96 seconds before persistence; vision averaged 19.90 seconds. Ten runs recorded provider-image work averaging 2.11 seconds and catalogue-image work averaging 0.68 seconds. Stage samples overlap and have different counts; do not add these averages or treat them as a before/after benchmark. Six runs with HTTP telemetry averaged 22.97 seconds at the vision provider.

Catalogue lookup and its subsequent image/learning enrichment now run as one branch beside provider-image enrichment. Previously catalogue image work waited for provider-image work even after catalogue lookup had finished. Resolution still waits for all branches and retains every existing evidence and human-review gate. Failure or cancellation cancels and awaits sibling work rather than returning partial evidence. Concurrency remains bounded by each existing image stage's four-request semaphore.

This improves the shared endpoint used by both browser portals and mobile. It does not claim to remove the dominant AI-reading delay. Changing reasoning effort, image detail, model or schema still requires a labelled photographic benchmark; historical source photos are intentionally not retained, so timing records alone cannot establish an accuracy-preserving model change.

The mobile capture path separately caps the longest edge at 1,500 pixels, matching the browser batch scanner, preserves aspect ratio and never enlarges smaller photos. A 3,000 × 4,000 portrait becomes 1,125 × 1,500 rather than 1,500 × 2,000 (43.75% fewer pixels). JPEG byte savings vary. Physical-device OCR acceptance remains required.

Validation: full backend tests, mobile typecheck/lint/tests, and Android/iOS/web bundle export. Deterministic concurrency tests prove catalogue enrichment starts before provider completion and that both branches finish before returning; tests also cover lookup/enrichment/provider failure and caller cancellation. Live latency improvement must be measured after deployment on representative scans.


## 2 October: overlapping capture presentation

The shared scanner now permits two in-flight photos, with independent pending
thumbnails, result association and errors. Auto-scan still observes physical
removal between captures. This is a batch-throughput/UI improvement, not a
per-photo vision optimisation. No model, vision prompt, image detail/resolution,
scoring threshold or evidence branch was weakened. Search corrections now use
both roles' full released catalogue; a read-only Japanese OP12-106 database probe
returned two printings in 671 ms (not an end-to-end phone timing benchmark).
The historical vision timings above remain the latest measured scan baseline.
