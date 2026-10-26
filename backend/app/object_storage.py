"""Optional S3-compatible cold storage for verified Drop Rate files.

This module never stores login details, inventory ownership or current prices.
It never deletes an object or a database row. All uploads are private by default;
public image delivery needs a separate rights and CDN approval workflow.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ObjectStorageError(RuntimeError):
    """A storage operation could not be verified; no cleanup is authorised."""


@dataclass(frozen=True, slots=True)
class ObjectStorageConfig:
    endpoint: str
    bucket: str
    region: str
    access_key_id: str
    secret_access_key: str
    prefix: str = "drop-rate"

    @classmethod
    def from_env(cls) -> ObjectStorageConfig | None:
        enabled = os.getenv("TCG_OBJECT_STORE_ENABLED", "false").strip().lower()
        if enabled in {"false", "0", "no", "off", ""}:
            return None
        if enabled not in {"true", "1", "yes", "on"}:
            raise ObjectStorageError("TCG_OBJECT_STORE_ENABLED must be true or false")
        names = (
            "TCG_OBJECT_STORE_ENDPOINT",
            "TCG_OBJECT_STORE_BUCKET",
            "TCG_OBJECT_STORE_REGION",
            "TCG_OBJECT_STORE_ACCESS_KEY_ID",
            "TCG_OBJECT_STORE_SECRET_ACCESS_KEY",
        )
        values = [os.getenv(name, "").strip() for name in names]
        if not all(values):
            missing = ", ".join(name for name, value in zip(names, values) if not value)
            raise ObjectStorageError(f"Missing object storage configuration: {missing}")
        prefix = os.getenv("TCG_OBJECT_STORE_PREFIX", "drop-rate").strip("/")
        config = cls(*values, prefix=prefix)
        config.validate()
        return config

    def validate(self) -> None:
        url = urlsplit(self.endpoint)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/"}):
            raise ObjectStorageError("Object storage endpoint must be a bare HTTPS origin")
        if not self.bucket or any(character in self.bucket for character in "/\\ \r\n"):
            raise ObjectStorageError("Invalid object storage bucket name")
        if not self.prefix or not all(char.isalnum() or char in "-_" for char in self.prefix):
            raise ObjectStorageError("Invalid object storage key prefix")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class S3ObjectStorage:
    def __init__(self, config: ObjectStorageConfig, *, client: Any = None):
        config.validate()
        self.config = config
        if client is None:
            # Import only for enabled storage, so existing deployments stay inert.
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=config.endpoint,
                region_name=config.region,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=5,
                    read_timeout=30,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        self.client = client

    def connectivity(self) -> None:
        """Verify bucket-scoped object listing without requiring account-level admin rights."""
        self.client.list_objects_v2(
            Bucket=self.config.bucket,
            Prefix=f"{self.config.prefix}/",
            MaxKeys=1,
        )

    def _verify_remote_file(self, key: str, expected_sha256: str, expected_size: int) -> None:
        """Read the *actual remote bytes*, not just untrusted ETag or metadata."""
        response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        digest = hashlib.sha256()
        size = 0
        body = response["Body"]
        try:
            for block in iter(lambda: body.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
                if size > expected_size:
                    raise ObjectStorageError("Remote object length differs from source")
        finally:
            body.close()
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise ObjectStorageError("Remote object failed byte-for-byte SHA-256 verification")

    def download_verified_file(self, key: str, target: Path, *, expected_sha256: str, expected_size: int) -> None:
        """Download a bounded private history object for typed restore verification.

        Only trusted worker-created paths and content-addressed history keys are
        accepted. Never use this as a public arbitrary-object download endpoint.
        """
        prefix = re.escape(f"{self.config.prefix}/reference-history/")
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or not isinstance(key, str)
                or not re.fullmatch(prefix + re.escape(expected_sha256) + r"\.(?:ndjson\.gz|manifest\.json|json)", key)):
            raise ObjectStorageError("Invalid private archive object identity")
        if type(expected_size) is not int or not 0 < expected_size <= 130_000_000:
            raise ObjectStorageError("Invalid bounded archive size")
        if target.exists() or target.is_symlink():
            raise ObjectStorageError("Archive download destination must be new")
        digest, size = hashlib.sha256(), 0
        response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        body = response["Body"]
        try:
            with target.open("xb") as output:
                for block in iter(lambda: body.read(1024 * 1024), b""):
                    size += len(block)
                    if size > expected_size:
                        raise ObjectStorageError("Downloaded archive length differs")
                    digest.update(block)
                    output.write(block)
            if size != expected_size or digest.hexdigest() != expected_sha256:
                raise ObjectStorageError("Downloaded archive failed SHA-256 verification")
        finally:
            body.close()

    def put_verified_file(
        self,
        path: Path,
        *,
        category: str,
        content_type: str,
    ) -> dict[str, str | int]:
        """Upload a content-addressed file, read back and verify; never delete.

        Files must be created and validated by trusted backend workers; do not
        accept arbitrary client paths or categories through HTTP endpoints.
        """
        if category not in {"reference-history", "exports", "private-media"}:
            raise ObjectStorageError("Unsupported private storage category")
        if not path.is_file() or path.is_symlink():
            raise ObjectStorageError("Source must be a regular file")
        digest, size = sha256_file(path)
        if size == 0:
            raise ObjectStorageError("Refusing to archive an empty file")
        suffix = "".join(path.suffixes)[-20:]
        if not suffix or any(character not in ".abcdefghijklmnopqrstuvwxyz0123456789" for character in suffix.lower()):
            raise ObjectStorageError("Invalid source file extension")
        key = f"{self.config.prefix}/{category}/{digest}{suffix.lower()}"
        # Reusing a digest key is idempotent, but still verify the remote bytes.
        try:
            self._verify_remote_file(key, digest, size)
        except ObjectStorageError:
            # An existing corrupted object must not be overwritten automatically.
            raise
        except Exception as exc:
            response = getattr(exc, "response", {})
            error_code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if str(error_code) not in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStorageError("Unable to establish remote object state") from exc
            with path.open("rb") as source:
                self.client.put_object(
                    Bucket=self.config.bucket,
                    Key=key,
                    Body=source,
                    ContentType=content_type,
                    Metadata={"sha256": digest},
                )
            self._verify_remote_file(key, digest, size)
        return {"key": key, "size_bytes": size, "sha256": digest, "verified": True}

    def put_verified_media(self, data: bytes) -> dict[str, str | int | bool]:
        """Upload a bounded, already decoded WebP to the *private* media area.

        Source ownership and reproduction rights must be checked by the caller;
        neither a successful upload nor an R2 object ever grants publication.
        """
        if not isinstance(data, bytes) or not 0 < len(data) <= 10_000_000:
            raise ObjectStorageError("Media bytes must be nonempty and at most 10 MB")
        if not data.startswith(b"RIFF") or data[8:12] != b"WEBP":
            raise ObjectStorageError("Only validated WebP media may be mirrored")
        digest = hashlib.sha256(data).hexdigest()
        key = f"{self.config.prefix}/private-media/{digest}.webp"
        try:
            self._verify_remote_file(key, digest, len(data))
        except ObjectStorageError:
            raise
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if str(code) not in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStorageError("Unable to establish private media object state") from exc
            self.client.put_object(
                Bucket=self.config.bucket,
                Key=key,
                Body=io.BytesIO(data),
                ContentType="image/webp",
                ContentDisposition="inline",
                CacheControl="private, max-age=3600",
                Metadata={"sha256": digest},
            )
            self._verify_remote_file(key, digest, len(data))
        return {"key": key, "size_bytes": len(data), "sha256": digest, "verified": True}

    def signed_media_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        """Temporary GET for one content-addressed media object, never a bucket.

        Returned URLs are bearer links for approved *public-facing* catalogue
        media only. Do not sign scans, archives or arbitrary client-supplied keys.
        """
        prefix = re.escape(f"{self.config.prefix}/private-media/")
        if not isinstance(key, str) or not re.fullmatch(prefix + r"[0-9a-f]{64}\.webp", key):
            raise ObjectStorageError("Refusing to sign an unrecognised media object key")
        if not isinstance(expires_seconds, int) or not 60 <= expires_seconds <= 3600:
            raise ObjectStorageError("Media link lifetime must be between 1 and 60 minutes")
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        destination = urlsplit(url)
        allowed = urlsplit(self.config.endpoint)
        if destination.scheme != "https" or destination.hostname != allowed.hostname:
            raise ObjectStorageError("Storage client produced an untrusted signed URL")
        return url


@lru_cache(maxsize=1)
def configured_object_storage() -> S3ObjectStorage | None:
    """One SDK client per app process; R2 configuration changes restart Railway."""
    config = ObjectStorageConfig.from_env()
    return S3ObjectStorage(config) if config else None

