"""INACTIVE private FastAPI->Cloudflare Worker D1 posting transport envelope.

Pure bytes/HMAC helper, no HTTP client or FastAPI route. Authentication of
original Shopify/eBay webhook, physical owner, sale status and allowed payment
event MUST take place before generating this envelope. The Worker accepts
only canonical fixed SQL statement shapes, never arbitrary SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from .d1_candidate_sale import CandidateSaleGuard, PreparedStatement

PATH="/internal/d1/candidate/post"
OPERATIONS={
    "POST_PAID_SALE",
    "POST_CARD_REFUND",
    "POST_SHIPPING_ALLOCATION",
    "POST_SHIPPING_REFUND",
    "POST_PAYMENT_FEE",
}
HOST_RE=re.compile(r"[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]\Z")


@dataclass(frozen=True,slots=True)
class SignedCandidateEnvelope:
    body: bytes
    headers: dict[str,str]


def sign_candidate_statements(
    operation: str, statements: tuple[PreparedStatement,...],
    *, host: str, secret: str, signed_at: datetime,
) -> SignedCandidateEnvelope:
    """Return EXACT signed request bytes and headers, never send or log them."""
    if operation not in OPERATIONS:
        raise CandidateSaleGuard("Invalid candidate D1 transaction operation")
    if (not isinstance(statements,tuple)
        or not 1<=len(statements)<=103
        or any(not isinstance(s,PreparedStatement) for s in statements)):
        raise CandidateSaleGuard("Missing prepared candidate financial statements")
    if (not isinstance(host,str) or not HOST_RE.fullmatch(host)
        or host.lower()!=host or host.startswith("-")
        or ".." in host):
        raise CandidateSaleGuard("Unapproved fixed staging service host")
    if not isinstance(secret,str) or len(secret)<40:
        raise CandidateSaleGuard("Staging signing key is missing or too short")
    if (not isinstance(signed_at,datetime) or signed_at.tzinfo is None
        or signed_at.utcoffset() is None):
        raise CandidateSaleGuard("Signed timestamp must be timezone aware")
    timestamp=str(int(signed_at.astimezone(timezone.utc).timestamp()))
    if not re.fullmatch(r"[0-9]{10,12}",timestamp):
        raise CandidateSaleGuard("Staging timestamp outside supported epoch")
    for statement in statements:
        if (not isinstance(statement.sql,str)
            or len(statement.sql)>100000
            or not isinstance(statement.params,tuple)
            or statement.sql.count("?")!=len(statement.params)
            or len(statement.params)>100):
            raise CandidateSaleGuard("Unsafe candidate prepared SQL shape")
    body=json.dumps({
        "version":1,
        "operation":operation,
        "statements":[{
            "sql":statement.sql,
            "params":list(statement.params),
        } for statement in statements],
    },ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")
    if len(body)>65536:
        raise CandidateSaleGuard("Candidate transaction envelope over 64 KiB")
    digest=hashlib.sha256(body).hexdigest()
    message="\n".join(("POST",host,PATH,timestamp,digest)).encode("utf-8")
    signature=hmac.new(secret.encode("utf-8"),message,hashlib.sha256).hexdigest()
    return SignedCandidateEnvelope(body=body,headers={
        "Content-Type":"application/json",
        "X-DR-Protocol":"1",
        "X-DR-Timestamp":timestamp,
        "X-DR-Body-Sha256":digest,
        "X-DR-Signature":signature,
    })
