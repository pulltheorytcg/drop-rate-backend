# DR95: disabled weekly private archive copier

`automation/n8n/workflows/dr-95-r2-drive-archive.json` is an **inactive,
credential-unbound** n8n 2.32.6 export. It copies only the two archive kinds
accepted by the separately disabled FastAPI transfer service:

- `REFERENCE_HISTORY`: immutable R2 history archives with the existing PostgreSQL restoration proof.
- `OPENLIBRARY_REVIEWED`: the fixed recovered factual source checkpoint and its evidence manifest.

Supabase remains the catalogue, ownership and pricing authority. The workflow
does not import records, calculate prices, mirror covers, modify rights, delete
R2 objects or authorize history cleanup. The **909 deferred Open Library records
remain held**; archiving their evidence does not approve them.

## Fixed destination and authentication

The intended Google account is `dropratetcg@gmail.com`. The only permitted parent
is folder `1NhFIsWesgxlf059UMdx65ps9kFMqQeO9`, named
`Drop Rate - Pricing History Archives`.

Before **every signed backend command**, DR95 makes actual OAuth requests to
Drive `about` and that folder's metadata. It requires the intended account,
matching account/owner permission IDs, one owner, no other permission, an
untrashed and unshared folder, and `canAddChildren=true`. The resulting evidence
gets its timestamp only after those responses pass. A stale timestamp routes
back through the real reads; it is never refreshed by changing the timestamp
alone. This includes a new destination check after the fresh file download and
before archive completion.

Google HTTP nodes use `googleDriveOAuth2Api`; the native Google Drive nodes use
type version 3 with `authentication: oAuth2`. **No credential ID or credential
secret is present in this export.** Missing or mismatched credentials fail the
run. The existing command secret signs `timestamp + '.' + exact JSON`; binary
readback carries that signed JSON as a bounded base64url header while its body
contains the downloaded bytes. The FastAPI service independently hashes those
bytes against its verified R2 manifest.

Raw JSON request nodes keep the exact signed request string and use response
autodetection with full response metadata. In pinned n8n 2.32.6, a raw request
forces a response stream; explicit JSON response mode does not consume that
stream, while autodetection parses the backend's JSON Content-Type. Strict
HTTP-status and `accepted` checks remain in place. DR91 needs the same separately
reviewed response-format correction before it can be used in production.

## Copy and retry sequence

For each manifest member, the serial workflow performs these steps:

1. Obtain one ID from Google's `files.generateIds`, then reserve it durably in
   R2 through `/reserve`. Use the ID returned by the reservation, including when
   a prior attempt or concurrent reservation wins.
2. Read that exact Drive ID. If it already exists, require the expected name,
   MIME type, private owner, sole parent, identity properties and complete size.
   An existing empty file is held for review. A nonempty mismatch is also held.
3. If absent, fetch the bounded verified R2 source through the signed backend.
   Check its returned length, source digest and actual bytes. Read the exact
   Drive ID again, then start a **resumable files.create** request containing the
   reserved ID, fixed parent and expected metadata. This is a creation request;
   the workflow contains no PATCH or native Update Content operation.
4. Accept only an HTTPS upload-session Location on exactly
   `www.googleapis.com/upload/drive/v3/files`, with the fixed `uploadType=resumable`
   and one bounded `upload_id`. Reject userinfo, fragments, additional parameters
   and other hosts/paths. Redirects are disabled. Send the already verified
   source bytes in one bounded PUT to that creation session. Resumable creation
   is used for small and large members, avoiding a second upload protocol.
5. A creation conflict returns to exact-ID metadata checks. A matching existing
   complete file proceeds to native **Download** without a write. The actual
   downloaded bytes must match the immutable SHA-256 and size whether or not
   Google supplied a checksum. A mismatch holds the run for review.
6. Read file ownership, parent, privacy and identity properties again after
   download; refresh account/folder evidence; send those actual downloaded
   bytes to `/verify-readback`. Advance the member checkpoint only after the
   backend returns its durable verified object receipt.
7. Call `/complete` after all members. Require the expected manifest, member
   count and immutable completion receipt before invoking DR91. DR91 uses a
   stable per-archive idempotency key. Archives listed as
   `RECORDED_BYTES_VERIFIED` replay `/complete` and that same DR91 receipt, so a
   failed notification after a successful copy is retried. Their bytes are not
   recopied. This is historical evidence; **current Drive availability is not
   assessed by replaying a prior completion**.

Google documents that pre-generated IDs support upload retries and that a
successful creation returns `409 Conflict` on subsequent retries, preventing
duplicate files: [upload retry contract](https://developers.google.com/workspace/drive/api/guides/manage-uploads#use_a_pre-generated_id_to_upload_files)
and [generated IDs](https://developers.google.com/workspace/drive/api/guides/create-file#generate_ids_to_use_with_your_files).
The same [upload guide](https://developers.google.com/workspace/drive/api/guides/manage-uploads#resumable)
documents starting a resumable creation with metadata, then uploading bytes to
its returned session URI. The current [files.update reference](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update)
and upload guide do not document an `If-Match` media-update guarantee; DR95 does
not assume one.

The pinned native [upload node](https://github.com/n8n-io/n8n/blob/n8n@2.32.6/packages/nodes-base/nodes/Google/Drive/v2/actions/file/upload.operation.ts)
cannot supply the reserved ID, so creation uses bounded Google HTTP nodes.
Readback uses the pinned native [download operation](https://github.com/n8n-io/n8n/blob/n8n@2.32.6/packages/nodes-base/nodes/Google/Drive/v2/actions/file/download.operation.ts).
An interrupted session is retried through the same durable reserved ID; an
existing incomplete/empty resource remains held. Real Google behavior for this
case still belongs in the bounded OAuth pilot.

## Bounds and continuation

The export schedules Sunday at 04:15 in `Europe/London` when eventually activated.
It also includes a manual review trigger. Both require the exact runtime opt-in
`DROP_RATE_DRIVE_ARCHIVE_ENABLED=true`. The backend separately requires
`TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED=true`.

Each run permits at most **40 listing pages, 32 objects and 32,000,000 source
bytes**. A single object is limited to **16,000,000 bytes**. The workflow stops
between units after its 600-second working budget; the hard execution timeout
is 900 seconds. Requests have explicit timeouts, and the native Google operations
are covered by the workflow's hard timeout.

Both source kinds are scanned. A page with no recognized archives still follows
`next_cursor` while `has_more=true`. Cursors remain opaque listing tokens and are
passed unchanged to FastAPI; they are never used as object keys or URLs. Blocked
archives, including oversized members, contribute to an `INCOMPLETE` report and
cannot become a complete or no-work claim.

A normal budget stop returns `INCOMPLETE` and saves the current page, archive
index and next member index in `dr95_checkpoint` workflow static data. This
allows a large archive to continue on the next scheduled run. A full scan resets
both cursors for the next sweep, so newly created objects that sort earlier are
not permanently missed. Metadata-only `dr95_last_run` retains the latest status,
counts and a bounded sample of blocked manifest digests even though execution
data saving is disabled. It contains no credentials, HMACs, URLs, source bytes
or downloaded bytes.

n8n saves workflow static data only for successful production executions. A
normal `INCOMPLETE` budget result ends normally to preserve that checkpoint;
it does not send an archive success receipt. Hard failures use DR90, leave the
previous checkpoint in place, and safely retry through the durable backend
reservations/receipts. Manual editor runs do not establish persisted resume
behavior. Test that behavior in the disposable pinned runtime before activation.

All success, failure, manual and progress execution-data saving is disabled in
the DR95 export. DR91 and DR90 retain their independently reviewed definitions;
they inherit instance execution-save defaults. Before enabling DR95, require
`EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` and
`EXECUTIONS_DATA_SAVE_ON_ERROR=none`, or separately reviewed equivalent settings
on those child workflows. A parent save setting does not govern a child receipt
workflow, which also temporarily handles a signature. Binary transport remains necessary during execution. Pinned
[BinaryDataConfig](https://github.com/n8n-io/n8n/blob/n8n@2.32.6/packages/core/src/binary-data/binary-data.config.ts)
defaults to filesystem storage for regular execution mode and database storage
for queue mode; deployment configuration and disposal of temporary binary data
must be checked in the actual runtime smoke. The export does not change them.

## Verification and current limit

The offline Node suite executes the exact committed Code-node sources with
synthetic Google/backend responses. Its 15 cases cover missing opt-in,
account/folder privacy, fresh evidence, empty pages and both kinds, bounds,
partial-member resume, reservation reuse, strict upload Locations, creation
conflicts, empty-file holds, source/download SHA checks, durable completion and
replaying a missing DR91 receipt. Five additional harness cases enforce fixture
immutability, isolated child environment, owned-temp cleanup, fake OAuth/HMAC
checks and create-only mock behavior. These offline cases pass locally.

### Pinned runtime gate

After building `Dockerfile.n8n` as `drop-rate-n8n:ci`, run:

```sh
sh tests/run_n8n_drive_archive_native_smoke.sh drop-rate-n8n:ci
```

The test-only wrapper uses Docker `--network none`, a fresh ephemeral TLS
certificate and `www.googleapis.com` mapped to a loopback mock. It never mounts
persistent n8n state. The child receives a minimal environment and a synthetic
OAuth credential imported only into its new SQLite database. Its reviewed
Code-node sources, settings and nontrigger graph remain unchanged. The only
workflow fixture mutations replace the schedule/manual triggers with a private
random-path webhook and bind the synthetic credential. DR91 is imported exactly
as reviewed; the child instance sets execution saving to `none`.

The harness requires three automatic executions. Two synthetic 16 MB members
hit the real unchanged 32 MB working budget, persist a metadata checkpoint,
and resume after the n8n process restarts. It then completes both archive kinds
and performs a sweep that replays existing completion/DR91 receipts without
another upload. The mock independently checks exact signed bodies, reserved
IDs, source/upload/native-download/readback bytes and receipt order. The test
observes actual filesystem binary storage during transfers and requires no
saved execution rows, node data or binary files after each successful run.

A successful native result is named `NATIVE_SYNTHETIC_DR95_VERIFIED`, with
`real_google_api_verified=false`, `real_oauth_verified=false` and
`production_backend_verified=false`. The synthetic manifests/bytes exercise
transport, bounds and item linking; they do not establish production archive
eligibility, Google concurrency semantics, account access or real R2 receipts.
The fixture deliberately uses loopback TLS and synthetic ownership evidence.

**The pinned native runtime gate passed on 2026-10-27 at 15:01:41 UTC** in
[PR #759's dedicated CI job](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40526508462/job/122267448635),
at commit `dd49785ecc6e0a035ab37a897a46855b331c6cca`. The result was
`NATIVE_SYNTHETIC_DR95_VERIFIED`: three automatic runs, one runtime restart,
three archives and seven objects. Native download, resumable creation, binary
disposal, durable static-data resume and completion-receipt replay all passed;
temporary-state cleanup completed. The checked DR95 definition hash was
`0fda958802b80f28a3675869137347994c5c1efb23177c4764837104ef9efbc5`.
The exact corrected DR91 definition was pinned to
`1687b41a0f99a4ef27f1c1ad99c07bbbbe2aa0d68d959670dd6670ef40055568`.
The result explicitly reports real Google API, real OAuth and production
backend verification as **false**. Independent source/fixture review found no
additional concrete blocker.

Deliberate binding of the verified OAuth credential, production child-retention
settings and one bounded actual create/download/readback with a durable backend
completion receipt remain activation gates. DR90 and DR91 must be published
with their verified definitions and receipt paths proven; the fixture does not
repair or activate either stored production workflow. No activation,
production credential binding, Drive write or source-rights change is included
in this implementation.
