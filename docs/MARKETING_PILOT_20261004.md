# Drop Rate creative and runtime test — 4 October 2026

## Scope and outcome

**Latest founder direction:** the newly rendered intro artwork was rejected.
Reuse the earlier conversation's designs for publication testing and keep
Higgsfield creative development separate. Do not schedule this intro artwork.
The Instagram and TikTok upload-validation drafts remain unscheduled and are
tagged `Rejected — do not publish`. Buffer's delete action is permanent, so the
drafts were labelled instead. YouTube accepted the Short in its composer, but it
was closed without saving a draft or scheduling; an unfinished composer recovery
item may remain. Queue and Sent counts were both zero on the final read-back.

Earlier image-generation records are recovered (see `BUFFER_CONNECTION_HANDOFF.md`),
but the files themselves are in `/workspace/scratch/6cfb63b411e7/generated_images/`
on the older durable host. A current read returned that host unavailable; the
browser route to the ChatGPT conversation returned an unauthenticated session.
The preferred earlier images must be made accessible before exact reuse. Their
illustrative price labels must remain; do not turn sample prices into claims.

Current target: Instagram, TikTok and YouTube, three stories per day adapted into
nine posts. Earlier five-platform and static YouTube plans are superseded.
This test is one brand introduction; it is not a researched news story or proof
of the whole unattended marketing loop. No daily publishing schedule is active.

Recovered and merged PR #512's existing DR-31 editorial preparation, research
playbook and template direction into PR #513. DR-31 still prepares slide text from
supplied evidence. It does not research, render, approve, store or publish content.

## Finished test media

- Four original 1080×1350 static slides and separately composed 1080×1920 slides.
- Native fixed-layout renderer: `automation/creative/drop-rate-intro.jsx`.
- Owned Drop Rate logo, navy/cyan/gold/cream palette and geometric decorations.
  No third-party card art, illustrative prices or invented market claims.
- The founder's previously approved take is reused verbatim: Higgsfield job
  `96af3017-1307-4d18-b738-5715476529a6`, custom voice `Drop-Rate-Founder`.
- Final Short: 1080×1920 H.264/AAC, 14.783 seconds, no music.
- Caption verification: 29/29 authored words, transcription similarity 0.9655;
  start/middle/end frames inspected. Full decode passed. Video stream 14.766667s,
  audio 14.783s; the approved voice tail is retained.
- Final confirmed Higgsfield media: `dc9d23d5-55b8-48b5-ad6c-57881989f6aa`.
- Clean master: `515610f0-73a2-4d3f-b30b-a68489c698b3`.
- Static assets archive: `ee192240-4ae3-4474-9158-ea10bd0cde06`.
- Contact sheet: `1c2d43ed-69a8-48ce-99c4-952e3f4bb031`.

These technical pilot designs have been rejected for publication. Rendering
happened through the connected Higgsfield media tools;
it is not yet a background n8n renderer. The caption helpers on the hosted
runtime were installed under `video-montage/scripts`, not `subtitles/scripts`.
The verified clean-caption burner was used with Montserrat, size 11, margin 43.

## Verification

- 36 targeted Python checks passed: editorial preparation, Buffer connection,
  queue and additive provisioning.
- 30 Node checks passed, including four new isolated-runner tests for completed
  execution proof, fail-closed output, production-secret/database isolation and
  workflow hash mismatch.
- GitHub Actions run `37175299478`, commit
  `38ff81759a23d31cbfecb20770dc55788f335b45`: backend, dashboard and n8n image passed.
- Buffer browser inspection confirmed all three expected channels connected and
  zero scheduled posts before this test. Instagram and TikTok four-image uploads
  were accepted by the composer with Automatic selected. Composer acceptance is
  not proof that the platform has published anything.

## Verified private n8n runtime check — 05:19 BST

`automation/n8n/runtime-smoke.mjs` runs the reviewed DR-32 read-only queue workflow
using n8n's CLI in a fresh temporary database. It substitutes a manual entry
trigger only for that isolated copy. Production SQLite, workflow definitions,
automation signing secrets and database credentials are not copied. Only the
existing Buffer key is passed to the read-only request. Raw execution output is
captured privately; the report allows only fixed status/count fields.

`build-runtime-smoke-command.mjs` packages the exact workflow and a SHA-256 into
a one-off Railway pre-deploy command. It contains no credential values. This
route avoids installing another automation platform or exposing the editor.

The founder explicitly approved the restart after the earlier approval prompt
did not reach them. The first deployment (`4ffef59b-0489-4143-8ddc-c228dc113352`)
replayed the old deployment's configuration and only repeated the prior Buffer
connection check. Railway redeploy reuses that deployment's configuration;
apply reviewed staged changes to run a new pre-deploy command instead.

The actual isolated workflow test on deployment
`0fd9bf67-9c46-4705-9f0b-e105dbca8ff3` reached the final Code node but returned
`buffer_response_invalid`. n8n 2.32.6 uses a response stream when the request body
is raw, while its explicit full JSON response path expects a string or object.
Changed both generated Buffer HTTP nodes to JSON request mode, keeping the same
queries and validators. Also enabled privately captured info-level CLI output:
n8n emits `--rawOutput` through its info logger. Only fixed status/count fields
and allowlisted failure codes are printed by the wrapper.

**Passed:** deployment `0970b4f3-da52-4f43-8155-ed8a8a731aaa` ran the corrected
DR-32 workflow from 04:18:52.685 to 04:19:00.400 UTC (05:19 BST). Its safe report:

```json
{
  "ok": true,
  "isolated_database": true,
  "queue_complete": true,
  "queue_empty": true,
  "scheduled_posts": 0,
  "all_connections_ready": true,
  "channels_total": 3,
  "channels_ready": 3,
  "counts": {"scheduled": 0, "sending": 0, "error": 0, "needs_approval": 0, "draft": 2},
  "publishing_verified": false,
  "automatic_posting_active": false
}
```

Workflow SHA-256: `2c42132ca30a70320b9e721ef0396432201d377bf8f21846c563233aecb63be9`.
The deployment remains on unchanged production main
`21a02f3bd2c1b09aa94cc45ad12ec0a78dcbafe1`; the test workflow was imported only
into its disposable database. PR #513 is not merged and this test did not import
or activate the fixed workflow in the persistent production database.

Afterwards the pre-deploy command was removed and its timeout restored to 30.
Railway reports SUCCESS, Online, one running replica, zero crashed replicas,
zero service issues and no pending work. No social posts were sent or scheduled.
Changed-code validation: 33 Node tests and 2 Python wrapper tests passed.

A successful read-only test must not be reported as successful publishing.
Full delivery still needs the real publisher and durable publication claims,
then per-channel Buffer and platform read-back. Do not blindly retry an ambiguous
publication or treat a saved draft as a delivered post.

## Remaining end-to-end work

The governed background research/creator discovery, approved creative renderer,
publication ledger and publisher, same-time scheduling, delivery reconciliation,
engagement ingestion and traffic/conversion attribution remain unproved. The
goal is still the full loop. These checks do not establish unattended readiness.
