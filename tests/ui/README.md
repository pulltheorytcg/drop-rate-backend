# Dashboard and scanner interaction checks

Run `npm ci` followed by `npm test` in this directory (Node 24).
The test loads the real dashboard HTML and its complete script list in jsdom.
Only startup authentication and network requests are stubbed. It never contacts
production or saves inventory.

Covers the five primary destinations, existing intake dialogs, filtered inventory navigation,
clearing filters, global search, keyboard navigation, unsaved form retention,
layout preferences, settings control retention and duplicate control IDs.

`scanner-flow.cjs` covers both account roles, pending thumbnails, unresolved matches,
per-item conditions/quantities, manual correction and stale searches, sealed review
gates, empty-frame/removal checks, uncertain saves and immutable retry keys, account
changes, camera denial and late permission grants. These checks run in the
`dashboard-ui` CI job. Network responses are fixtures, not recognition benchmarks.

Responsive layout is verified separately in the browser at desktop and mobile
widths; jsdom does not perform layout or simulate camera hardware.
