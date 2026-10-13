# Existing-provider identity coverage probe

The public Cardmarket export omits Pokemon collector numbers, so duplicate names
cannot be assigned a quote safely. The already connected CardTrader API exposes
blueprints and explicit Cardmarket cross-IDs. Before buying another feed or
enabling a mapping adapter, verify what those fields actually contain for the
high-gap English reference releases.

Revision 16 runs a bounded read-only probe in the existing Pokemon price pass.
It uses the existing CardTrader client/token without exposing credentials,
creating a service, reading inventory, buying capacity or enabling a new quote
source. At most ten API requests cover games, expansions and eight named Pokemon
sets: dp1, dp2, dp3, dp6, xyp, bwp, sv01 and swsh1. Each request has an eight-second
timeout. Credentials and provider exception messages never enter reports.

An exact full English set title must match a unique Pokemon expansion. Candidate
identity counts require one explicit collector number on each checklist, exact
card names across the reference/blueprint/Cardmarket product, and one positive
Cardmarket cross-ID pointing to a Pokemon single. All numbered blueprints count
toward ambiguity, including entries without cross-IDs. A region/title conflict
is not solved by fuzzy text, guessed numbers or price availability.

The receipt contains per-set data-shape counts and a few public product identity
examples. It writes **zero prices, references or mappings**. The ordinary price
refresh remains unchanged; diagnostics fail independently when the existing
provider is unavailable. Candidate counts are not coverage gains. Source data
must be reviewed before enabling any additional price assignment.

Primary contract: https://www.cardtrader.com/docs/api/full/reference

Regressions verify collision handling, source mismatches, bounded calls,
unchanged inputs, absence of quote writes and credential-safe errors.
