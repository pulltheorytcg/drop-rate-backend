# Operational D1 cloud-only disaster recovery

9 November 2026. **Inactive engineering candidate. No real operational backup, export, off-site copy or restore has been verified from this change.** Gates A/H remain incomplete; Supabase remains authoritative.

## Verified starting position

Main `5cbe287f88ad9cf2db6d6d2f1bc4002689b4f88b` contains #1037's local verifier and #1038's replay recovery. Main CI 42659821712/42659821718 passed, with protected staging skipped. Preceding release: Railway API `69915f2b-314f-4d3e-bdd6-4f61fa7985fd` and n8n `39eb4721-24b7-4f51-b5d7-4d619e965225` independently ACTIVE/successful; live/ready passed. These are preceding-release receipts, not deployment evidence for this candidate.

Existing R2: private EU bucket `drop-rate-private`. Both pages under `drop-rate/exports/` were reviewed through authenticated UI; source archives/manifests exist, but no named standalone SQLite backup was identified. This is not a search of every bucket key, and ndjson is not SQLite. No new export initiated.

**Actually created Drive folder:** [Drop Rate – Operational D1 Backups](https://drive.google.com/drive/folders/1LrbyYjb5dkYPQehmN0q-IKIsmBFcH_pg), ID `1LrbyYjb5dkYPQehmN0q-IKIsmBFcH_pg`, sibling of the pricing archive in My Drive. Authenticated UI showed `dropratetcg@gmail.com` as sole owner and general access **Restricted**. No upload occurred. Browser verification is not cloud OAuth/API permission evidence. Original pricing folder is unchanged.

## Implemented route

1. `d1_operational_cloud_backup.py`: documented SQL export API for only the existing account and operational shadow name. Its actual UUID must come from separately signed source evidence and match live metadata. The client exposes only metadata/bookmark reads and export; no SQL mutation, remote restore or delete. Identical bookmarks before, throughout polling and after download are mandatory. Internal maintenance can advance bookmarks without data changes; conservative rejection is intentional. The existing replay single-writer concurrency group is reused.
2. SQL stays in memory and reconstructs an empty memory-only SQLite database. Attachments, virtual/temp objects, unsafe PRAGMAs and extensions are denied; CPU, pages, statements and file sizes are bounded. **Missing/changed schema is never synthesized.** Exact tracked DDL, every independently pinned table count/full-row digest and the existing restore verifier must pass. D1 export is SQL, not a standalone SQLite guarantee; lost triggers, changed DDL, precision loss or mixed generation must stop the release.
3. Separately signed source approval binds the generation ID/SHA, actual D1 UUID, schema fingerprint, all tracked table fingerprints, trusted evidence-run URL/SHA and approval timestamp. Its Ed25519 signer must differ from the backup writer and be independently controlled. Never derive this approval from the writer's backup. Existing nine-table receipts alone do not contain all new metadata-table digest pins; a fresh independent attestation remains required.
4. Completed SQLite bytes receive their file SHA256, then AES-256-GCM encryption with a random 96-bit nonce. Associated data binds source approval, file identity, key ID, execution and retention. The writer-signed manifest includes the separately signed source approval. Ciphertext and manifest keys are calculated from actual byte hashes under `drop-rate/operational-d1-backups/v1/`, then conditionally created and independently read back. A durable execution binding cannot be overwritten. An orphan/partial object stays incomplete and retained for review.
5. Existing DR95 transport gains separately disabled `OPERATIONAL_D1_SQLITE`: only ciphertext + original signed manifest, both signatures checked, distinct pinned operational folder, actual OAuth/owner-only permission checks, generated-ID reservation, create-only upload, fresh Google download and independent backend SHA/size verification of every member. Completion proves a dated copy, not whole-system recovery or perpetual availability. Original pricing/archive modes remain unchanged by default.
6. `d1_operational_cloud_restore.py`: protected cloud runner reads exact R2 ciphertext/manifest, checks independently retained manifest/file/generation pins and signatures, decrypts and runs the unchanged verifier in SQLite memory. Private immutable receipt identifies the GitHub verifier run; safe status/hash metadata only in logs.
7. `d1_operational_drive_restore.py`: independently reads exact Google file IDs, live account/folder/file permissions and immutable properties, downloads fresh bytes and repeats memory-only restore. It needs **no Cloudflare credential or connection**, so recovery is possible during Cloudflare account loss. Actual recovery still requires outside-Cloudflare key custody, IDs and pins. It emits only safe hash/boolean metadata in attributable GitHub logs.

The verifier retains its 64 MB file, 100,000 restored-row and 32-generation bounds. Existing Drive ciphertext cap remains 16,000,000 bytes; larger snapshots fail. Coverage is **nine operational source tables and exact tracked shadow/replay metadata**, not all 150 relations, artwork or live D1 atomicity. Unsupported nonempty tables fail. Replay journals/high-water marks are checked, but cloud reports explicitly retain `interrupted_generation_resume_executed=false`; a separate real interrupted-generation resume drill remains outstanding.

## Security and release blockers

Live Cloudflare readback after saving and refreshing confirms bucket-lock rule `operational-d1-backups-30d`: prefix `drop-rate/operational-d1-backups/v1/`, 30 day(s), Enabled. Existing media/archive prefixes and the default multipart-abort rule are unchanged. No objects were exported or uploaded by this metadata change. The EU bucket also reports Data Access Logs unavailable for jurisdictional buckets; end-to-end attributable job/transfer receipts and access-event coverage remain required.

No encryption/signing keys, cloud credentials, export/restore/transfer enable flags, protected environments or recurring jobs were configured.

- Independent source signer: separate trusted read-only capture and Ed25519 key unavailable to the writer. Retain the signed evidence independently of backup bytes. A signature proves the configured signer, not that an operator performed an independent capture.
- Writer: dedicated export access for the reviewed shadow; separately managed AES and signing keys; short-lived R2 session scoped to backup objects/prefix. Restore: no export token/writer signing key; session scoped to exact approved objects and create-once receipt paths. Code requires a session and fixed EU endpoint, but TTL/permission verification is a separate release obligation.
- Google: separate approved OAuth credential, actual API identity/permission reads, no tokens sent to backend and no R2 credentials in n8n. Browser login does not bind this credential.
- Key recovery: approved independently protected cloud key store/broker outside Cloudflare, plus retained public trust roots, manifest/file/generation pins and actual Drive file IDs. A ciphertext with lost keys is not DR. Do not generate secrets into source/logs or extract browser credentials.
- Retention: propose an initial protected restore point of at least 30 days, then approve RPO/RTO and recurrence using measured change rate/size/cost. **No automatic deletion exists.** The scoped R2 lock is enabled for 30 days; independently verify it remains active for actual object timestamps and the approved retention date. Administrative removal remains possible, so this is not immutable protection against a compromised account administrator. Verify Google access/retention separation; and recovery without the primary account. Conditional PUT and a manifest retention date are not administrative WORM or proof these protections exist.
- Cloud runners: hosted ephemeral Linux only; swap/core dumps disabled; operational SQL/SQLite only in process memory. No public backup artifacts, caches, shell tracing or provider error logging. Runner teardown discards memory; Python does not guarantee zeroization of every immutable byte copy. Local engineering tests contain synthetic data only.

## Manual release and incident procedure

The new workflow runs synthetic tests on PR/push. All operational jobs require **manual main dispatch, operation-specific enable flag, exact commit AND run approval, offline success and distinct protected environment**. No recurring schedule exists. A merge cannot export or transfer operational data. The Drive-only restore job receives no Cloudflare secrets.

Before first export, discover any already-approved backup; otherwise independently measure D1 size/read usage/account plan/export outage, R2/Drive requests/storage and runner cost. Cloudflare export temporarily blocks requests. Prepare separate signed source evidence, actual lock/key/credential policy and cost/security approval SHA references. Approve only the exact export SHA/run with a chosen retention date. Do not bypass protected import budgets. Writer status deliberately remains `R2_BYTES_VERIFIED_OFFSITE_AND_INDEPENDENT_RESTORE_PENDING`.

Independently retain the actual produced manifest/file hashes; approve a distinct R2 restore run using those pins. Review/import the updated stored DR95 definition (normal startup never overwrites existing workflows), verify Google OAuth/permissions and DR90 error handling, then approve the exact operational n8n execution. Backend requires both `TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED` and `TCG_OPERATIONAL_D1_DRIVE_TRANSFER_ENABLED`, exact `TCG_OPERATIONAL_D1_DRIVE_FOLDER_ID`, and source/writer public keys. n8n additionally requires `DROP_RATE_DRIVE_ARCHIVE_ENABLED`, `DROP_RATE_OPERATIONAL_D1_ARCHIVE_MODE` and `DROP_RATE_OPERATIONAL_D1_ARCHIVE_APPROVED_EXECUTION_ID`. Keep source workflow inactive until reviewed; operational mode uses separate resume state and rejects scheduled executions without their own exact ID approval.

Only after both Drive members have fresh download receipts, retain their actual IDs/pins outside Cloudflare and approve `restore-drive-existing`. A cloud credential broker supplies its short-lived Google token; the tool neither requests nor stores refresh tokens. Archive attributable run/log hashes and private final receipts. Recurrence, cost limits and RPO/RTO require separate approval after both real restores and controlled failure/notification drills. **Current automation: manual-only, disabled.**

Failures exit nonzero with fixed sanitized errors; GitHub marks failure and DR95 uses existing DR90 while saving no binary execution data. Real alert delivery still needs a controlled drill. No recipient was configured or messaged. Permission drift, hash failures, partial transfer or missing approvals never produce completed DR status.

Rollback: leave flags unset/false, stop operational DR95 mode and preserve all restore points. Revoke only newly issued sessions through the approved issuer if necessary. Revert code through a reviewed PR; existing stored n8n definitions remain untouched by normal startup. No production data rollback is needed for an inactive code release. Never test restoration by overwriting production or invoking destructive Time Travel.

## Acceptance still outstanding

The empty private Drive folder and scoped 30-day R2 lock are verified. Actual R2 SQLite key/file SHA, independent new source attestation, encrypted artifact, Drive backup file IDs/readback SHA, real cloud export/restore receipt, key custody/Google retention/access-event controls, interrupted-generation recovery and approved recurrence remain **unverified**. Folder creation is complete; it is not a backup. Synthetic tests/deployment do not close Gates A/H or authorize retirement.

## Primary references checked 9 November 2026

- [D1 SQL export API, polling/bookmark and one-hour download](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/export/)
- [Export request blocking and numeric precision limitations](https://developers.cloudflare.com/d1/best-practices/import-export-data/)
- [Bookmark read API](https://developers.cloudflare.com/api/resources/d1/subresources/database/subresources/time_travel/methods/get_bookmark/)
- [Time Travel and internal bookmark advances](https://developers.cloudflare.com/d1/reference/time-travel/)
- [R2 scoped temporary credentials](https://developers.cloudflare.com/r2/api/s3/temporary-credentials/)
- [Google generated-ID retry safety](https://developers.google.com/workspace/drive/api/guides/create-file#generate-ids)

Reuse: `D1_OPERATIONAL_LOCAL_RESTORE_DRILL_20261109.md`, `R2_GOOGLE_DRIVE_ARCHIVE_TRANSFER.md`, `R2_DRIVE_N8N_WORKFLOW.md`.
