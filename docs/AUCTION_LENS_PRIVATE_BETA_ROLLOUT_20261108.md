# Drop Rate Auction Lens — selected-account private beta rollout

**8 November 2026 · PRE-RELEASE, NOT DEPLOYED**

Stacking order:
1. [Auction Lens recognition proof PR #983](https://github.com/pulltheorytcg/drop-rate-backend/pull/983)
2. [Compact branded quote/banner PR #1002](https://github.com/pulltheorytcg/drop-rate-backend/pull/1002)
3. Private beta account gate (this branch; merge only after predecessors and CI)

## What and why

Expose the **authorised local-video lab**, **not third-party live auction capture**, to named, explicitly approved signed-in Drop Rate users while every other account stays locked out. The current Expo iPhone capture proof is not compiled and no system-wide PiP overlay is available. Do not describe the video lab as the finished iPhone scanner.

One server-side account allowlist protects both recognition and entitlement APIs. No new database table, credential copying, paid API, Shopify write, n8n automation, inventory ownership change, consignment event or settlement operation.

## Account release gates

All are required:

- Authenticated, verified Supabase JWT through existing require_user; never user-supplied name, email, request header, profile role or user_metadata.
- User's canonical **auth user UUID** is in server setting **TCG_AUCTION_LENS_BETA_USER_IDS**. Comma-separated list; max **25** distinct canonical UUIDs. Empty, malformed, duplicated or oversized configurations reject **all** accounts. No founder is automatically granted access.
- Global server switch **TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED=true**, default OFF. Both /api/v1/auction-lens/pilot/access and /pilot/resolve reject outsiders with 404.
- Active membership checked via current_owner in a per-user read-only PostgreSQL transaction. Beta invitation never changes inventory or owner permissions.
- Market values require independent **TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED=true** only after rights evidence and current eligible, exact-print UK sold data. Keep OFF in an initial identification-only beta.
- User declares they own the test footage or have specific rights to process it. A checkbox is not a Whatnot/eBay licence.

## Railway state verified on 8 November 2026

Connected project drop-rate-backend (9329767b-b092-495c-bf18-75cf69c28536) has **only one environment: production** (6f00816c-b630-4d0b-bcc1-26ac71fa712d). API services drop-rate-api-live and drop-rate-api follow main. No staging environment exists yet.

Do not link an unmerged experimental branch to the live production API. A second, isolated Railway test environment (with a test database and its own secrets/URL) is preferred. The connected Railway tools do not expose environment creation; this requires a dashboard action or separately approved equivalent. Do not copy production credentials to an experimental service.

## Safe deployment procedure

1. Clear parent PR #983 conflicts, PR #1002, this beta PR, Expo dependency compatibility and **all** required CI gates. Validate real JWT/RLS authorisation in staging.
2. Founder nominates participating Drop Rate accounts through a secure admin channel. Resolve login email -> auth.users.id via authorised read-only lookup, confirm each target, and put only UUIDs in the beta allowlist. Do not put emails/passwords, full user records or tokens into environment variables or Git.
3. Provision staging environment and a separate beta service/branch; use staging DB + distinct secrets and URL, not a production-credential clone.
4. Set TCG_AUCTION_LENS_BETA_USER_IDS to the approved UUIDs and TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED=true on **staging service only**. Keep TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED=false.
5. Selected account signs into Drop Rate and loads /auction-lens-lab. Page GETs /api/v1/auction-lens/pilot/access with JWT and enables controls only after server permission. Confirm unselected account, missing/bad token, revoked membership, malformed allowlist and globally disabled feature cannot access the API.
6. Use only owned/expressly permitted local video, confirm crop and printing, record aggregate QA evidence without storing video in logs/GitHub. Card banner must hide on stop/seek/lot transition and value expiry.
7. Remove a UUID in staging configuration and redeploy to test revocation. Server rejects at the next request *after configuration takes effect*; the lab rechecks entitlement every 15 seconds. Railway changes may require a deployment. Do not claim instantaneous revocation when editing a config value.
8. Only with signed-off security, legal source-rights and benchmark evidence: consider limited production beta. Keep unselected accounts excluded, no public navigation, and no third-party automated capture.

## Kill switch and rollback

- Set TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED=false on beta API; after configuration takes effect both routes deny all accounts.
- Remove or empty TCG_AUCTION_LENS_BETA_USER_IDS for an independent deny-all switch.
- Keep TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED=false until rights and eligible price evidence are independently cleared.
- Roll back beta branch/service without affecting live Shopify, orders, settlements or owner records.

## Test and failure gates

- Valid *nonselected* bearer token with forged owner UUID in headers/body -> 404 **before** image decoding/index/DB work.
- Selected active user -> private entitlement, after current_owner check; expired/inactive account -> deny.
- Invalid, empty, duplicate or oversized allowlist -> deny all.
- Lab controls disabled by default; no upload or recognition without entitlement; periodic recheck stops an active test if access is removed or network unavailable.
- Parent exact-print, recent quote, stale generation, market evidence and cost tests stay mandatory.
- Do not log raw footage, full JPEG, bearer tokens, account roster or access secrets.

**No actual test account has been designated yet in this conversation. A configuration-only beta is not a live deployment.** No production Railway settings, database owner rights or live services should be changed until user selection and CI are verified.
