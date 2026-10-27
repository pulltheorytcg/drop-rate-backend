# Private R2 to Google Drive archive transfer

Status: backend prepared and mounted, disabled by default, no live transfer or publication.
The DR-95 workflow draft is a separate deliverable. A Google Drive OAuth
credential for the intended account must be connected and independently checked
before a live pilot. The 27 October 2026 n8n metadata inspection completed with
no stored `googleDriveOAuth2Api` or `googleApi` credentials; that inspection did
not rule out unrelated generic OAuth credentials.

## Destination and scope

The only destination is `dropratetcg@gmail.com`, folder
`1NhFIsWesgxlf059UMdx65ps9kFMqQeO9`, named **Drop Rate - Pricing History Archives**.
The workflow must fetch Google `about.user` and the exact folder metadata using
the bound OAuth credential. It checks the authenticated email, owner permission
ID, folder ID/name/type, owner, non-trashed status, owner-only permissions and
private sharing state. A credential display name or caller-supplied folder
string is insufficient. Signed destination evidence expires after five minutes;
refresh the actual Google reads during a longer run.

Supported archive kinds are:

| Kind | Source allowed by the backend |
| --- | --- |
| `REFERENCE_HISTORY` | Content-addressed manifests under `reference-history/`, with the existing `drop-rate-reference-history-postgres-json-gzip-v2` schema, complete original snapshot identity and `POSTGRES_TEMP_TABLE_EVERY_FIELD_V1` restore proof. The member archive and original manifest are both required. |
| `OPENLIBRARY_REVIEWED` | The fixed `openlibrary-reviewed-20261027-v1` checkpoint under `exports/`, matching the reviewed source commit and all 14 existing path/role/raw-size/raw-SHA pins. All compressed members and the original manifest are required, for 15 objects. Source gzip bytes are also decompressed and checked against the independently pinned raw SHA/size before transfer. |

Disposable catalogue input caches, media, arbitrary exports, other buckets,
caller-selected object keys and caller-selected download URLs are unsupported.
No copy operation changes catalogue data, imports, prices, rights or inventory.
No Drive receipt authorizes R2 deletion or historical database cleanup.

## Deployment boundary and operational stop

`backend/app/drive_archive_api.py` exports a router with its **full** prefix:

```text
/api/v1/automation/commands/storage/drive-archive
```

The router is mounted directly in `main.py`, alongside the existing
automation-command router. It is not nested beneath that router's prefix.
It requires both `TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED=true` and the existing
enabled/configured private object storage. Its dedicated flag defaults false.
Setting either flag false stops new transfer commands. No repository-wide
automation pause/kill flag was found in the existing command/settings paths;
the established command families have their own feature gates.

All requests require the existing automation command secret and timestamp HMAC.
The backend never supplies its R2 credentials to n8n, and n8n never supplies its
Google credential or OAuth token to the backend. There are no unauthenticated
download URLs or presigned archive URLs. Use the existing fixed API origin and
fixed Google API endpoints; disable redirects on the signed API HTTP nodes.

## Signed request contract

All endpoints use POST. JSON commands sign the exact request-body bytes with the
existing contract:

```text
X-Drop-Rate-Timestamp: <Unix seconds>
X-Drop-Rate-Signature: sha256=<HMAC-SHA256(secret, timestamp + '.' + raw JSON)>
```

The existing verifier permits a five-minute timestamp skew. Each action has a
distinct literal, so a signed body cannot be replayed as a different operation.
Unknown JSON model fields are rejected. Commands require:

```json
{
  "schema_version": 1,
  "action": "<exact action from table>",
  "execution_id": "<n8n execution ID>",
  "occurred_at": "<current timezone-aware ISO timestamp>",
  "kind": "REFERENCE_HISTORY",
  "destination": {
    "account_email": "dropratetcg@gmail.com",
    "account_permission_id": "<actual Google about.user.permissionId>",
    "folder_id": "1NhFIsWesgxlf059UMdx65ps9kFMqQeO9",
    "folder_name": "Drop Rate - Pricing History Archives",
    "folder_mime_type": "application/vnd.google-apps.folder",
    "folder_trashed": false,
    "folder_shared": false,
    "folder_owner_email": "dropratetcg@gmail.com",
    "folder_owner_permission_id": "<actual matching Google owner permission ID>",
    "permission_roles": ["owner"],
    "checked_at": "<timestamp of actual Google preflight reads>"
  }
}
```

| Endpoint | Action | Additional input | Successful response |
| --- | --- | --- | --- |
| `/plan` | `PLAN_DRIVE_ARCHIVE_COPY` | `cursor` null/opaque previous cursor; `limit` 1–2 | `archives`, `blocked_archives`, `has_more`, `next_cursor`, `scan_scope: PAGE`. Each archive supplies its kind/manifest SHA/ID, dated copy status and member SHA/expected size/name/MIME/role. |
| `/reserve` | `RESERVE_DRIVE_ARCHIVE_FILE` | `manifest_sha256`, `object_sha256`, `proposed_file_id` from Google `files.generateIds` | `file_id`, `file_name`, `app_properties`. Always use the returned ID, including after a competing reservation or retry. |
| `/object` | `READ_DRIVE_ARCHIVE_OBJECT` | `manifest_sha256`, `object_sha256` | Binary bytes, exact `Content-Length`, `X-Drop-Rate-Content-SHA256`, safe attachment name, `Cache-Control: no-store`, and `nosniff`. The source is staged to a bounded temporary file and SHA/size checked before response. |
| `/verify-readback` | `VERIFY_DRIVE_ARCHIVE_READBACK` | Binary body; signed metadata envelope described below | `status: BYTES_VERIFIED`, object SHA, size, reserved Drive ID, verification time and immutable receipt SHA. |
| `/complete` | `COMPLETE_DRIVE_ARCHIVE_COPY` | `manifest_sha256` | `status: ARCHIVE_COPY_RECORDED`, archive ID, manifest SHA, count of verified objects, completion time and receipt SHA. The backend discovers and checks every expected member receipt itself. |

JSON responses also include `accepted: true` and `execution_id`.

### Binary readback

The HTTP body must be the **fresh Google Drive Download node's binary output**.
It must not be the earlier R2 response or a metadata checksum.

Put the exact verification JSON envelope in `X-Drop-Rate-Command` as unpadded
base64url. Sign the decoded envelope bytes with the same timestamp/HMAC contract.
The envelope has the common fields, source manifest/member SHA, and:

```json
{
  "drive_file": {
    "id": "<reserved Google file ID>",
    "name": "<reserved exact file name>",
    "parents": ["1NhFIsWesgxlf059UMdx65ps9kFMqQeO9"],
    "owner_email": "dropratetcg@gmail.com",
    "owner_permission_id": "<authenticated owner permission ID>",
    "shared": false,
    "trashed": false,
    "mime_type": "<exact expected member MIME type>",
    "size_bytes": 12345,
    "app_properties": {
      "drSchema": "drive-copy-v1",
      "drKind": "REFERENCE_HISTORY",
      "drManifest": "<manifest SHA-256>",
      "drObject": "<member SHA-256>"
    }
  }
}
```

The workflow obtains these fields through actual Google file metadata reads.
The backend checks the fixed destination, exact reservation and immutable
properties, then hashes/counts the incoming binary stream. It records success
only when those independently computed values equal the authoritative source
manifest. The receipt method is deliberately named
`BACKEND_SHA256_OF_N8N_DRIVE_DOWNLOAD_V1`: the backend independently verifies
bytes while the pinned trusted workflow supplies the authenticated Drive read.
The backend does not claim to hold or independently exercise Google OAuth.

## Retry-safe workflow sequence

1. Perform the actual OAuth account/folder preflight.
2. Iterate `/plan` for both allowed kinds. For each pending member, call Google
   `files.generateIds`, then `/reserve` **before any Google file creation**.
3. Inspect the exact reserved Google ID. Hold any existing empty or mismatching
   file. An existing complete file must match the owner, parent, name, MIME,
   size and immutable app properties before its contents are downloaded.
4. If absent, fetch and verify the bounded R2 bytes, check that the reserved ID
   is still absent, then initiate a resumable **files.create** with that ID,
   name, properties, MIME and fixed parent folder. Upload only to the strictly
   validated Google session URI with redirects disabled. A Google 409 causes
   another read of that same ID; no update/PATCH operation is allowed.
5. Native Drive **Download** by the reserved ID; pass its fresh binary data to
   `/verify-readback`. A matching metadata checksum alone never completes a
   copy. The download bytes must independently match the manifest SHA and size.
6. After all members including the original manifest have verified receipts,
   call `/complete`. Only its accepted durable completion may lead to DR-91.

Native n8n 2.32.6 **Upload** does not expose a caller-supplied file ID. DR95 uses
the Google upload API's documented pre-generated-ID creation flow and the
native Download node. Repeated successful creation at the same ID returns 409
without duplicating the file. The workflow never creates an empty placeholder
and later overwrites it; incomplete existing resources remain held for review.

R2 reservations and copy receipts use atomic `PutObject` with `If-None-Match: *`
and actual readback. A losing reservation receives the existing winner's Drive
ID. Retries cannot create a second binding, overwrite a receipt or silently
promote a partial copy to a completed archive.

Existing `/automation/control/receipt` deduplicates on
`(owner_id, job_type, idempotency_key)` and never changes an earlier stored
result. Use a deterministic **successful** archive/destination key for DR-91;
failures retain distinct per-execution DR-90 keys. Reusing one business key for
a failure and its later success would retain the original failure row.
An already recorded archive replays idempotent `/complete` and the same DR-91
success key, recovering a crash between durable completion and notification.

## Pagination, backlog and incomplete runs

The opaque cursor is versioned, bound to the archive kind, and represents a
fixed-prefix listing position. It is not an object-read capability. It safely
advances past unrelated exports and is independent of the manifest/member
allowlist. Legacy and canonical history-manifest names are deduplicated.

Always continue while `has_more=true`, including pages with `archives=[]` or
only already-recorded copies. Preserve the next cursor at a workflow budget
stop and label that run **INCOMPLETE**; resume it rather than repeatedly reading
the first page. After reaching the end of a kind, reset its cursor for the next
complete sweep, since newly created immutable hashes can sort before an old
cursor. Check both kinds before declaring a whole sweep finished.

`blocked_archives` is distinct from no work. Oversized entries include their
manifest-declared size and the current transfer limit; missing/corrupt members
fail their transfer and cannot create a completion receipt. A budget stop,
blocked source or incomplete pagination must not become a success/no-backlog
claim. Copy status `RECORDED_BYTES_VERIFIED` is explicitly dated evidence, not
a fresh claim that Google still retains the file. The backend reports
`drive_current_availability: NOT_ASSESSED` on every planning response.

The existing `archive_backlog` check concerns live PostgreSQL history only.
An empty live-history table is never evidence of a Drive backup. No new code
changes that check or the guarded historical cleanup path.

## Bounds and activation evidence

| Resource | Limit |
| --- | --- |
| One transferred object | 16,000,000 bytes |
| Archive manifest read | 256,000 bytes |
| One immutable copy-control record | 64,000 bytes |
| JSON command read | 65,536 bytes; 10 seconds |
| Encoded binary verification envelope | 8,192 bytes |
| Binary readback | Exact expected member length; 120 seconds |
| SDK read chunks | 65,536 bytes, bounded file staging |
| In-flight storage threads | 2, retained until the actual worker ends even after caller timeout |
| One listing call | 40 keys |
| One planning page | At most 2 recognised bundles |

The 16 MB cap is conservative. It is not evidence that all live R2 history
members fit. Before activation, inspect every planned manifest's sizes; the
backend checks actual R2 ContentLength, byte count and SHA before each transfer.
Larger valid archives remain explicitly blocked until their bounded transport
limit is reviewed.

Offline verification includes actual reviewed-source producer output through
the real storage uploader into a synthetic bucket, not only a manually built
manifest. Further release evidence must include the correct OAuth identity,
folder privacy, a bounded real pilot with independent download bytes, retry
after interruption, existing-file 409 handling, error routing and the complete
immutable receipt. Keep DR-95 inactive and credential bindings absent until
these checks are satisfied. Do not save workflow binary payloads, signatures,
OAuth responses or provider error bodies in execution data or logs; use only
bounded sanitized status/identifier/checksum summaries.

## Primary API references

- [Google Drive: generated IDs and retry behavior](https://developers.google.com/workspace/drive/api/guides/create-file#generate-ids)
- [Google Drive files resource metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)
- [n8n HTTP Request: predefined credentials and binary file requests](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/)
- [Pinned n8n 2.32.6 Drive upload implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/Google/Drive/v2/actions/file/upload.operation.ts)
- [Pinned n8n 2.32.6 Drive update implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/Google/Drive/v2/actions/file/update.operation.ts)
- [Pinned n8n 2.32.6 Drive download implementation](https://github.com/n8n-io/n8n/blob/n8n%402.32.6/packages/nodes-base/nodes/Google/Drive/v2/actions/file/download.operation.ts)
- [Cloudflare R2 conditional create-once writes](https://developers.cloudflare.com/r2/api/s3/extensions/)
