# Authentication security and social login

## Current password controls

Drop Rate uses Supabase Auth for identity and FastAPI/PostgreSQL for application authorization.

The current Supabase project is configured with:
- minimum password length: 12 characters
- lowercase required
- uppercase required
- number required
- symbol required

Leaked-password protection is a Supabase Pro-plan feature. On the current plan it cannot be enabled.
Treat it as a required pre-public-launch hardening item if/when the project moves to Pro.

Existing passwords that predate the stronger policy must remain usable until they are changed.
The UI therefore enforces the 12-character rule only for new passwords, password resets and new
email/password registrations.

## Social authentication

Drop Rate supports Google and Apple OAuth in the frontend, but provider buttons are shown only when
the matching provider is actually enabled in Supabase Auth.

Authentication never grants Founder HQ access by itself.

After any email/password, Google or Apple login:
1. Supabase Auth proves identity.
2. Drop Rate calls `GET /api/v1/access/me`.
3. Founder HQ opens only when `founder_hq_allowed=true`.
4. An authenticated user with no membership or an `OWNER` membership is denied Founder HQ.

Future seller/consignor portals will use the same identity providers but remain owner-scoped by
membership + RLS.

## Supabase redirect configuration

In Supabase Dashboard:

Authentication -> URL Configuration

Use the production Drop Rate URL as the Site URL and add exact allowed redirect URLs for:
- the Founder HQ root
- the invitation/onboarding route

Avoid production wildcards where possible.

## Google

In Supabase Dashboard:

Authentication -> Sign In / Providers -> Google

Create a Web OAuth client in Google Auth Platform / Google Cloud.

Google requires:
- Authorized JavaScript origin: the production Drop Rate origin
- Authorized redirect URI: the **Supabase Callback URL (for OAuth)** shown on the Google provider
  panel in Supabase

Enable only the standard identity scopes needed by Supabase:
- `openid`
- email
- profile

Store the client ID/secret only in the provider configuration; never expose the client secret in
Drop Rate frontend code.

## Apple

In Supabase Dashboard:

Authentication -> Sign In / Providers -> Apple

Apple web OAuth requires an Apple Developer account, Services ID and Sign in with Apple key.

Use the **Supabase Callback URL (for OAuth)** shown on the Apple provider panel as Apple's return URL.

Important operational rules:
- Apple OAuth client secrets expire and must be rotated. Supabase documentation currently notes a
  six-month rotation requirement for the web OAuth secret.
- Keep the Apple `.p8` signing key in a secure secrets store and never commit it.
- Apple may provide a private relay email when the user chooses Hide My Email.
- Email-locked invitations must fail closed if the authenticated provider email does not match the
  invitation. Do not weaken that check to accommodate relay addresses; use Share My Email or issue a
  deliberately compatible invitation after verifying the user.

## MFA target

Before any external seller/consignor accounts are launched:
- require MFA for `PLATFORM_ADMIN` accounts
- strongly encourage or require MFA for seller/consignor accounts once supported in the owner portal
- retain rate limits, email verification and session controls in Supabase Auth
