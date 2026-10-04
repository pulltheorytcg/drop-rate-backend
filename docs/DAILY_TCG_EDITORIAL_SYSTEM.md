# Daily Drop Rate editorial system

Status: DESIGNED; a stateless preparation component is implemented in this branch.
No production deployment, account connection, live research or publication is verified.
Updated 4 October 2026 after the founder expanded coverage and requested static content.

## Current source of detail

Read [Static social research and playbook](STATIC_SOCIAL_RESEARCH_AND_PLAYBOOK.md)
for screenshot observations, creator research and limits, the full editorial mix,
14-slot rotation, design direction, evidence/rights rules, traffic and sales
measurement, implementation contract, publishing gaps and the delivery sequence.
The original video-first plan is superseded by this static-first brief. Git history
preserves it; it must not be used to justify automatic Shorts production now.

The founder wants One Piece, Pokemon, Dragon Ball, Naruto, comics, manga,
Riftbound, Lorcana, anime, live-action releases and comic-book films. Artist
stories are one occasional format. Keep franchise, medium and format separate.
Multiple posts daily: three distinct stories at 10:00, 14:00
and 19:00 Europe/London as initial test slots. The founder confirmed Instagram,
Facebook, YouTube, TikTok and X: fifteen platform slots daily. The intended system researches, creates, manages, posts,
measures and adapts automatically; the preparation component alone does not
fulfil that goal. No music. Retain Drop Rate navy/cyan/gold/cream branding, strong typography,
real undistorted assets and restrained visual character. Final templates remain
unapproved; the latest balanced previews are direction references only.

## Repository contracts

- `automation/n8n/plans/daily-tcg-editorial.json` remains a design specification,
  not an n8n export or a runtime-consumed configuration.
- `backend/app/editorial_preparation.py` accepts structured observations, builds
  6-8-slide briefs and screens evidence, grading comparisons and destinations.
- `POST /api/v1/automation/commands/editorial/prepare` uses existing command HMAC.
  It performs no database writes, network fetches, rendering or social publication.
- `automation/n8n/workflows/dr-31-static-editorial-preparation.json` is a real
  inactive subworkflow targeting that implemented route. Input: `brief_json`.
  It has no daily scheduler and does not emit a durable success receipt.
- Every response is `publishable:false` and `stored:false`. A content fingerprint
  supports comparison of repeated input; it is not a publication lock.
- Set `TCG_EDITORIAL_STOREFRONT_ORIGIN` only to a verified public HTTPS origin.
  Without it, the preparation output contains no commerce link. Destination
  relevance and timestamps remain caller observations pending authoritative checks.
- Creative/publishing registry families remain DESIGNED: this component does not
  complete either whole family. Existing production workflows remain untouched.

## Platform target and known limit

Instagram carousel, Facebook Page multi-image post, TikTok photo carousel and X image post/thread
are candidate static outputs, pending actual account/provider capability checks.
YouTube native Community image posts exist, but no documented public Data API
creation route was found. Five-platform static unattended delivery is therefore
not established. Do not convert to video or insert a daily manual step implicitly.

## Evidence and operation

AI may draft structured original copy; backend code computes numeric facts and
validates exact identity. n8n orchestrates; Postgres will own durable jobs/evidence
once that contract exists. Social posts supply leads, not verified sale prices or
release dates. Card images, promotional art and source access need permitted-use
contracts. Do not copy creator artwork or captions to imitate engagement.

Raw-to-graded content focuses on affordable raw cards with a large repeatable
PSA 10 premium and lower-grade context. The prototype uses proposed GBP30/4x/
five-sales-per-state/30-day filters and produces no profit or expected-value claim.
The example GBP20 versus GBP200 is illustrative, not a verified card valuation.

Keep sale/asking/index values distinct; record language, print/variant, condition,
currency, dates and fee basis. Release stories retain region, language and medium.
Recheck time-sensitive claims and available stock immediately before publication.
Use a still-valid evergreen item when fresh research does not qualify; otherwise
skip the slot and emit one exception. Nine validated evergreen briefs are a
launch target; none are claimed ready in this branch.

Before live delivery, implement source adapters, governed persistence, versioned
claims, licensed rendering, destination/attribution support and actual account
connections. Prove provider read-back, ambiguous-response reconciliation, partial
channel retry, bounded spending and independent stop switches. Queued/accepted,
private and notification-only responses do not count as public publication.

Content Machine PR #216 remains unmerged. GitHub now reports it mergeable;
the older conflict statement is stale. Schema and grants still require review.
No migration, paid plan, infrastructure change or publishing activation is part
of this preparation update. iPhone work remains separately paused in PR #511.
