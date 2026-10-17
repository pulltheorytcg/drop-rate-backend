# Comics and manga in the live scanner

The 17 October iPhone recording showed that **COMICS / MANGA** closed the shared scanner and opened a manual photo form. Its camera button then launched the phone's separate file-capture camera. The tab did not select a live scanner mode.

The tab now selects `COMIC` in the existing scanner. It keeps the current camera stream, uses a book-shaped guide, and shares the shutter, gallery, auto-scan, stable-object/removal gate and two-request limit. Captures call the existing authenticated `/api/v1/owner/books/recognize` endpoint directly. Captured covers and suggested series/issue or volume appear in the same results tray as other scans.

Book review receives the captured photo and completed recognition response, so opening review does not repeat recognition. The seller can add a barcode/copyright-page/label photo, correct the edition and physical-copy details, check existing matching market evidence and explicitly add a draft. Closing review returns to the scanner results without opening another camera stream. A successful intake receipt marks only its originating scan as added and clears its captured photo.

Books cannot enter card recognition feedback or card/graded-card intake. A failed read cannot inherit the manual form's Marvel/English defaults. No printing, condition, price, graded identity or publication is automatically approved. Failed recognition keeps the photo available for retry. An uncertain save retains its original payload, idempotency key and originating scan even if a different queued book is opened. Account changes and scanner destruction invalidate late results/callbacks.

## Verification

- Local scanner suite: 50 interaction scenarios, including comic/manga mode, shared auto-scan/removal gating, recognition routing, no write/second recognition on review, failed reads, stale account results and uncertain-save callback ownership.
- Local focused Python checks: 75 passed for owner shell, book recognition, comic intake and browse boundaries.
- Real Chromium/WebKit checks at 390px and 1440px exercise the shared live-camera controls with a fixture stream, real canvas/gallery image encoding, captured-photo handoff, book review and explicit save/return receipt. Existing card/sealed/graded/browser and PostgreSQL gates also run in the PR.
- CI and deployed asset readback are release gates; the completed receipt belongs in the PR description.

The supplied recording contains no book being recognised. These interaction tests do not establish recognition accuracy for a real cover, glare, a slab label or an unreadable printing. The eBay sold-data provider limit remains separate; this change creates no market prices, new service, database migration or Shopify publication.
