from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


RESEND_API_URL = "https://api.resend.com/emails"
WEBHOOK_TOLERANCE_SECONDS = 300


class ResendWebhookVerificationError(ValueError):
    pass


def verify_resend_webhook(
    *,
    raw_body: bytes,
    webhook_secret: str,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    now: int | None = None,
) -> None:
    secret = webhook_secret.strip()
    if not secret.startswith("whsec_"):
        raise ResendWebhookVerificationError("Invalid Resend webhook secret")

    event_id = svix_id.strip()
    timestamp_text = svix_timestamp.strip()
    signatures = svix_signature.strip()
    if not event_id or not timestamp_text or not signatures:
        raise ResendWebhookVerificationError("Missing Resend webhook signature headers")

    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise ResendWebhookVerificationError("Invalid Resend webhook timestamp") from exc

    current = int(time.time() if now is None else now)
    if abs(current - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        raise ResendWebhookVerificationError("Resend webhook timestamp is outside tolerance")

    encoded_secret = secret.removeprefix("whsec_")
    encoded_secret += "=" * (-len(encoded_secret) % 4)
    try:
        secret_bytes = base64.b64decode(encoded_secret, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ResendWebhookVerificationError("Invalid Resend webhook secret encoding") from exc

    signed = (
        event_id.encode("utf-8")
        + b"."
        + timestamp_text.encode("ascii")
        + b"."
        + raw_body
    )
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    ).decode("ascii")

    candidates = []
    for part in signatures.split():
        version, separator, signature = part.partition(",")
        if separator and version == "v1" and signature:
            candidates.append(signature)

    if not candidates or not any(
        hmac.compare_digest(expected, candidate)
        for candidate in candidates
    ):
        raise ResendWebhookVerificationError("Invalid Resend webhook signature")


class ResendApiError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SellerInviteEmail:
    subject: str
    html: str
    text: str


def build_seller_invite_email(
    *,
    invited_name: str,
    invite_url: str,
    commission_bps: int,
    expires_at: datetime,
    logo_url: str,
) -> SellerInviteEmail:
    name = html.escape(invited_name.strip() or "Seller")
    safe_invite_url = html.escape(invite_url, quote=True)
    safe_logo_url = html.escape(logo_url, quote=True)
    commission = f"{commission_bps / 100:.2f}".rstrip("0").rstrip(".")
    expiry = expires_at.strftime("%d %b %Y at %H:%M UTC")

    subject = "You're invited to sell with Drop Rate"
    plain = (
        f"Hi {invited_name.strip() or 'Seller'},\n\n"
        "You've been invited to join Drop Rate as a seller / consignor.\n"
        f"Your Drop Rate commission rate is {commission}%.\n"
        f"This invitation expires {expiry}.\n\n"
        f"Complete your onboarding: {invite_url}\n\n"
        "Your account is private and restricted to your own inventory, sales and payouts. "
        "Returning cards to Personal Collection keeps them off marketplace channels until "
        "you explicitly make them sellable again.\n\n"
        "If you were not expecting this invitation, you can ignore this email."
    )

    body = f"""<!doctype html>
<html>
  <body style="margin:0;background:#071b3f;font-family:Arial,Helvetica,sans-serif;color:#12213b;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#071b3f;padding:32px 14px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#f6f7fb;border-radius:24px;overflow:hidden;">
            <tr>
              <td style="background:#071b3f;padding:30px 34px 22px;text-align:center;">
                <img src="{safe_logo_url}" width="160" alt="Drop Rate" style="display:inline-block;max-width:160px;height:auto;">
              </td>
            </tr>
            <tr>
              <td style="padding:38px 38px 20px;">
                <div style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;font-weight:700;color:#5b6c8b;margin-bottom:10px;">Seller invitation</div>
                <h1 style="font-size:30px;line-height:1.15;margin:0 0 14px;color:#071b3f;">Your cards. Your proceeds.</h1>
                <p style="font-size:16px;line-height:1.65;margin:0 0 18px;color:#40506a;">Hi {name}, you've been invited to join Drop Rate as a seller / consignor.</p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:16px;border:1px solid #dfe5ef;margin:24px 0;">
                  <tr>
                    <td style="padding:18px 20px;border-bottom:1px solid #e8edf5;">
                      <span style="font-size:13px;color:#6a7891;">Drop Rate commission</span><br>
                      <strong style="font-size:20px;color:#071b3f;">{commission}%</strong>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 20px;">
                      <span style="font-size:13px;color:#6a7891;">Invitation expires</span><br>
                      <strong style="font-size:16px;color:#071b3f;">{html.escape(expiry)}</strong>
                    </td>
                  </tr>
                </table>
                <p style="font-size:15px;line-height:1.6;color:#40506a;margin:0 0 24px;">Your account is private and owner-scoped. You'll see only your own inventory, sales, settlement information and payouts.</p>
                <div style="text-align:center;margin:28px 0 26px;">
                  <a href="{safe_invite_url}" style="display:inline-block;background:#1e73ff;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;padding:15px 28px;border-radius:12px;">Start seller onboarding</a>
                </div>
                <p style="font-size:13px;line-height:1.6;color:#738098;margin:0;">If the button doesn't work, copy and paste this secure link into your browser:<br><span style="word-break:break-all;color:#40506a;">{safe_invite_url}</span></p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 38px 34px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eaf0ff;border-radius:14px;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <strong style="font-size:14px;color:#071b3f;">What happens next</strong>
                      <ol style="margin:10px 0 0;padding-left:20px;color:#40506a;font-size:14px;line-height:1.7;">
                        <li>Create or sign in to your Drop Rate owner account.</li>
                        <li>Review your commission and restricted owner access.</li>
                        <li>Open your private owner portal.</li>
                        <li>Set up Stripe payouts when you're ready to receive proceeds.</li>
                      </ol>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background:#071b3f;padding:22px 34px;text-align:center;color:#9fb0cf;font-size:12px;line-height:1.6;">
                This is a private transactional invitation from Drop Rate. If you were not expecting it, you can ignore this email.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return SellerInviteEmail(subject=subject, html=body, text=plain)


class ResendEmailClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 12.0):
        clean = api_key.strip()
        if not clean:
            raise ValueError("Resend API key is required")
        self._api_key = clean
        self._timeout = httpx.Timeout(timeout_seconds)

    async def send(
        self,
        *,
        sender: str,
        recipient: str,
        email: SellerInviteEmail,
        idempotency_key: str,
        reply_to: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "from": sender,
            "to": [recipient],
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
        }
        if reply_to:
            payload["reply_to"] = reply_to

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(RESEND_API_URL, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ResendApiError(
                "Resend request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ResendApiError(
                "Resend request failed",
                retryable=True,
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ResendApiError(
                f"Resend returned HTTP {response.status_code}",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ResendApiError(
                "Resend returned invalid JSON",
                retryable=True,
                status_code=response.status_code,
            ) from exc

        message_id = str(data.get("id") or "").strip()
        if not message_id:
            raise ResendApiError(
                "Resend did not return an email ID",
                retryable=True,
                status_code=response.status_code,
            )
        return message_id
