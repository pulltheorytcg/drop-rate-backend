# Seller Hub launch registration — deployment and privacy boundary

## Purpose

The public `app.droprate.co.uk` root is a branded **prelaunch landing page**, not
the unfinished Seller Hub dashboard. It explains planned tools and collects
consensual launch-notification registrations now. A clearly distinct secondary
action allows visitors to create a restricted seller account early using the
existing, already deployed Supabase Auth flow at `/owner/join`.

The parent `droprate.co.uk` and `www.droprate.co.uk` stay on Shopify. Its live
Horizon theme and password/launch gate are not changed by this backend PR.

## Routes and ownership

| Route | Result | System |
| --- | --- | --- |
| `https://app.droprate.co.uk/` | Prelaunch page | Existing Railway FastAPI service |
| `/seller-hub` on any API host | Same prelaunch page | Railway |
| `POST /api/v1/public/seller-hub/waitlist` | Validated, idempotent launch opt-in | FastAPI → private Postgres function |
| `/owner/join` and `/owner/join?invite=...` | Existing verified owner onboarding and invitations | FastAPI → Supabase Auth/Postgres |
| `/owner`, `/app`, existing API routes | Unchanged authentication/owner features | Existing service |
| `https://drop-rate-api-live-production.up.railway.app/` | Existing founder dashboard | Railway |

This uses no extra Railway service and no separately exposed `api.` DNS host.
API calls are same-origin from the launch page. `TCG_PUBLIC_APP_URL` should
eventually be `https://app.droprate.co.uk` so *new* secure invite URLs use the
branded origin; old Railway URLs continue to work.

## Database and consent

- Canonical migration: `database/migrations/20261031190234_seller_hub_launch_waitlist.sql`.
- Stores normalized unique email, optional name, interest, opt-in version/time,
  source, state and timestamps. No password, IP, payment detail or inventory.
- Forced RLS, with all direct access revoked from browser roles and `tcg_api`.
  Only `tcg_api` may execute the narrowly scoped `tcg_private` insertion
  function. The function reactivates previously unsubscribed signups only
  after fresh explicit opt-in; repeated other signups are idempotent.
- The public endpoint checks explicit consent; a honeypot rejects simple bots.
  It returns the same success response for new and existing emails to avoid
  address enumeration. On DB failure it returns 503 and does **not** claim a
  successful registration. The UI never receives a secret Supabase key.
- Any eventual launch campaign must honour `UNSUBSCRIBED` status and use a
  verified sender, an unsubscribe mechanism and the existing email adapter or
  another separately approved sending workflow.

**Crucial:** Registration is enabled by this release. Automatic launch emails
are **not** enabled, since there is no verified transactional sender configured
on `drop-rate-api-live`. The collected consent-backed list is ready to use when
the founder explicitly launches the app and configures compliant sending.

## Deployment checklist

1. Feature branch, Python/JS tests and full applicable GitHub CI pass.
2. Apply the exact committed Supabase migration once and verify table RLS,
   grants, function execution and duplicate behavior with a controlled test.
   Do not insert real customer emails as tests.
3. Merge into `main`, wait for existing Railway production deploy success and
   healthy `/health/ready`; confirm `/seller-hub` serves expected assets.
4. Add `app.droprate.co.uk` to the existing Railway `drop-rate-api-live` service.
   Add the **exact CNAME and verification TXT** Railway returns in Squarespace.
   Leave Shopify apex/`www`, MX, SPF, DKIM, DMARC and `_domainconnect` untouched.
5. Confirm Railway domain/certificate verification, HTTPS response,
   browser visual/mobile QA, signup endpoint and invite-token route.
6. Update Shopify's **Sell With Us** destination to the branded landing page.
   Keep any other theme publication gate intact. Do not publish Brand Redesign.
7. Verify `TCG_PUBLIC_APP_URL` to avoid disrupting old invite links; if updated,
   send new invites through the new hostname without invalidating existing ones.

## Failure/rollback

- If the custom domain fails verification, keep using the existing Railway
  origin and `/seller-hub` while correcting **only** the new DNS records.
- If a signup DB error occurs, display a retry message; never silently accept
  an email that was not saved. Inspect Railway logs using request IDs.
- If app routing regresses, revert the application PR and redeploy. The
  additive waitlist table can remain empty or retained for future rollout.
- Existing invitations are not changed or revoked by the launch page.
- Do not remove existing DNS records, drop the waitlist table, or disable RLS
  as a rollback shortcut.

## Tests

- `PYTHONPATH=backend pytest tests/test_seller_hub_launch.py`: root host
  routing, direct route, invite preservation, new/duplicate signup,
  consent/validation, honeypot, database failure, SQL security contract.
- `node tests/ui/seller-hub-launch.cjs`: browser DOM structure, success,
  retry, no duplicate submit, explicit consent.
- `PYTHONPATH=backend pytest` and `npm test --prefix tests/ui` are release
  gates, alongside native PostgreSQL migration/security verification.
