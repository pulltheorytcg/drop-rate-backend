# Pricing continuation — 30 October 2026, 00:29 UTC

## Verified readback and coverage correction

The full physical denominator remains **67,066**. The corrected read-only query
returns **43,475 supported (64.8242%)**, **0 asking-only**, and **235 model-only**
records. The verified 89% threshold is **59,689**, leaving **16,214**.

PR #798 introduced `DROP_RATE_COMPUTED_MARKET_V1` rows in
`reference_catalogue_prices`. The older evidence SQL treated every positive
catalogue row as an external guide and returned 43,710. Those 235 model values
must be separate for this verified-source continuation; they are not new source
evidence. This correction changes only the evidence query, not application
display, founder-authorized calculations, catalogue records or the denominator.
The model join retains identity and two-day freshness/expiry checks. External
prices and validated asking evidence take precedence; expired model values
do not contribute to either supported or model-only totals.

Use [the corrected evidence SQL](evidence/market_coverage_20261029.sql).
Both the filtered verified-only form and the separate-model-bucket form
were executed read-only against production: 43,475 supported in each.
The latter additionally returns 235 model-only.

One additional permitted external guide since the 29 October 23:07 readback:
TCGdex / POKEMON_TCG / English / `ex15-88`, **GBP 2.39**,
`CARDTRADER_EXPANSION_ASKING`, observed 30 October 00:05:44 UTC.
This is an active-asking guide excluding shipping, not a sale or physical
valuation. Durable job `9375edff-e174-454c-a5ff-fb17cc1906a6` completed at
00:06:34 UTC: 63 provider calls, 30 sets, 4,336 references examined,
2,894 exact printing matches, one eligible quote, one actual write, zero
provider failures. These are CardTrader calls, not eBay Browse requests.
The 235 separate model writes belong to job
`b248de12-98b5-4861-9c5a-d7a60d976de0`.

## Cloud quota diagnostic and deployment

No active asking run existed before or after the diagnostic. The completed
worker was not restarted with its old acquisition command. Its command was
replaced with a quota-only call to existing `read_browse_quota` and
`quota_windows`, then its source was pinned to current main
`989d614a92fecbe7ae608cfa3a806a2d6f072fb8`.
PR #798's head `68cb654c78c533f9cb3219261829c9f6a94789e9` had all applicable
reported CI checks successful (production-readback intentionally skipped).

Existing worker service `6ddca000-0de6-4c73-9808-4f2e9fa755c8`,
production environment `6f00816c-b630-4d0b-bcc1-26ac71fa712d`:
deployment **`c3d64899-a3e7-4a89-ae05-d229e7b20c64` reached SUCCESS**.
Runtime diagnostic ID `pricing-quota-20261030-0033` recorded its actual
observation at **00:28:47 UTC** and output at 00:28:49 UTC.
The diagnostic identifier is only a label, not the observation timestamp.

Actual provider window: limit 5,000, count 1,070, remaining **3,930**,
reset **30 October 07:00 UTC**, time window 86,400 seconds.
The 500-request headroom leaves at most 3,430 in this observed window before
further external consumption. The local UTC-day allowance is **0/2,000**.
The unchanged global charged ledger is **2,030**. A later acquisition must
refresh quota and combine it with all durable reservation anchors again.

This operation performed **0 searches, 0 detail requests, 0 reference checks,
0 accepted prices and 0 price writes**. It called only the provider Analytics
quota endpoint (plus application authentication), with credentials retained
inside existing Railway variable references. No secrets were exported.

The worker remains one replica, no public endpoint, no cron, and
`restartPolicyType=NEVER`. Its configured command is now **quota-only**.
Do not blindly redeploy it expecting an acquisition batch. A justified future
acquisition needs a reviewed command, fresh unique run ID and checkpoint,
same English/apply scope and the appropriate saved resume run.

The API is independently deployed at
`1449b271-7e3b-4237-b7f1-39428ca6bf89` (SUCCESS), same main commit.
No API service settings were changed in this continuation.

## Why another identical Browse batch is held

All seven durable asking receipts were inspected. Latest acquisition remains
`503d9c3f-b368-498c-89b7-6ffef19be279`, completed 29 October 08:12:53 UTC,
INCOMPLETE / REQUEST_LIMIT, with 259 searches, 601 details, 945 references
scanned, 259 searches collected and **zero accepted/written estimates**.
Its process log and terminal deployment agree with the database receipt.

The repaired 1,000-request block comprised 327 searches and 673 detail GETs,
1,067 scanned references and zero accepted/written estimates. Latest receipt
has 258 insufficient-comparable rejections, 159 missing/conflicting language,
170 game mismatches, 133 set mismatches and 20 missing/conflicting finish.
These categories are not mutually exclusive price or reference counts.
Retained full-detail examples prove a lightly played card, missing finish,
and an explicitly prerelease set; they do not support weakening validation.

The five reviewed later-release aliases are now available in current main,
but the forward cursor is beyond those sets. Replaying them merely because
quota reset is not supported by retained positive comparable evidence.
DB/EB original-game-family and exact printing proof remain unresolved.
No new retrieval/identity repair was deployed or claimed in this check.

Preserve the saved forward cursor exactly:
`["Bandai Official","DRAGON_BALL_SUPER_MASTERS","English","428602:DB2-143.png"]`.
Preserve all failed/uncertain charges and immutable history. A future corrected
earlier-cohort retry must record this cursor and retain its prior charges.
Do not start an identical 1,000-request batch solely to consume available quota.

Permitted CardTrader/PokeWallet source pipelines continue within existing
limits and are still producing measured gains. The overall continuation
therefore remains useful; 89% is not reached. Resume Browse acquisition only
after a supported retrieval/identity improvement or source-quality evidence.
TCGCSV/TCGplayer reuse remains permission-blocked.

## Protected-state readback

At **00:29:20 UTC**: database **373,345,427 bytes**, below 400,000,000;
zero active asking runs; zero asking cache and history rows.
All **616 physical inventory rows** retain
`47a316ca0609fbbfedcd32f002c4c335`.
No inventory, ownership, acquisition costs, Store Prices, orders, settlement,
payout or Shopify writes were performed by this continuation.
