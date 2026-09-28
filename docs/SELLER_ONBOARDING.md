# Seller / consignor invitation onboarding

## Scope

Founder HQ can invite a third-party seller/consignor by name, email address and
commission basis points. The invite creates no inventory and grants no access by
itself.

The flow is:

1. Founder HQ creates the invite.
2. FastAPI generates a cryptographically random token and stores only its
   SHA-256 hash in PostgreSQL.
3. FastAPI sends the branded transactional email through the email adapter.
   The raw token is used only to build that outbound email and the manual copy
   link; it is never written to PostgreSQL or an automation outbox.
4. The recipient opens the owner join URL, sees their masked invited email,
   commission and expiry, and creates or signs into their account.
5. The authenticated account email must exactly match the invited email.
6. The recipient explicitly acknowledges the restricted owner/commission
   onboarding contract.
7. PostgreSQL creates a CONSIGNOR owner and an OWNER membership transactionally
   and marks the invitation redeemed.
8. The owner portal opens with an onboarding-complete checklist and Stripe payout
   setup as the next financial step.

OWNER can never become PLATFORM_ADMIN through this flow.

## Transactional email

The initial provider adapter is Resend. Provider code is isolated in
backend/app/resend_email.py so it can be replaced without changing invitation
or ownership rules.

Required production configuration for actual sending:

- TCG_PUBLIC_APP_URL — canonical HTTPS origin for Drop Rate onboarding.
- TCG_RESEND_API_KEY — server-side Resend API key.
- TCG_SELLER_INVITE_FROM_EMAIL — verified branded sender.
- TCG_SELLER_INVITE_REPLY_TO — optional monitored support address.
- TCG_RESEND_WEBHOOK_SECRET — Resend webhook signing secret.

If sending is not configured, invite creation remains usable and returns the
secure copy-link fallback with email_delivery.status = NOT_CONFIGURED.

Every outbound attempt uses a provider idempotency key. Resending rotates the
invitation token hash before sending a fresh message, invalidating the previous
invite URL.

## Delivery webhooks

POST /api/v1/webhooks/resend reads the exact raw request body and verifies the
Svix signature headers before parsing JSON.

Tracked email event types:

- email.sent
- email.delivered
- email.delivery_delayed
- email.bounced
- email.failed
- email.suppressed
- email.complained

Webhook events are deduplicated using the provider webhook event ID. PostgreSQL
stores only provider IDs, event type, timestamp and a SHA-256 payload
fingerprint; it does not retain webhook payloads or recipient content in the
event ledger.

Founder HQ shows email state independently from onboarding state. An invitation
may be DELIVERED but still INVITED until the recipient finishes onboarding.

## Security boundaries

- Raw invitation tokens are never persisted.
- Public invitation preview masks the invited email address.
- Redemption trusts the verified JWT account email, never an email supplied in
  the redeem request body.
- Expired, revoked and already-redeemed invitations fail closed.
- Resend delivery events cannot create owners, change commission, redeem
  invitations or grant permissions.
- The legacy three-argument redeem function loses tcg_api execution in the
  delivery migration so onboarding acknowledgement cannot be bypassed.
- Invite creation/list/resend/revoke remains platform-admin only.
- The created membership is always restricted OWNER.

## n8n boundary

n8n should orchestrate later seller lifecycle work such as reminders, incomplete
onboarding follow-up and operational alerts by calling backend APIs. It should
not own invitation validity, commission, ownership, or the raw invite secret.

The initial email is deliberately sent by FastAPI because placing the one-time
raw token in an asynchronous outbox or n8n execution history would widen the
secret boundary unnecessarily.

## Release test gate

Before enabling production email delivery:

1. CI must pass Python compilation, JavaScript syntax checks and all tests.
2. The migration must apply cleanly and its grants/RLS must be verified.
3. A verified sender domain must exist at the email provider.
4. The webhook signing secret must be configured.
5. Send one controlled invite to an authorised test address.
6. Confirm Founder HQ transitions SENT -> DELIVERED.
7. Confirm wrong-email redemption is rejected.
8. Complete the invite and confirm only an OWNER / CONSIGNOR account is created.
9. Confirm the user lands in the owner portal and cannot open Founder HQ.
10. Confirm resend, revoke and expiry behaviour.
