# Drop Rate - Seller Hub iPhone handoff

**Prepared for Claude | 3 October 2026 | Europe/London**

## 1. Current position and the user's decision

The current live Seller Hub has been packaged as a separate Swift/WKWebView iPhone application. The application compiles, its automated checks pass, and the work is saved in draft PR #511. It has not been installed on a physical iPhone, signed for distribution, uploaded to TestFlight or released through the App Store. Do not describe it as a fully verified, delivered iPhone app yet.

The user's latest instruction at 23:27 BST on 3 October is to pause installation work until tomorrow, **4 October 2026**, and prepare this detailed GitHub/PDF handoff. Resume implementation when the user returns. No membership purchase or installation work is requested tonight.

### Confirmed requirements and constraints

- Convert the **current Seller Hub** first; postpone redesign and new features until that conversion is working.
- Leave Eamon's separate `mobile/` application, its prototype routes and the older SwiftUI draft alone. This implementation is in `seller-hub-ios/`.
- The user has an **iPhone 16 Pro Max**, no MacBook, and has now confirmed access to a **Windows laptop or PC**.
- The user does **not** have a paid Apple Developer membership and has explicitly said funds are limited. Do not assume a subscription purchase is approved.
- The user instructed us not to read the Phase 2 or Phase 3 manuals for this task. Continue from current code, this handoff, build status and the connected GitHub/Supabase/Railway/Shopify systems.
- The free Windows personal-testing route has been discussed, but has **not** been packaged, installed or verified. A Home Screen web app is a separate fallback, not delivery of the native build.

### Exact GitHub starting point

| Item | Value |
| --- | --- |
| Repository | `pulltheorytcg/drop-rate-backend` |
| Feature branch | `feat/current-seller-hub-iphone` |
| Pull request | [PR #511 - current Seller Hub iPhone app](https://github.com/pulltheorytcg/drop-rate-backend/pull/511) |
| PR state at handoff | Open, draft, not merged |
| Application baseline | `bae0f9ebe76c683be0017ed29ae6612a858efdee` |
| Main inspected | `21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1` |
| Native source | `seller-hub-ios/` |
| Build workflow | `.github/workflows/seller-hub-ios.yml` |

The handoff documentation is a follow-up commit on the same branch. Main does not contain this app yet. Claude must inspect PR #511 or check out the feature branch; reading only main will miss this work. Recheck branch heads before making changes so another contributor's work is preserved.

<!-- pagebreak -->

## 2. Architecture and the existing live system

This is a native iOS application container around the hosted, working Seller Hub. SwiftUI supplies loading/error screens; WKWebView displays the existing product UI. It is not a rewrite of every screen in SwiftUI. That choice follows the request to get the current hub onto iPhone before making design or feature changes.

The app opens **[the live /app entry](https://drop-rate-api-live-production.up.railway.app/app)**. The existing web authentication and backend access checks select the signed-in user's Seller/Owner or Founder workspace. Native code does not choose an owner, assign a role or grant Founder access.

| Component | Responsibility |
| --- | --- |
| Native iPhone container | iOS lifecycle UI, camera permission handling, secure session persistence, dialogs, downloads and external links |
| Hosted Seller Hub | Existing screens, scanner, inventory, catalogue search, pricing, sales and payout controls |
| FastAPI on Railway | Authentication enforcement, access checks and deterministic business rules |
| Supabase/PostgreSQL | Authentication and authoritative application data, including owner boundaries/RLS |
| Shopify | Existing commerce integration; accessed through the current system, without embedding Shopify admin credentials in the app |

### Read-only integration evidence from this session

- Railway's production API readiness endpoint reported `status: ready` and `database: connected`.
- Supabase project `ozrxenrdladkooixutmm` (`pull-theory-dev`) was active/healthy. Inspected application tables had RLS enabled. Do not infer that the project is disposable from its name.
- The connected Shopify store returned real products, including 461 active products at the inspection snapshot. That count is time-sensitive and is not a reconciliation or a promise about future stock.
- `/api/v1/public-config` supplies public client authentication configuration. No service-role key or Shopify secret was added to the app or this document.
- Supabase Google and Apple social providers were both disabled when inspected. Existing email/username/password sign-in is the current acceptance path.

### Infrastructure references

| Reference | Identifier |
| --- | --- |
| Railway project | `9329767b-b092-495c-bf18-75cf69c28536` |
| Production environment | `6f00816c-b630-4d0b-bcc1-26ac71fa712d` |
| Live API service | `6aa92310-153f-4fc9-9e22-dc338282605b` |
| Supabase project reference | `ozrxenrdladkooixutmm` |

These observations were made on 3 October; they are not continuous monitoring. No backend deployment, schema migration, inventory change, owner activation, payout, Shopify publishing change, new Railway service or subscription was made for this app work. Existing backend and hosted web files are unchanged by PR #511.

Root `README.md` includes historical foundation descriptions. Check current code, recent build status and live evidence before interpreting old descriptions as current publishing/integration state.

<!-- pagebreak -->

## 3. Implemented iPhone behavior

| Area | Implementation and practical boundary |
| --- | --- |
| App entry and navigation | Loads the real `/app` entry. Current server-verified workspace routing and hosted screens remain in control. |
| Scanner | Uses the existing WebKit camera scanner. Camera requests are prompted only for a trusted main frame; microphone capture is denied. Real camera behavior still needs phone testing. |
| Photos and CSV | Existing file inputs use iOS system selection. No new import/recognition backend was introduced. |
| Session retention | A narrow native bridge persists required login tokens to device-only Keychain storage and restores them before web startup. See section 4. |
| Confirmations | Native handlers implement JavaScript alert, confirm and prompt dialogs, including existing listing confirmations. |
| Downloads | Trusted hub/blob downloads use WKDownload and the iOS share sheet. Temporary downloaded files are removed after sharing/dismissal. |
| External links | External HTTPS pages open in SFSafariViewController. Returning with Done reveals the hub; existing refresh controls remain available. |
| Failure recovery | Main-page failures show explicit Retry. Thumbnail failures do not replace the whole app. A terminated web process requires an explicit reload. |
| Form safety | No automatic page reload, mutation resubmission, swipe refresh or second navigation toolbar was added. Interrupted changes must be reconciled against Inventory before retrying. |
| Branding | The existing Drop Rate logo is fitted to the iPhone icon canvas at build time; the previous app's green P icon is not used. |

### Build configuration

The target/scheme is `SellerHub`, bundle identifier `com.pulltheory.sellerhub`, display name `Drop Rate`, marketing version `1.0.0`, iPhone-only, portrait and light interface style. The deployment target is iOS 16.4. Swift language mode is 5.0. XcodeGen generates the project from `project.yml`; the application has no third-party runtime dependencies.

The cloud workflow selects Xcode 26.3 on `macos-15`, runs Node 24 bridge tests, generates the app icon/project, selects an available iPhone simulator (preferring iPhone 16 Pro Max), runs native tests and compiles the device Release build without signing. The checked build used the iPhone 16 Pro Max simulator. Simulator verification does not reproduce physical camera hardware.

### Deliberate limits

The app requires online access to the hosted hub, authentication and recognition services. It does not add offline inventory editing, push notifications, new recognition capabilities, Android/desktop packaging or a redesigned dashboard. Existing hosted features and defects are inherited; this packaging work does not independently validate every backend workflow.

Social login is not enabled. Enabling Google/Apple later requires an appropriate native authentication return flow and its own tests. Simply opening an OAuth provider in an external browser would not finish native sign-in. Password recovery currently follows the existing email/website flow; the resulting password can then be used in the app.

<!-- pagebreak -->

## 4. Authentication, session safety and authority

The hosted hub uses `sessionStorage["drop_rate_hub_session"]` through the existing shared `hub-session.js`. The native wrapper extends persistence without changing that web module or moving authorization into the client.

### Session lifecycle

1. On startup, native code reads its Keychain record. A locked/unavailable Keychain presents a retry state instead of silently replacing the previous session.
2. A main-frame document-start script restores a saved session only on the exact trusted HTTPS hub origin. It will not overwrite a newer session already in the tab.
3. The hosted app still validates the user and obtains backend access/role information. Native code does not trust stored profile or role fields as authorization.
4. The bridge observes writes/removals of the single hub session key and the existing `hub-session-cleared` event. It forwards refresh rotation, sign-in and logout to native persistence.
5. Native code retains only `access_token`, `refresh_token`, `token_type` and numeric expiry fields. Passwords, profile/user objects, roles, other storage keys and forms are excluded.
6. Logout records a non-secret tombstone before deleting Keychain data. A subsequent launch cannot restore an old account if deletion was interrupted. A successful new sign-in clears the tombstone.

### Important race fix

JavaScript-to-native messages are asynchronous. A logout followed immediately by navigation could otherwise re-inject the previous native snapshot before the clear message arrived. The bridge now seeds once per tab using `drop_rate_native_session_bootstrapped`. `sessionStorage.clear()` preserves that marker before publishing the cleared session. A regression test covers immediate logout/navigation.

### Boundaries in the implementation

- Keychain records use `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`. The logout tombstone is an app-only UserDefaults flag, not a credential.
- The message handler validates main-frame origin and URL. The accepted hub origin is HTTPS, exact host, no embedded username/password, and no nonstandard port.
- Session payloads are validated and capped at 32 KiB. Client-supplied roles cannot become native privileges.
- External pages do not enter the session-bearing WKWebView. Own-origin blob downloads are allowed; third-party blob downloads are rejected.
- Failed session persistence blocks further navigation and requires retry. The app does not silently report successful secure persistence after a Keychain failure.
- The script-message handler is weakly held to avoid a retain cycle. Native download filenames are constrained to a final path component.
- The privacy manifest declares no tracking and includes the app-only UserDefaults required-reason declaration `CA92.1`.

This is implementation and automated-test evidence, not a full security audit. Real token expiry/revocation, account switching, process termination and free-account re-signing must still be exercised on the physical phone. When re-signing on Windows, verify the effective bundle ID and Keychain access group remain consistent; do not assume simulator entitlements prove free-account device signing.

<!-- pagebreak -->

## 5. Verification evidence and fixes already completed

### Latest verified application baseline

**Commit `bae0f9ebe76c683be0017ed29ae6612a858efdee`: both Seller Hub iPhone verification and Backend checks passed.** The TestFlight job was skipped as designed, not successfully uploaded.

| Evidence | Result and link |
| --- | --- |
| Latest iPhone workflow | [Run 37157893766](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/37157893766): verification successful; TestFlight skipped |
| Latest backend workflow | [Run 37157893757](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/37157893757): successful |
| Final session race fix | [Run 37157400843](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/37157400843): successful on `d151e3b` |
| Earlier native proof | [Run 37157094411](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/37157094411): successful on `478f7fc` |
| Local verification | Seven bridge tests; signing-shell syntax; plist/YAML checks; clean whitespace diff |

Seven JavaScript tests cover bootstrap restoration, preserving a newer tab session, refresh/logout/clear ordering, ignoring unrelated storage/profile data, blocking external/subframe injection, the actual shared hub logout and the immediate logout/navigation race. These tests use fixtures/mocked browser objects, not real account credentials.

Six native XCTest cases cover exact HTTPS origin policy, own-origin blob downloads, stripping client authority/password fields from stored sessions, download filename traversal, actual simulator Keychain rotation/logout/new-account behavior and the interrupted-logout tombstone. These are policy/storage tests, not end-to-end scanner or seller-workflow UI tests.

### Development history worth preserving

| Commit | Change |
| --- | --- |
| `de5f182` | Initial independent native container, configuration, workflow, tests and documentation |
| `049085f` | Replaced failing AppKit icon bitmap preparation with CoreGraphics/ImageIO; selected Xcode 26.3 |
| `478f7fc` | Added app Keychain entitlement and ad-hoc simulator signing; actual Keychain tests then passed |
| `d151e3b` | Added the once-per-tab bootstrap guard for immediate logout/navigation |
| `bae0f9e` | Corrected the Xcode 26 provisioning-profile directory and recorded native build evidence |

The initial failed runs were diagnostic and fixed, not ignored: run `37156530119` failed icon generation; run `37156695086` compiled the app but failed two Keychain tests in the unsigned simulator configuration. Subsequent successful runs cover the fixes.

The workflow uploads an `.xcresult` test-results artifact with seven-day retention. It currently does **not** upload a distributable IPA or even a Windows-ready unsigned IPA. An unsigned device compile is not an installation package and cannot be installed by tapping a link.

This handoff commit changes documentation only. Any check run triggered by the documentation update is separate from the verified application baseline above; inspect the current PR checks before a future merge or release.

<!-- pagebreak -->

## 6. Budget decision and the free Windows route

The user has no paid Apple Developer membership and wants to avoid extra cost. The app's prepared TestFlight route requires developer-program access, but personal testing has other options. Apple documents free Personal Team device testing with provisioning profiles that expire after seven days. [A1]

| Route | Cost/setup implication | Status for Drop Rate |
| --- | --- | --- |
| Windows personal installation | A tool such as Sideloadly supports a free Apple account; signing expires after seven days and must be refreshed. A Windows computer is needed for installation/refresh. [A2] | Candidate for tomorrow; package and device behavior unverified |
| Borrowed Mac and Xcode | Apple's free Personal Team testing route; recurring provisioning/reinstallation limits apply. [A1] | Possible alternative; user does not own a MacBook |
| Safari Home Screen web app | No Apple developer-program fee; Add to Home Screen and Open as Web App. [A3] | Can use the hosted hub, but does not install or test this native build |
| TestFlight / App Store | Apple Developer Program membership and account/signing setup; annual regional pricing. [A4] | Deferred; no membership or signing setup available |

Do not describe the Home Screen option as proof that the native application works. Its session persistence, browser permissions and lifecycle differ from the Keychain-backed wrapper. Adding a Home Screen icon has not been performed for the user in this session.

### Work required when the user resumes

1. Confirm the available Windows version, iPhone iOS version, cable/network access and chosen personal-installation tool. Follow the tool publisher's current requirements; Windows-side setup has not been done by the assistant.
2. Add a deliberate packaging/export step for the already-compiled device app. A normal unsigned IPA has `Payload/SellerHub.app` at its root. Produce a versioned artifact and checksum; make its unsigned/uninstallable-until-signed status explicit.
3. Review free-account signing compatibility, particularly the Keychain access group and any bundle-ID rewriting. A container with no extensions still needs correct personal signing; do not promise compatibility before testing it.
4. The user signs in to Apple locally in the chosen tool and pairs/trusts the iPhone. Do not collect Apple passwords or two-factor codes in chat, source files or GitHub Actions logs. Enable Developer Mode if the current installation instructions require it.
5. Install the app, prove launch/login/logout/camera/Files behavior, and record results against the installed build identifier. Only then call the personal test build usable.
6. Set up and prove refresh before the seven-day expiry. Automatic refresh still depends on the tool's computer/device connectivity requirements. Test that refreshing an existing installation preserves expected app/session behavior.

Sideloadly's documentation supports this general route; no claim is made that this exact package, its entitlements or the user's current iOS version has already worked with it. No Windows packaging changes or sideload installation were made tonight. Keep the existing native work; evaluate this route when the user returns rather than starting another app.

<!-- pagebreak -->

## 7. Prepared TestFlight route - deferred, not deployed

The repository contains a manual signing/upload workflow for a future TestFlight release. Keep it available; do not require the user to buy membership merely to continue today's handoff. Apple lists membership at USD 99 per year, with regional pricing shown during enrollment. This document does not assert an unverified UK checkout price. [A4]

### Existing workflow behavior

- PR/push verification performs the bridge tests, native simulator tests and unsigned device Release compile.
- A manual `workflow_dispatch` input, `upload_testflight=true`, enables upload only when run against reviewed `main`, after verification succeeds.
- The upload job references GitHub environment `seller-hub-testflight`. The name in YAML is not evidence that the environment, protection rules or credentials have been configured.
- The release script validates the supplied profile's team, exact app suffix, expiration and App Store distribution type; rejects development, ad-hoc or enterprise profiles; imports signing into a temporary Keychain; archives/exports and invokes Apple's upload tool.
- The script cleans its temporary signing files, Keychain and copied profile. The profile directory is the Xcode 16+ location: `~/Library/Developer/Xcode/UserData/Provisioning Profiles`.
- Build numbers are generated from the Actions run number/attempt. Upload is manual, not triggered by a PR; uploading is not the same as processing, invitation or approval.

### Future prerequisites

The owner needs an Apple Developer team/membership, the registered bundle `com.pulltheory.sellerhub`, a matching App Store Connect app record, an Apple Distribution certificate/private key, an App Store provisioning profile and a permitted App Store Connect API upload key. Register the app under the intended owner's account. Do not revoke or replace another application's certificate to proceed.

| GitHub secret name | Intended input |
| --- | --- |
| `APPLE_TEAM_ID` | Owning Apple development team identifier |
| `IOS_CERTIFICATE_BASE64` | Password-protected distribution P12, Base64 encoded |
| `IOS_CERTIFICATE_PASSWORD` | P12 password |
| `IOS_PROFILE_BASE64` | Matching App Store profile, Base64 encoded |
| `ASC_KEY_ID` | App Store Connect API key identifier |
| `ASC_ISSUER_ID` | App Store Connect issuer identifier |
| `ASC_PRIVATE_KEY_BASE64` | API private key, Base64 encoded |

Only variable names are listed here. No values were created, copied or verified. The connected GitHub fetch capability cannot inspect the repository's secrets/environment administration endpoints; their absence cannot be inferred from that tool. What is confirmed is the user's lack of paid membership and that no signing/upload happened in this work.

After a future upload, verify Apple processing and tester access separately. External testing may require beta review. A public App Store release additionally needs complete metadata, privacy disclosures and Apple review; this handoff does not claim eligibility or approval. [A5]

<!-- pagebreak -->

## 8. Physical iPhone acceptance and remaining risks

**Every device acceptance item below is still open.** Neither native unit tests nor a successful device compile prove these workflows. Use the iPhone 16 Pro Max, the installed build number and an authorized account. Record iOS version, result, reproduction steps and evidence for failures.

| Test area | Acceptance to record |
| --- | --- |
| Installation and refresh | App installs, launches and remains usable after personal-signing refresh; record effective bundle ID and refresh method. |
| Login and cold launch | Existing login opens the correct workspace; close/reopen retains the right account; logout/reopen stays signed out. |
| Account and permissions | Switching accounts cannot restore the previous user's session or inventory. Seller/Owner/Founder permissions match server access. |
| Token lifecycle | Expired and revoked sessions, refresh rotation, network interruption and locked-phone persistence failures produce correct recovery. |
| Camera | Allow/deny permission; recover after changing Settings; capture raw/graded/sealed examples supported by the existing scanner; background/foreground behavior works. |
| Recognition review | Candidate images and review controls work. Packaging does not guarantee recognition accuracy or justify confirming an uncertain identity. |
| Photos and Files | Select a photo; select an explicitly authorized test CSV; preserve the existing import validation and duplicate handling. |
| Inventory | Search, open, edit and save an authorized test item; confirm audit/ownership/readiness behavior matches the web hub. |
| Dialogs | Cancel and confirm are visible. Cancelling a listing/other confirmation causes no mutation. |
| Downloads | Export opens the share sheet, can be saved to Files, and does not leave a broken screen after dismissal. |
| External links | Shopify/Stripe links open separately, Done returns to the hub, and existing refresh reflects completed changes. |
| Sales/payout screens | Values and permitted controls match the web account. Do not move real money merely to smoke-test navigation. |
| Interruption | Airplane mode, reconnect, force quit, low-memory web termination and backgrounding give recoverable states. Check Inventory before repeating an interrupted save. |
| Layout | Notch/home indicator, keyboard, long forms, scrolling and accessibility text sizes remain usable. |

### Outstanding engineering risks

The free-signing package and entitlement transformation are untested. Real-world camera, file picker, downloads, external-return and auth lifecycle behavior need device proof. Social OAuth return is unimplemented because the providers are currently disabled. Password-reset return remains a website/email process. SessionStorage/form state may be lost if iOS terminates the web process; the app does not implement offline transactions or automatic save reconciliation.

Existing server-side rules remain authoritative. Do not disable RLS, weaken authentication, mass-publish products, activate external owners, modify financial history or create duplicate inventory to make a demo pass. Use existing repository safety rules and narrowly scoped, authorized test data.

### Rollback boundary

Nothing from this branch has been merged/deployed into the live web backend. Closing/reverting this app PR would not require a data rollback. Once a phone installation exists, removal/reinstallation can affect local credentials, so use explicit logout and verify identity rather than assuming uninstall clears Keychain. A future web change is a separate production change and needs its own checks.

<!-- pagebreak -->

## 9. File map and documentation changes

Paths in this table are relative to the repository root. This is the implemented package, not a list of future files to create.

| Path | Purpose |
| --- | --- |
| `seller-hub-ios/project.yml` | XcodeGen application/test targets and build settings |
| `seller-hub-ios/Info.plist` | Display identity, camera/photo descriptions, orientation and app metadata |
| `seller-hub-ios/SellerHub.entitlements` | App Keychain access group |
| `seller-hub-ios/Sources/SellerHubApp.swift` | SwiftUI entry, loading/error/retry/notice UI |
| `seller-hub-ios/Sources/HubWebView.swift` | WKWebView, navigation/media/dialog/download delegates and bridge coordination |
| `seller-hub-ios/Sources/SessionStore.swift` | Device-only Keychain storage and signed-out tombstone |
| `seller-hub-ios/Sources/HubPolicy.swift` | Trusted-origin rules, session sanitization and download names |
| `seller-hub-ios/Resources/session-bridge.js` | Single-key session bridge and once-per-tab bootstrap guard |
| `seller-hub-ios/Resources/PrivacyInfo.xcprivacy` | Privacy manifest and UserDefaults reason |
| `seller-hub-ios/Tests/HubPolicyTests.swift` | Six native policy/Keychain tests |
| `seller-hub-ios/scripts/session-bridge.test.mjs` | Seven bridge regressions |
| `seller-hub-ios/scripts/prepare-assets.swift` | Generates the app icon from the existing Drop Rate logo |
| `seller-hub-ios/scripts/testflight.sh` | Deferred manual distribution signing/export/upload |
| `seller-hub-ios/Assets.xcassets/Contents.json` | Asset catalogue metadata |
| `seller-hub-ios/Assets.xcassets/AppIcon.appiconset/Contents.json` | App icon catalogue definition |
| `seller-hub-ios/.gitignore` | Excludes generated project/build/icon outputs |
| `seller-hub-ios/README.md` | App behavior, setup, release and device acceptance |
| `.github/workflows/seller-hub-ios.yml` | Cloud verification and manual TestFlight upload |
| `BUILD_STATUS.md` | Current progress, release limits and this pause/handoff |

### Documentation updated with this handoff

- **This file:** the complete technical/product handoff, current evidence, known limits, installation choices and resume checklist. The PDF is generated from the same text.
- **BUILD_STATUS.md:** records that the latest application baseline passed both workflows; records no membership, limited funds, Windows availability, installation pause until the user resumes on/after 4 October, and the unprepared Windows route.
- **seller-hub-ios/README.md:** adds the latest budget/testing decision and a link to the detailed handoff; updates the next-step wording so TestFlight is clearly deferred.
- **CLAUDE.md:** adds a short pointer to this active handoff without changing the existing engineering safety contract.
- **PR #511 description:** replaces stale running-check language with verified results, links the handoff and records the pause and release limits.

No runtime Swift, JavaScript, workflow, signing script, backend, database, Shopify or Railway behavior is changed by this documentation update. Native-source changes remain the five application commits listed in section 5. The generated PDF is a shareable companion, not a new source of runtime configuration.

<!-- pagebreak -->

## 10. Resume checklist, commands and source links

### Give Claude this starting instruction

Continue the current Seller Hub iPhone work from draft PR #511 and branch `feat/current-seller-hub-iphone`. Read this handoff and the current build status, then inspect the latest branch/main/checks. Preserve the existing Seller Hub and Eamon's separate application. The owner has an iPhone 16 Pro Max and a Windows PC, no MacBook or paid Apple Developer membership, and limited funds. Installation was paused on 3 October. When the owner resumes, evaluate and prepare free Windows personal installation of this existing native build; do not purchase membership or substitute a Home Screen web app without explaining the difference. Build/unit checks pass, but no physical-device or signing success is claimed.

### First steps on return

1. Inspect the current PR state, branch heads and workflows. Do not overwrite another contributor's changes or force-push.
2. Check out the feature branch in a clean checkout. Read `CLAUDE.md`, `BUILD_STATUS.md`, `seller-hub-ios/README.md`, this handoff and the relevant tests/code.
3. Start with the Windows packaging/signing gap in section 6. Do not rebuild Eamon's Expo application or create another competing shell.
4. Keep the installation artifact, signing method and expected seven-day refresh process concrete before asking the user to install anything.
5. Use the phone acceptance checklist. Record actual results and unresolved failures in GitHub, with the exact build/commit installed.
6. Only consider a merge/release after current checks, review and the relevant device/signing work are complete. Never convert a passing unsigned build into a claim of TestFlight availability.

### Useful commands

```sh
git fetch origin
git switch feat/current-seller-hub-iphone
git log -5 --oneline
git status --short
node --test seller-hub-ios/scripts/session-bridge.test.mjs
bash -n seller-hub-ios/scripts/testflight.sh
```

The last command validates shell syntax only; it does not sign or upload. Xcode compilation runs on the cloud Mac workflow. Do not run `testflight.sh` or request its paid-account credentials as a prerequisite for evaluating free personal testing.

### Primary sources for the distribution choices

- **[A1] Apple - developer account and free Personal Team limits:** [developer account overview](https://developer.apple.com/help/account/basics/about-your-developer-account). Seven-day provisioning and free personal testing are distinct from distribution membership.
- **[A2] Sideloadly - publisher documentation:** [main site](https://sideloadly.io/index.html) and [FAQ](https://sideloadly.io/faq.html). Windows support, free-account signing, seven-day validity and computer-dependent refresh. These document the tool, not a successful Drop Rate installation.
- **[A3] Apple - iOS 26 Home Screen web apps:** [Safari web app instructions](https://support.apple.com/en-gb/guide/iphone/iphea86e5236/26/ios/26).
- **[A4] Apple - developer membership enrollment:** [enrollment and regional pricing](https://developer.apple.com/programs/enroll/).
- **[A5] Apple - TestFlight:** [testing and distribution overview](https://developer.apple.com/testflight/).
- **[A6] Apple Developer Technical Support - current profile location:** [provisioning profile discussion](https://developer.apple.com/forums/thread/812538). Supports the Xcode 16+ directory used in the release script.

Sources were checked on 3 October 2026. Follow current publisher instructions when installation resumes. The application and CI evidence are linked in sections 1 and 5; the handoff file's GitHub history identifies the documentation commit. No credentials are included in this handoff.
