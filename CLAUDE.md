# CLAUDE.md — Drop Rate Engineering Safety Contract

This repository powers the Drop Rate production TCG marketplace.

Claude may assist with architecture, code, tests, documentation and diagnostics, but must follow these rules.

## 1. Read before writing

Before changing anything:
- read `BUILD_STATUS.md`
- read `README.md`
- read the relevant files under `docs/`
- inspect recent Git history
- inspect tests covering the area
- verify the current live state before assuming documentation is exact

Do not treat this as a greenfield project.

## 2. Production safety

Do not perform destructive or difficult-to-reverse production actions without explicit human approval.

Never:
- drop or truncate production tables
- delete production rows to "clean things up"
- rewrite ownership history
- rewrite financial ledger history
- delete historical market observations
- reset production databases
- disable RLS
- weaken authentication or webhook verification
- disable audit logging
- overwrite secrets
- rotate credentials without approval
- force-push `main`
- bypass CI/tests
- bulk publish inventory
- automatically move real money
- infer ownership from Shopify/eBay data alone
- bulk confirm uncertain card identities
- approve uncertain/high-value recognition results
- auto-approve unverified media

If a task appears to require one of these actions, stop and explain why.

## 3. Source of truth

- PostgreSQL/Supabase is the master source of truth.
- FastAPI contains deterministic business rules.
- Shopify is storefront/cart/checkout/order surface.
- n8n is orchestration only.
- AI can assist, but cannot silently override deterministic rules.

Do not move ownership, pricing, settlement or identity integrity rules into frontend code, Shopify, n8n or prompts.

## 4. Database changes

Schema changes must:
- be version-controlled
- use the canonical migration path
- preserve RLS/security
- be reproducible
- be tested
- be reversible where practical

Do not manually change production schema without a matching migration.

Prefer read-only inspection during onboarding/debugging.

## 5. Git workflow

Prefer:
feature branch → implementation → tests → PR → CI → deployment → verification

Do not overwrite another agent's work.

Always inspect latest `main` before editing.

For small documentation-only changes, direct main commits may be acceptable if current project practice explicitly allows it; otherwise use a branch/PR.

## 6. Supabase

When connected to Supabase:
- default to read-only inspection
- never expose service-role keys
- do not run destructive SQL
- do not mass-update production rows without explicit approval
- preserve auditability
- preserve historical observations
- preserve owner boundaries
- preserve RLS

For data corrections:
- identify exact affected rows first
- explain intended mutation
- make the smallest possible change
- verify afterwards

## 7. Railway

When connected to Railway:
- inspect deployments/logs/configuration safely
- do not delete services/environments
- do not replace environment variables blindly
- do not expose secret values in chat/logs
- do not trigger production deploys unless the code change is intended and verified
- check health after any approved deployment

## 8. Ownership and finance

Every physical item has an exact Inventory ID and owner.

A sale resolves:
Order → Order Item → Inventory ID → Owner → Fees/Commission → Net Proceeds → Settlement.

Never:
- merge physical inventory ownership for presentation convenience
- change owner silently
- infer owner from product title
- modify settlement/ledger rows to make totals "look right"

Financial calculations must remain deterministic and auditable.

## 9. Recognition

Card identity and exact printing are separate.

Never substitute:
- base art for promo art
- one parallel for another
- a standard card for ROUND1/release-event/regional/stamped treatment
- English artwork for Japanese exact-print proof

Low-confidence/high-value/conflicting results remain human-reviewed.

Only verified/confirmed media and scans may become trusted recognition/fingerprint/training evidence.

## 10. Media

Canonical artwork and physical inventory photos are different.

For graded cards:
- canonical art = identity/reference
- slab FRONT/BACK = physical customer-facing evidence

Do not generate fake slab images.

Respect media rights and provenance.

## 11. Shopify

Backend/Supabase remains authoritative.

Shopify automation must:
- use exact Inventory ID/SKU linkage
- be idempotent
- verify remote writes
- fail closed on ambiguity
- archive/zero exact sold inventory safely

Do not bulk-publish uncertain stock.

## 12. n8n

n8n is orchestration.

It may:
- receive events
- schedule jobs
- call FastAPI
- call approved external services
- route exceptions/notifications

It must not:
- become the database
- calculate settlements
- decide ownership
- determine final pricing
- bypass publication gates
- silently mutate canonical identity

## 13. Testing requirements

For meaningful changes test:
- happy path
- duplicate/retry
- stale version
- wrong owner
- race/concurrency risk
- external provider failure
- invalid provider data
- partial failure
- idempotency
- rollback/fail-closed behavior

Do not only make the visible test pass.

## 14. Before implementing any feature

Explain:
1. what is being built
2. why it belongs
3. what it connects to
4. failure points
5. how it will be tested

## 15. Completion

A feature is not "done" merely because code exists.

Where applicable:
- code complete
- tests pass
- migration applied
- deployment succeeds
- health checks succeed
- live state verified
- documentation/build status updated

## 16. When uncertain

Stop, inspect, and ask rather than guessing.

Production correctness is more important than speed.
