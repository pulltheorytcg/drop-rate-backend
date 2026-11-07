# Auction Lens video acceptance corpus and performance gate — 7 November 2026

**Status: Ready to run against permitted, human-labelled footage. No measured real-device performance is claimed.**

The first experimental Auction Lens pilot exists separately in draft [PR #983](https://github.com/pulltheorytcg/drop-rate-backend/pull/983). This independent QA harness does **not** touch its branch, alter its feature flags, capture third-party streams, or change FastAPI/database data. It measures actual evidence as soon as rights-cleared, labelled video observations have been collected.

## What gets measured and why

Use \`python backend/scripts/auction_lens_video_acceptance.py path/to/results.jsonl\` after a run of the authorised video lab (or subsequent iPhone signed pilot). The script reports:

- **Exact-print precision:** correct exact identity / all claimed exact identities; wrong exact-print matches are always blocking.
- **Coverage:** correct exact matches / all examples with a known target printing; abstention counts against coverage, not precision.
- **Median and nearest-rank p95 latency:** real elapsed milliseconds per labelled scene, not mocked network timings.
- **No stale lot:** mismatched scene generations and old answers displayed after a lot transition.
- **No unsafe market value:** price shown for an ineligible/stale source, non-exact item, or without authorised footage.
- **Cohort breakdown:** English/Japanese Pokémon, One Piece, graded, sealed, comics, manga, blur, mirror, multiple items, confusing reprints, no collectible and lot changes.

Default **proposed, not achieved** release gates are 100 independent labelled cases, exact precision ≥99.5%, supported-case coverage ≥75%, p95 ≤4000ms, and zero wrong-exact, stale-result, unsafe-price or unauthorised-source cases. Tune thresholds only after review; don't lower them to force a green result. The existing auction proposal's median <2s is an additional goal to inspect.

## Minimal privacy-preserving JSONL schema

One JSON object **per line**. Only these keys are accepted; the harness refuses extra keys so raw screenshot URLs, names, emails and video payloads cannot be accidentally put in reports:

\`\`\`json
{"case_id":"fictional-case-001","cohort":"english_pokemon_raw","expected_identity":"pokemon:example-print:english:normal","returned_identity":"pokemon:example-print:english:normal","decision":"EXACT","elapsed_ms":850,"expected_generation":3,"returned_generation":3,"price_displayed":false,"market_value_eligible":false,"source_authorised":true,"lot_changed_during_request":false}
\`\`\`

Identifiers are QA pseudonyms, not user or seller identifiers. The example is fictional and is **not** a performance result. If the item cannot be identified by a human reviewer, set expected_identity to null and decision appropriately; do not borrow a nearby printing. If market evidence is missing, market_value_eligible=false and price_displayed=false.

## Pilot protocol

1. Obtain rights-cleared, owner-created footage from the Drop Rate live-selling setup or separately authorised sources. Preserve consent/usage approval outside the manifest. Do not silently capture or bulk-download Whatnot/eBay.
2. Use the private \`/auction-lens-lab\` on the PR #983 test environment, never activate an unapproved third-party production capture. Obtain verified benchmark labels from an independent reviewer. Record timing from clear stable crop to final on-screen result.
3. Record a unique case per auction *lot*, including deliberately repeated identical cards, scene transitions, wrong variants, English/Japanese, blurry images, lighting glare, sleeves, graded labels and no-match footage. Use separate cohorts for unsupported categories; gate per supported cohort before extending support.
4. Preserve only this metadata manifest and aggregate metrics in CI evidence. Video files stay in approved private storage and do not enter Git, automatic logs, or AI-training stores.
5. Run the script with gate thresholds and record its JSON result and source coverage. Independently verify with real iPhone: screen permission revoked mid-session, protected content, device background, 30-minute power/thermal, network loss and signed app viability. The script is **not** a replacement for these device tests.

**Failure modes:** false positive instead of abstention, future/stale generation results, a reference guide mislabelled as current UK sold Market Value, missing delivery/buyer charges, excessive latency, silently captured audio, leaking chat/seller personal data. Address each before launch.

**Rollback:** no migrations, no production flags, no service changes. Remove this standalone tool/CI if necessary. Video test evidence remains private.
