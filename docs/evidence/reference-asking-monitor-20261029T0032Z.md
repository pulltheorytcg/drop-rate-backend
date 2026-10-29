# Pricing monitor — 29 October 2026 00:32 UTC

Decision: leave active batch running; no restart, overlapping worker, new provider probe or database mutation.

Read current BUILD_STATUS.md, REFERENCE_ASKING_BACKFILL.md and REFERENCE_ASKING_CLOUD_RUNNER.md. Main tree inspected at 993bbc31be2ad2e9c52e1ced88c2eca274acb4a4; no newer asking runbook found.

## Evidence

- Railway service 6ddca000-0de6-4c73-9808-4f2e9fa755c8 has one deployment c40c993b-1335-4582-83f3-ea6d46224834, SUCCESS, pinned 0b8a89d60d29117923ebe111872397bd5129f100. Config: English apply, max 1000, one replica, restart NEVER, unique original checkpoint, no predeploy command, no cron; deployment URL null. No secrets exported.
- Run ce1f435a-3a1c-4a94-889d-8fe887da7147 is RUNNING with no finish time. Charges advanced 727 -> 770 -> 801, proving active progress. At 00:31:40: 769 collected, 3698 scanned, 382 summaries, zero matched/written. Saved cursor [Bandai Official, DRAGON_BALL_SUPER_MASTERS, English, 428016:BT16-091_PR.png]. Database cursor remains authoritative.
- At 00:32:16: all-time ledger 831; UTC-day charges 801; local allowance remaining 1199. Three earlier pilot receipts remain present, 10 charges each, zero accepted prices. No reset or ledger mutation.
- At 00:31:08, direct asking cache count 0 and history count 0.
- Full-denominator SQL from docs/evidence/market_coverage_20261028.sql aggregated with unchanged eligibility at 00:31:29: 43454/67065 = 64.7939%. Asking tables empty, so combined coverage is identical. Target 59688, gap 16234.
- Database size 372960403 bytes, below 400000000 guard by 27039597 bytes.
- Inventory count 616 and full-row snapshot 47a316ca0609fbbfedcd32f002c4c335 match the pre-batch receipt.
- Saved worker quota observation at session 700: limit 5000, provider count 710, provider remaining 4290, conservative remaining 4250, global anchor 730, headroom 500, reset 2026-10-29 07:00 UTC. This is the active worker's provider observation, not a separate fresh quota call; subsequent charges must be deducted. Worker continues periodic refreshes.

## Zero-yield gate

At 769 collected: 2928 unresolved parallels excluded before search; all 769 searches lacked sufficient comparables. Summary rejection counts: language 128, game 114, slab 86, name 24, set 14, multi-item 11, number 5. Low retrieval yield and missing identity evidence are evident; this does not prove a validation defect. Bounded saved examples are insufficient primary-source proof for a fix.

Before another identical 1000-check batch, inspect final receipt/process exit and investigate persistent zero yield. Require primary-source proof, regression tests, normal CI and reviewed deployment for genuine fixes. Prefer permitted exact source mapping. Never weaken identity, condition, language, shipping, seller independence or freshness. TCGCSV/TCGplayer remains permission-blocked.

A later safe continuation must preserve scope/apply mode and cursor using --resume-run, fresh run ID and unique checkpoint, >=1000 remaining local daily requests, provider windows/headroom, 1 request/second, 45-minute deadline and capacity guard. Do not overlap an active/uncertain worker. Verify persisted writes and inventory again at completion. No target attainment is claimed. Monitoring remains enabled because the batch is still active; no user action is required by this interim receipt.
