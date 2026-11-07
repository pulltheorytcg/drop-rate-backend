> Archived development path: this Expo project is preserved for reference.
> Active development has moved to [`../native`](../native/README.md), using Xcode and Android Studio without Expo.

# Drop Rate — one app, two account roles

The iPhone and Android app displays the existing Seller Hub and Founder HQ from
`https://app.droprate.co.uk`. Shopify remains the separate existing storefront.
There are no replacement native dashboards or demo accounts in the active app routes.

## How it works

- One embedded browser starts at `/app`, using one Drop Rate login.
- The server-verified account role selects Seller Hub (`OWNER`) or Founder HQ (`PLATFORM_ADMIN`).
- Both web hubs use one tab-scoped session. A founder redirect no longer requires a second login after the backend assets are deployed.
- Only the three explicitly enrolled founders can enter Founder HQ. Founders retain their own inventory tools and have read-only Accounts oversight of all sellers. Seller APIs remain restricted to the authenticated seller.
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
The `/app` route and founder roster migration must be deployed before installing this build.
Legacy hub sessions require a fresh sign-in once after that deployment.

The earlier replacement screens are preserved under `prototype-routes/` and are not
registered with Expo Router. Their API helpers/tests remain as reference material.
The prior localhost live-proxy scripts are not part of the unified hub app.

## Home Screen web app

The hosted `/app` and `/owner` shells share `/assets/app.webmanifest`. Its start
URL is `/app`; the root scope keeps both role destinations inside one standalone
window. The Home Screen icons use the existing Drop Rate storefront artwork.
Regenerate them with `node scripts/home-screen-icons.mjs` from this directory.

After deploying these assets, open the hosted `/app` URL in iPhone Safari and
choose Share → Add to Home Screen (enable Open as Web App if offered). On Android,
open the same URL in Chrome and use its Install app / Add to Home screen menu.
Sign in inside the installed app; an existing browser login may not carry over.
This is the hosted web app, not a signed native iOS or Android release. It requires
an internet connection; no service worker or private-data offline cache is added.

Physical-device acceptance remains pending: install and relaunch, seller/founder
routing, camera capture and photo upload, external links, background/resume, and
sign-out. The native app build and signing requirements above still apply.
