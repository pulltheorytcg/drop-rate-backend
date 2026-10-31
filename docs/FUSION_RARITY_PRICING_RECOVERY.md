# Fusion World rarity and model recovery — 31 October 2026

The official Fusion World grid does not include rarity next to each image. The
previous importer therefore stored all Fusion World rarities as null, preventing
the existing ordinary common/uncommon model from finding eligible cohorts.

The importer now reads the official C and UC filters for each English/Japanese
FB booster checklist. It verifies the selected rarity, locale, exact set query,
and declared result count. Rarity is attached only when the full base-card ID,
name, number, source URL and image URL match the unfiltered checklist. Parallel,
promotional, cross-set and conflicting entries stay unresolved. A failed filter
holds that set's refresh, preserving the existing record for the next retry.

The 31 October review made 44 public publisher requests and verified 1,718 base
card rarity records. The compressed manifest is
`backend/data/fusion_official_rarity_20261031.json.gz`, SHA-256
`69208a53efbae3150b9a49b2fbf468655fdd244e0924cd08d401ec8961557aac`.
It contains identities and source-page hashes, without card rules text.

Reproduce from a current reference export with:

```sh
PYTHONPATH=backend python scripts/verify_fusion_rarity.py \
  --refs /path/to/fusion-base-refs.json --output /path/to/verified.json
```

The script does not write a database. Reviewed entries can be applied in bounded
batches with `fusion_official_rarity.WRITE_SQL`; it rechecks identity, blank
rarity, and the unmodified base variant. Replays do not overwrite records.
The daily importer reproduces the same evidence from the publisher's live lists.

Model revision 2 admits only Fusion World C/UC references with that exact bound
receipt. It retains the existing model: at least five independent, current,
same-set/language/rarity base-card peers; no model values as peers; an interquartile
spread no wider than threefold; a low-confidence estimate at the lower quartile.
Physical inventory and selling prices are unchanged. The separate £1 selling
minimum never inflates the model's market estimate.

A dry run against the reviewed snapshot found 486 unpriced base C/UC references,
of which 45 met the existing evidence requirements (20 English, 25 Japanese).
The other 441 had insufficient or too-variable same-set evidence. This recovery
does not declare the catalogue-wide 89% pricing target complete.
