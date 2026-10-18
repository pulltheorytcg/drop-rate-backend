# Artwork, pricing capacity and book rescan recovery — 18 October 2026

The founder reopened the existing artwork/pricing and comic-scanner work. This
repair keeps the collection-first flow and the Phase 2 storefront publish gate.
No new service, subscription, external-owner activation or storefront publication.

## Verified storage recovery

At 01:44:32 UTC, production held 50,378 reference-market-history records and used
405,662,867 bytes. Every full row was exported in UUID order through that cutoff
in 26 chunks; each raw checksum, gzip checksum, field set and row boundary passed.
All 50,378 rows were restored into disposable PGlite 0.5.9 / PostgreSQL 18.6 with
the production column types, primary/unique keys and checks. Every restored
canonical row and quote digest matched; cross-chunk duplicate IDs were rejected.

The restore checker previously inherited the host timezone, causing identical
timestamp instants to serialize differently. It now sets UTC and ISO date style,
matching the production archive guard; no digest validation was weakened.

The connected account and folder permissions were verified as
`dropratetcg@gmail.com`, owner-only. The archive was uploaded to the established
private Drop Rate folder, downloaded in full, and passed complete SHA-256 and ZIP
CRC checks before the existing atomic content guard was called.

- Drive file: `1kcQLe59MTkMgx9nuyw70gWZZQZMObPeD`
- Archive ID: `drop-rate-reference-history-20261018-014432`
- Package bytes: 7,516,613
- Package SHA-256: `bfb1b0bae8afe0c4e9da52e6f0ee8aaddf4a2a0b3135fc3398a17bdc94abd5ea`
- Full content root: `580ae9dca18c179ec3458a2a9c8745bb95a809f008c2c864eff0260ce22cbff6`
- Restore verified: 01:49:21 UTC; download verified: 01:50:43 UTC.
- Atomic archive committed: 01:51:23 UTC; reclaimed 77,053,952 bytes.
- Fresh connection: database 328,608,915 bytes, read/write, live history 0 rows.
- Inventory owner/status/Store Price fingerprint unchanged:
  `269f6a8aebed9e4b29ddc8236ec853cf`.
- Complete current reference-price cache fingerprint unchanged:
  `f0b98c9b30f6074d6e8bf6e4b3f5f546`.

The 400 MB bulk-update guard now permits work again. Weekly Monday 03:00 UK bulk
pricing and daily catalogue scheduling remain unchanged. This was an explicitly
verified maintenance run, not proof that unattended daily archiving works.

## Book rescan correction

A new scan that failed or returned NO_MATCH could retain the last successful
book's identity and displayed value. Starting another read or changing photos now
clears the old identity, publisher selection/cover and price display. Failed reads
retain the photos for retry and allow manual entry without Marvel/English defaults.
Immutable save retries still lock the original payload; photo changes cannot
alter a pending save. Existing owner and asynchronous-response guards remain.

Chromium/WebKit regression cases exercise success → provider failure, success →
NO_MATCH, removal of photos, stale value removal and no unintended intake writes.
The owner shell versions the changed book script. Publisher research and exact
printing confirmation remain suggestions followed by explicit Add to collection.

The real PostgreSQL gate also exposed a concurrent Add race: another request
could commit between the initial receipt lookup and the inventory lookup, causing
a false 409 despite an atomic copy+receipt commit. Intake now rereads the receipt
in that case and checks the original payload hash/owner before replaying. A
deterministic signed-HTTP test forces that exact interleaving and confirms one copy.
Genuinely receiptless rows and changed payloads still fail closed.

## Source work and remaining limits

The opt-in CardTrader review probe uses the existing credential internally to
read up to 12 named Pokémon releases (14 API requests maximum, 90-second cap).
Each log line contains public blueprint identity/artwork only. It does not read
private inventory, request market listings, write mappings/images/prices, or add
a scheduler. Output is evidence for exact matching and visual review, not approval
to substitute English artwork for Japanese cards or a generic image for a variant.

At the start of this repair, 10,904 Pokémon references lacked image URLs. The last
full pricing audit was 40,443 / 67,060 physical references (60.31%), including
labelled mixed-language guides. eBay/Trawl remains paused after HTTP 429 until
18 October 17:39:35 UTC. No early retry or invented sold price is permitted.
Book printings/condition still need confirmation before exact sold-value matching.
Final artwork changes, source receipts, CI and deployment are recorded in the PR.

## Physical iPhone check still required

1. Open Scan → Comics / Manga and photograph a real cover.
2. Check the proposed title, issue/volume, language and publisher cover.
3. If the printing is unresolved, add a photo of the copyright page/barcode and
   identify again; the customer should not need to research it themselves.
4. Add the book, return to Collection, and confirm exactly one copy and the same
   artwork. Unknown printing/value must remain visibly unknown.
5. Try a different cover and an unreadable photo: the prior title/cover/value must
   not remain as the new result.
6. Record the taps, time and any wrong match on the user's iPhone 16 Pro Max.

Browser fixtures and public publisher cover probes do not establish real-copy
recognition accuracy. Keep the original photos out of Git and public logs.

Rollback the UI to main bfb1f688d4914a12d48ef59cb58f848153afe033 if necessary.
History remains retrievable from the verified private archive; do not bulk restore
it into the production Free database. No schema rollback is required.
