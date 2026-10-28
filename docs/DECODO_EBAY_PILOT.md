# Decodo eBay sold-data pilot

The acquisition client is ready for a bounded live sample once the operator supplies
`TCG_DECODO_API_KEY` in the executing process's secure environment. It is a current
Web Data API bearer key, not a legacy proxy/Scraping API token.

## Scope

`backend/app/decodo_ebay.py` calls the documented
`https://data.decodo.com/v1/scrape` endpoint for fixed eBay UK sold-search URLs.
It returns the same `site/currency/results` shape used by our sold-data logic,
plus Decodo provenance, date precision and rejection/usage diagnostics.

`backend/scripts/decodo_ebay_pilot.py` consumes up to 36 reference candidates.
It prepares searches by default; `--run` requests pages. Each search remains
marked `identity_review_required`: collector numbers, language and printed
variant still require verification. This stage does not call the database,
set a market value, change an inventory price or register a production adapter.

## Usage

From the repository root, prepare the plan:

```sh
python backend/scripts/decodo_ebay_pilot.py \
  --manifest docs/evidence/market_source_pilot_20261028.json \
  --output evidence/decodo-plan.json --rps 10
```

Configure the secret in the environment of the runner, then run the sample:

```sh
python backend/scripts/decodo_ebay_pilot.py \
  --manifest docs/evidence/market_source_pilot_20261028.json \
  --output evidence/decodo-pilot.json --rps 10 --pages 1 --max-requests 72 --run
```

For Railway execution the secret belongs in the API service's Variables and
must be present in the process actually running this command. Adding a variable
does not itself launch the pilot. Do not paste the key into chat, code or reports.

After the commit containing this pilot is deployed, an authenticated Railway CLI
can run it inside the existing service without exporting the key. The connected
Railway MCP used for setup exposes configuration/status operations, not a shell.
Do not attach this collection job to application startup or pre-deploy checks.
Those checks have a 300-second timeout and should not depend on Decodo availability.

Use one runner/client for the initial pilot. The rate limiter is per client,
not a distributed global rate limit: do not launch parallel runners. The pilot
is sequential, so latency can reduce throughput below the ceiling. Its built-in
maximum is 10 requests/second and 200 requests/run; default settings are 1/second,
72 requests and one page/reference. Maximum is two pages/reference.

Default extraction uses the standard proxy pool without JavaScript. An explicit
`--javascript` run has different costs; no automatic proxy/rendering escalation
or quota top-up is implemented. Normal failures are not retried because an
ambiguous timeout may already have consumed credit. 429 stops the run and records
numeric Retry-After when available. The operator can resume only after addressing
the reported error, using a new evidence filename.

Reports checkpoint after each reference, preserve completed evidence on failure,
refuse to overwrite an earlier report and always record zero newly priced
references. Request counts are local attempts, not an invented provider billing
receipt. No raw response headers, cookies, session data or credentials are saved.

## Evidence handling

The deterministic parser supports the documented eBay card-container patterns,
but synthetic fixtures do not prove current live layout compatibility. Unknown
markup is an error, not zero results. Login/challenge pages and non-200 target
responses stop the run. No eBay login/session forwarding is supported.

Only explicit dated sold badges within 90 days and single GBP display prices
are extracted. Accepted/possible Best Offer prices, struck prices, ranges,
unsold/undated results, lots and proxies are excluded. Missing postage remains
unknown. Repeated item IDs are deduplicated; contradictory observations are
quarantined across pages. Parsed display prices retain that label and must not
be promoted to confirmed accepted prices without evidence.

Review each result against the canonical game/set/number/language/variant, then
apply the existing physical condition/grade and multi-sale pricing rules where
appropriate. Inventory's five-sale pipeline is not the same thing as database-wide
reference coverage. Do not attach raw pilot rows directly to the reference cache.

## Validation

- The database audit and 36-candidate manifest were verified read-only.
- Plan-only CLI executed successfully: 36 searches, zero requests, zero writes.
- Parser/transport tests cover sale-date limits, Best Offer ambiguity, non-GBP
  and range prices, postage, duplicate/conflicting listings, rate and request
  caps, auth/quota/server errors, HTML drift, fixed hosts and no credential leak.
- Local Windows asyncio stalls creating its loopback socketpair before async
  tests start. The mocked tests were run with a local selector-loop harness that
  rejects real I/O; no production runtime workaround is included. Standard CI
  must independently run the same tests on its normal event loop.
- The follow-up parser review added regression cases for negative sold labels
  and valueless HTML attributes; 46 focused tests pass in the mock-only runner.
  Normal CI must verify the final commit independently.
- Live provider responses and exact-card recovery are **not yet verified**.

## Official references

- [Current request/response contract](https://help.decodo.com/docs/web-data-api-scrape-real-time-requests)
- [Request options](https://help.decodo.com/docs/web-data-api-scrape-parameters)
- [Rates](https://help.decodo.com/docs/web-data-api-billing)
- [Source audit, coverage constraints and outstanding checks](MARKET_COVERAGE_SOURCE_PILOT_20261028.md)
