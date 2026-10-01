# PullTheory TCG mobile

Shared Expo / React Native app for Android and iPhone, developed in VS Code. Version 0.1.0 is a working first mobile slice, not an App Store / Play Store release or full replacement for Founder HQ.

## Run in Visual Studio Code

Open the repository folder, then open a terminal in `mobile/`:

```sh
npm ci
npm start
```

The generated `PullTheory.code-workspace` deliverable also provides **Terminal → Run Task → PullTheory: start mobile**, **check app**, and **browser preview** tasks. No VS Code extension is required.

For a browser demo without native tooling or filesystem watchers:

```sh
npm run export
npm run preview
```

Open http://127.0.0.1:8084 and choose **Seller demo** or **Admin demo**. Browser previews deliberately disable live sign-in: the current production backend's browser-origin policy has not been expanded. Demo data is isolated in memory and does not call production. Reloading clears it. Native sessions and pending intake requests use device-only secure storage; the browser preview has memory-only storage.

Node 22.13 or later is required; development was verified with Node 24.14.1. Commit and use `package-lock.json`. Expo SDK 57-compatible native dependencies are selected using `npx expo install`. On macOS, Metro may need Watchman if the OS reports `EMFILE`. The static preview above does not need it.

## Implemented

- Existing backend email/username/password sign-in and server-verified OWNER / PLATFORM_ADMIN access, single-flight token refresh and device-only session storage. No role is inferred from editable user metadata.
- Seller home totals and paginated inventory, search/status filters, exact-copy item details, account name/username updates, financial summary, sales and payout history.
- Founder home readiness counts, own-account inventory, version-checked cost/store-price/notes editing and paginated Action Required queue. This does not expand an administrator's existing owner scope.
- Rear camera with torch and permission recovery, photo picker, JPEG normalization, explicit upload for recognition, human match review, catalogue correction and guarded materialization of previously unmapped provider card references.
- Explicit physical condition / seal-state selection. Human feedback is recorded before draft intake. Founder intake remains `identity_confirmed=false`; seller intake uses the existing restricted endpoint.
- Account-bound immutable pending intake, persisted before transmission, retrying the same request key and payload after uncertain failure. New scans are blocked while an uncertain save remains. Permanent validation/permission rejections clear the queue; conflicts/timeouts/server failures remain recoverable.
- A backend change, migration, Supabase key, Shopify token, Stripe token or production deployment is not required for this client slice.

The existing SwiftUI draft PR #433 is preserved. This shared app starts from current main contracts rather than copying its branch-only mobile API. Android and iPhone use the same code under `src/app/`.

## What remains in the browser

Payout requests/banking changes, detailed slab/certificate intake, media/identity approval, registered location assignment, Shopify publication and advanced company operations open the existing portal. Browser authentication is separate; bearer tokens are never placed in URLs. Comics and graded recognition are not advertised as complete native features. A failed recognition run cannot be saved through seller intake even though the backend permits manual feedback on that run; the app asks for a new scan.

For native founder scans, draft ownership is the founder's current membership. Assigning intake to another consignor would require an explicitly designed, audited backend flow; the app does not infer or spoof owner IDs.

## Configuration and builds

`.env.example` contains only the public API URL. The default targets the existing Railway API. Supabase public authentication configuration comes from the backend. Never embed service-role, Shopify, Stripe or provider secrets.

The proposed app identifiers are `com.pulltheory.tcg` (both platforms). Confirm ownership/availability before registering store records. The card-stack app icon is a preliminary vector design in `assets/app-icon.svg`, rendered by `node scripts/icon.mjs`; it still needs brand approval.

```sh
# Validate JavaScript and generate native projects; not signed installers
npm run check
npm run export
npx expo prebuild --no-install

# Cloud-signed internal distribution (requires your Expo/developer accounts)
npx eas-cli@24.8.0 login
npm run build:android
npm run build:ios
```

`eas.json` defines development, internal preview and production profiles. Android preview produces an APK; production defaults to the store build format. iOS internal distribution requires Apple signing and registered test devices. Initialize/link the EAS project in your account before building; no account/project ownership or paid build has been created on your behalf. Store submission is a separate release action.

Native `ios/` and `android/` directories are generated and ignored. Change `app.json` or config plugins, not generated native files. Local native compilation additionally needs Xcode + CocoaPods for iOS and an Android SDK/JDK for Android. The current Mac has command-line tools but not a verified complete native toolchain; CocoaPods validation fails.

## Validation performed, 1 October 2026

- TypeScript and Expo ESLint passed.
- 24 automated tests passed: role routing, owner mismatch, secure-storage failure, token refresh concurrency, unauthorized retry, invalid refresh, logout during refresh, session changes during pending reads/save cleanup, concurrent save retries, uncertain save replay across restart, conflict/validation handling, duplicate submissions, provider materialization, physical-state contracts and minor-unit values.
- Production JS/Hermes bundles exported successfully for Android and iOS; web bundle exported successfully.
- Both native projects generated with `expo prebuild --no-install`; camera/photo permission configuration inspected. Microphone recording permission is blocked.
- Browser walkthrough at 390×844: seller demo, recognition selection, condition and human-confirmation gates, draft save, seller financials, logout, admin demo and Action Required. Demo execution never wrote to the live database.
- Expo dependency checks pass. With generated native projects present, the tooling check reports missing CocoaPods. This is not proof of a signed native build or real-device camera/Keychain behavior.

Release still requires real Android/iPhone testing with authorized accounts, two-owner isolation checks against staging, reconnect/background tests, camera accuracy acceptance, approved privacy/support/account-deletion flows, store artwork/metadata, and signing/distribution. Do not use production inventory as disposable test data.

`npm audit` currently reports 13 moderate transitive findings from the SDK/tooling tree (including legacy `uuid` via `xcode` and `decode-uri-component` via `query-string`). Its suggested automatic fixes downgrade Expo/Router to incompatible major versions. No forced downgrade or unverified replacement is applied; resolve upstream/compatible upgrades before a production release. The lockfile records the inspected versions.

Reference documentation: [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/), [Expo Router](https://docs.expo.dev/router/introduction/), [SecureStore](https://docs.expo.dev/versions/v57.0.0/sdk/securestore/), [EAS Build](https://docs.expo.dev/build/introduction/).
