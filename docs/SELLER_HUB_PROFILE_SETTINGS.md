# Seller Hub Profile & Account Settings

## Purpose

Give each restricted Seller Hub owner a safe place to manage their account identity without exposing Founder HQ or allowing profile changes to mutate ownership, commission, inventory or settlement records.

The profile view is reached from the signed-in account chip or the **Profile** Seller Hub navigation item.

## Source of truth

PostgreSQL remains the source of truth for Seller Hub profile identity that belongs to the marketplace:

- `tcg.owners.display_name`
- `tcg.owners.username`
- owner type, membership and commission remain read-only in this view.

Supabase Auth remains the source of truth for authentication credentials:

- login email;
- email verification state;
- password.

The browser never receives a service-role credential and Drop Rate never stores a password.

## Username contract

Usernames are optional and:

- normalised to lowercase;
- 3–30 characters;
- start with a letter or number;
- contain only lowercase letters, numbers and underscores;
- unique case-insensitively across `tcg.owners`.

The unique constraint is enforced in PostgreSQL, not only in browser validation.

## Profile update security

`tcg.update_owner_profile(text,text)` is a SECURITY DEFINER function available only to `tcg_api`.

It independently resolves `tcg.current_user_id()`, requires an active `OWNER` membership, locks that owner's row, updates only that owner, and writes an `OWNER_PROFILE_UPDATED` audit event containing the old/new display name and username.

It does not change:

- `owner_type`;
- `founder_slot`;
- `commission_bps`;
- ownership of inventory;
- settlement or payout data;
- membership role.

## Email changes

Email changes are requested directly against the authenticated Supabase Auth `/user` endpoint with the seller's own bearer token. The UI explains that the login email only changes after Supabase's configured verification flow completes.

The profile screen reads the current Auth user back into the Seller Hub session instead of copying email into PostgreSQL.

## Password changes

For email/password accounts the Seller Hub requires the current password first. It obtains a fresh authenticated session through the normal password grant and only then submits the new password to Supabase Auth.

Password values are never written to PostgreSQL, logs, audit events, local storage or the Seller Hub backend.

OAuth-only sellers continue using their identity provider; this profile milestone does not silently create a password for those accounts.

## Mobile UX

The Seller Hub bottom navigation becomes horizontally scrollable below 900 px so existing destinations plus **Profile** remain usable without compressing every item into unreadable fixed-width tabs.

## Tests

The regression suite verifies:

1. database username constraints and case-insensitive uniqueness;
2. owner-scoped SECURITY DEFINER enforcement;
3. profile audit logging;
4. backend profile GET/PATCH routes require Seller Hub owner access;
5. username normalisation and validation;
6. profile/email/password controls exist in Seller Hub;
7. password change re-authenticates before credential update;
8. no service-role secret is present in browser code;
9. the profile destination remains reachable on mobile.
