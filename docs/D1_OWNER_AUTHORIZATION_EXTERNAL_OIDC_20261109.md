# Drop Rate — inactive external OIDC → exact owner permissions proof (9 Nov 2026)

Tracker: https://github.com/pulltheorytcg/drop-rate-backend/issues/1010

## What and why

Supabase Auth still supplies live sessions and PostgreSQL `tcg.current_user_id()` / RLS still protects stock and owner balances. Cloudflare D1 is SQLite and **does not provide PostgreSQL RLS**. A valid signed access token alone must never grant access to all three founders' stock or to another consignor's money.

This patch builds an **inactive, read-only, database-backed external identity → unique owner authorization gate**, linked to the already-existing `auth_oidc_shadow.verify_external_token` and original `ops_shadow_*` D1 schema.

Components:
- `backend/app/d1_owner_authorization_shadow.py` — exact indexed D1 SQL join from immutable generation/provider/external subject to verified legacy UUID to owner membership and owner. It returns only one owner-scoped `D1OwnerScope`.
- `tests/test_d1_owner_authorization_shadow.py` — integration of the real D1 shadow SQLite schema with a cryptographically verified synthetic RS256 external OIDC subject; no network or user data.
- No schema mutation, new Cloudflare plan, new login route, Auth/Shopify/Railway configuration, Supabase query or production D1 read/write.

## Connections / guarantees

A **separately selected and configured** external OIDC issuer issues a signed JWT. The existing inactive verifier must check signature, issuer, audience, time and nonanonymous subject; the new gate accepts only its `VerifiedExternalSubject` and the same server-fixed `TrustedOIDCProvider`. The original UUID is never inferred from email, self-declared role, founder slot or token metadata. A verified identity link must exist in the private, fully `PARITY_VERIFIED` source generation, with exactly one active membership to exactly one active owner. Multiple memberships, missing link, revoked owner, stale stage, changed provider, wrong founder slot and unsupported role fail closed.

The authorized owner ID is **derived from the joined database records**, not an owner_id URL/claim. Every business query at future cutover must include an exact server-derived `WHERE owner_id=?` and, for writes, a SQL owner/lineage/stock guard inside the same D1 transaction. Frontend code must never have a D1 token.

### Crucial missing founder roster

The live PostgreSQL function `tcg.is_platform_admin()` validates an independently rostered founder, beyond `owner_memberships.role`. The existing D1 shadow contains `role`, `founder_slot` and `owner_type`, but **not equivalent verified roster proof**. Therefore this gate deliberately returns `founder_hq_allowed=False` and `business_allowed=False` for **all** subjects, including valid founders whose D1 membership says `PLATFORM_ADMIN`. Founder access is reduced to exact personal-owner portal scope pending separate signed founder-roster import and test. This prevents accidental privilege escalation during migration.

## Potential failures and security tests

- Signed role/founder_slot/app_metadata/email forged by an account holder cannot change derived owner scope; valid consignment subject cannot view Founder 1 stock.
- Missing identity links (all six original staged mappings are currently unlinked), incorrect issuer/provider, incomplete source generation, inactive/ambiguous membership, invalid UUID, transport exception and two concurrent membership rows fail closed with no PII emitted.
- Synthetic verified RS256 JWTs plus real SQLite schema test one founder and one consignor, founder-to-founder isolation, revoked mapping, stale snapshot, unsupported roles, query plan/indexed lookup and private transport errors.
- Token signature verification is mandatory **before** caller invokes this function. It does not authenticate the raw bearer token itself, and no public auth endpoint calls this module today.

## Release and rollback

This component is **not active in FastAPI require_user**. It is a necessary offline gate, not a deployed identity provider or a migration of user login credentials. Replace Supabase Auth only after selecting an independent supported identity provider, provisioning account recovery and MFA, linking external subjects through verified enrolment rather than email, proving complete founder roster, testing revoked sessions, and cutting over frontend/backend together with a documented rollback plan.

Reverting this isolated module/test/doc has no live operational effect; no existing D1 shadow row changes. **Supabase Auth and PostgreSQL remain live.**
