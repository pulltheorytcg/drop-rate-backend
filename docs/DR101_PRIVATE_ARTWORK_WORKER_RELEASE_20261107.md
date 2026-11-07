# DR101 — Deploy the existing Cloudflare artwork shadow Worker (private staging ONLY)

**7 November 2026. Scope:** close the Worker deployment/reachability gate for issue #966, without publishing card images or changing the storefront.

## What and why
The artwork-only D1 database \`drop-rate-d1-artwork-shadow-20261106\` has a verified empty schema receipt in GitHub Actions run [42308082427](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42308082427), but the existing \`cloudflare/artwork-shadow/worker.mjs\` has not been proven deployed in Cloudflare. The six DR98 private R2 evidence worklists operate independently. This release configures the **existing** Worker rather than adding infrastructure or duplicating DR94/DR95.

## Connections / boundaries
\`Backend-approved signed artwork staging receipt -> Cloudflare HMAC-only Worker -> exact existing R2 object SHA/size/WebP check -> existing private D1 STAGED_PRIVATE row\`.

The Worker has **no public image route**, no public D1 query endpoint, no Shopify writes, no SQL/Postgres writes and no permissions to alter prices, owners or inventory. The optional workers.dev hostname is network-reachable but every staging write requires HMAC; this is **application-private**, not a Cloudflare Access/private-network endpoint. Do not call it a fully private network. Do not activate DR95 or change FastAPI's existing staging secrets in this release.

## Release prerequisites (fail closed)
1. Verify the correct Drop Rate repository/Cloudflare account and GH main branch. Existing account ID is fixed to \`e4d4b363540e991048d2e1812d5ef53e\`.
2. On GitHub repository Settings, keep existing \`CLOUDFARE_D1_PILOT_TOKEN\` (historical spelling) unchanged. It is used only for D1 **read-only preflight**. Provisioning happened earlier; DR101 must not create D1.
3. Add a **separate limited-scope** Actions secret \`CLOUDFLARE_ARTWORK_WORKER_TOKEN\` with permission to deploy only this account's Worker. Never paste it into chat or commit.
4. Add an independent Actions secret \`ARTWORK_COMMAND_SECRET\` of 32+ random characters, and arrange the matching backend-only FastAPI credential after separate explicit review. No secret contents in code or logs. The Worker remains inert for real images until that signed integration is approved.
5. Set Actions repository **variable** \`ARTWORK_R2_BUCKET_NAME\` to the existing verified production R2 media bucket name. Do not create or pick a new bucket. Confirm it matches the existing \`TCG_OBJECT_STORE_BUCKET\` Railway environment variable using the authorised operational dashboard (the chat connector only reveals variable names).
6. Set repository variable \`DROP_RATE_ARTWORK_WORKER_DEPLOY_APPROVED=true\` only after reviewing 1–5. This variable alone does **not** deploy.
7. Merge this PR only after all preflight CI checks pass. Trigger workflow **DR101 guarded private artwork shadow Worker release** using GitHub Actions → Run workflow on **main**. Never run it from a PR branch.

## Automated release sequence
- CI runs existing Worker+SQLite/HMAC byte-integrity tests and the new exact-account/binding safety tests.
- The manual deploy job verifies required token separation and secret/bucket presence, then uses the already-provisioned D1 name, its actual Cloudflare UUID, exact two schema objects and read-only row count. Drift, duplicate database names, unexpected account, malformed bucket or missing permission abort before deployment.
- Generates a transient \`wrangler.generated.json\` with **only** \`ARTWORK_R2\` (explicit existing bucket) and \`ARTWORK_D1\` (exact existing D1 UUID), current \`worker.mjs\` and a fixed Worker name. No D1 or R2 resources are automatically provisioned because concrete IDs/names are present.
- Deploys with pinned Wrangler, adds \`ARTWORK_COMMAND_SECRET\` via secret store and probes GET /public/artwork/no-such-public-route for **404** and incorrect HMAC POST /v1/internal/artwork/shadow for **401**. Neither probe can stage bytes.
- Exact Worker deployment URL and Cloudflare credentials remain runtime-only; no guessing URL or claiming image availability from a healthy deploy.

## Failure cases and rollback
| Failure | Expected result |
|---|---|
| Wrong account / D1 drift / duplicated shadow | Refuse deploy, no cloud write |
| Missing Worker token / R2 bucket name / HMAC secret | Refuse deploy |
| Bad Worker token / missing Cloudflare permission | Wrangler fails, existing images and D1 source stay unchanged |
| Worker deploy succeeds but secret injection fails | HMAC route rejects all writes; stop release, repair secret (do not open a public bypass) |
| Public image route unexpectedly resolves or bad HMAC accepted | Mark release failed, rollback Worker deployment via Cloudflare Workers version rollback; no app read pointer changed |
| Correct card but unavailable permission or exact image bytes | No staging/publication; stays \`PENDING_RIGHTS\` or \`AMBIGUOUS\` |
| Browser asks for a graded slab | Still requires actual owner-specific first-party slab image; reference art never substitutes |

**Acceptance criteria:** GitHub workflow preflight success, exact D1 UUID/schema verified, Worker deployment receipt, valid HMAC secret installed, two negative network smokes passed, and D1 row count unchanged until separately rights-approved actual image tests. Only then upgrade DR101 from **Ready** to **Deployed / Live verified**. Signing a synthetic receipt to stage a non-approved image is explicitly prohibited.

## Not part of DR101
- No rights licence is granted by YGOPRODeck, Lorcast, MTGJSON, Riot or checklists.
- No real images from YGO/Lorcana/Magic/sports/Riftbound are acquired or published.
- No approval of any UK completed-sale Market Value.
- No new paid services, Shopify updates or owner/settlement changes.
- No public D1 artwork resolver or founder/seller UI changes. Those remain later #966 gates after exact-print rights and mobile/desktop checks.


## 7 November 2026 — DR102 EU-jurisdiction R2 binding correction

**Evidence:** First actual manual DR101 GitHub workflow [run #42385886177](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42385886177) passed preflight and remote read-only D1 schema/bucket-name configuration checks. The first deployment failed because workers.dev had not yet been registered. Its second attempt successfully reached Cloudflare Worker upload but failed with Cloudflare **code 10085** ("R2 bucket 'drop-rate-private' not found"). The actual existing R2 bucket settings, confirmed by the account owner, explicitly show **Jurisdiction: European Union (EU)** and an EU-specific R2 S3 endpoint.

**Code correction:** Keep the same Worker, existing bucket name and D1 UUID. Generate an \`ARTWORK_R2\` binding with \`"jurisdiction": "eu"\`. Cloudflare documents this field for EU-restricted R2 buckets: https://developers.cloudflare.com/r2/reference/data-location/ . No new bucket, content copy, R2 public URL, or new source-image permission is created.

**Test:** \`tests/test_artwork_shadow_worker_deploy.py\` now asserts the precise EU jurisdiction for the unchanged account/D1 binding, with existing HMAC/auth/r2 byte integrity tests unchanged. Full PR CI and the dedicated DR101 preflight must pass before merge.

**Rerun instructions:** The previous failed run is pinned to its *old* commit. **Do not use "Re-run failed jobs" for #42385886177.** Once the tested DR102 change is merged to \`main\`, use GitHub Actions → DR101 guarded private artwork shadow Worker release → **Run workflow** on \`main\` to create a fresh run using the corrected Worker configuration. Verify the Wrangler upload, HMAC secret binding and 404/401 negative network smokes; do not infer live success from CI alone.

**Further boundaries:** A live private Worker is not public image delivery. YGO/Lorcana/MTG exact-artwork rights, owner-specific graded slab photography, and signed-in image visual checks remain separate issue #966 release gates. The R2 bucket stays private, the Worker does not return public images, and production Shopify/ownership/prices must remain unchanged.
