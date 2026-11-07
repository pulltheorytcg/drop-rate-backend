"""Fail-closed deployment configuration for the EXISTING private Cloudflare artwork Worker.

Does not create/delete cloud resources, download images, mutate D1/R2, or touch
Supabase/Shopify. Remote preflight only reads the already-provisioned D1 index.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from urllib import error, request, parse

from d1_artwork_shadow_provision import ACCOUNT, DB_NAME, ALLOWED, _remote_objects
from d1_remote_catalogue_pilot import D1Client

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "cloudflare/artwork-shadow/wrangler.generated.json"
WORKER = "drop-rate-artwork-shadow"
BUCKET_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?\Z")
DB_UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


class ArtworkDeploymentBlocked(ValueError):
    """An exact-identity, account, schema, or binding requirement failed."""


def build_config(*, database_id: str, bucket: str) -> dict:
    if not DB_UUID_RE.fullmatch(database_id):
        raise ArtworkDeploymentBlocked("Exact D1 UUID required")
    if not isinstance(bucket, str) or not BUCKET_RE.fullmatch(bucket):
        raise ArtworkDeploymentBlocked("Explicit existing R2 bucket name required")
    return {
        "name": WORKER,
        "main": "worker.mjs",
        "compatibility_date": "2026-11-06",
        "workers_dev": True,
        # The production drop-rate-private bucket has EU jurisdiction.
        # Omitting it makes Cloudflare falsely report R2 bucket not found (10085).
        "r2_buckets": [{"binding": "ARTWORK_R2", "bucket_name": bucket, "jurisdiction": "eu"}],
        "d1_databases": [{
            "binding": "ARTWORK_D1", "database_name": DB_NAME,
            "database_id": database_id.lower(),
        }],
    }


def prepare(client, *, bucket: str, account: str) -> dict:
    if account != ACCOUNT or getattr(client, "account_id", None) != ACCOUNT:
        raise ArtworkDeploymentBlocked("Refusing other Cloudflare accounts")
    databases = client.list_databases()
    if not isinstance(databases, list) or len(databases) > 10:
        raise ArtworkDeploymentBlocked("Cloudflare D1 inventory ambiguous")
    matches = [db for db in databases
               if isinstance(db, dict) and db.get("name") == DB_NAME]
    if len(matches) != 1:
        raise ArtworkDeploymentBlocked("Existing artwork-only D1 database must be unique")
    dbid = matches[0].get("uuid")
    config = build_config(database_id=dbid, bucket=bucket)
    if _remote_objects(client, dbid) != ALLOWED:
        raise ArtworkDeploymentBlocked("Artwork-only D1 schema drift")
    result, _ = client.query(dbid, "select count(*) as total from artwork_shadow_candidates")
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0].get("total"), int):
        raise ArtworkDeploymentBlocked("D1 row count readback failed")
    if rows[0]["total"] < 0:
        raise ArtworkDeploymentBlocked("D1 row count invalid")
    return {"config": config, "existing_staged_rows": rows[0]["total"]}


def smoke_url(value: str) -> dict:
    """Only harmless unauthenticated refusals. Never send a synthetic valid stage."""
    url = parse.urlsplit(value)
    if url.scheme != "https" or url.username or url.password or url.port or url.query or url.fragment:
        raise ArtworkDeploymentBlocked("Worker smoke URL must be an HTTPS workers.dev origin")
    if not re.fullmatch(r"drop-rate-artwork-shadow\.[a-z0-9-]+\.workers\.dev", url.hostname or ""):
        raise ArtworkDeploymentBlocked("Refusing to probe any other Worker")
    origin = "https://" + url.hostname
    probes = (
        ("GET", "/public/artwork/no-such-public-route", None, 404),
        ("POST", "/v1/internal/artwork/shadow", b"{}", 401),
    )
    for method, path, body, expected in probes:
        req = request.Request(origin + path, method=method, data=body, headers={
            # Cloudflare workers.dev Browser Integrity Check can block Python-urllib's
            # default User-Agent with 403 before this Worker sees the request.
            # Identify the test client explicitly; do not bypass Cloudflare security.
            "User-Agent": "DropRate-Artwork-Shadow-Smoke/1.0 (GitHub-Actions)",
            "Content-Type": "application/json",
            "x-drop-rate-timestamp": "1000000000",
            "x-drop-rate-signature": "sha256=" + "0" * 64,
        })
        try:
            with request.urlopen(req, timeout=15) as response:
                status = response.status
        except error.HTTPError as exc:
            status = exc.code
        except (error.URLError, TimeoutError) as exc:
            raise ArtworkDeploymentBlocked("Worker not reachable for negative smoke") from exc
        if status != expected:
            raise ArtworkDeploymentBlocked(
                f"Worker negative smoke unexpected response: {method} {path} HTTP {status}"
            )
    return {
        "status": "PRIVATE_WORKER_NEGATIVE_HTTP_SMOKE_VERIFIED",
        "worker_host": url.hostname,
        "public_image_get": 404,
        "bad_signed_staging": 401,
        "image_bytes_written": 0,
        "d1_rows_written": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--smoke-url")
    args = parser.parse_args()
    if args.smoke_url:
        print(json.dumps(smoke_url(args.smoke_url), sort_keys=True))
        return
    if args.validate_only:
        output = {"status": "LOCAL_CONFIG_VERIFIED",
                  "worker": build_config(database_id="12345678-1234-1234-1234-123456789abc",
                                         bucket="test-media-bucket")["name"]}
    else:
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        token = os.environ.get("CLOUDFARE_D1_PILOT_TOKEN", "")
        bucket = os.environ.get("ARTWORK_R2_BUCKET_NAME", "")
        result = prepare(D1Client(account, token), bucket=bucket, account=account)
        CONFIG.write_text(json.dumps(result["config"], sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
        output = {"status": "EXISTING_D1_AND_R2_BINDING_CONFIG_VERIFIED",
                  "worker": WORKER, "artwork_d1": DB_NAME,
                  "existing_staged_rows": result["existing_staged_rows"],
                  "new_databases_created": 0, "media_published": False,
                  "supabase_writes": 0, "shopify_writes": 0}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
