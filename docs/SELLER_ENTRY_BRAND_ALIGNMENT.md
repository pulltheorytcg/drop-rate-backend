# Seller entry brand alignment — 11 October 2026

User-requested correction following the launch audit / #598. Registration must look like login, and Shopify Sell With Us must enter the normal login (/app), not automatically select signup.

## Implemented in this change

The existing /owner/join document now uses the SAME #auth-view layout, collector-worlds.css revision, approved Seller Hub logo, decorative two-slab artwork and brand copy as /app. Only signup-specific checkbox, long-message, safe-area and text-input sizing is added in owner-join.css. The login page is not restyled.

The registration feature list is a native disclosure to keep the form compact. Commission/invitation information and required acknowledgement remain visible. Removed the misleading invitation progress strip from public self-registration. Existing loading/error, invite callback, public-registration, provider and existing-account form IDs are preserved. owner-join.js, auth routes, session handling, permissions and commission rules are unchanged. Public existing-account navigation already routes to /app; invitation continuation remains on the invitation form so its token is not lost.

## Evidence / tests

Node syntax and local HTML/CSS structure parsing passed before PR. Added owner-join-brand.cjs to the existing dashboard CI command. It uses JSDOM plus the actual registration script, with synthetic read-only network responses: shared branding, required inputs/acknowledgements, ordinary public preview, mismatched passwords, invited existing-account switch/back, provider availability, expired invitation and no unexpected write. These are mocked DOM checks, NOT real account creation, visual rendering, email delivery or physical-phone acceptance.

CI, production deployment and phone acceptance must be recorded separately on the release PR. No production user, membership, inventory, money or Shopify theme publication is created by this change. No new service, dependency, workflow or database migration.

## Storefront follow-up in the same approved work

The desktop/header and mobile Sell With Us links need /app in the unpublished Brand Redesign theme, with matching committed source. Keep signup available via the normal Create your account link in /app. Never redirect /owner/join globally: email and invitation callbacks require that route. No live theme publication is authorised.

Rollback: revert the HTML/CSS change to the prior release; no database rollback is required. Preserve owner-join.js and any unrelated concurrent import work.
