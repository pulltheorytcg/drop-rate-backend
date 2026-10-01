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
