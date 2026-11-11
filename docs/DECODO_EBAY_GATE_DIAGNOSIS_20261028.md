# Decodo eBay sold-data pilot diagnosis — 28 October 2026

The diagnostic confirmed a genuine eBay sign-in page for the tested sold search. This was not an SVG title or hidden-navigation false positive.

## Evidence

- Deployed backend commit: `2b925b593aae6318b98710323d4c3855c0f7295c`.
- Query: `Energy Marker E-141 English`; first candidate in `market_source_pilot_20261028.json`.
- Original pilot stopped after one request with `TARGET_ACCESS_GATE`.
- One subsequent diagnostic used the same query, UK locale, standard proxy pool, no JavaScript rendering, one page, one-request cap and no client retries.
- Decodo HTTP status: 200. Embedded target HTTP status: 200.
- Document HEAD title: `Sign in or Register | eBay`.
- Two matching sign-in forms targeted `signin.ebay.co.uk` at `/signin/s` and `/signin/scl/s`; neither had an explicit hidden hint.
- Recognized result cards: 0.
- The existing detector independently matched document-title, form-action and form-ID rules.
- Diagnostic ran from 21:32:08 to 21:32:21 UTC on 28 October 2026. Provider task ID is retained in the evidence JSON.
- Across the original pilot and this diagnostic: two client requests; zero database writes and zero newly priced references.

The original HTML was not retained, so the diagnostic establishes the returned page on the second request rather than byte-for-byte identity with the first response. It confirms the access barrier for this tested configuration and query, not a universal claim about every eBay endpoint.

## Validation and handling

A temporary diagnostic wrapped the existing client's HTTP transport and returned the response unchanged to the deployed parser. Six offline tests passed: genuine sign-in, normal navigation link, SVG title, hidden sign-in form with redaction, metadata allowlisting, and one-request transport integration. No eBay credentials, cookies, raw HTML, response headers, or hidden form values were saved. The production adapter and stop rules were unchanged.

The browser console did not inherit Python on PATH. Its verified interpreter is `/app/.venv/bin/python` (Python 3.12.14). Use that absolute interpreter path in this console.

## Decision

Keep the bulk pilot stopped. Increasing request rate does not address this observed sign-in requirement. Do not count successful HTTP delivery of a login page as a usable sold-data observation. Establish a supported, permitted sold-data access path before attempting the larger import. Current evidence does not justify weakening the detector.

## Saved reports

- [Original pilot](evidence/decodo-pilot-20261028-browser.json)
- [One-request diagnostic](evidence/decodo-gate-diagnostic-20261028.json)
