## What is changing?

- 

## Architecture / business-rule impact

- What does this connect to?
- Does it change source-of-truth boundaries?
- Does it change ownership, pricing, finance, identity, inventory state or external integrations?

## Failure modes reviewed

- [ ] Invalid input
- [ ] Duplicate/retry/idempotency
- [ ] Stale version / concurrent write
- [ ] Permission / RLS / ownership boundary
- [ ] External provider failure
- [ ] Partial failure / rollback
- [ ] Historical/audit integrity
- [ ] Not applicable (explain below)

## Tests

- [ ] Targeted tests added/updated
- [ ] Full pytest suite passes
- [ ] Python compile check passes
- [ ] Migration tested/reviewed if applicable
- [ ] Production smoke/invariant checks completed if applicable

## Production verification

- Deployment:
- Health/readiness:
- Live invariant checks:
- Rollback / recovery plan:

## Release decision

- [ ] Safe to merge
- [ ] Feature remains deliberately gated
- [ ] Known limitations documented
