# Manga demographic review — 4 November 2026

## Scope and rationale

Add **42 exact reviewed series/edition keys** to the existing catalogue *display*
classification. This is **not** a genre classifier. Shōnen/Shōjo/Seinen/Josei
refer to the original Japanese magazine's publishing demographic, not whether
a story has romance, action, male/female characters, its age rating, or its
English translation's imprint. Where a series moved magazines, the initial
manga series' source dominates only when the matching catalogue entry is the
original serial; ambiguous sequels/alternative works stay Unclassified.

No SQL migration, bulk catalogue import, artwork, pricing, inventory, seller,
owner, purchase or financial changes are involved. Both Python result display
and the SQL predicate used **before pagination** read the same literal
allowlist. Existing 10 previously reviewed keys remain unchanged.

## Reviewed series and evidence

Source references below support the *original serial or Japanese imprint*;
named English omnibuses and unusual punctuation are **exact source-database
title aliases** of that serial, not separate demographic evidence.

### Shōnen — original publications

| Exact catalogue series / alias | Original magazine / evidence |
| --- | --- |
| Rave Master; Rave Master (Rave Master (Graphic Novels)) | [Weekly Shōnen Magazine](https://en.wikipedia.org/wiki/Rave_Master) |
| Steel Angel Kurumi | [Ace Next / Shōnen Ace](https://en.wikipedia.org/wiki/Steel_Angel_Kurumi) |
| Suzuka | [Weekly Shōnen Magazine](https://en.wikipedia.org/wiki/Suzuka_(manga)) |
| Iron Wok Jan | [Weekly Shōnen Champion](https://en.wikipedia.org/wiki/Iron_Wok_Jan) |
| A.I. Love You | [Weekly Shōnen Magazine](https://en.wikipedia.org/wiki/A.I._Love_You) |
| Flame of Recca | [Weekly Shōnen Sunday](https://en.wikipedia.org/wiki/Flame_of_Recca) |
| School Rumble | [Weekly Shōnen Magazine](https://en.wikipedia.org/wiki/School_Rumble) |
| Sgt. Frog | [Monthly Shōnen Ace](https://en.wikipedia.org/wiki/Sgt._Frog) |
| The Law of Ueki | [Weekly Shōnen Sunday](https://en.wikipedia.org/wiki/The_Law_of_Ueki) |
| Yakitate!! Japan | [Weekly Shōnen Sunday](https://en.wikipedia.org/wiki/Yakitate!!_Japan) |
| Zatch Bell! | [Weekly Shōnen Sunday](https://en.wikipedia.org/wiki/Zatch_Bell!) |
| Shaman King | [Weekly Shōnen Jump](https://findyourjump.com/en/manga/shaman-king) |
| Gin Tama | [Weekly Shōnen Jump](https://www.viz.com/gin-tama) |
| Slam Dunk | [Weekly Shōnen Jump; official series site](https://slamdunk-movie.jp/en/about/) |
| D.Gray-man | [Weekly Shōnen Jump; VIZ](https://www.viz.com/d-gray-man) |
| GetBackers (Getbackers source spelling also matches) | [Weekly Shōnen Magazine](https://en.wikipedia.org/wiki/GetBackers) |
| Case Closed | [Weekly Shōnen Sunday; VIZ](https://www.viz.com/manga-books/vizmanga/section/shonen-sunday) |
| Hayate The Combat Butler | [Weekly Shōnen Sunday; VIZ](https://www.viz.com/hayate-the-combat-butler) |
| The Prince of Tennis | [Weekly Shōnen Jump; VIZ](https://www.viz.com/prince-of-tennis) |

### Seinen — original publications

| Exact catalogue series / alias | Original magazine / evidence |
| --- | --- |
| Lupin III | [Weekly Manga Action](https://en.wikipedia.org/wiki/Lupin_III_(manga)) |
| Battle Royale | [Young Champion](https://en.wikipedia.org/wiki/Battle_Royale_(manga)) |
| Chobits | [Weekly Young Magazine](https://en.wikipedia.org/wiki/Chobits) |
| ES: Eternal Sabbath (ES: Eternal Sabbath) | [Morning; Kodansha original-publication page](https://www.kodansha.co.jp/comic/products/0000012564) |
| Oh My Goddess! | [Monthly Afternoon](https://en.wikipedia.org/wiki/Oh_My_Goddess!) |
| Emma | [Comic Beam](https://en.wikipedia.org/wiki/Emma_(manga)) |
| Vagabond; Vagabond VIZBIG Edition | [Morning; original series](https://en.wikipedia.org/wiki/Vagabond_(manga)); [VIZBIG edition](https://www.viz.com/manga-books/manga/vagabond-vizbig-edition-volume-1/product/1507) |
| Mushishi | [Afternoon Season Zōkan / Monthly Afternoon](https://en.wikipedia.org/wiki/Mushishi) |

### Shōjo — original publications

| Exact catalogue series / alias | Original magazine / evidence |
| --- | --- |
| Land of the Blindfolded - | [LaLa](https://en.wikipedia.org/wiki/Land_of_the_Blindfolded) |
| Vampire Game | [Wings](https://en.wikipedia.org/wiki/Vampire_Game) |
| Dragon Knights | [Wings](https://en.wikipedia.org/wiki/Dragon_Knights) |
| From Eroica with Love - | [Viva Princess / Princess](https://en.wikipedia.org/wiki/From_Eroica_with_Love) |
| Gals! (Super Gals) | [Ribon; creator](https://en.wikipedia.org/wiki/Mihona_Fujii) |
| Fruits Basket; Fruits Basket Ultimate Edition | [Hana to Yume](https://en.wikipedia.org/wiki/Fruits_Basket) |
| S.A | [Hana to Yume](https://en.wikipedia.org/wiki/S.A_(manga)) |
| Wild Act; Wild Act (Wild Act (Graphic Novels)) | [Sho-Comi](https://en.wikipedia.org/wiki/Wild_Act) |

### Josei — original publications

| Exact catalogue series / alias | Original magazine / evidence |
| --- | --- |
| Happy Mania | [Feel Young](https://en.wikipedia.org/wiki/Happy_Mania) |
| Suppli | [Feel Young](https://en.wikipedia.org/wiki/Suppli) |
| With the Light: Raising an Autistic Child | [For Mrs.](https://en.wikipedia.org/wiki/With_the_Light) |

## Quantified read-only production dry-run

On 4 November 2026, a *read-only SQL join* of reviewed keys against
`tcg.comic_printing_details` (exact `MANGA` rows, normalised with
`lower(btrim(series_title))`) returned:

| Measure | Rows | Share of 805 |
| --- | ---: | ---: |
| Manga records in scope | 805 | 100% |
| Previously classified (10 keys) | 53 | 6.58% |
| Additional classifications (42 exact aliases) | 208 | 25.84% |
| Total classified **after this code release** | 261 | 32.42% |
| Still Unclassified | 544 | 67.58% |

These numbers are a **pre-deployment projection**, not an assertion of live
current distribution until the matching application commit is deployed.
The `GetBackers` and `Getbackers` source spellings share the *same*
case-folded rule, not two separate joins. The new map must not double-count
those four rows. A reference does not imply owned inventory or sales.

## Safeguards and deferred titles

- Do not classify from publisher, genre, age rating, language or a partial
  title match. The generated SQL predicate uses the **same exact dictionary**
  and binds all values; it filters before pagination and owner-scoped joins.
- **Priest**, **Faeries' Landing**, and **Chronicles of the Cursed Sword**
  (including Korean manhwa) remain Unclassified pending appropriate cataloguing
  treatment. Spin-offs, film manga, uncertain adaptations and composite
  anthologies are not blanket-classified.
- The initial manga demographic can vary across a franchise's magazine moves
  and editions: check any non-identical printing/series identity separately.
- No Kodomo titles are added by this batch; an empty group must remain honest.
- Do not fetch, copy or store publisher artwork in this process. These links
  support factual classification only, not broad data or media rights.

## Release and test gates

Run exact-series and unknown-title tests, the full browser group/filter suite,
the R2-first catalogue safety tests, native PostgreSQL group-query/pagination
tests, and the full backend suite. Release through PR/CI, then check exact
Railway commit and application readiness. Accept signed-in browse only after
a real user/device check confirms correct category counts and owner visibility.
Rollback: revert the literal dictionary addition; no data restore needed.
