# iOS 27 Auction Lens capture — isolated feasibility code

**EXPERIMENTAL ONLY. NOT COMPILED, NOT IN EXPO AUTOLINK, NOT A SHIPPING FEATURE.**

\`DropRateAuctionScreenProbe.swift\` is a native capture **source** built from the API shape published by Apple for iOS 27 ScreenCaptureKit. It is intentionally kept out of \`mobile/modules\` and \`mobile/src\` until an Xcode 27 SDK device pilot and explicit product/privacy review.

The real current Drop Rate app is an Expo WebView wrapper. A native service must be added and explicitly bridged to the authenticated FastAPI session; simply shipping this Swift file would not provide iPhone auction scanning.

## What this experimental source does

- Presents Apple's **system** full-screen content-sharing picker after an explicit, confirmed product-region selection. No silent recording.
- Attaches **screen output only**; audio/microphone recording remains disabled. Processes up to four crops per second.
- Crops the selected object **on-device** before generating a JPEG; computes a 64-bit difference hash used by the existing \`mobile/src/lib/auctionLensStream.ts\` scheduler.
- Forwards cropped data **only to a local callback**, not a server; no recording to disk, no persistent frame buffer.
- Stops or signals revocation if capture ends; rejects blank, low-contrast content.

## Key limitations

- This does NOT run on iOS 26 or earlier, and Apple marks its 2026 iOS sample documentation as preliminary. Compile against the final iOS 27 SDK and verify the exact picker/capture signatures with a real device.
- iOS background execution requires an Apple-approved screen-capture background mode and careful treatment of Expo/React Native suspension. An Expo JavaScript callback is **not** a reliable background transport while another auction app is frontmost; a native, credential-safe bounded queue/uploader and authenticated server session are separate required work. Do not grant the WebView token to the native layer implicitly.
- A screen-capture permission prompt is not a third-party platform licence. No capture from Whatnot/eBay is authorised by this code. Pilot only on owner-created/expressly permitted footage and test actual third-party terms separately.
- The cropped region can still contain user names or notifications if placed poorly. Implement user review, guidance, secure processing disclosures, stop controls and rate controls before uploading anything.
- No Picture-in-Picture overlay is implemented. iOS PiP and Live Activity are different presentation mechanisms, subject to their intended uses and device constraints.

## Acceptance checks before linking

1. Native Swift builds on the final SDK and produces consent/picker/capture callbacks on a supported physical iPhone.
2. Denied/revoked/blank stream does not upload and clears old price; no request after Stop.
3. 30-minute capture battery/thermal measurements, real frame-crop hash throughput, background/suspended app behavior.
4. Independent access controls: one signed-in user -> one capture session, no cross-user or provider credential leakage; secure short-lived native authentication with expiry.
5. Genuine authorised video corpus, accuracy by exact printing/variant/grade and measured median/p95 time, before any customer exposure.
6. Document platform permissions and result presentation approach. Never emulate an audio/video call to acquire unrelated PiP background privileges.

Official references:
- https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-on-ios
- https://developer.apple.com/documentation/screencapturekit/sccontentsharingpickerobserver
- https://developer.apple.com/documentation/screencapturekit
