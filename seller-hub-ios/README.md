# Current Seller Hub on iPhone

This is the **current hosted Seller Hub**, packaged in a separate Swift/WKWebView
iPhone application. It does not use or change Eamon's `mobile/` application, its
prototype routes, or the older SwiftUI PR. The real hub is the only product UI;
there are no demo accounts or replacement dashboards.

The app opens `https://drop-rate-api-live-production.up.railway.app/app`. The
existing backend verifies the signed-in account and selects its current workspace.
Inventory, scanning, search, pricing, sales, payouts, ownership and permissions
continue to use the existing FastAPI/Supabase/Shopify system. No backend deployment,
database migration, new Railway service or Expo subscription is needed.

## iPhone integration

- The existing full-screen scanner uses WebKit camera capture with an iOS camera
  permission prompt. Photo/CSV inputs use the iOS system picker.
- A main-frame, exact-origin bridge saves only the hub's access/refresh tokens and
  expiry fields to device-only Keychain storage. A new launch restores them before
  the unchanged web authentication code runs; the server still validates the user.
  Refresh rotation and logout update that same record. No service-role or Shopify
  credentials are present in the app. Browser sessions outside the app are separate.
- JavaScript confirmations/prompts work, including existing listing confirmations.
- Trusted downloads use WebKit's native download delegate and the iOS share sheet.
  Temporary files are removed after the share sheet is dismissed.
- External HTTPS pages open in Apple's in-app browser. Untrusted schemes and
  third-party pages cannot enter the token-bearing web view.
- Main-page failures show Retry; failed thumbnails do not replace the whole hub.
  The app does not automatically reload, resubmit mutations or retry inventory
  saves. If iOS kills the web process, unsaved form/scan state may be lost. Check
  Inventory before repeating an interrupted save.
- There is no offline inventory editing or new push-notification feature.

Read-only inspection on 3 October confirmed both Google and Apple social providers
are disabled in the current Supabase project. Existing email/username/password
login is retained. Enabling social login later requires a native system-auth return
flow and separate device acceptance; opening a provider in a browser alone does
not complete native sign-in. Password recovery currently uses the existing email
and website flow, after which the new password can be used in the app.

## Build without owning a Mac

The **Seller Hub iPhone** GitHub Actions workflow runs on GitHub's macOS runners.
Every PR for this folder runs JavaScript session tests, generates the Xcode project,
runs iPhone simulator tests and compiles the device Release build without signing.
The workflow fits the existing Drop Rate logo into the app-icon canvas at build
time; it does not use the previous app's green P icon.

Local checks available on any computer:

```sh
node --test seller-hub-ios/scripts/session-bridge.test.mjs
bash -n seller-hub-ios/scripts/testflight.sh
```

On a Mac/cloud Mac, from this directory: `swift scripts/prepare-assets.swift`,
`xcodegen generate`, then open `SellerHub.xcodeproj`. XcodeGen is a build tool;
the app itself has no third-party runtime dependencies.

## TestFlight setup still required

1. The owner enrolls in the Apple Developer Program (or supplies their existing
   team). Apple handles identity, agreements and membership payment. This can be
   done using Apple's Developer app on the iPhone. No password should be posted in
   chat or the repository.
2. Register `com.pulltheory.sellerhub` and create the Drop Rate app record in App
   Store Connect for that bundle ID. It is distinct from the existing Expo app.
3. Prepare an Apple Distribution certificate/private key, an App Store provisioning
   profile for this bundle, and an App Store Connect upload API key. A certificate
   signing request/private key can be generated on a cloud/Linux machine; its
   certificate and provisioning profile can be issued through Apple's website.
   A local Mac is not needed. Never revoke another app's certificate to proceed.
4. Store the following in GitHub environment `seller-hub-testflight`: `APPLE_TEAM_ID`,
   `IOS_CERTIFICATE_BASE64` (password-protected P12), `IOS_CERTIFICATE_PASSWORD`,
   `IOS_PROFILE_BASE64`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY_BASE64`.
   These are secrets, never source files or build artifacts. Configure the
   environment to allow only reviewed `main` releases.
5. Run **Seller Hub iPhone** on main with `upload_testflight=true`. It runs the
   checks, validates the profile, imports signing into an ephemeral Keychain,
   archives/signs the app and uploads it. It removes the signing files afterwards.
   Upload is manual; no PR automatically uploads or publishes the app.
6. Wait for Apple's processing, select the build for an internal tester with
   appropriate App Store Connect access, and install with the **TestFlight** app
   on the iPhone 16 Pro Max. External testing can require beta review. A successful
   upload is not a TestFlight invitation or App Store approval.

The build number is generated for each upload. The unsigned device build cannot
be installed on a physical iPhone. A paid Apple Developer membership is required
for this TestFlight distribution route. There is no signed build or invitation yet.

## Physical iPhone acceptance

Use the real iPhone and account. Record each result; a compile is not device proof.

| Check | Acceptance |
| --- | --- |
| Sign in and cold launch | Correct existing workspace; close/reopen stays signed in; logout/reopen stays signed out |
| Role/owner boundaries | Same inventory and permissions as the web hub; no role chosen by native code |
| Scanner | Allow/deny camera, open Settings after denial, raw/graded/sealed capture, choose existing photo, review candidates |
| Inventory | Search, open item, condition/price edits and existing draft/review workflow with an authorized test item |
| Uploads | Import an explicitly approved test CSV from Files; photo upload opens the iOS picker |
| Confirmations | Cancel/confirm dialogs appear; cancelling produces no mutation |
| Sales/payouts | Current figures and controls match web; do not move real money as a smoke test |
| External links | Shopify/Stripe pages open, Done returns to hub, existing refresh reflects completed changes |
| Interruption | Airplane mode/reconnect, background during scan, force quit, expired/revoked session and interrupted-save reconciliation |
| Layout | iPhone 16 Pro Max notch, home indicator, keyboard, small-text settings and long forms remain usable |

Online connectivity is required for live inventory and recognition. A public
App Store release needs its own metadata, privacy disclosures and Apple review.
This work targets the requested current-hub TestFlight build first.
