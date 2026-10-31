"""Bounded official CardTrader expansion-wide *asking* guides for missing cards.

One permitted expansion API request covers up to thousands of source offers.
Only exact, unambiguous catalogue printings with three independent Near Mint
English sellers may receive an indicative GBP asking guide. No sold prices,
physical inventory, ownership, Shopify or store prices are changed.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from uuid import uuid4

from .cardtrader_client import CardTraderApiError
from .cardtrader_market_adapter import (
    _bundle_size, _on_vacation, _price, _quantity, _seller, _to_gbp_minor,
)
from .cardtrader_media import _collector_number
from .access_control import require_platform_admin
from .db import user_connection
from .masters_cardtrader_market import (
    SINGLE_CATEGORIES as MASTERS_CATEGORIES,
    blueprint_rarity, number_key as masters_number, official_printing, rarity_key,
)
from .one_piece_market import normalized
from .pokewallet_one_piece_market import WRITE_SQL
from .pokemon_cardtrader_market import (
    SINGLE_CATEGORIES as POKEMON_CATEGORIES,
    blueprint_card_name, blueprint_number_key, cardtrader_release_titles,
)
from .cardtrader_reference_probe import number_key as pokemon_number
from .reference_applicability import POCKET_RELEASES
from .reference_sealed import normalized as source_normalized

SOURCE = "CARDTRADER_EXPANSION_ASKING"
JOB = "CARDTRADER_EXPANSION_GUIDES"
REVISION = 8
MIN_SELLERS = 3
MAX_PRICE_SPREAD = Decimal("3")
MAX_SETS_PER_RUN = 30
LOT_HINT = re.compile(
    r"\b(?:lot|bundle|playset|multipack|multi-pack|set of [2-9]\d*|"
    r"pack of [2-9]\d*|[2-9]\d*\s*(?:cards?|copies)|"
    r"[x×]\s*[2-9]\d*|[2-9]\d*\s*[x×])\b", re.I)

READ_SQL = """select r.provider,r.system_code,r.language,r.provider_id,
 r.name,r.set_id,r.card_number,r.rarity,r.finish,r.image_url,r.evidence,r.source_url,
 s.declared_card_count,s.name as set_name,
 (coalesce(p.market_value_minor,0)>0 and
  p.pricing_updated_at>=now()-interval '7 days') as has_detail,
 (coalesce(b.market_value_minor,0)>0 and
  b.pricing_updated_at>=now()-interval '7 days') as has_catalogue,
 coalesce(b.market_value_minor,0)>0 as has_any_catalogue,
 b.quotes->0->>'source' as existing_catalogue_source
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 where r.language='English'
 and ((r.provider='Bandai Official' and r.system_code='DRAGON_BALL_SUPER_MASTERS')
   or (r.provider='TCGdex' and r.system_code='POKEMON_TCG'))
 and (s.release_date is null or s.release_date<=current_date)"""


def missing(ref):
    return (not ref.get("has_detail") and not ref.get("has_catalogue")
            and (not ref.get("has_any_catalogue") or
                 ref.get("existing_catalogue_source") == SOURCE))


def missing_artwork(ref):
    return (ref.get('provider') == 'TCGdex' and ref.get('system_code') == 'POKEMON_TCG'
            and ref.get('language') == 'English' and not str(ref.get('image_url') or '').strip())


def masters_printings(refs, blueprints, expansion, categories):
    """Map full official checklists to blueprint IDs; variants block collisions."""
    by_ref, by_blueprint = defaultdict(list), defaultdict(list)
    families = {m[1] for r in refs
                if (m := re.match(r"(BT\d+)-\d+", str(r.get("card_number") or "")))}
    code = str(expansion.get("code") or "").upper()
    family = code if code in families else next(iter(families)) if len(families) == 1 else None
    if not family:
        return {}
    for ref in refs:
        by_ref[masters_number(ref.get("card_number"), None)].append(ref)
    unnamed = set()
    for bp in blueprints:
        if (bp.get("game_id"), bp.get("expansion_id")) != (expansion["game_id"], expansion["id"]):
            continue
        if bp.get("category_id") not in categories:
            continue
        number = masters_number(_collector_number(bp), family)
        if number is None:
            unnamed.add(normalized(bp.get("name")))
        by_blueprint[number].append(bp)
    result = {}
    for number, group in by_ref.items():
        possible = by_blueprint.get(number, [])
        if not number or not possible or any(rarity_key(r.get("rarity")) is None for r in group):
            continue
        if any(blueprint_rarity(bp) is None for bp in possible):
            continue
        for rarity in {rarity_key(ref.get("rarity")) for ref in group}:
            refs_of_rarity = [r for r in group if rarity_key(r.get("rarity")) == rarity]
            bps_of_rarity = [bp for bp in possible if blueprint_rarity(bp) == rarity]
            identity = official_printing(refs_of_rarity)
            if not identity or len(bps_of_rarity) != 1:
                continue
            name, members = identity
            bp = bps_of_rarity[0]
            collector = str(_collector_number(bp) or "").strip().upper()
            if (type(bp.get("id")) is not int or bp["id"] <= 0
                    or not re.fullmatch(r"(?:BT\d+-)?\d+[A-Z]{0,3}", collector)
                    or normalized(name) != normalized(bp.get("name"))
                    or normalized(name) in unnamed):
                continue
            for ref in members:
                result[ref["provider_id"]] = bp["id"]
    return result


def pokemon_printings(refs, blueprints, expansion, categories):
    """Only complete, unique collector-number/name pairs; never infer an alt art."""
    if refs[0]["set_id"] in {"g1", "sma"}:
        # Generations and Hidden Fates need special partition/scope checks;
        # their existing Cardmarket identity bridge covers that separately.
        return {}
    declared = refs[0].get("declared_card_count")
    if type(declared) is not int or declared <= 0 or len(refs) < declared:
        return {}
    by_ref, by_blueprint = defaultdict(list), defaultdict(list)
    for ref in refs:
        by_ref[pokemon_number(ref.get("card_number"))].append(ref)
    for bp in blueprints:
        if ((bp.get("game_id"), bp.get("expansion_id")) !=
                (expansion["game_id"], expansion["id"]) or
                bp.get("category_id") not in categories):
            continue
        by_blueprint[blueprint_number_key(bp, expansion)].append(bp)
    result = {}
    for number, group in by_ref.items():
        candidates = by_blueprint.get(number, [])
        if number is None or len(group) != 1 or len(candidates) != 1:
            continue
        ref, bp = group[0], candidates[0]
        prefix = ref["set_id"] + "-"
        if (type(bp.get("id")) is not int or bp["id"] <= 0 or
                not ref["provider_id"].startswith(prefix) or
                pokemon_number(ref["provider_id"][len(prefix):]) != number or
                normalized(ref["name"]) != normalized(blueprint_card_name(bp)) or
                (("◇" in ref["name"]) != ("◇" in blueprint_card_name(bp)))):
            continue
        result[ref["provider_id"]] = bp["id"]
    return result


def exact_printings(system, refs, blueprints, expansion, categories):
    if system == "DRAGON_BALL_SUPER_MASTERS":
        matched = masters_printings(refs, blueprints, expansion, categories)
    elif system == "POKEMON_TCG":
        matched = pokemon_printings(refs, blueprints, expansion, categories)
    else:
        return {}
    # An upstream duplicate source id is never grounds to share a market quote
    # between unrelated cards. Two official leader faces are the sole exception.
    by_blueprint = defaultdict(list)
    for ref in refs:
        blueprint_id = matched.get(ref["provider_id"])
        if blueprint_id:
            by_blueprint[blueprint_id].append(ref)
    result = {}
    for bp_id, group in by_blueprint.items():
        if len(group) > 2 or (len(group) == 2 and system != "DRAGON_BALL_SUPER_MASTERS"):
            continue
        for ref in group:
            result[ref["provider_id"]] = bp_id
    return result


def _signature(properties):
    """Every distinct foil/edition surface must agree before choosing a quote."""
    keys = ("foil", "reverse", "edition", "stamp", "holo", "finish", "parallel")
    return tuple(sorted((str(k), str(v).casefold()) for k, v in properties.items()
                        if any(flag in str(k).lower() for flag in keys)))


def confirmed_single_unit(row, counts, *, verified_single_blueprint=False):
    """Handle the two documented unit fields without treating a multipack as one.

    CardTrader marketplace responses may omit the legacy bundle_size field,
    while exposing bundled_quantity. Only explicit one-unit evidence is valid.
    An explicit multi-unit bundle always wins over any conflicting fallback.
    A missing pair of unit fields is accepted only when the caller has already
    proven the product is an unambiguous official single-card blueprint and
    the seller did not describe a lot. Such a guide remains catalogue-only.
    """
    primary = _bundle_size(row)
    supplementary = row.get("bundled_quantity")
    if primary == 1:
        counts["confirmed_bundle_size_one"] += 1
        return True
    if primary is None:
        counts["bundle_size_missing_or_invalid"] += 1
    elif primary == 0:
        counts["bundle_size_zero"] += 1
    else:
        counts["bundle_size_multiple"] += 1
    if type(supplementary) is int and supplementary == 1:
        counts["bundled_quantity_one"] += 1
        if primary in (None, 0):
            counts["single_unit_fallback_confirmed"] += 1
            return True
    elif supplementary is None:
        counts["bundled_quantity_missing"] += 1
    else:
        counts["bundled_quantity_not_one"] += 1
    if primary is None and supplementary is None and verified_single_blueprint:
        description = row.get("description") or ""
        tag = row.get("tag") or ""
        if (isinstance(description, str) and len(description) <= 2000
                and isinstance(tag, str) and len(tag) <= 250
                and not LOT_HINT.search(description + " " + tag)):
            counts["single_blueprint_unreported_unit_accepted"] += 1
            return True
        counts["seller_lot_description_or_invalid"] += 1
    return False


def eligible_seller_offers(rows, blueprint_id, expansion_id, *, diagnostics=None,
                           verified_single_blueprint=False):
    """Return eligible rows; GBP-normalised seller deduplication happens later."""
    offers = []
    all_signatures = set()
    counts = defaultdict(int)
    for row in rows:
        counts["source_offers"] += 1
        if row.get("blueprint_id") != blueprint_id:
            counts["wrong_blueprint"] += 1
            continue
        if row.get("graded") is not False:
            # A missing graded flag is unknown, not evidence of a raw card.
            counts["graded_or_unconfirmed"] += 1
            continue
        if _on_vacation(row):
            counts["unavailable_seller"] += 1
            continue
        if not confirmed_single_unit(
                row, counts, verified_single_blueprint=verified_single_blueprint):
            counts["not_confirmed_single_unit"] += 1
            continue
        if _quantity(row) < 1:
            counts["no_available_quantity"] += 1
            continue
        expansion = row.get("expansion")
        if isinstance(expansion, dict) and expansion.get("id") != expansion_id:
            counts["wrong_expansion"] += 1
            continue
        properties = row.get("properties_hash")
        if not isinstance(properties, dict) or properties.get("condition") != "Near Mint":
            counts["condition_not_near_mint"] += 1
            continue
        if any(value is True for key, value in properties.items()
               if any(flag in str(key).lower() for flag in ("signed", "altered", "proxy"))):
            counts["signed_or_altered"] += 1
            continue
        if any(str(value).strip().casefold() not in {"en", "english"}
               for key, value in properties.items() if "language" in str(key).lower()):
            counts["different_language"] += 1
            continue
        price = _price(row)
        user_id = _seller(row).get("id")
        if price is None or type(user_id) is not int or user_id <= 0:
            counts["invalid_price_or_seller"] += 1
            continue
        all_signatures.add(_signature(properties))
        if type(row.get("id")) is not int or row["id"] <= 0:
            counts["invalid_listing_id"] += 1
            continue
        offers.append((user_id, price, row["id"]))
    counts["qualified_offers"] = len(offers)
    counts["qualified_distinct_sellers"] = len({row[0] for row in offers})
    counts["finish_signatures"] = len(all_signatures)
    if diagnostics is not None:
        diagnostics.update(counts)
    if len(all_signatures) != 1 or len({row[0] for row in offers}) < MIN_SELLERS:
        return []
    return offers


async def asking_guide(ref, blueprint_id, expansion_id, rows, fx_provider, observed,
                       fx_cache, *, diagnostics=None, verified_single_blueprint=False):
    offers = eligible_seller_offers(rows, blueprint_id, expansion_id,
                                    diagnostics=diagnostics,
                                    verified_single_blueprint=verified_single_blueprint)
    if len(offers) < MIN_SELLERS:
        return None
    per_seller = {}
    for seller, (minor, currency), listing_id in offers:
        if currency not in {"EUR", "GBP", "USD"}:
            continue
        if currency not in fx_cache:
            fx_cache[currency] = (await fx_provider.quote(
                base_currency=currency, quote_currency="GBP", at=observed)).validate()
        fx = fx_cache[currency]
        amount = _to_gbp_minor(minor, fx)
        if amount > 0:  # Market evidence can be below the separate £1 selling floor.
            row = (amount, seller, listing_id, minor, currency)
            prior = per_seller.get(seller)
            if prior is None or row < prior:
                per_seller[seller] = row
    amounts = sorted(per_seller.values())
    if diagnostics is not None:
        diagnostics["independent_sellers_with_positive_price"] = len(amounts)
    selected = amounts[:7]
    if len(selected) < MIN_SELLERS or selected[-1][0] > selected[0][0] * MAX_PRICE_SPREAD:
        if diagnostics is not None and len(selected) >= MIN_SELLERS:
            diagnostics["spread_rejected"] = 1
        return None
    gbp_minor = int(Decimal(str(median(item[0] for item in selected))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    if gbp_minor <= 0:
        return None
    fx_evidence = {c: {"rate": str(fx_cache[c].rate),
                       "source": fx_cache[c].source,
                       "effective_at": fx_cache[c].effective_at.isoformat()}
                   for c in {row[4] for row in selected}}
    quote = {
        "source": SOURCE, "market": "CARDTRADER", "access_method": "OFFICIAL_API",
        "endpoint": "/marketplace/products?expansion_id=...&language=en",
        "observation_type": "ACTIVE_ASKING", "source_blueprint_id": blueprint_id,
        "source_expansion_id": expansion_id, "source_field": "MEDIAN_DISTINCT_SELLER_NM_ASKS",
        "price_gbp_minor": gbp_minor, "seller_count": len(selected),
        "sample_listing_ids": [row[2] for row in selected],
        "sample_gbp_minor": [row[0] for row in selected],
        "original_currency_fx": fx_evidence, "shipping_included": False,
        "condition": "Near Mint", "reference_language": "English",
        "physical_language_confirmed": True, "condition_specific": True,
        "physical_valuation_eligible": False, "sold_comparable": False,
        "valuation_role": "INDICATIVE_ACTIVE_ASKING_GUIDE",
        "unit_evidence": (
            "EXACT_SINGLE_CARD_BLUEPRINT_UNIT_UNREPORTED"
            if diagnostics and diagnostics.get("single_blueprint_unreported_unit_accepted")
            else "EXPLICIT_SINGLE_UNIT_SOURCE_FIELD"),
        "match_basis": "EXACT_RELEASE_NUMBER_NAME_RARITY_UNAMBIGUOUS_CARDTRADER_BLUEPRINT",
        "reference_printing_id": ref["provider_id"],
        "reference_rarity": ref.get("rarity"),
        "reference_identity": {k: ref[k] for k in ("name", "set_id", "card_number", "set_name")},
        "observed_at": observed.isoformat(), "expires_after_days": 7,
    }
    return quote, gbp_minor


def selected_releases(refs, games, categories, expansions, *, previous_cursor=None, limit=15):
    game_ids = {}
    for system, labels in {
        "DRAGON_BALL_SUPER_MASTERS": {"dragon ball super", "dragon ball super masters"},
        "POKEMON_TCG": {"pokemon", "pokemon tcg"},
    }.items():
        ids = {g.get("id") for g in games if source_normalized(g.get("name")) in labels}
        if len(ids) == 1:
            game_ids[system] = ids.pop()
    grouped = defaultdict(list)
    for ref in refs:
        grouped[(ref["system_code"], ref["set_id"])].append(ref)
    candidates = []
    for (system, set_id), group in grouped.items():
        if system not in game_ids or not any(missing(r) or missing_artwork(r) for r in group):
            continue
        if system == "DRAGON_BALL_SUPER_MASTERS":
            from .dragon_ball_market import MASTERS, release_identity
            identity = release_identity(MASTERS, group[0]["set_name"], include_starters=False)
            titles = {identity[1]} if identity else set()
        else:
            if POCKET_RELEASES.get(set_id) == group[0]["set_name"]:
                continue
            titles = {normalized(title) for title in cardtrader_release_titles(group[0])}
        possible = [e for e in expansions if e.get("game_id") == game_ids[system]
                    and normalized(e.get("name")) in titles]
        if len(possible) != 1 or type(possible[0].get("id")) is not int:
            continue
        category_names = MASTERS_CATEGORIES if system == "DRAGON_BALL_SUPER_MASTERS" else POKEMON_CATEGORIES
        category_ids = {c["id"] for c in categories if c.get("game_id") == game_ids[system]
                        and source_normalized(c.get("name")) in category_names}
        if not category_ids:
            continue
        candidates.append((f"{system}:{set_id}", group, possible[0], category_ids))
    candidates.sort(key=lambda entry: (-sum(missing(r) or missing_artwork(r) for r in entry[1]), entry[0]))
    if previous_cursor:
        index = next((i + 1 for i, row in enumerate(candidates)
                      if row[0] == previous_cursor), 0)
        candidates = candidates[index:] + candidates[:index]
    return candidates[:limit], len(candidates)


async def refresh_cardtrader_expansion_guides(pool, actor, fx_provider, client, *,
                                              dry_run=True, expansion_limit=15,
                                              previous_cursor=None, previous_artwork_cursors=None):
    if not 1 <= expansion_limit <= MAX_SETS_PER_RUN:
        raise ValueError("invalid CardTrader expansion batch size")
    observed = datetime.now(timezone.utc)
    report = {"source": SOURCE, "dry_run": dry_run, "input_cursor": previous_cursor,
              "cursor": previous_cursor, "provider_calls": 0,
              "provider_failures": 0, "sets_checked": 0, "references_examined": 0,
              "exact_printings": 0, "eligible_quotes": 0, "writes_attempted": 0,
              "writes_applied": 0, "inventory_writes": 0, "store_price_writes": 0,
              "by_release": {}, "failed_release_ids": [], "request_limit": expansion_limit,
              "quote_type": "ACTIVE_ASKING_NOT_SOLD", "scope": "CATALOGUE_ONLY"}
    report.update(artwork_probes=0, artwork_verified=0, artwork_written=0)
    report['artwork_cursors'] = dict(previous_artwork_cursors or {})
    async with user_connection(pool, actor, str(uuid4())) as connection:
        await require_platform_admin(connection)
        rows = await connection.fetch(READ_SQL)
    refs = [dict(row) for row in rows]
    fx_cache = {}
    try:
        report["provider_calls"] += 2
        games, expansions = await asyncio.gather(client.list_games(), client.list_expansions())
        report["provider_calls"] += 1
        categories = await client.list_categories()
        selected, all_releases = selected_releases(
            refs, games, categories, expansions, previous_cursor=previous_cursor,
            limit=expansion_limit)
        report["available_releases"] = all_releases
        for index, (cursor, group, expansion, category_ids) in enumerate(selected):
            report["cursor"] = cursor
            report["references_examined"] += len(group)
            release = {"references": len(group), "missing_before": sum(map(missing, group)),
                       "matched": 0, "quotes": 0, "writes": 0,
                       "blueprints_with_offers": 0, "candidate_source_offers": 0,
                       "with_three_matching_sellers": 0, "rejection_counts": {}}
            report["by_release"][cursor] = release
            try:
                report["provider_calls"] += 2
                blueprints, offers_by_blueprint = await asyncio.gather(
                    client.list_blueprints(expansion_id=expansion["id"]),
                    client.list_marketplace_expansion_products(
                        expansion_id=expansion["id"], language="en"))
                if not blueprints or len(blueprints) > 10_000:
                    raise ValueError("invalid blueprint export size")
                matches = exact_printings(group[0]["system_code"], group,
                                          blueprints, expansion, category_ids)
                release["matched"] = len(matches)
                report["exact_printings"] += len(matches)
                from .cardtrader_reference_artwork import MAX_PROBES, recover_reference_artwork
                artwork = await recover_reference_artwork(
                    pool, actor, group, blueprints, matches,
                    limit=MAX_PROBES-report['artwork_probes'], dry_run=dry_run,
                    previous_cursor=report['artwork_cursors'].get(cursor))
                report['artwork_probes'] += artwork['probed']
                report['artwork_verified'] += artwork['verified']
                report['artwork_written'] += artwork['written']
                release['artwork'] = artwork
                if artwork['cursor']:
                    report['artwork_cursors'][cursor] = artwork['cursor']
                values = []
                rejections = defaultdict(int)
                for ref in group:
                    bp_id = matches.get(ref["provider_id"])
                    if not bp_id or not missing(ref):
                        continue
                    offers = offers_by_blueprint.get(bp_id, [])
                    release["blueprints_with_offers"] += int(bool(offers))
                    release["candidate_source_offers"] += len(offers)
                    diagnostics = {}
                    guide = await asking_guide(ref, bp_id, expansion["id"],
                                               offers, fx_provider, observed, fx_cache,
                                               diagnostics=diagnostics,
                                               verified_single_blueprint=True)
                    release["with_three_matching_sellers"] += int(
                        diagnostics.get("qualified_distinct_sellers", 0) >= MIN_SELLERS
                        and diagnostics.get("finish_signatures", 0) == 1)
                    for key, value in diagnostics.items():
                        if key != "finish_signatures":
                            rejections[key] += value
                    if not guide:
                        continue
                    quote, minor = guide
                    values.append((ref["provider"], ref["system_code"], ref["language"],
                                   ref["provider_id"], json.dumps([quote]), minor,
                                   minor, observed, observed,
                                   observed + timedelta(days=7), ref["name"], ref["set_id"],
                                   ref["card_number"], ref["set_name"], ref.get("rarity"),
                                   SOURCE, ref.get("image_url"), None))
                release["quotes"] = len(values)
                release["rejection_counts"] = dict(sorted(rejections.items()))
                report["eligible_quotes"] += len(values)
                if not dry_run and values:
                    async with user_connection(pool, actor, str(uuid4())) as connection:
                        await require_platform_admin(connection)
                        for start in range(0, len(values), 100):
                            group_values = values[start:start + 100]
                            # The guarded SQL refuses a changed reference identity
                            # or a positive quote owned by another feed.
                            report["writes_attempted"] += len(group_values)
                            await connection.executemany(WRITE_SQL, group_values)
                            # asyncpg executemany returns None; the exact number
                            # is reconciled after the batch from the source rows.
                        ids = [r[3] for r in values]
                        release["writes"] = await connection.fetchval(
                            """select count(*) from tcg.reference_catalogue_prices
                               where provider=$1 and system_code=$2 and language='English'
                                 and provider_id=any($3::text[])
                                 and quotes->0->>'source'=$4""",
                            group[0]["provider"], group[0]["system_code"], ids, SOURCE)
                    report["writes_applied"] += release["writes"]
                report["sets_checked"] += 1
            except (CardTraderApiError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                release["error_type"] = type(exc).__name__
                if isinstance(exc, CardTraderApiError):
                    # Error details are fixed messages emitted by our own client,
                    # never raw upstream bodies or credential-bearing URLs.
                    release["error_detail"] = exc.detail
                    release["http_status"] = exc.status_code
                report["provider_failures"] += 1
                report["reason"] = type(exc).__name__
                report["failed_release_ids"].append(cursor)
                # Rate limits, auth failures and transient network errors pause
                # the whole session. A single missing/invalid release should
                # not stop the other expansions in the allowed batch.
                if (not isinstance(exc, CardTraderApiError) or exc.retryable or
                        exc.status_code in {401, 403, 429}):
                    report["cursor"] = selected[index - 1][0] if index else previous_cursor
                    break
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(1)  # conservative pacing, independent of 10/s maximum
    except (CardTraderApiError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        report["reason"] = type(exc).__name__
        report["provider_failures"] += 1
    return report
