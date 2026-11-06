# Inactive external OIDC boundary — safe Supabase Auth exit design (6 November 2026)

**Status: code-contract only, NOT production login replacement.**

## Verified source and reasons

A read-only audit on 6 November found **9 Supabase Auth users**, 9 confirmed emails, 6 distinct active owner-membership users and 3 active founder-app users. There were **227 existing auth session records**; those are NOT migration records or evidence of unique active human sessions. Never export password hashes, active refresh tokens, MFA seeds, session cookies or OAuth secrets into R2/D1.

Cloudflare D1 cannot enforce PostgreSQL RLS. FastAPI must verify the signed replacement-provider identity and enforce deterministic owner membership and founder roster on every request. Email addresses and JWT claims such as `role=PLATFORM_ADMIN` are NOT trusted as ownership evidence.

## Shadow implementation

- `backend/app/auth_oidc_shadow.py` contains only an **inactive** RS256/ES256 JWT verifier and an **exact, previously verified** identity link resolver. The issuer, audience and HTTPS JWKS origin are pinned, and no anonymous/unsigned/expired token is permitted.
- The existing isolated private D1 `ops_shadow_identity_map` has `external_subject`, `provider` and `verified_at` columns for explicit links. The current operational shadow import populated only `legacy_user_id` values, **not external subjects, provider links, passwords or sessions**. The resolver intentionally returns an error while no link is verified.
- `require_user` and all current FastAPI routes **continue using Supabase Auth** unchanged. No frontend, Shopify, email or Founder HQ login switches are made by this work.
- Any `PLATFORM_ADMIN` privilege under a future provider additionally requires independently migrated, verified founder-roster and owner-membership data, not merely a matching JWT/email or a raw D1 identity mapping. This proof does **not** implement that live D1 access-control path.

## Failure modes / test gates

- Block wrong issuer/audience/algorithm, expired or forged token, unapproved JWKS URL, anonymous identity, duplicate or unverified subject link and foreign D1 generation.
- No automatic email-based account linking. Require a user-verifiable re-enrolment or signed migration ceremony; record confirmation, operator and timestamp.
- Never silently migrate someone else's founder membership; verify all 3 founders and all consignor owners against the original trusted roster. Verify access denial to another owner before release.
- Revoke Supabase sessions only **after** replacement sign-in, MFA policy, account-recovery workflows and founder/consignor permissions have been tested and production cutover is approved. Maintain rollback or a controlled recovery route.
- Test lost-provider/JWKS outage, revoked identity and compromised token. Disable or age out old tokens after cutover.

**Release gate:** choose/configure an independently controlled OIDC provider, link all intended active users (currently 9 Auth accounts, 6 owner memberships), build its server-side D1 owner-authorization and recovery path, demonstrate real sign-in/permissions in a separate environment and document rollback. Until that passes, Supabase Auth remains active.
