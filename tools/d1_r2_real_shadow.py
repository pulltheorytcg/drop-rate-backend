"""Bounded, real Lorcast R2 -> new isolated Cloudflare D1 shadow import.

GitHub Actions uses its short-lived OIDC identity to read a verified source
via the Railway backend. Its D1-scoped API token never goes to Railway.
No catalogue search route, production D1 DB, Shopify or ownership is changed.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
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
    if source_path not in (
        SOURCE_PATH, SOURCE_PATH + "/yugioh",
        SOURCE_PATH + "/magic", SOURCE_PATH + "/legacy", SOURCE_PATH + "/legacy-d1",
        *(SOURCE_PATH + "/followon/" + name for name in
          ("sports","sports-heritage","figures","magic")),
    ):
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


def _existing_lorcana_proof(client: D1Client, source: projection_codec.Projection):
    """Read-only proof of a previous source-identical completed import.

    Main-branch changes can trigger this job again. Never create a duplicate
    database or replace its data, but a valid existing shadow is still success.
    """
    existing = [db for db in client.list_databases()
                if str(db.get("name", "")).startswith(SHADOW_DB_PREFIX)]
    if not existing:
        return None
    if len(existing) != 1:
        raise MigrationGuard("Ambiguous previous isolated Lorcana database")
    db = existing[0]
    uid = db.get("uuid")
    if (not isinstance(uid, str)
            or not re.fullmatch(r"[a-fA-F0-9-]{36}", uid)):
        raise MigrationGuard("Invalid previous Lorcana D1 UUID")
    registry = _query(client, uid, """select manifest_sha,provider,system_code,
        language,expected_rows,projection_sha,source_content_sha,source_revision
        from shadow_generations""")
    expected = (source.manifest_sha, *source.scope, source.expected_rows,
                source.projection_sha, source.source_content_sha, source.source_revision)
    columns = ("manifest_sha","provider","system_code","language","expected_rows",
               "projection_sha","source_content_sha","source_revision")
    matching=[r for r in registry if r.get('manifest_sha')==source.manifest_sha]
    if matching and (len(matching)!=1 or tuple(matching[0][key] for key in columns)!=expected):
        raise MigrationGuard("Existing Lorcana D1 generation differs from R2 source")
    pointers = _query(client,uid,"select provider,system_code,language,manifest_sha from shadow_active_partitions")
    if (len(pointers)!=1 or tuple(pointers[0][k] for k in ('provider','system_code','language'))!=source.scope):
        raise MigrationGuard('Previous Lorcana D1 generation active pointer mismatch')
    if pointers[0]['manifest_sha']!=source.manifest_sha:
        return _refresh_lorcana_generation(client,uid,db['name'],source,registry,pointers[0]['manifest_sha'])
    if not matching:
        raise MigrationGuard('Active Lorcana generation is missing')
    if verify_d1_projection(client, uid, source) != source.expected_rows:
        raise MigrationGuard("Existing Lorcana D1 readback does not match source")
    pointers = _query(client, uid, "select provider,system_code,language,manifest_sha "
                      "from shadow_active_partitions")
    if (len(pointers) != 1 or
            tuple(pointers[0][key] for key in
                  ("provider","system_code","language","manifest_sha"))
               != (*source.scope,source.manifest_sha)):
        raise MigrationGuard("Previous Lorcana D1 active pointer mismatch")
    return {"status":"REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED",
            "database_name":db["name"],"database_uuid":uid,
            "r2_source_manifest_sha":source.manifest_sha,
            "d1_projection_sha":source.projection_sha,
            "source_rows":source.expected_rows,"d1_verified_rows":source.expected_rows,
            "existing_readonly_reverified":True,
            "main_catalogue_reads_switched":False,"production_shopify_writes":0,
            "production_money_or_owner_writes":0,
            "production_market_value_writes":0,"supabase_writes":0,"r2_writes":0}


LORCANA_REFRESH_BUDGET_SQL="""create table if not exists shadow_lorcana_refresh_budget(
 utc_day text primary key,
 manifest_sha text not null,
 prior_manifest_sha text not null,
 rows_reserved integer not null check(rows_reserved between 1 and 8000)
)"""


def _refresh_lorcana_generation(client,uid,name,source,registry,prior_sha,*,now=None):
    """Append only a verified bounded refresh in the existing Lorcana database."""
    prior=[r for r in registry if r.get('manifest_sha')==prior_sha]
    if len(prior)!=1 or tuple(prior[0][k] for k in ('provider','system_code','language'))!=source.scope:
        raise MigrationGuard('Original Lorcana generation metadata is invalid')
    if not 1<=prior[0]['expected_rows']<=source.expected_rows<=MAX_SOURCE_ROWS:
        raise MigrationGuard('Lorcana source count decrease requires review')
    verify_d1_projection(client,uid,replace(source,manifest_sha=prior_sha,
        expected_rows=prior[0]['expected_rows'],projection_sha=prior[0]['projection_sha']))
    # Preserve all prior stable identities. Removed products require explicit review.
    old_keys=[]
    field_changes={}
    changed_identities=0
    wanted={row[1]:row for row in source.rows}
    for offset in range(0,prior[0]['expected_rows'],100):
        prior_rows=_query(client,uid,D1_READBACK_SQL,[prior_sha,100,offset])
        for row in prior_rows:
            key=row['card_key'];old_keys.append(key)
            if key in wanted:
                fields=[column for i,column in enumerate(projection_codec.SQLITE_COLUMNS)
                        if column!='manifest_sha' and row[column]!=wanted[key][i]]
                if fields:changed_identities+=1
                for column in fields:field_changes[column]=field_changes.get(column,0)+1
    if len(old_keys)!=prior[0]['expected_rows'] or not set(old_keys)<=wanted.keys():
        raise MigrationGuard('Prior Lorcana identities removed or incomplete')
    page_count=_query(client,uid,'PRAGMA page_count')[0]['page_count']
    page_size=_query(client,uid,'PRAGMA page_size')[0]['page_size']
    database_bytes=page_count*page_size
    # Conservative preflight, followed by actual post-copy size readback.
    projected_bytes=database_bytes+6*sum(len(json.dumps(row).encode()) for row in source.rows)+65536
    if projected_bytes>450_000_000:
        raise MigrationGuard('Lorcana retained-generation storage headroom exhausted')
    _query(client,uid,LORCANA_REFRESH_BUDGET_SQL)
    today=(now or datetime.now(timezone.utc)).date().isoformat()
    receipt=_query(client,uid,'select manifest_sha,prior_manifest_sha,rows_reserved from shadow_lorcana_refresh_budget where utc_day=?',[today])
    if receipt and (len(receipt)!=1 or receipt[0]['manifest_sha']!=source.manifest_sha or receipt[0]['prior_manifest_sha']!=prior_sha):
        return {'status':'LORCANA_REFRESH_DEFERRED_DAILY_BUDGET','source_rows':source.expected_rows,
                'main_catalogue_reads_switched':False,'production_money_or_owner_writes':0,
                'production_shopify_writes':0,'production_market_value_writes':0,'supabase_writes':0,'r2_writes':0}
    if not receipt:
        _query(client,uid,'insert into shadow_lorcana_refresh_budget values(?,?,?,?)',
            [today,source.manifest_sha,prior_sha,source.expected_rows])
    existing=[r for r in registry if r.get('manifest_sha')==source.manifest_sha]
    if not existing:
        statement=projection_codec.generation_statement(source)
        _query(client,uid,statement['sql'],statement['params'])
    count=_query(client,uid,'select count(*) as n from shadow_cards where manifest_sha=?',[source.manifest_sha])[0]['n']
    staged={}
    for offset in range(0,count,100):
        for row in _query(client,uid,D1_READBACK_SQL,[source.manifest_sha,100,offset]):
            key=row['card_key']
            if key in staged or key not in wanted or tuple(row[c] for c in projection_codec.SQLITE_COLUMNS)!=wanted[key]:
                raise MigrationGuard('Partial Lorcana refresh differs from immutable R2')
            staged[key]=row
    if len(staged)!=count:raise MigrationGuard('Partial Lorcana refresh count mismatch')
    missing=[row for key,row in sorted(wanted.items()) if key not in staged]
    # Original codec chunks keep every statement within D1 100-bind limit.
    width=len(projection_codec.SQLITE_COLUMNS);chunk=100//width;statements=[]
    for offset in range(0,len(missing),chunk):
        rows=missing[offset:offset+chunk]
        statements.append({'sql':projection_codec.INSERT_CARD_SQL+','.join('('+','.join('?' for _ in range(width))+')' for _ in rows),
                           'params':[v for row in rows for v in row]})
    for offset in range(0,len(statements),12):client.batch(uid,statements[offset:offset+12])
    verify_d1_projection(client,uid,source)
    final_size=_query(client,uid,'PRAGMA page_count')[0]['page_count']*_query(client,uid,'PRAGMA page_size')[0]['page_size']
    if final_size>450_000_000:raise MigrationGuard('Lorcana actual retained-generation size limit exceeded')
    # CAS: never replace a generation another publisher advanced after our read.
    _query(client,uid,'update shadow_active_partitions set manifest_sha=? where provider=? and system_code=? and language=? and manifest_sha=?',
           [source.manifest_sha,*source.scope,prior_sha])
    pointer=_query(client,uid,'select manifest_sha from shadow_active_partitions where provider=? and system_code=? and language=?',source.scope)
    if pointer!=[{'manifest_sha':source.manifest_sha}]:
        raise MigrationGuard('Concurrent Lorcana generation advance')
    verify_d1_projection(client,uid,source)
    return {'status':'REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED','database_name':name,'database_uuid':uid,
            'r2_source_manifest_sha':source.manifest_sha,'r2_source_content_sha':source.source_content_sha,
            'd1_projection_sha':source.projection_sha,'source_rows':source.expected_rows,
            'd1_verified_rows':source.expected_rows,'new_rows_this_run':len(missing),
            'refreshed_existing_database':True,'prior_generation_retained':True,
            'changed_existing_identities':changed_identities,'new_identities':len(wanted)-len(old_keys),
            'changed_projection_field_counts':dict(sorted(field_changes.items())),
            'database_bytes_before':database_bytes,'database_bytes_after':final_size,
            'main_catalogue_reads_switched':False,'production_shopify_writes':0,
            'production_money_or_owner_writes':0,'production_market_value_writes':0,
            'supabase_writes':0,'r2_writes':0}


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
    prior = _existing_lorcana_proof(cloud, source)
    if prior is not None:
        return prior
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
