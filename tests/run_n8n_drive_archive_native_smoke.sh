#!/bin/sh
set -eu

# Build Dockerfile.n8n first. No image pull, real credentials or persistent mount.
DR95_SMOKE_IMAGE=drop-rate-n8n:ci
if [ "$#" -gt 0 ]; then DR95_SMOKE_IMAGE="$1"; fi
DR95_SMOKE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DR95_SMOKE_TLS="$(mktemp -d /tmp/drop-rate-dr95-tls-XXXXXX)"
trap 'rm -rf -- "$DR95_SMOKE_TLS"' EXIT HUP INT TERM
chmod 0700 "$DR95_SMOKE_TLS"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj '/CN=www.googleapis.com' \
  -addext 'subjectAltName=DNS:www.googleapis.com' \
  -keyout "$DR95_SMOKE_TLS/key.pem" -out "$DR95_SMOKE_TLS/cert.pem" \
  >/dev/null 2>&1
chmod 0400 "$DR95_SMOKE_TLS/key.pem" "$DR95_SMOKE_TLS/cert.pem"
docker run --rm --pull never --network none --user root --entrypoint node \
  --add-host www.googleapis.com:127.0.0.1 \
  --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --security-opt no-new-privileges \
  -e DROP_RATE_DR95_NATIVE_SMOKE=true \
  -v "$DR95_SMOKE_TLS:/fixture-tls:ro" \
  -v "$DR95_SMOKE_ROOT/tests:/source/tests:ro" \
  -v "$DR95_SMOKE_ROOT/automation/n8n/ops:/source/automation/n8n/ops:ro" \
  -v "$DR95_SMOKE_ROOT/automation/n8n/workflows:/source/automation/n8n/workflows:ro" \
  "$DR95_SMOKE_IMAGE" --no-warnings /source/tests/n8n_drive_archive_native_smoke.cjs
