# Seller Hub launch registration — deployment and privacy boundary

## Purpose

The public `app.droprate.co.uk` root is a branded **prelaunch landing page**, not
the unfinished Seller Hub dashboard. It explains planned tools and collects
consensual launch-notification registrations now. A clearly distinct secondary
action allows visitors to create a restricted seller account early using the
existing, already deployed Supabase Auth flow at `/owner/join`.

The parent `droprate.co.uk` and `www.droprate.co.uk` stay on Shopify. Its live
Horizon theme and password/launch gate are not changed by this backend PR.

## Prelaunch visuals and app badges

- The **Seller Hub landing page header only** shows familiar App Store and
  Google Play badges. Neither mobile app is available to download yet, so the
  badges explicitly say **Coming Soon** and take visitors to the existing
  `#early-access` opt-in form. Replace those same-page links with verified
  store listing URLs only after the corresponding mobile apps are published.
  No Shopify storefront header, page, navigation or theme is edited here.
- The Seller Hub hero uses **actual photographed, individually certified slabs
  from Drop Rate's own Shopify product media**: PSA 10 Japanese Eevee 078/066
  (cert 113437109), PSA 10 Japanese Monkey D. Luffy P-001 (cert 165543324)
  and PSA 10 Japanese Mega Charizard X ex 223/193 (cert 160349012). They were
  visible with item-specific front/back media on active Shopify products when
  checked on 31 October 2026. The landing image collage adds visual frames
  around real photographs; it does not fabricate slab labels or current stock.
- A separate six-tile collection gallery makes the intended breadth explicit:
  raw Pokémon cards, graded cards, sealed One Piece, One Piece graded cards,
  comics and manga. The Pokémon/comics/manga photos come from named Unsplash
  photographers under the Unsplash licence and are **editorial examples, not
  Drop Rate-owned stock**. The OP17 sealed pack is the manufacturer's product
  picture already in Drop Rate's Shopify product media, not a photo of the
  individual inventory copy. On-page photo credit/disclosure is included.
  Exact original URLs, sources, provenance, transformations and SHA-256 hashes
  are recorded in `backend/app/static/collection-photos/sources.json`.
- The previous hero's official artworks remain in
  `backend/app/static/grail-art/` and one exact OP17 reference image appears in
  the clearly labelled **illustrative** live-auction UI; it retains the
  original SAMPLE watermark. No price is invented. No Ancient Mew, BGS Black
  Label 10 OP17 or CGC-graded Batman slab/cover photo is labelled as Drop Rate
  inventory without item-specific proof and permission. Do not label an image
  with an unverified grade or certification.
- Feature copy now describes a **planned** low-admin progression from scan to
  catalogue to listings on Drop Rate's own store and, where supported, eBay
  and Whatnot. It does not imply unattended publishing or that all marketplace
  integrations are live. The **Live Auction Lens** is explicitly a future
  concept: optional user-consented screen recording, visible-card recognition,
  and comparisons against eligible market references for under/around/over
  value. Platform capture restrictions, exact identity and market data evidence
  are prerequisites to any such real feature; the on-page overlay is a visual
  concept and displays no fabricated live prices.

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

## Optional Shopify customer contact mirror

The founder wants the opted-in Seller Hub audience available inside Shopify
Customers for future mailing-service migration. The new form explicitly
discloses that the contact email will also be stored in Shopify for the same
Seller Hub launch and early-access purpose. It sends
`shopify_contact_consent=true` only after the required checkbox is checked.

- Canonical additive migration:
  `database/migrations/20261031210000_seller_hub_shopify_contact_sync.sql`.
  Applied in production Supabase migration history as version
  `20261031203048` on 31 October 2026. The existing launch-list migration
  was applied as `20261031192146`; both versions are mapped in
  `database/migration_history_baseline.json` to prevent future reapplication.
  RLS remained forced; neither the browser roles nor `tcg_api` can read the
  contact table directly.
- **Existing pre-disclosure rows** default to `NOT_REQUESTED` and are never
  included in a Shopify export. The original four-argument registration path
  remains Supabase-only for old browser assets. A fresh, disclosed opt-in can
  move such a row to `PENDING`, updating its consent version/time.
- The private `tcg_api` outbox functions claim at most 10 records with
  `FOR UPDATE SKIP LOCKED`, use 10-minute leases and per-attempt tokens, and
  only acknowledge a record after Shopify confirms **both** mutations.
  Interrupted attempts back off and retry, including when customer creation
  succeeded but tagging failed. Unsubscribed records cannot be claimed.
- The existing server-side `ShopifyAdminClient` uses its Railway credentials
  to call the 2026-07 GraphQL API. `customerSet` upserts using the email as
  its unique identifier. Only the `email` input is sent: an existing name,
  addresses, notes, tags and other customer data are preserved. A second
  `tagsAdd` appends `Drop Rate Seller Hub - Launch List` and verifies the
  returned customer ID. This never creates seller access or makes inventory
  publishable.
- **No call is made to `customerEmailMarketingConsentUpdate`.** Consent for
  Seller Hub launch news is narrower than generic Shopify/store promotion.
  The Shopify tag is for audience management, not proof of unlimited marketing
  permission. Keep the Supabase consent version, timestamp and status when
  migrating to any mailing service, and exclude `UNSUBSCRIBED` contacts. A
  future opt-out workflow must also reconcile/remove remote Shopify tags
  before any Shopify-only mailing or export of that audience.
- Early **seller account creation** at `/owner/join` remains separate and
  does not automatically turn account creation into marketing consent. A
  seller must explicitly join the launch list to enter this audience.

### Controlled activation

1. Verify Python, JS, migration/security and Shopify mock tests and merge
   through CI. The additive migration has already been applied and its grants
   and row-level security verified; do not apply it again.
2. **Completed 31 October 2026:** Shopify Dev Dashboard app version
   `drop-rate-backend-customer-sync-20261031` (ID `1189657608193`) was
   released as active with `write_customers` plus the original six required
   scopes. The Drop Rate production store accepted Shopify's **Update data
   access** prompt for editing customers. Verify this remains true after any
   later Shopify app installation/version changes.
3. **Completed 31 October 2026:** Railway production service
   `drop-rate-api-live` now has
   `TCG_SHOPIFY_WAITLIST_SYNC_ENABLED=true`; configuration deployment
   `37b2793a-3a76-4e6e-81ca-8edaa0793eeb` reached **SUCCESS** with one
   running replica and no warnings. Restore the variable to `false` for a
   safe rollback if access is later revoked.
4. Watch worker processed/success counts (without email addresses), and
   inspect privacy-safe sync totals via read-only SQL:

   ```sql
   select shopify_sync_state, count(*)
     from tcg.seller_hub_launch_waitlist
    group by shopify_sync_state
    order by shopify_sync_state;
   ```

5. With an explicitly consented real signup, verify one Shopify Customer with
   the tag, exactly one matching Supabase `SYNCED` receipt and no change to
   pre-existing customer marketing status. Do not make a fake production
   customer merely to test, or delete production customer records as cleanup.

If scope authorization, API calls or deployment fail, keep or set the flag
to `false`. All signups continue to persist securely in Supabase; pending
contact mirrors are retried when the approved worker is next enabled.

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
- `PYTHONPATH=backend pytest tests/test_seller_hub_shopify_sync.py`: customer
  upsert+tag, duplicate replay, remote error/partial failure, leased outbox
  acknowledgements, explicit consent and private SQL contract.
- `PYTHONPATH=backend pytest` and `npm test --prefix tests/ui` are release
  gates, alongside native PostgreSQL migration/security verification.
