# Verified catalogue repair — 18 October 2026

Applied 540 missing English Pokémon reference images at 02:29 UTC. Fresh database
readback at 02:31 UTC matched every intended ID, release, name, collector number,
URL and image SHA-256. All ten reviewed releases now have zero missing image URLs.
Pokémon gaps fell from 10,904 to 10,364 (English 1,780 to 1,240; Japanese unchanged).
These are reference images, not approved physical-copy media or finish identities.

## Evidence

- `source-report.json` records the bounded 12-request CardTrader export and the
  ten complete checklists: 2,137 public records. Its `source_order` lists the JSON
  files to concatenate. Canonical JSON (sorted object keys, UTF-8, no extra
  whitespace) has SHA-256
  `e3293fd6242a35d9913d699be93109627efcc7692f51d8a4d4008c0e871f58f5`.
- Each `artwork-*.json` contains the exact applied identity, observed source URL,
  image hash, language evidence and review receipt. All 540 HTTP responses decoded
  as rasters. Only the same-path redirect from cardtrader.com to www.cardtrader.com
  was accepted. Original provider preview URLs were retained; no guessed original
  URL, generated image, generic card or English-for-Japanese substitution was used.
- 462 images were visually checked, including every source-label exception;
  78 others had multiple English text markers in local OCR. The source's editable
  language default was never sufficient on its own. Contact sheets and OCR were
  temporary QA tools, not modified catalogue assets. Image hashes identify the
  exact reviewed source bytes.
- Full source and reference checklists were considered when counting competing
  collector numbers. Unmapped/unpriced candidates still count as ambiguity.
  Gallery matches require the named parent release and SV/GG/TG prefix. No ordinary
  release or similarly named regional product can substitute for those galleries.
- `before-artwork.json` proves all 540 old URLs were null and all lacked an
  `image_reference`. Six conditional updates touched only those reference fields.
  `write-receipts.json` records every updated ID. `verification.json` contains the
  independent readback and unchanged inventory/current physical-price fingerprints.

## Individually reviewed source-label exceptions

The full source records are retained unchanged. The applied proof records the
correction separately; there is no broad fuzzy-name or number fallback.

- Shining Fates blueprint 153083 says `Hatternee`; its English card visibly says
  Hatterene, SV56. The exact reference is `swsh4.5sv-SV056`.
- Lost Origin blueprint 221499 includes `- Lysandre` in the source name. The
  printed English card is Boss's Orders TG24; the reference is `swsh11tg-TG24`.
- Dragon Majesty blueprints 114272 and 114375 expand the printed diamond to
  `◇ Prism Star`. The reviewed cards retain that diamond (Victini 7, Lance 61).
- Aquapolis and Skyridge each encode H1–H9 as `0H1/H32` through `0H9/H32` in the
  fixed property. Their separate version field and the reviewed images show
  H1/H32 through H9/H32. Only those 18 exact source records received that correction.

## Price guides and deployment

PR #685 preserves Nidoran's `[F]`/`[M]` identity and the explicit Prism diamond while
matching provider labels. Its 70 focused tests and both CI workflows passed.
Main `4a3cfe56c87701a400843f8f1a156e1ae86f6c94` deployed successfully as Railway
`cf4b00cd-2915-410c-8299-3b13f08291fc`; production predeploy passed 6,161 tests.
Readiness and owner HTML returned 200, and the live book-rescan-v2 script matched
the reviewed bytes. The original predeploy command was restored after the probe.

`price-repair.json` retains original empty cache rows, exact source product IDs,
the dated Cardmarket guide fields and ECB conversion evidence for Skyridge 81/82
and Dragon Majesty 7. Six quotes across these three references were written only
after exact reference checks and a compare-and-set against the prior empty cache.
They remain mixed-language, condition-unspecified guides and are ineligible for
physical-copy valuation. No Store Price or inventory value was changed.

`coverage.json` is the application's live coverage query after repair: 40,446 of
67,060 physical references have a reference or labelled guide (60.31%). This does
not mean every guide is a fresh exact sold price. eBay/Trawl remained in its
existing HTTP 429 cooldown; no early request was made. The first permitted
recheck is 18 October 17:39:35 UTC, and official sold-data access remains unresolved.

## Guarded rollback

This is an audit snapshot, not an unattended repair job. Load manifests through a
client; never read files or run operating-system commands through database SQL.
For artwork rollback, first require each current identity, URL, repair batch and
image SHA to equal the corresponding applied manifest. Only then restore its
original null URL and remove that batch's `image_reference`, preserving all other
evidence. Skip a row changed by a later provider refresh or repair. Daily imports
already preserve a fallback image and its provenance when the same identity's
source feed omits artwork.

For guide rollback, require the entire current quotes, checked timestamp and
source timestamp to equal this repair before restoring its `before.prior_guides`
entry. Never overwrite newer market data. The history archive is independently
registered and verified; do not restore it wholesale into the Free database.

Unresolved source releases (both promo families), other missing English/Japanese
artwork, missing provider access/mappings and the real-comic iPhone trial remain
separate follow-up work. No Shopify publication or new service was performed.
