# Founder dashboard interaction checks

Run `npm install --ignore-scripts` followed by `npm test` in this directory.
The test loads the real dashboard HTML and its complete script list in jsdom.
Only startup authentication and network requests are stubbed. It never contacts
production or saves inventory.

Covers all nine routes, existing intake dialogs, filtered inventory navigation,
clearing filters, global search, keyboard navigation, unsaved form retention,
layout preferences, settings control retention and duplicate control IDs.

Responsive layout is verified separately in the browser at desktop and mobile
widths; jsdom does not perform layout or simulate camera hardware.
