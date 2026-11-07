# Unified workspace navigation

## Problem and scope

The 2 October user recordings show two sign-in designs, a second full-screen app navigation inside Search, delayed game tiles, and an unstructured More screen. This release addresses that shell and navigation. Recognition, scanner v4, inventory ownership, settlement rules, channel publishing flags and database schema are unchanged.

## Entry and permissions

`/app` is the shared entry, with `/` as a compatible alias. Both serve the same HTML. It accepts email or username through the existing rate-limited public owner-session endpoint, then reads `/access/me`. The explicit founder roster is still required for Founder HQ. An OWNER with OWNER_PORTAL is routed to `/owner`; an unsigned visitor there returns to `/app`. Tokens remain tab-scoped. Recovery and invitation callback processing remain before normal session restoration.

Expired concurrent requests share one token-refresh operation. Logout/account changes during refresh cannot restore an earlier session. Transient access or panel failures retain the session and offer recovery; authentication/authorisation failures clear or deny it.

## Workspace

Both roles use Home, Search, Scan, Inventory and More. The catalogue mounts inside the Search view rather than replacing the app with a second navigation. Known game identities/artwork are rendered before fetching current catalogue metadata; no counts or prices are fabricated. Exact product requests still use the authenticated server catalogue. Filters and incomplete save retries are retained on navigation. Leaving Search cancels obsolete results and does not move focus back to the Search tab.

More groups existing controls into Selling & payouts, Collection tools and Workspace, with descriptions and a More return action on secondary screens. Reparenting existing controls preserves listeners and unsaved forms. Browser history records main navigation. No founder controls are added to seller pages.

## Verification and rollback

`npm test --prefix tests/ui` includes the new workspace-navigation suite covering concurrent refresh, logout during refresh, founder roster denial, owner routing, transient failures, legacy sign-in routing, immediate tiles, delayed metadata and embedded-sheet cleanup. Existing scanner tests remain intact. Isolated browser fixtures cover desktop and 390/320-pixel phone widths, game tiles, tool navigation, focus, overflow and script errors. Fixtures are simulated and do not prove real-account or real-phone acceptance.

Run the existing full backend suite and deployment health gate. Verify both live entry documents and byte equality of released JS/CSS. Application rollback is commit `6b8b973d7b0a07afc6776cbb706b5eb67b97abf0` (Railway `0e5a8200-378e-4989-a0a2-27f492737119`); no data rollback is required.
