"""Exact CardTrader collector-number links to first-party Cardmarket guides.

CardTrader supplies identity only. Prices still come from the existing dated
Cardmarket export, and all resulting quotes remain mixed-language references.
"""
import asyncio
import re
from collections import defaultdict

from .cardtrader_client import CardTraderApiError
from .cardtrader_media import _collector_number
from .cardtrader_reference_probe import number_key
from .pokemon_catalogue_market import normalized, product_card_name, release_titles
from .reference_applicability import POCKET_RELEASES
from .reference_sealed import cardmarket_product_id, normalized as game_name

MATCH_BASIS = 'CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID'
SINGLE_CATEGORIES = {'pokemon single', 'pokemon singles', 'pokemon single card',
                     'pokemon single cards', 'single card', 'single cards'}


def blueprint_card_name(blueprint):
    # The source expands the printed diamond; keep the actual identity symbol.
    return re.sub(r'(?<=◇) Prism Star$', '', str(blueprint.get('name') or ''))


def match_blueprints(references, blueprints, expansion, single_categories, singles):
    if any((r.get('provider'),r.get('system_code'),r.get('language'))!=
           ('TCGdex','POKEMON_TCG','English') for r in references):
        return {}
    refs_by_number, blueprints_by_number = defaultdict(list), defaultdict(list)
    for ref in references:
        refs_by_number[number_key(ref.get('card_number'))].append(ref)
    for blueprint in blueprints:
        if (blueprint.get('game_id')==expansion['game_id'] and
                blueprint.get('expansion_id')==expansion['id'] and
                blueprint.get('category_id') in single_categories):
            # Unpriced and unmapped prints still count as ambiguity.
            blueprints_by_number[number_key(_collector_number(blueprint))].append(blueprint)
    matches = {}
    claims = defaultdict(list)
    for number, refs in refs_by_number.items():
        candidates = blueprints_by_number.get(number, [])
        if number is None or len(refs)!=1 or len(candidates)!=1:
            continue
        ref, blueprint = refs[0], candidates[0]
        prefix = ref['set_id']+'-'
        if (not ref['provider_id'].startswith(prefix) or
                number_key(ref['provider_id'][len(prefix):])!=number):
            continue
        product_id = cardmarket_product_id(blueprint)
        product = singles.get(product_id)
        if (not product or product.get('idCategory')!=51 or
                product.get('categoryName')!='Pokémon Single' or
                str(product.get('idProduct'))!=product_id or
                type(blueprint.get('id')) is not int or blueprint['id']<=0):
            continue
        blueprint_name, product_name = blueprint_card_name(blueprint), product_card_name(product)
        if not (normalized(ref['name'])==normalized(blueprint_name)==normalized(product_name)):
            continue
        if not (('◇' in ref['name']) == ('◇' in blueprint_name) == ('◇' in product_name)):
            continue
        proof = {'mapping_source':'CARDTRADER', 'cardtrader_blueprint_id':blueprint['id'],
                 'cardtrader_expansion_id':expansion['id'],
                 'cardtrader_collector_number':_collector_number(blueprint),
                 'cardtrader_version':blueprint.get('version'),
                 'collector_number_source':'CARDTRADER', 'match_basis':MATCH_BASIS,
                 'physical_valuation_eligible':False}
        matches[ref['provider_id']] = {'product':product, 'proof':proof}
        claims[product_id].append(ref['provider_id'])
    return {key:match for key,match in matches.items()
            if len(claims[str(match['product']['idProduct'])])==1}


async def cardtrader_matches(client, references, singles, base_matches):
    report = {'status':'INCOMPLETE', 'provider_calls':0, 'provider_failures':0,
              'sets_checked':0, 'exact_candidates':0, 'by_release':{}}
    groups = defaultdict(list)
    for ref in references:
        if ((ref.get('provider'),ref.get('system_code'),ref.get('language'))==
                ('TCGdex','POKEMON_TCG','English') and
                POCKET_RELEASES.get(ref['set_id'])!=ref['set_name']):
            groups[ref['set_id']].append(ref)
    result, failed_sets = {}, set()
    try:
        report['provider_calls'] += 1
        games = await client.list_games()
        ids = {g['id'] for g in games if game_name(g.get('name')) in {'pokemon','pokemon tcg'}}
        if len(ids)!=1:
            raise ValueError('Pokemon game identity unavailable')
        game_id = next(iter(ids))
        report['provider_calls'] += 2
        expansions, categories = await asyncio.gather(
            client.list_expansions(), client.list_categories(game_id=game_id))
        single_categories = {c['id'] for c in categories if c.get('game_id')==game_id and
                             game_name(c.get('name')) in SINGLE_CATEGORIES}
        if not single_categories:
            report['category_names'] = [str(c.get('name'))[:100] for c in categories[:30]]
            raise ValueError('Single-card categories unavailable')
        selected = []
        for set_id, refs in groups.items():
            if not any(r['provider_id'] not in base_matches and not r.get('current_detail_priced') for r in refs):
                continue
            declared = refs[0].get('declared_card_count')
            if type(declared) is not int or declared<=0 or len({r['provider_id'] for r in refs})<declared:
                continue
            titles = {normalized(title) for title in release_titles(refs[0])}
            candidates = [e for e in expansions if e.get('game_id')==game_id and
                          normalized(e.get('name')) in titles]
            if len(candidates)==1 and type(candidates[0].get('id')) is int and candidates[0]['id']>0:
                selected.append((set_id,refs,candidates[0]))
        if len(selected)>400:
            raise ValueError('Release request bound exceeded')

        async def fetch_one(entry):
            set_id, refs, expansion = entry
            report['provider_calls'] += 1
            try:
                blueprints = await client.list_blueprints(expansion_id=expansion['id'])
                if not blueprints or len(blueprints)>10000:
                    raise ValueError('Blueprint count invalid')
                matches = match_blueprints(refs,blueprints,expansion,single_categories,singles)
                report['sets_checked'] += 1
                report['by_release'][set_id] = {'checked':len(refs),'matched':len(matches)}
                return matches
            except (CardTraderApiError,ValueError,TypeError,KeyError):
                failed_sets.add(set_id)
                report['provider_failures'] += 1
                return {}

        # Three concurrent reads stay well below the existing API rate limit.
        # Stop subsequent batches on a provider failure; retain prior evidence.
        for start in range(0,len(selected),3):
            for matches in await asyncio.gather(*(fetch_one(e) for e in selected[start:start+3])):
                result.update(matches)
            if failed_sets:
                failed_sets.update(e[0] for e in selected[start+3:])
                break
        claims = defaultdict(list)
        for key, match in result.items():
            claims[match['product']['idProduct']].append(key)
        conflicting = {key for keys in claims.values() if len(keys)>1 for key in keys}
        result = {key:match for key,match in result.items() if key not in conflicting}
        report.update(status='PARTIAL' if failed_sets else 'COMPLETE',exact_candidates=len(result),
                      cross_release_conflicts=len(conflicting))
    except (CardTraderApiError,ValueError,TypeError,KeyError) as exc:
        report.update(status='UNAVAILABLE',provider_failures=1,reason=type(exc).__name__)
        failed_sets.update(groups)
    return result, report, failed_sets
