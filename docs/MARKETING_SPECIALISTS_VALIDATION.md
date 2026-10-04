# Marketing specialists: verified checkpoint — 4 October 2026

## Result

The separate-specialist implementation in PR #514 passed its isolated backend, PostgreSQL and actual n8n workflow tests. It has **not** been merged, deployed, migrated into production or activated. No real model, Higgsfield, Buffer, Shopify or social-platform call was made by these tests.

Verified code commit: `a8479845339241f0a174e3916cf7d27eeac304ec`.

- Backend checks run `37180606848`: **SUCCESS**.
- Marketing specialist integration run `37180606781`: **SUCCESS**.
- PostgreSQL integration job `111372245393`: **SUCCESS**.
- n8n import/execution job `111372245490`: **SUCCESS**.

Later documentation-only commits do not change the tested runtime. Current-head CI and production rollout must still be read back before release.

## What passed

The targeted Python suite covers role registration, separate prompts, closed schemas, evidence/metric references, actor checks, unsigned/tampered/oversized requests, feature gates, upstream review, duplicate calls, conflicting snapshots, model refusal/malformed output/HTTP errors/timeouts and the blocked publisher. Generated Code-node checks execute the actual signers, identifier verifier and handoff gates, including the JSON request-mode regression.

The full backend suite, dashboard UI checks, JavaScript syntax, Python compilation and pinned n8n image build passed through normal Backend checks. This is not a claim that unrelated production workflows were retested with real customers.

Disposable PostgreSQL 17.6 applied the exact canonical migration and tested the actual PostgresStore: RLS enabled/forced, denied public grants, platform-admin and actor isolation, immutable job/result history, replay, an eight-way concurrent race producing exactly one execution claim, abandoned-run UNKNOWN recovery and protection against late completions. Foundational auth/owner tables were fixtures. No production Supabase data was touched.

Actual n8n 2.32.6 imported all seven committed workflow exports and read them back with matching IDs, nodes, connections and settings while inactive. The isolated test then published the n8n workflow versions inside its disposable database, because CLI subworkflow execution uses published versions. No production workflow was published or activated.

With all external network access disabled and only a local signed HTTP fixture available, the actual n8n runner verified:

1. Research → brief → copywriting → design calls reached the signed backend fixture in order, and the result stopped at AWAITING_MEDIA.
2. A NEEDS_REVIEW result stopped before the next specialist; later stages were not called.
3. The publishing child returned BLOCKED; it did not contact a social provider.

The fixture verifies HMAC against the actual received bytes and echoes the exact job/revision/stage identifiers. It stands in for the backend, not a live model. The PostgreSQL and n8n tests are separate integration tests, not a claim that an actual research-to-public-post campaign ran.

## Issues found and corrected

The first CLI test rejected inactive child workflows. Exact n8n source confirmed CLI execution resolves published child versions. Only the disposable fixture versions are now published for the execution test; source exports and production remain inactive.

The next test reached the backend but failed the response identity guard. Exact n8n HttpRequestV3 source showed raw request mode disables JSON decoding. The generator and committed exports now use JSON body mode, and both byte-level signature checks and returned-identity checks pass. No guard was weakened to make the test pass.

## Live state and next steps

The six roles and coordinator are implemented in the feature branch. The current production services still run the earlier release. The additive Supabase migration remains unapplied, the feature flags remain off, and no real model request has been tested.

Before enabling preparation: review and apply only the canonical additive migration; deploy the existing API/n8n services; confirm SUCCESS, health and actual inactive workflow imports; verify error routing for the new workflow IDs; then perform one bounded authenticated live-model preparation test. Keep recurring scheduling off.

Current first-slice limits remain intentional: research consumes supplied evidence, design creates a layout/storyboard rather than finished media, and social management consumes supplied metrics. Automatic source/metric feeds and rendering are not implemented.

The publishing role is a hard-blocked boundary, not a finished Buffer publisher. The founder's approved media, immutable asset approval, per-platform publication claims, the real Buffer write adapter and delivery reconciliation remain necessary before the immediate publishing pilot. Approved media by itself does not complete those missing components. Do not publish the rejected drafts or claim a manual Buffer post proves n8n.

No new Railway services, paid-plan purchase, credential rotation, production inventory/ownership/price/finance change or usage-limit increase occurred. The Railway coding agent exhausted its existing allowance; direct GitHub implementation continued without raising that limit.

Rollback after a later release means disabling the specialist flags and reverting code while retaining durable history and existing n8n data—not deleting tables, workflows, drafts or social posts.

## Production migration checkpoint — 4 October 2026, 13:33 UTC

The reviewed migration is now applied as `20261004133308_marketing_specialists_v1`. Read-back verifies forced RLS and narrow grants; both new tables are empty. Earlier unapplied statements above are historical. Runtime deployment and an actual authenticated backend/model probe are still pending. A connector SET ROLE test was refused before any test insertion; do not claim it passed or broaden role membership to bypass it.
