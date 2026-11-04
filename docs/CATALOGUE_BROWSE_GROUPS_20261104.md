# Catalogue brands, publisher groups and manga demographics

This is a read-only navigation feature. It does not create inventory, import a
new provider, verify an identity, establish a price, approve an image, or change
ownership. PostgreSQL remains authoritative for canonical identities and owner
stock. The R2-first reference index derives the same facet from its already
reviewed metadata, without altering immutable manifests or provider identities.

## Contract and failure handling

`GET /api/v1/catalogue-browser/products` and `/sets` accept optional
`browse_group`, default empty. A nonempty group must have a matching category or
system. Unknown groups, contradictory category/system combinations, and global
saved-key requests with no category/system context return HTTP 422. Category-only
Sports/Figures group requests resolve the relevant system before dispatch, so
they include both canonical records and published R2-first references.

| Category | Allowed group IDs | Classification evidence |
| --- | --- | --- |
| Comics | `MARVEL`, `DC`, `INDIE`, `OTHER` | Canonical comic system; exact reviewed publisher for Indie |
| Manga | `SHONEN`, `SHOJO`, `SEINEN`, `JOSEI`, `KODOMO`, `UNKNOWN` | Exact reviewed series, independently of publisher and genre |
| Sports | `PANINI`, `TOPPS`, `OTHER` | Structured manufacturer |
| Figures | `FUNKO_POP`, `FIGURINES`, `OTHER` | Reviewed manufacturer **and** product line |

Indie is a shop navigation grouping for the reviewed non-Marvel/DC publishers
Image Comics, Dark Horse and IDW; it is not a legal claim about corporate
independence or franchise ownership. Unreviewed or absent publishers stay Other.
Manga demographics are not genres or publishers: no blanket classification of
VIZ, Kodansha, all teenage books, or books whose title happens to contain Shonen.
Unknown manga stays Unknown. The Kodomo option currently has no reviewed series
mapping; an empty result is not hidden or populated with invented records.

Funko plus exact `Pop!`/`Pop` is Funko Pop. Good Smile Company plus exact
`Nendoroid` is Figurines. Other maker/line combinations remain Other until
reviewed; all non-Funko products are not assumed to be figurines. Sports accepts
the exact manufacturer aliases `Panini`, `Panini America`, and `Topps`.

Case and outer ASCII spaces are ignored. Substrings, fuzzy titles, punctuation
rewrites, arrays, objects, and unreviewed aliases cannot establish a group.

## Reviewed source evidence (4 November 2026)

Only short factual classification rules are stored; no artwork, descriptions,
prices, or bulk source content is copied for this feature.

| Exact manga series | Group | First-party evidence |
| --- | --- | --- |
| One Piece | Shonen | [VIZ official Shonen Jump series](https://www.viz.com/shonenjump/chapters/one-piece?locale=en) |
| Naruto | Shonen | [VIZ company FAQ, named Shonen Jump series](https://www.viz.com/company-faq) |
| Dragon Ball Z | Shonen | [VIZ volume 1, Shonen Jump imprint](https://www.viz.com/manga-books/manga/dragon-ball-z-volume-1/product/118) |
| Hunter x Hunter | Shonen | [VIZ official Shonen Jump series](https://www.viz.com/shonenjump/chapters/hunter-x-hunter?locale=en) |
| Jujutsu Kaisen | Shonen | [VIZ company FAQ, named Shonen Jump series](https://www.viz.com/company-faq) |
| Death Note | Shonen | [VIZ series, Shonen Jump designation](https://www.viz.com/death-note) |
| Baby & Me | Shojo | [VIZ volume 1, Shojo Beat imprint](https://www.viz.com/manga-books/manga/baby-me-volume-1/product/468) |
| Initial D; Initial D Omnibus | Seinen | [Kodansha's named seinen series list](https://kodansha.us/2026/04/28/spring-of-seinen-digital-sale/) |
| Princess Jellyfish | Josei | [Kodansha's complete-series description](https://kodansha.us/series/princess-jellyfish-complete-manga-box-set/) |

Publisher identities: [Image Comics](https://imagecomics.com/about-us),
[Dark Horse](https://digital.darkhorse.com/about/), and
[IDW Publishing](https://idwpublishing.com/pages/about-us). The group is based on
the **edition publisher**, not characters in the story (including licensed work).

Figure maker/product-line evidence remains the exact source receipts in
`backend/data/r2_figure_starter_20261104.json` and
`backend/data/collectible_catalogue_starter_20261103.json`, including Funko's
individual Pop product pages and Good Smile's exact Nendoroid product pages.
Sports manufacturer evidence remains the existing official/reference source
receipts; this facet neither expands their coverage nor assigns a brand from a
player's name, a set-title substring, or an unsupported licensing assumption.

## Query and ownership boundaries

`catalogue_browse_groups.group_for` is the pure shared classification helper;
`validate_browse_group` raises `ValueError`; HTTP routes translate it to 422.
`group_predicate` binds reviewed maps and the requested group as SQL parameters.
Canonical facts are fetched only through their existing profile/book records and
ordinary RLS. No unbounded private attributes are added to API responses.

Products apply the facet with language, search, set, saved-key and owned filters
**before** sorting and pagination. Grouped set aggregation starts with matching
entries, so counts/owned totals cannot include another brand/demographic or a
declared-but-empty checklist. Both query builders return `limit + 1` rows as the
existing pagination sentinel. Empty-group SQL/parameters remain unchanged.

The legacy R2 projection does not contain book publisher/demographic or private
profile details. Grouped canonical reads therefore use the ordinary SQL path,
not an unfiltered legacy index or a full 70k-row JSON projection fallback. The
R2-first sports/figure index uses its disposable local `browse_group` column;
the bounded canonical/reference union filters each side before the shared page.
Mixed saved keys pass the same facet to both engines before final pagination.

## Tests and release gates

- `tests/test_catalogue_browse_groups.py`: closed groups and mismatch failures,
  exact-vs-unknown classification, malformed JSON-shaped facts, SQL parameter
  coverage, filter-before-page/counts, category-only dispatch, mixed saved keys,
  and avoidance of the legacy shared-index hydration for canonical facets.
- `tests/catalogue_browse_groups_postgres.py`: actual production query strings
  against a disposable PostgreSQL database, Python/SQL classification parity,
  set counts, pagination, two owners, literal injection-shaped text, saved keys,
  future/unreviewed sports exclusion, existing read RLS, and unchanged inventory.
  Native DSNs are restricted to localhost `catalogue_browse_groups_test` and a
  nonempty database is refused. Local `--pglite` uses the existing isolated test
  transport and never accepts production credentials.
- Existing book/browser tests must retain their approval, artwork, market-value,
  RLS and empty-group query contracts; root integration additionally tests R2
  search/sets and UI selection/reset behavior.

No migration or production mutation is required for these facets. Code/tests do
not establish that a release is live: CI, exact-commit deployment and
authenticated application verification remain separate release gates. Rollback
is the prior application release; original identities and manifests are intact.

Deployment and initial coverage are recorded in the
[4 November release receipt](CATALOGUE_GROUPS_RELEASE_20261104.md). The controls
are deployed, but factual classification is partial (53 of 805 current manga
references), and authenticated device/visual acceptance is still pending.
