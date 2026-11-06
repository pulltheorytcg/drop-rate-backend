"""Bounded, real Lorcast R2 -> new isolated Cloudflare D1 shadow import.

GitHub Actions uses its short-lived OIDC identity to read a verified source
via the Railway backend. Its D1-scoped API token never goes to Railway.
No catalogue search route, production D1 DB, Shopify or ownership is changed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, urlsplit

import httpx

from app import d1_shadow_catalogue as projection_codec
from app import r2_first_catalogue as source_codec
from d1_remote_catalogue_pilot import D1Client, PilotError

API_ORIGIN = "https://drop-rate-api-live-production.up.railway.app"
SOURCE_PATH = "/api/v1/internal/d1-shadow"
AUDIENCE = "drop-rate-readonly-r2-d1-shadow-20261106"
ALLOWED_SCOPE = ("lorcast", "DISNEY_LORCANA", "English")
MAX_SOURCE_ROWS = 8000
MAX_PARTS = 25
MAX_TOTAL_BYTES = 8_000_000
MAX_RETRIES = 6
# Railway and trusted-main GitHub Actions deploy independently. The prior
# 14-attempt window expired before the security-diagnostic build came online.
MAX_SOURCE_READ_ATTEMPTS = 30
MAX_DB_COUNT = 7
SHADOW_DB_PREFIX = "drop-rate-d1-real-lorcast-shadow-"
MAX_EXPORT_CONTENT = 4_000_000
D1_READBACK_SQL = (
    "select " + ",".join(projection_codec.SQLITE_COLUMNS)
    + " from shadow_cards where manifest_sha=? order by card_key limit ? offset ?"
)


class MigrationGuard(PilotError):
    """Verified source, GitHub identity or D1 parity was not established."""


def _oidc_token():
    auth_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    parsed = urlsplit(auth_url)
    if not auth_url or not request_token:
        raise MigrationGuard("GitHub Actions OIDC environment missing")
    # GitHub's documented token exchange service is vstoken; pipelines and
    # token are also GitHub-owned OIDC endpoints. Never follow redirects or
    # leak the runner's bearer token to any non-GitHub host.
    # GitHub's hosted runners use regional token-service subdomains.
    # GitHub documents *.actions.githubusercontent.com for OIDC egress;
    # constrain it to exactly ONE DNS label inside that GitHub-owned zone.
    owned_host = bool(re.fullmatch(
        r"[a-z0-9-]{1,63}\.actions\.githubusercontent\.com",
        parsed.hostname or ""))
    if (parsed.scheme != "https" or not owned_host
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.fragment):
        raise MigrationGuard("GitHub Actions OIDC URL outside GitHub-owned token domain")
    separator = "&" if parsed.query else "?"
    url = auth_url + separator + "audience=" + quote(AUDIENCE, safe="")
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        response = client.get(url, headers={"Authorization": "Bearer " + request_token})
        if response.status_code != 200 or response.is_redirect:
            # Only the numeric status is safe to print. Never log runner
            # request URLs, Location headers, token exchange response bodies
            # or authorization values. A redirect remains fail-closed.
            raise MigrationGuard(
                f"GitHub Actions OIDC minting failed (HTTP {response.status_code})"
            )
        body = response.json()
        token = body.get("value") if isinstance(body, dict) else None
        if not isinstance(token, str) or not 100 < len(token) < 8192:
            raise MigrationGuard("GitHub Actions OIDC token missing")
    return token


def fetch_bytes(client: httpx.Client, path: str, token: str, size_limit: int, *,
                source_path: str = SOURCE_PATH) -> bytes:
    """Only fixed Railway origin and known private catalogue paths are accepted."""
    if source_path not in (SOURCE_PATH, SOURCE_PATH + "/yugioh"):
        raise MigrationGuard("Unapproved R2 export partition path")
    if (path != source_path + "/manifest"
            and not re.fullmatch(re.escape(source_path) + r"/part/[0-9]{1,3}", path)):
        raise MigrationGuard("Non-allowlisted R2 export path")
    if type(size_limit) is not int or not 0 < size_limit <= 4_000_000:
        raise MigrationGuard("Invalid R2 response limit")
    with client.stream("GET", API_ORIGIN + path,
                       headers={"Authorization": "Bearer " + token}) as response:
        if response.status_code != 200 or response.is_redirect:
            raise MigrationGuard(f"R2 export rejected: HTTP {response.status_code}")
        if str(response.url) != API_ORIGIN + path:
            raise MigrationGuard("R2 export origin was changed")
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > size_limit:
                raise MigrationGuard("R2 export exceeds bounded source limit")
    if not data:
        raise MigrationGuard("R2 export returned empty source")
    return bytes(data)


class BytesStorage:
    def __init__(self, objects):
        self.objects = objects

    def read_verified_reference_snapshot(self, sha):
        raw = self.objects.get(sha)
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != sha:
            raise MigrationGuard("Incomplete or corrupt R2 object")
        return raw


def load_verified_source(
    client: httpx.Client, token: str, *,
    source_path: str = SOURCE_PATH,
    allowed_scope: tuple[str, str, str] = ALLOWED_SCOPE,
    min_rows: int = 1000,
    max_rows: int = MAX_SOURCE_ROWS,
    max_parts: int = MAX_PARTS,
    max_bytes: int = MAX_TOTAL_BYTES,
):
    """Read the ACTUAL published R2 objects through an explicitly fixed path."""
    raw_manifest = fetch_bytes(client, source_path + "/manifest", token, 1_000_000,
                               source_path=source_path)
    manifest = source_codec.validate_manifest(source_codec._decode(raw_manifest))
    manifest_sha = source_codec.manifest_digest(manifest)
    if (hashlib.sha256(raw_manifest).hexdigest() != manifest_sha
            or tuple(manifest[x] for x in ("provider", "system_code", "language")) != allowed_scope
            or not min_rows <= manifest["record_count"] <= max_rows
            or manifest["raw_bytes"] > max_bytes
            or len(manifest["parts"]) > max_parts):
        raise MigrationGuard("Unapproved real R2 source partition")
    objects = {manifest_sha: raw_manifest}
    for ordinal, part in enumerate(manifest["parts"]):
        raw = fetch_bytes(client, f"{source_path}/part/{ordinal}", token, MAX_EXPORT_CONTENT,
                          source_path=source_path)
        source_codec._parse_part(raw, part, allowed_scope)
        if part["sha256"] in objects:
            raise MigrationGuard("Repeated R2 content digest")
        objects[part["sha256"]] = raw
    # Rebuild the ORIGINAL full R2 source index and verify cumulative raw digest.
    async def build():
        return await source_codec.load_catalogue(manifest, BytesStorage(objects))
    snapshot = asyncio.run(build())
    try:
        projection = projection_codec.from_verified_snapshot(snapshot)
    finally:
        snapshot.close()
    if (projection.manifest_sha != manifest_sha
            or projection.source_content_sha != manifest["content_sha256"]
            or projection.expected_rows != manifest["record_count"]):
        raise MigrationGuard("Immutable source/projection mismatch")
    return projection, manifest


def _query(client: D1Client, database_id: str, sql: str, params=()):
    result, _ = client.query(database_id, sql, tuple(params))
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise MigrationGuard("Malformed D1 query response")
    return result["results"]


def verify_d1_projection(client: D1Client, database_id: str,
                         projection: projection_codec.Projection):
    """Every D1 row and original source ID must match the R2 projection.

    The final parity hash is stable key sorted, independently recomputed by D1.
    The active pointer must remain UNCHANGED until this exact verification.
    """
    expected = projection.expected_rows
    count = _query(client, database_id,
                   "select count(*) as n from shadow_cards where manifest_sha=?",
                   (projection.manifest_sha,))
    if len(count) != 1 or count[0]["n"] != expected:
        raise MigrationGuard("D1 staged row count does not match R2")
    hasher = hashlib.sha256()
    offset = 0
    while offset < expected:
        batch = _query(client, database_id, D1_READBACK_SQL,
                       (projection.manifest_sha, 100, offset))
        if len(batch) != min(100, expected-offset):
            raise MigrationGuard("Incomplete D1 row readback")
        for item in batch:
            if not isinstance(item, dict) or set(item) != set(projection_codec.SQLITE_COLUMNS):
                raise MigrationGuard("D1 returned unexpected column set")
            original = tuple(item[col] for col in projection_codec.SQLITE_COLUMNS)
            hasher.update(json.dumps(original, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        offset += len(batch)
    if hasher.hexdigest() != projection.projection_sha:
        raise MigrationGuard("D1 source identity SHA256 parity mismatch")
    return expected


def _new_isolated_real_shadow(client: D1Client, run_id: str, attempt: str) -> tuple[str,str]:
    if (not re.fullmatch(r"[0-9]{1,20}", run_id) or
            not re.fullmatch(r"[0-9]{1,4}", attempt)):
        raise MigrationGuard("Missing unique trusted GitHub Actions run")
    databases = client.list_databases()
    if len(databases) > MAX_DB_COUNT:
        raise MigrationGuard("D1 account database budget exceeded; no writes")
    if any(str(x.get("name","")).startswith(SHADOW_DB_PREFIX) for x in databases):
        raise MigrationGuard("An earlier real Lorcana D1 shadow already exists; no duplicate")
    name = SHADOW_DB_PREFIX + run_id + "-" + attempt
    if any(x.get("name") == name for x in databases):
        raise MigrationGuard("Shadow database exists; no overwrite")
    result, _ = client.call("POST", client.path, {"name": name})
    if not isinstance(result, dict) or result.get("name") != name:
        raise MigrationGuard("Cloudflare did not create expected shadow database")
    uid = result.get("uuid")
    if not isinstance(uid, str) or not re.fullmatch(r"[a-fA-F0-9-]{36}", uid):
        raise MigrationGuard("Invalid new D1 database ID")
    return name, uid


def _schema(client: D1Client, database_id: str):
    for statement in projection_codec.SCHEMA.split(";"):
        if statement.strip():
            _query(client, database_id, statement)


def import_real_lorcana(account: str, d1_token: str, run_id: str,
                        attempt: str, *, client: httpx.Client | None = None):
    """Only public reference facts; one NEW D1 DB. No money, prices or owner IO."""
    if not re.fullmatch(r"[0-9]{1,20}", run_id):
        raise MigrationGuard("GitHub Actions execution required")
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20)) as http:
            return import_real_lorcana(account, d1_token, run_id, attempt, client=http)
    # Main-branch CI and Railway deploy concurrently. Wait only for the
    # narrow, feature-gated export route to finish its verified rollout.
    # Never retry a bad OIDC identity (401/403) or a source checksum failure.
    for stage_attempt in range(MAX_SOURCE_READ_ATTEMPTS):
        identity = _oidc_token()
        try:
            source, manifest = load_verified_source(client, identity)
            break
        except MigrationGuard as exc:
            if str(exc) not in {"R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503"} or stage_attempt == MAX_SOURCE_READ_ATTEMPTS - 1:
                raise
            time.sleep(10)
    cloud = D1Client(account, d1_token)
    name, database_id = _new_isolated_real_shadow(cloud, run_id, attempt)
    _schema(cloud, database_id)
    init = projection_codec.generation_statement(source)
    _query(cloud, database_id, init["sql"], init["params"])
    statements = list(projection_codec.insert_statements(source))
    for idx in range(0, len(statements), 12):
        cloud.batch(database_id, statements[idx:idx+12])
    verified = verify_d1_projection(cloud, database_id, source)
    if verified != source.expected_rows:
        raise MigrationGuard("Incomplete source")
    active = _query(cloud, database_id,
                    "select count(*) as n from shadow_active_partitions")
    if len(active) != 1 or active[0]["n"] != 0:
        raise MigrationGuard("Shadow had unexpected prior active pointer")
    swap = projection_codec.activation_statement(source)
    _query(cloud, database_id, swap["sql"], swap["params"])
    pointer = _query(cloud, database_id,
                     "select manifest_sha from shadow_active_partitions where provider=? and system_code=? and language=?",
                     source.scope)
    if len(pointer) != 1 or pointer[0]["manifest_sha"] != source.manifest_sha:
        raise MigrationGuard("Verified D1 shadow did not activate")
    # A second readback guards against a pointer/routing mismatch.
    if verify_d1_projection(cloud, database_id, source) != verified:
        raise MigrationGuard("D1 shadow post-activation changed")
    return {
        "status":"REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED",
        "database_name": name, "database_uuid": database_id,
        "r2_source_manifest_sha":source.manifest_sha,
        "r2_source_content_sha":source.source_content_sha,
        "d1_projection_sha":source.projection_sha,
        "source_rows":source.expected_rows,
        "d1_verified_rows":verified,
        "d1_sql_insertion_batches":(len(statements)+11)//12,
        "source_revision":manifest["source_revision"],
        "main_catalogue_reads_switched":False,
        "production_shopify_writes":0,
        "production_money_or_owner_writes":0,
        "production_market_value_writes":0,
        "supabase_writes":0,
        "r2_writes":0,
    }


def main() -> int:
    try:
        result = import_real_lorcana(
            os.environ.get("CLOUDFLARE_ACCOUNT_ID",""),
            os.environ.get("CLOUDFARE_D1_PILOT_TOKEN",""),
            os.environ.get("GITHUB_RUN_ID",""),
            os.environ.get("GITHUB_RUN_ATTEMPT",""),
        )
    except (MigrationGuard, PilotError, ValueError, httpx.HTTPError) as exc:
        # No authentication headers or provider response body is ever logged.
        print("Real shadow import failed safely: " + str(exc), file=sys.stderr)
        return 1
    report = Path("d1-lorcana-real-shadow-report.json")
    report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
