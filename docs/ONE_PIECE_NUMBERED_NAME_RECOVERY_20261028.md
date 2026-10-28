# One Piece numbered source titles — 28 October 2026

## Problem and scope

The 17:05 UTC production One Piece receipt examined complete OP09–OP16
source sets. For OP09, six base products passed the existing release,
collision, number, rarity and subtype checks, but none passed the name check.
PokéWallet's official One Piece documentation shows names such as
`Roronoa Zoro (001)`. The publisher reference uses `Roronoa Zoro`.

This change accepts that precise three-digit suffix only for an English base
reference whose full printed number matches the source row. It also requires
an explicit Normal subtype and independent Cardmarket product title and HTTPS
single-card URL evidence for the same full number and base version. A generic
suffix stripper would erase alternate-art evidence and is deliberately avoided.

The original exact-name path is unchanged. Complete source pagination,
release identity, rarity, unique-printing resolution, current database identity,
write protection and the source quota remain in effect. Conflicting versions,
unknown competitors, parallel reference suffixes and Japanese references do not
gain a match through this new path. Source guides remain mixed-language
references, not sold comparisons or physical-copy valuations.

## Verification

Local Python collection: 7,825 cases, including 18 optional PGlite skips.
The first full run found 62 environment failures caused by a missing SOCKS
transport dependency in this workspace. Installing that local dependency and
rerunning those 62 cases passed; no application dependency changed.

Tests cover wrong numbers and characters, alternate-art labels, unknown and
duplicate products, missing subtype/title evidence, conflicting versions,
untrusted/malformed URLs, Japanese releases and parallel references.

Before release, require normal exact-head CI and the live read-only source
probe. A matching code path does not itself establish new priced references.

## Measured coverage

A live replay of the unchanged production coverage SQL still reports
43,277 / 67,065 physical references (64.53%): 16,411 more are needed for the
59,688 threshold. The eight-reference gain from the morning baseline belongs
to existing Dragon Ball jobs. Fresh 28 October Cardmarket One Piece exports
produced no new eligible candidates under the existing exact matchers.

The probe and post-release measurements will be recorded separately. No
coverage gain is claimed for this change until a normal source-backed write
and distinct-reference readback establish it.

Sources: [PokéWallet One Piece API](https://pokewallet.io/api-docs/one-piece),
[existing recovery contract](PRICING_89_PERCENT_RECOVERY_20261028.md).
