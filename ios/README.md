# Drop Rate for iPhone

Native SwiftUI Seller Hub client, iOS 17+. Uses the existing Drop Rate production API and restricted OWNER accounts. Founder administrator accounts intentionally cannot enter the seller APIs.

## Build

Open `DropRate.xcodeproj` in Xcode on a Mac, select the `DropRate` scheme, and choose an iPhone simulator or physical iPhone. There are no third-party iOS dependencies. Select your Apple Developer team and register the final bundle identifier before device distribution. Camera testing requires a physical device.

The `iPhone app checks` GitHub workflow builds and runs XCTest on a Mac. Unsigned simulator builds are not installable iPhone releases.

## Implemented

- Existing email/username login; password is never persisted. Session tokens use device-only Keychain storage, single-flight refresh, and local session revocation on sign-out.
- Native full-screen rear camera opens from the Scan tab without an upload/open-camera screen. Portrait capture, torch, permission recovery, and background shutdown.
- Raw card, slab, comic, graded comic modes. English/Japanese OCR on device; card photos go to the existing recognition API after capture.
- PSA/BGS/ACE/CGC label-text extraction with editable certificate field; ambiguous readings require manual input. This does **not** verify certificates with graders.
- Card candidates, manual catalogue correction, condition/language/grade entry, explicit confirmation, draft intake with an immutable request payload and idempotency key for retry. Interrupted saves survive app restarts in device-only Keychain records separated by authenticated user ID.
- Image grid portfolio with real market/store totals, status/search filters, pagination, item details, and missing valuations kept visibly unknown.
- Global card search, TCG browsing, exact language filters and pagination using new read-only `/api/v1/owner/mobile` routes.
- Native profile name/username settings. Sales/payouts/security open the existing Seller Hub in the browser.

## Remaining release work — do not represent as complete

1. Comic cover OCR works, but the current database/recognition/intake contracts support cards only. A comic catalogue, comic physical-state model, valuation sources and owner-safe intake must be built before comics can be identified and saved. The app explicitly reports this limitation.
2. Certificate OCR needs a real slab acceptance dataset across PSA, BGS, ACE and CGC, including label revisions, glare and barcode formats. Provider verification integrations are not implemented and must not be inferred from OCR.
3. Validate live login, two-owner isolation, refresh, scan accuracy, cancellation, offline/retry, actual portfolio images, and real iPhone camera permission/background behaviour. Tests cannot establish card-recognition accuracy or Collectr parity.
4. New catalogue browsing routes require backend deployment before the app's TCG search works. Existing card lookup and inventory endpoints already exist.
5. Finish native sales/payouts/security flows, account deletion entry, final approved App Store icon, accessibility/device visual QA and privacy review. App Store privacy declarations must cover the deployed backend and recognition processors.
6. Apple Developer team, App Store Connect record, signing/provisioning and TestFlight upload are required. None were available/configured in this Windows session. This repository contains source, not a signed IPA or App Store release.

## Behaviour notes

Portfolio totals are the backend's active-stock totals, independent of grid filters; sold stock is excluded from those totals. Store value falls back to recommended retail where no explicit store price exists. Each tile remains a distinct physical inventory item. Catalogue values are reference values, not slab-specific valuations.

No database migration, production data mutation, or Shopify publishing changes are included. OCR never approves an identity. Inventory saving remains on existing server-owned validation, audit and pricing paths. A timed-out save can be retried in the review screen with the same idempotency key. After restarting, a recovery prompt offers the same request; the Scan tab also reopens that prompt until the pending save succeeds. A permanently rejected pending request requires support/reconciliation before scanning another item; it is not silently discarded.
