# Storefront “Sell With Us” → Seller Hub

## Purpose

Connect the Shopify storefront to Drop Rate's restricted Seller Hub so a customer can
become a seller without needing a founder to manually issue an invitation first.

The public path is:

`Shopify storefront → Sell With Us → verified account → restricted CONSIGNOR/OWNER membership → Seller Hub`

Founder HQ remains a separate PLATFORM_ADMIN boundary.

## Public registration contract

The public registration page is `/owner/join`.

It supports two modes:

1. existing founder-issued seller invitations, preserving the existing email-locked invite contract;
2. invite-free verified self-registration from the storefront.

Invite-free registration uses `POST /api/v1/owner-self-register` and the
`tcg.self_register_owner` SECURITY DEFINER function.

The database function—not browser input—verifies:

- the authenticated Supabase user exists;
- the account is not anonymous;
- the account has a non-empty email;
- the account email is confirmed;
- the user does not already hold a different Drop Rate role.

A new self-registered seller receives:

- `owners.owner_type = CONSIGNOR`;
- `owner_memberships.role = OWNER`;
- active membership;
- default commission `1000 bps / 10%`;
- no Founder HQ permission.

Existing active OWNER/CONSIGNOR membership is idempotently reused. An existing
PLATFORM_ADMIN or other conflicting membership fails closed and is never overwritten.

## Storefront CTA

The Brand Redesign header contains a visible **Sell With Us** CTA on desktop and compact
**Sell** label on mobile. It links to the public Seller Hub join page.

The CTA uses the same Drop Rate blue/navy visual system and remains separate from the
Shopify customer-account control.

## Security boundaries

Self-registration does not grant:

- PLATFORM_ADMIN;
- Founder HQ access;
- ownership of another seller's inventory;
- payout approval/execution;
- manual settlement adjustment;
- unrestricted inventory mutation.

All Seller Hub APIs continue to enforce owner-scoped access.

## Testing

Before Brand Redesign publication:

1. migration CI/security assertions pass;
2. invite mode still calls the existing invite redemption endpoint;
3. invite-free mode calls the self-registration endpoint;
4. email confirmation is enforced in the database;
5. existing OWNER registration is idempotent;
6. conflicting admin membership fails closed;
7. desktop CTA renders and routes correctly;
8. mobile CTA renders and routes correctly;
9. Seller Hub redirects only to `/owner`, never Founder HQ;
10. Brand Redesign theme source/runtime parity is reverified after deployment.

## Activation

The migration must be applied through the normal Supabase migration process after its PR
is merged. The updated header is then synced only to the unpublished Brand Redesign
theme and read back before launch.
