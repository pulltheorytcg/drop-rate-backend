# Drop Rate mobile-app YouTube Short capture plan

## Goal

Record the real Drop Rate mobile app in use as a short product demonstration. This must be a genuine capture of the current unified app, not the retired prototype routes, a mocked demo account, or AI-generated UI.

Target output: 1080×1920, 9:16, approximately 30–45 seconds, with narration and burned-in captions before YouTube approval.

## What the current app actually is

The active iOS/Android wrapper opens the live Drop Rate `/app` hub. The authenticated server role selects Founder HQ or Seller Hub. The mobile wrapper does not maintain a replacement native dashboard.

The current shared scanner genuinely supports:
- RAW / GRADED / SEALED mode tabs;
- live rear-camera capture;
- auto-scan;
- exact candidate review with reference artwork;
- condition selection for raw cards;
- grader/grade/certificate handling for graded cards;
- visible market value when a valid valuation exists;
- Review Your Matches;
- Add to Inventory;
- inventory refresh after save.

Do not record `mobile/prototype-routes` or the `createDemo` fixture. They are not the active product.

## Capture account/data

Use an authorised founder account with no password typing shown in the recording. Start already authenticated.

Use one deliberately selected physical raw card that:
1. is not already in inventory under the same physical item;
2. is known to resolve reliably through the live recognition corpus;
3. has clean reference artwork;
4. has a valid market value if possible;
5. is safe to create as a real inventory item and can remain in inventory after the demonstration.

Never invent a card, result, price, recognition confidence or successful save for the video.

## Primary 35-second sequence

### 0–3 s — App launch

Open Drop Rate from the iPhone home screen.

Hold briefly on the real Founder HQ/Seller Hub landing screen so viewers understand this is an actual product rather than a design animation.

Suggested caption:
**Your TCG collection. One app.**

### 3–7 s — Open scanner

Tap the real Scan action.

Let the full-screen camera settle long enough to show the actual `RAW | GRADED | SEALED` control.

Suggested caption:
**Scan raw, graded or sealed.**

### 7–13 s — Scan one real card

Stay on RAW.

Place the chosen physical card inside the live camera guide and let auto-scan/capture trigger naturally. Do not cut before the actual captured thumbnail appears.

Suggested narration:
“Scan a card and Drop Rate starts matching the exact printing.”

### 13–21 s — Recognition/review

Show the real candidate/reference artwork and then `Review Your Matches`.

The visible name, set, collector number, variant and language must correspond to the physical card. If recognition enters review instead of exact match, show the human review rather than hiding it.

Suggested caption:
**Exact print first. No guessing.**

### 21–27 s — Physical details + market value

Open the real detail sheet.

Show condition selection and, only when present, the real market value. Do not substitute a number in post-production.

Suggested narration:
“Confirm the print, condition and live valuation before it enters inventory.”

### 27–32 s — Add to Inventory

Tap the real `Add to Inventory` action.

Keep the save state visible until the app itself reports success.

Suggested caption:
**One tap to inventory.**

### 32–38 s — Payoff

Tap/view Inventory and show the newly added physical item.

End on the Drop Rate identity / inventory screen.

Suggested narration:
“From card to tracked inventory in seconds. This is Drop Rate.”

End card:
**DROP RATE**
**droprate.co.uk**
**Cards. Data. Ownership.**

## Optional second recording

Capture GRADED mode separately for a later Short:
- switch to GRADED;
- frame the full slab;
- scan/read certificate QR where available;
- show grader + grade + certificate evidence;
- confirm exact card;
- add to inventory.

Do not combine both raw and graded flows into the first 35-second video unless the real interaction remains readable.

## Editing rules

- Keep the actual UI pixels untouched except for crop/reframe needed to fit the native 9:16 capture.
- No fake taps, fake loading completion, fake values or replaced UI.
- Never show passwords, auth tokens, private email addresses, other owners' sensitive information or customer data.
- Do not speed-ramp recognition so aggressively that the app appears faster than the actual recorded interaction.
- Remove dead time with hard cuts, but preserve the real order of events.
- Narration and captions may explain what happened; they must not claim a feature that was not shown.
- No music is required. Prefer app sounds/clean narration where appropriate.

## YouTube publication gate

After the edit:
1. export exact 1080×1920 H.264 MP4 with AAC narration;
2. burn approved captions into the pixels;
3. founder reviews the final rendered MP4;
4. upload the exact approved file to the approved Drop Rate host;
5. bind URL, SHA-256, byte count, duration, title, description, category and approval into the immutable YouTube pilot manifest;
6. run read-only preflight;
7. temporarily enable that exact revision;
8. publish once through n8n → FastAPI → Buffer;
9. read provider delivery status separately;
10. replay the identical trigger and prove no second upload;
11. disable the exact revision and remove temporary operator commands.

The existing YouTube channel readiness and inactive contract do not themselves authorise publication.
