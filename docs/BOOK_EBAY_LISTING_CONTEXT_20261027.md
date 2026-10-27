# Book artwork redirects and eBay listing context — 27 October 2026

## What this fixes

A bounded sample of twelve current comic/manga source images returned eleven
decodable JPEGs and one missing image. Four of the existing images redirected
through Internet Archive, which the deployed image policy blocked. Allowing
the observed download and regional archive destinations in `img-src` fixes this
display failure without changing source identity, media approval or other CSP
directives. A real Chromium comparison reproduced zero of four images before
and four of four after the change. The isolated browser needed its local
interception certificate error ignored; production TLS configuration is unchanged.
The sample is not a full catalogue coverage estimate.

The second change adds current eBay asking prices and optional listing photos
for exact ISBN editions. The official Browse API returns active offers, so these
are explicitly labelled **eBay asking price(s)**. They do not establish a sold
market value or the value/printing/condition of an owned copy.

## Source and matching

`GET /api/v1/catalogue-browser/books/{catalogue_id}/listing-context` requires an
authenticated user with current active account access. It reads the canonical
book through the existing user-scoped connection, releases the transaction,
and uses the official eBay application token and GB Browse API. A second short
read checks access and the edition digest after provider I/O. Client-supplied
queries, ISBNs, URLs and ownership claims are not accepted by the endpoint.

The matcher requires returned ISBN identifiers, language, volume, a physical
binding, a positive GBP fixed price, a safe source item URL and compatible
edition facts. Search ranking alone is insufficient. Conflicting identifiers,
volumes, language, declared binding, edition qualifiers, sold-out/ended items,
bundles, digital products, accessories, auctions, graded or special copies are
excluded. An imported manga edition with unspecified binding can display a
matching ISBN offer with an explicit source binding; this does not fill the
canonical binding or confirm a physical printing. Existing metadata review
holds remain enforced. A cover-only exclusion does not invalidate an otherwise
eligible ISBN reference from a different source.

Requests use at most one GTIN search and three item details. The process shares
in-flight requests, a concurrency limit of two, a bounded cache, a one-hour
maximum positive TTL and a five-minute negative TTL. An earlier listing end
shortens expiry. Credential and rate-limit failures stop further provider work
for a bounded backoff. `TCG_BOOK_EBAY_CONTEXT_DAILY_CALL_LIMIT` defaults to 500
actual Browse calls per process and accepts 1–4000. This local limit resets with
the process and is not a substitute for eBay's account-wide quota enforcement.

## Display boundaries

Only visible catalogue rows are looked up, with two browser requests at a time.
The browser cancels stale navigation work and checks account, edition and expiry
before rendering. Prices show their actual source condition, source links and
postage qualification. The detail panel includes the last checked time.

An eBay listing photo is a final fallback after existing publisher/community
images fail to load. It is fetched directly from the approved eBay image host,
without an authenticated proxy or application credentials, and labelled
**eBay listing photo · Copy may vary** with its matching item link. A successful
existing image keeps priority. Selection previews may reuse fresh context
without another provider lookup; no source price, condition or binding is copied
into the physical-item intake form.

No tables, schema, price snapshots, sold observations, portfolio totals, R2 media,
canonical images, recognition evidence, Shopify products or financial records
are written. The separate sold-market-value fields retain their existing rules.

## Activation and verification

`TCG_BOOK_EBAY_CONTEXT_ENABLED` defaults to false and is independent of generic
market ingestion. The opt-in `backend/scripts/book_ebay_context_probe.py` accepts
only pinned public editions and emits allowlisted public source diagnostics.
Use Naruto volume 1, ISBN 9781569319000, for the initial live probe; its exact
ISBN, volume and release year are confirmed by the
[publisher source](https://www.viz.com/manga-books/manga/naruto-volume-1-0/product/91).
The older +Anima fixture, ISBN 9781427800022, is a Scholastic Exclusive edition;
an explicit exclusive listing remains rejected until that qualifier is reconciled
in the canonical identity. It is not interchangeable with ISBN 9781598163476.
The probe makes no database or media writes,
does not call Trawl or Parse, and skips when no exact probe flag is supplied.

Run the bounded probe in the existing API deployment after all normal predeploy
gates. Verify provider access, actual matching listings, image delivery and
source attribution before enabling the display flag. Preserve and restore the
original predeploy command. Record the exact CI, deployment and live probe
results on the release pull request. A source returning no eligible offer must
remain unavailable; it is not evidence of a zero price.

The artwork comparison is recorded in
[the browser evidence](evidence/book-cover-redirect-browser-20261027.json).
Provider behavior is based on eBay's
[inventory discovery guide](https://developer.ebay.com/develop/guides/buy/inventory-discovery-and-refresh-guide).
