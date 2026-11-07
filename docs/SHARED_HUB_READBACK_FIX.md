# Shared hub production readback repair

7 November 2026 — Implemented locally; review and CI pending. No UI/runtime/auth/database changes.

What: replace the outdated absence assertion in `.github/workflows/business-readback.yml`
with exact reviewed founder script inclusion in both `/app` and `/owner`. Extract the
read-only probe into a stdlib Python script so negative fixtures exercise the same code.
Why: the unified founder design deliberately uses the personal owner shell. Presence
of shared JavaScript is not an authorization grant; founder API guards remain authoritative.
Connections: versioned HTML entries, three static assets, readiness and three founder GETs.
Risks: stale releases, accidental weakening of denial checks, leaking server response bodies
into public artifacts. Preserve exact hashes, 401/no-store checks and bounded retries;
record only status codes, hashes and fixed failure labels, never response bodies/headers.
Tests: valid shared shell, old absence assertion reproduction, missing/wrong/duplicate
script, stale hash, missing cache protection, unauthorized success, readiness and network
failure, retry and report-on-failure. Existing founder UI, guard and PostgreSQL owner tests.
Rollback: revert this workflow/script/tests commit. No migration or production rollback.

PR #511 was reviewed read-only: draft `feat/current-seller-hub-iphone`, independent
`seller-hub-ios/` Swift wrapper and workflow. Its installation/signing remains paused;
no dependency on it is required for this check. It is not merged or modified here.

## Exact obsolete assertion and correction

Previously, `.github/workflows/business-readback.yml` asserted:

```python
if code!=200 or b'founder-accounts.js' in body:
    raise AssertionError('Seller shell changed or loads founder module')
```

The workflow now runs `scripts/business_readback.py`. Both `/app` and `/owner`
must return HTTP 200 with exactly the reviewed versioned founder script from source.
Asset SHA-256 equality, database readiness, and anonymous 401/no-store checks remain.
The probe writes a redacted failure artifact as well as successful evidence.

## Verification on 7 November 2026

- Nine probe unit tests passed, including the reproduction of the obsolete check
  and rejection of wrong/absent/duplicate scripts, stale assets and anonymous API access.
- Read-only Railway probe passed at 18:34:30 UTC: exact three asset hashes, both
  entry pages, connected database readiness, and all three founder GETs returning
  anonymous 401 with no-store. One attempt, zero mutations. This is production
  evidence for these public checks only, not authenticated authorization evidence.
- 100 Python tests passed (Python 3.12): readback, business access, unified founder
  access, owner-isolation release gate, access control, scan intake and manual intake.
  HTTP tests use synthetic identity/SQL; some isolation/intake tests inspect source.
- The next blocker review expanded the HTTP authorization matrix across all three
  business endpoints: ordinary owner, consignor, revoked/unregistered admin, forged
  founder metadata, invalid/missing slot and wrong owner type are denied before
  business queries. All three registered founder slots have read-only access and
  lose it immediately on revocation. Runtime authorization is unchanged.
- Disposable PostgreSQL (PGlite) shared-founder migration tests passed for personal
  owner isolation, uniqueness, direct cross-owner write denial, revocation and audit.
- Mocked DOM tests passed: founder accounts, unified founders, 83 scanner scenarios,
  11 photo upload/recovery/isolation groups and 10 collection interaction contracts.
- Initial test invocations needed the repository's normal `PYTHONPATH=backend` and
  UI working directory; corrected invocations passed. No application failure was
  inferred from those invocation errors.

## Remaining launch evidence

The ownership blocker is not closed: separate live founder/seller/consignor account
acceptance remains unverified. Scan persistence has passing synthetic/source and
interaction checks, but real device save/reload and duplicate/concurrent retry
proof remains outstanding. First-party publication, market freshness/capacity,
provider attribution/refunds/reconciliation and physical-iPhone acceptance remain
in the user's priority queue. No provider writes, new service, deployment or merge
were performed by this repair. PR #511 remains separate.
