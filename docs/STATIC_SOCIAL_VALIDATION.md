# Static social validation

4 October 2026; static editorial branch, draft PR #512. Base main checked at
`21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1` before update.

## Verified locally

- Full backend pytest suite: **2,427 passed**, one third-party Starlette/AnyIO
  deprecation warning. Python 3.12; project-pinned FastAPI/Pydantic/httpx/pytest,
  asyncpg, PyJWT and Pillow versions. A separate virtual environment was used.
- Signed route exercised through FastAPI: valid request returns a nonpublishing
  preparation; unsigned/tampered requests return 401, oversized requests 413 and
  invalid schema 422. No production database or account was touched.
- Evidence checks cover stale/future observations, missing references, repeated
  source IDs and social-only claims. Source text stays inert; unknown request
  fields cannot enable publication.
- Grading checks cover exact printing/language, duplicate original transactions,
  old sales, outlier dispersion, asking-versus-sold basis, affordable raw cost,
  PSA 9 downside and the absence of invented profit/expected value.
- Destination tests cover wrong hosts, deceptive hostname suffixes, credentials,
  non-HTTPS, alternate ports, query redirects, home pages and stale observations.
  Relevant fixture links retain tracking; live relevance/stock remain unverified.
- Card grading cannot apply to comics. An entertainment/screen brief prepares
  independently. YouTube remains blocked in the static platform output; no music.
- The actual n8n Code-node signer executed under Node produces the exact backend
  HMAC format and configured command path. Workflow JSON parses, remains inactive
  and has no scheduler, publisher or durable success receipt. This is NOT an n8n
  import/runtime execution test.
- Python compilation, all n8n JSON parsing and `git diff --check` pass.

The first broad local run lacked Pillow; after installing the pinned version,
one unrelated keepalive-client test needed the scratch environment's SOCKS
support package. Installing `socksio==1.0.0` in that isolated environment resolved
it. No application requirements were changed to accommodate the environment.

## Not verified or delivered

GitHub CI on the new commit is separate from local tests. No new workflow was
imported or executed in the live n8n service. No production API deployment,
social authentication, live feed, authoritative evidence lookup, finished renderer,
licensed-media pipeline, durable content persistence, publisher, conversion
instrumentation or end-to-end multi-daily research/create/publish/learn loop has been verified. No costs, migrations,
inventory, money or public social state changed.

The creator evidence is a scouting study, not a complete native 120-post dataset.
In particular, smaller creators with repeated strong engagement remain unverified.
Five-platform unattended STATIC delivery is not established because a documented
public YouTube Community creation route was not found.

## Handoff and rollback

The PDF handoff reproduces the full research/playbook and this validation record.
It is a review document; the repository contains the executable preparation code.
The PR remains draft and unmerged. Reverting this branch's changes removes the
preparation route/configuration/workflow and documentation without a database
rollback. A future deployment would add DR-31 as an inactive stable ID; the
existing additive n8n provisioner must never overwrite earlier workflows.
