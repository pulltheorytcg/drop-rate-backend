# Drop Rate native app

Active mobile development lives here. The iPhone app uses Swift/UIKit/WKWebView;
Android uses Java and Android WebView. Neither project depends on Expo, React
Native, a Node server, or an Expo account. The older `mobile/` project is retained
for reference only. Edit these projects in VS Code using `DropRate.code-workspace`.

Both apps start at https://app.droprate.co.uk/app. The hosted site owns login,
server-verified seller/founder access, inventory, scanning and selling. Shopify
remains the separate storefront. No authentication token bridge is added.
Both apps require a connection. Closing the app may require a new sign-in because
the hosted hub uses sessionStorage; cookies alone do not persist that session.

## iPhone

1. Install and launch Xcode, including its iOS platform support.
2. Open `ios/DropRate.xcodeproj` (or the VS Code task **Drop Rate: open iPhone project**).
3. Select the DropRate target → Signing & Capabilities → your Personal Team.
4. Choose an iPhone simulator and Run, or connect your iPhone, trust the Mac,
   enable Developer Mode when prompted, select it and Run.

A free Apple Account can be used for personal-device testing. Distribution via
TestFlight/App Store requires Apple Developer membership. Existing app identity
`com.pulltheory.tcg` is preserved; the display name and icon are Drop Rate.
Do not change an existing registered identity without checking signing ownership.

`./scripts/check.sh` runs the actual Swift navigation-policy tests, validates the
project, and builds for the simulator when Xcode is available. This machine's
Command Line Tools currently fail even Foundation imports with duplicate
SwiftBridging module definitions; this is an environment blocker, not a test pass.
Install full Xcode and run the checks again before treating this as a working build.

## Android

Install Android Studio with its JDK and Android SDK 36. Open `android/`, allow
Gradle sync, then choose a connected device or emulator and Run. The committed
Gradle 8.13 launcher and distribution are checksum-verified; AGP is pinned to
8.13.2. No global Gradle install is needed.

VS Code task **Drop Rate: build Android APK** runs `./gradlew assembleDebug`.
Set JAVA_HOME to Android Studio's JDK and ANDROID_HOME to the installed SDK when
building from a terminal. The debug APK appears at
`android/app/build/outputs/apk/debug/app-debug.apk`. Release signing is not configured.

## Device acceptance — not yet verified

- Sign in with a seller and an enrolled founder; verify each sees only allowed data.
- Run the existing live scanner with camera permission allowed, denied, and restored.
- Select card photos, cancel the picker, and test large photos and poor connections.
- Confirm a real card identity before adding inventory; don't fabricate test stock.
- Test keyboard, safe areas, Android Back, iPhone back swipe, and app background/resume.
- Verify logout, relaunch, session expiry and no cross-account data exposure.
- Verify external links and popup links. Social sign-in return from the browser is
  not implemented; use email/password for initial testing.
- Android's file input currently selects existing images only; live camera capture
  uses the site's getUserMedia scanner. Test both paths on a physical device.
- Downloads/export sharing and push notifications are not implemented in these shells.
- Audit privacy disclosures, account deletion and store submission requirements.

## Current evidence

Project/Info plists and Android manifest parse correctly. Native icon files are
present. iOS compilation and executable tests are blocked by the local Apple
toolchain; Android compilation is blocked by missing JDK/SDK. Neither native
project has been installed on a phone, signed for distribution, or store-reviewed.
The earlier Expo test results do not validate these replacement native projects.
