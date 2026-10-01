# Recognition quality benchmark

## Purpose

Drop Rate recognition is a core Seller Hub capability. The current reference corpus is large, but corpus size is not proof of exact-print recognition quality. This benchmark makes recognition improvement measurable without expanding recognition scope or weakening fail-closed safeguards.

This work is quality instrumentation only. It does not add games, add providers, change scoring weights, auto-promote models, change inventory identity, alter prices, or publish anything to Shopify.

## Ground truth

Only explicit human-reviewed recognition labels are eligible.

Evaluation uses active learning examples from:

- `VALIDATION` for tuning and comparison while developing changes.
- `HOLDOUT` for final regression evidence before a deliberate production promotion.

`TRAIN` examples are rejected by the evaluator. They may support the bounded online learning behavior already documented, but they cannot be used to claim evaluation quality.

Superseded labels are excluded. Unreviewed AI output is never ground truth.

## Metrics

The benchmark reports:

- exact-decision precision;
- exact recall against positive human labels;
- top-1 accuracy;
- unsafe exact count;
- review / no-match / failure rates;
- safe-abstention rate;
- median and P95 observed pipeline latency;
- per-game/system breakdowns;
- recurrent wrong-top / correct-truth confusion pairs;
- review/risk-flag frequency.

The primary safety target is simple: **an exact decision that human truth later disproves counts as an unsafe exact result.** `NEEDS_REVIEW` and `NO_MATCH` are deliberate abstentions, not false exact matches.

No accuracy percentage is considered trustworthy without its sample count and game/system breakdown.

## Endpoint

Platform-admin recognition users can call:

`GET /api/v1/recognition/learning/evaluation?dataset_split=VALIDATION`

or:

`GET /api/v1/recognition/learning/evaluation?dataset_split=HOLDOUT`

The endpoint is read-only and owner-scoped by the existing recognition RLS/access model.

## Improvement loop

Recognition refinement should now follow this loop:

1. collect explicit human-confirmed labels;
2. measure the existing engine on VALIDATION;
3. identify confusion pairs, frequent review gates and latency bottlenecks;
4. change one bounded recognition concern;
5. rerun unit/regression tests and VALIDATION evaluation;
6. reject changes that increase unsafe exact matches even if headline recall improves;
7. use HOLDOUT only for final evidence before deliberate promotion;
8. record the measured result in the PR / BUILD_STATUS.

Thresholds, weights or model versions must never self-promote from benchmark results. Human review remains required.

## Failure handling

The evaluator fails closed when:

- a TRAIN row is supplied;
- a row contains a non-terminal recognition decision;
- a positive label lacks catalogue truth;
- a REJECTED_ALL label incorrectly has selected catalogue truth;
- a requested split is mixed with another split.

Malformed latency values are ignored rather than affecting identity metrics.

## Testing

Regression coverage verifies:

- wrong `EXACT_CANDIDATE` decisions are counted as unsafe;
- `NEEDS_REVIEW` / `NO_MATCH` remain safe abstentions;
- TRAIN examples cannot enter evaluation;
- requested VALIDATION/HOLDOUT splits cannot mix;
- latency percentiles and per-system summaries are deterministic;
- evaluation code contains no database mutation statements;
- the API only exposes VALIDATION/HOLDOUT evaluation.

This benchmark is the measurement foundation for the recognition-quality workstream. It is not permission to expand the reference corpus before the Phase 3 gate is met.
