# Collectr reference scanner flow

## Status — 2 October 2026

Released to Seller Hub and Founder HQ on 2 October at 15:03 BST. PR #497
merged, followed by catalogue PR #498. The deployed main commit is
`725fb745d5857a9a5ed51b2e46ad638091b2f8d2`; Railway deployment
`46762407-3faf-4198-919a-b1f99a5c3c10` is successful.

Both health endpoints return 200. The live `/`, `/owner` and `/app` pages
load the reviewed scanner and catalogue scripts/styles; all eight checked
assets match the release byte-for-byte. Anonymous catalogue requests remain
401. Railway's pre-deploy suite passed 2,372 tests. Reload existing open tabs
to receive the new UI. Physical camera/card/provider acceptance is still pending.

The follow-up requested at 06:03 BST adds visible **RAW | GRADED | SEALED**
controls both before and inside the shared camera. Each scan retains its mode;
a mode change cannot reinterpret an in-flight image or an existing batch item.
RAW and SEALED keep the current recognition service and matching gates. SEALED
uses a square guide to include packs, boxes and sets. GRADED uses the existing
QR parser, certificate lookup and slab-label reader, then requires a human card,
grade and certificate confirmation. One certificate creates at most one slab;
raw-card prices never appear as graded values. Conflicts remain blocked.
Founders use a founder-authorized adapter to the same certificate intake checks;
sellers retain their restricted endpoint. Both start as Draft with identity review.
The shared camera now opens from both hubs on desktop as well as mobile; the
older standalone photo workflows remain available.

Targeted verification: 20 scanner scenarios and 58 existing slab/intake/shell
checks pass. The baseline camera/review browser fixture passes for both hubs.
No live card recognition, certificate provider acceptance or production write was
performed during implementation. Product browsing shipped through separate PR
#498. The user clarified that testing meant the new UI in the actual hubs, so the
earlier baseline hold ended and both changes were deployed. No database migration,
provider configuration, recognition scoring or native installer is part of this
change.

The reference is the user's 110-second Collectr screen recording supplied on
2 October. This change follows its camera → thumbnails → details → review → add
sequence in the existing mobile web app, shared by Seller Hub and Founder HQ.
Following the user's review, the same structure now uses Drop Rate's established
navy, blue and cyan palette, with white/pale-grey detail and review surfaces.
This follow-up changes colours only: component geometry, copy and scanner behaviour
are preserved. Both hub entry points load the updated stylesheet version.
The active native app's WebView receives this web presentation when it reloads
the live URL; physical-device compatibility still requires acceptance testing.

## Interaction

- The live camera stays full screen, with a thin guide, translucent toolbar,
  compact newest-first thumbnail tray, total, gallery, shutter and Next button.
  A captured thumbnail appears immediately as Loading while the real recognition
  request completes. Only one recognition request runs at a time.
- The settings menu retains camera switching and a torch when the hardware
  supports it, and lets the user turn automatic capture off.
- A thumbnail opens Scan Details: the captured photo and reference artwork,
  alternative matches, manual search, printing information, condition, quantity,
  remove and Looks Good. Alternative printing selection stays tied to a real
  catalogue/reference identity, not free-text variant claims.
- Review Your Matches shows each scan and its physical details, with a persistent
  total and Add to Inventory action. Conditions must be chosen explicitly for
  raw cards. Quantities from 1 to 50 create that many physical inventory copies.
  Unknown market values remain unknown; a partial total identifies pending values.
- Completed saves can open the existing inventory. Captured photos remain only
  in memory and are cleared when the item is saved, removed or the session ends.

Drop Rate keeps its inventory terminology and approval rules. Collectr portfolio
selection, sold-listing links, optional price-paid controls and free grader
selection are not invented. The existing dedicated graded-slab/certificate flow,
desktop scanner and standalone photo-upload workflow remain available. The new
gallery control inside the mobile camera uses this new thumbnail/review flow.

## API and safety boundaries

`scanner-flow.js` owns the common presentation and batch interaction. Its role
adapters use existing endpoints:

| Operation | Seller Hub | Founder HQ |
| --- | --- | --- |
| Recognition and feedback | Existing `/api/v1/recognition/*` | Same authenticated endpoints |
| Search correction | Existing owner-scoped catalogue and governed-reference search | Existing canonical catalogue search |
| Inventory save | `/api/v1/owner/recognition-intake` | `/api/v1/inventory/intake` |
| Destination | Signed-in seller's inventory | Signed-in founder's inventory |

No browser-supplied owner ID is accepted or sent. Founder roster, authentication,
RLS, channel permissions and database rules are unchanged. Founder intake remains
Draft with identity confirmation false. Seller intake retains its existing
verified-exact-sealed exception and post-commit market refresh.

Unresolved recognition cannot be added. A human may choose a canonical candidate
or explicitly materialize a governed printing through the existing server gates.
Manual correction is recorded as `CORRECTED_BY_SEARCH`; other confirmations use
the existing top/candidate feedback outcomes before inventory intake. Unverified
sealed candidates remain blocked for Drop Rate review.

Every physical copy receives its own immutable idempotency key and serialized
payload before saving starts. A second click coalesces into the active save.
After a lost response, retry uses the same key and exact payload; confirmed copies
are skipped. Editing/removal is locked once requests have been prepared. A failure
in inventory refresh does not change the recorded save result.

Async work is tied to the signed-in account and scanner lifetime. Logout clears
photos, aborts pending reads, releases the camera and prevents subsequent writes
from that batch. An in-flight server request can still complete for the original
account; its result cannot become another account's batch. A camera permission
grant arriving after close immediately stops the returned tracks.

Scanner requests snapshot their authorization token and disable the legacy
request helper's automatic retry. Expiring sessions refresh against the captured
account, and the result is checked before installing the session or sending the
request. A late refresh cannot restore an old account after a different login.

The previous foreground-presence/stability thresholds and two-empty-frame removal
gate are retained. Capture now maps the visible guide to the camera's actual
`object-fit: cover` geometry. Output is JPEG capped at 1,500 pixels without
upscaling. Recognition latency and accuracy are not changed or benchmarked here.

## Verification

- 2,349 backend tests and JavaScript syntax checks pass; existing role, recognition,
  graded-slab, sealed-intake and authorization tests remain intact.
- `npm ci && npm test` in `tests/ui`: existing workspace/account checks plus 15
  scanner scenarios covering pending states, unresolved/unknown values, both
  role adapters, condition/quantity validation, human correction, stale searches,
  unverified sealed products, removal gates, partial multi-copy saves, lost
  responses, double clicks, session changes and camera permission failures.
- The dashboard interaction suite now runs in the `dashboard-ui` CI job.
- Browser checks exercised the real Seller Hub entry at 390×844, 320×568 and
  844×390, and Founder HQ at 390×844. Camera guide/tray geometry and review were
  checked for horizontal overflow; both intake adapters completed their fixture
  flow with no page errors.
- The brand-colour follow-up was checked against the approved layout: every
  non-colour CSS declaration is identical, as are the measured camera guide/tray
  positions at all three screen sizes. Refreshed previews cover both hub themes.
- Screenshots use a local simulated camera, official SAMPLE reference artwork,
  fixture recognition/value responses and simulated saves. They are UI previews,
  not recognition evidence or production inventory writes.

Outstanding live acceptance: user's baseline findings, real rear-camera permission
and gallery behavior on iPhone/Android, accurate guide framing with actual cards,
glare/parallel/promo correction and real network-interruption acceptance. If the
new flow regresses, restore Railway API deployment
`c408306f-8aef-4ec2-87d8-6bbf51e7c44d` (commit `a7ba4be9603e838d2631a6d83c564ecd43482867`),
then check health and both hub pages. No database rollback is required.
