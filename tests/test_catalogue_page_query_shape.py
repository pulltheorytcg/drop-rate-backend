"""Catalogue page price lookups stay bounded by the cards on the page.

On 28 Nov 2026 a 41-card Pokemon page spent 5.5 s in the asking-price lookup
(to return no rows) and 0.46 s in the price-history lookup, because PostgreSQL
planned each as one flat join and walked whole sets per requested card. Both
now read the requested cards by primary key in MATERIALIZED steps. These checks
pin that shape and the eligibility rules it must not change; the real SQL is
executed in tests/reference_asking_postgres.py and the shared-reference,
catalogue-maintenance and R2-cache PostgreSQL tests.
"""
from app.catalogue_price_history import HISTORY_SQL
from app.reference_asking_display import (
    ASKING_DISPLAY_SQL, ASKING_SETS_SQL, asking_cache_join,
)
from app.uk_eu_reference_display import MODEL_DISPLAY_SQL


def flat(sql):
    return " ".join(sql.split())


def test_asking_lookup_reads_page_cards_first_and_only_those_with_a_cached_ask():
    sql = flat(ASKING_DISPLAY_SQL)
    assert sql.startswith("with wanted as materialized (")
    assert "r as materialized ( select w.key,card.* from wanted w join tcg.reference_cards card" in sql
    assert "using(provider,system_code,language,provider_id) where exists (select 1 from tcg.reference_asking_prices cached" in sql
    # The outer query starts from that small set, never from the whole catalogue.
    assert "from r join tcg.reference_sets s using(provider,system_code,language,set_id)" in sql
    assert "from wanted w join tcg.reference_cards r" not in sql
    assert sql.endswith("where a.provider_id is not null")


def test_asking_lookup_counts_printing_groups_over_whole_sets_of_the_page_only():
    sql = flat(ASKING_DISPLAY_SQL)
    # Narrowed to the page's sets; the count itself is still over every card
    # ("other") of each of those sets, so no group count can change.
    assert "from tcg.reference_cards other join ( select distinct provider,system_code,language,set_id from r ) asking_sets" in sql
    assert flat(ASKING_SETS_SQL) not in sql
    assert "a.evidence->'reference_group_count'=to_jsonb(asking_groups.reference_group_count)" in sql


def test_shared_eligibility_is_unchanged_for_the_other_callers():
    default = flat(asking_cache_join())
    assert flat(ASKING_SETS_SQL) in default
    assert "from tcg.reference_cards cached_ref join tcg.reference_asking_prices cached" in default
    page = flat(asking_cache_join(sets_sql="select distinct provider,system_code,language,set_id from r"))
    # Everything after the set scope - identity, evidence, sample and freshness
    # rules - is the same text for every caller.
    marker = ") asking_sets using(provider,system_code,language,set_id)"
    assert default.split(marker)[1] == page.split(marker)[1]
    for rule in ("a.method_version='EBAY_UK_RAW_ASK_V1' and a.currency='GBP'",
                 "a.listing_count>=3 and a.seller_count>=3 and a.seller_count<=a.listing_count",
                 "a.evidence->>'condition'='Near Mint'",
                 "a.expires_at<=a.observed_at+interval '3 days'",
                 "'finish',r.finish,'rarity',r.rarity"):
        assert rule in default and rule in flat(ASKING_DISPLAY_SQL)


def test_page_clock_is_the_only_time_source_in_the_asking_lookup():
    sql = flat(ASKING_DISPLAY_SQL)
    assert "now()" not in sql
    assert sql.count("$2::timestamptz") == 3 and sql.count("$1::jsonb") == 1


def test_model_lookup_inherits_the_bounded_shape_and_adds_its_two_price_joins():
    sql = flat(MODEL_DISPLAY_SQL)
    assert MODEL_DISPLAY_SQL != ASKING_DISPLAY_SQL
    assert sql.startswith("with wanted as materialized (") and "r as materialized (" in sql
    assert "select r.key,a.*,a.snapshot_id as source_snapshot_id,r.evidence as reference_evidence," in sql
    assert "left join tcg.reference_market_prices m on" in sql
    assert "left join tcg.reference_catalogue_prices b on" in sql
    assert sql.endswith("where a.provider_id is not null")


def test_history_lookup_reads_page_cards_by_primary_key_before_joining_sets():
    sql = flat(HISTORY_SQL)
    assert sql.startswith("with k as materialized (")
    assert "r as materialized ( select k.key,card.provider,card.system_code,card.language,card.provider_id," in sql
    assert "from k join tcg.reference_cards card using(provider,system_code,language,provider_id) )" in sql
    assert "from r join tcg.reference_sets s using(provider,system_code,language,set_id) cross join lateral (" in sql
    # Unchanged rules: released sets only, positive value, older than seven days.
    assert ("where (s.release_date is null or s.release_date<=current_date) and prices.market_value_minor>0 "
            "and prices.pricing_updated_at<$2::timestamptz-interval '7 days'") in sql
    assert sql.count("$1::jsonb") == 1 and sql.count("$2::timestamptz") == 1
