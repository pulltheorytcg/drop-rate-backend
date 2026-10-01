# PullTheory — one app, existing hubs

The iPhone and Android app displays the existing Seller Hub and Founder HQ from
`https://drop-rate-api-live-production.up.railway.app`. Shopify remains the separate existing storefront.
There are no replacement native dashboards or demo accounts in the active app routes.

## How it works

- One embedded browser starts at `/owner`, using the real Seller Hub login and UI.
- The server-verified account role selects Seller Hub (`OWNER`) or Founder HQ (`PLATFORM_ADMIN`).
- Both web hubs use one tab-scoped session. A founder redirect no longer requires a second login after the backend assets are deployed.
- Founder accounts still cannot use seller-only APIs; switching a founder into the restricted Seller Hub is not implemented. No membership, API guard, RLS or financial permission was expanded.
- Tokens stay in the existing website's browser session, never native messages or URLs added by the wrapper.
- Non-hub HTTPS links open in the device browser. Other schemes are blocked. Social login return from an external browser still needs native integration and device testing; use the existing email/password flow for initial acceptance.
- Camera capture uses the existing hub scanner. Native camera permissions are configured, but camera, file upload, downloads, reconnect and background behaviour require physical-device testing.
- Web preview opens the actual hosted hub directly. It is live, not a read-only demo.

## Development

Run `npm ci`, `npm run check`, and `npm start` from this directory in VS Code.
`npm run export` produces web and native JavaScript bundles, not an installed app.
`npm run preview` serves the web entry locally on port 8084; it opens the existing hosted hub.

Use `npm run build:ios:testflight` after linking an Expo project and Apple Developer
signing account. Android internal build: `npm run build:android`.
No signed build, TestFlight invitation, or store release has been created.
Backend shared-session changes must be deployed before the unified login handoff works.
Legacy hub sessions require a fresh sign-in once after that deployment.

The earlier replacement screens are preserved under `prototype-routes/` and are not
registered with Expo Router. Their API helpers/tests remain as reference material.
The prior localhost live-proxy scripts are not part of the unified hub app.
