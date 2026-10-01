# Seller Hub Email-or-Username Login

## Purpose

Allow a Seller Hub owner to sign in with either their verified login email or their unique Drop Rate username while keeping Supabase Auth as the credential authority.

The username is an authentication alias only. Email remains the verification, recovery and Supabase Auth identity.

## Flow

1. The browser submits `identifier` and `password` to `POST /api/v1/public/owner-session`.
2. FastAPI normalises the identifier and checks shared PostgreSQL login-failure throttles.
3. If the identifier contains `@`, it is treated as an email address.
4. Otherwise FastAPI resolves the username to the linked Supabase Auth email through `tcg.resolve_owner_login_email(text)`.
5. The resolved email never appears in an unauthenticated API response.
6. FastAPI sends the email/password pair to Supabase Auth's password token endpoint.
7. On successful Supabase authentication, the normal Supabase session is returned and the existing Seller Hub access check still decides whether the account may open Seller Hub or Founder HQ.
8. On failure, the public response is always the generic message **Invalid email, username or password**.

Drop Rate does not verify passwords itself and never stores them.

## Username resolution

`tcg.resolve_owner_login_email(text)` is a SECURITY DEFINER function.

It:

- resolves only active owners with an active owner membership;
- joins the username to the corresponding `auth.users` record server-side;
- is executable by `tcg_api` only;
- is not executable by `public`, `anon` or the browser `authenticated` role.

The browser therefore cannot use the resolver as an email-discovery endpoint.

## Enumeration resistance

Unknown usernames still trigger a real Supabase password-auth request, using a synthetic `@example.invalid` address derived from a one-way identifier hash.

This keeps the public response shape the same for:

- a username that does not exist;
- a valid username with the wrong password;
- an email with the wrong password.

The backend never returns the internally resolved email on an unauthenticated failure.

## Brute-force throttling

Failed Seller Hub password attempts are recorded in `tcg.owner_login_failures` using SHA-256 hashes of:

- the normalised identifier;
- the client network identity.

Raw email addresses, usernames, IP addresses and passwords are not stored in this table.

The shared PostgreSQL limiter blocks when either threshold is reached inside a rolling 15-minute window:

- 8 failed attempts for the same identifier;
- 30 failed attempts from the same network identity.

The endpoint returns HTTP 429 with `Retry-After` when the Drop Rate limiter is active. Supabase Auth's own upstream rate limiting remains in place as an additional layer.

## Failure handling

- Invalid credentials: HTTP 401 with a generic message.
- Drop Rate throttle: HTTP 429.
- Supabase Auth throttle: HTTP 429.
- Supabase/network outage: HTTP 503 without leaking provider details.
- Successful session responses include `Cache-Control: no-store`.

## Tests

Regression coverage verifies:

- email login skips username resolution;
- username login resolves only on the server;
- unknown usernames use a synthetic email and return the same generic 401;
- failed logins are recorded;
- throttled requests stop before username resolution or Supabase authentication;
- raw network/identifier values are hashed before throttle storage;
- username resolver permissions remain server-only;
- the Seller Hub login UI sends `identifier` rather than assuming email;
- the browser no longer calls Supabase's password-token endpoint directly for Seller Hub password login.
