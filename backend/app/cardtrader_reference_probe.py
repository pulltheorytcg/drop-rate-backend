"""Bounded read-only audit of the existing CardTrader identity connection.

No quote, reference, inventory or mapping is written. Provider credentials never
enter receipts. The probe checks whether explicit product IDs can close missing
catalogue identities before any new price adapter is enabled.
"""
from collections import Counter, defaultdict
import re

from .cardtrader_client import CardTraderApiError
from .cardtrader_media import _collector_number
from .pokemon_catalogue_market import normalized, release_titles
from .reference_sealed import cardmarket_product_id, normalized as game_name

TARGET_SETS = ('dp1', 'dp2', 'dp3', 'dp6', 'xyp', 'bwp', 'sv01', 'swsh1')


def number_key(value):
    value = str(value or '').split('/', 1)[0].strip().upper()
    match = re.fullmatch(r'([A-Z]*)(\d+)([A-Z]*)', value)
    return (match[1], int(match[2]), match[3]) if match else None


async def probe_cardtrader_references(client, references, singles):
    report = {'status': 'INCOMPLETE', 'read_only': True, 'provider_calls': 0,
              'price_writes': 0, 'inventory_rows_read': 0, 'sets': []}
    try:
        report['provider_calls'] += 1
        games = await client.list_games()
        ids = {g['id'] for g in games if game_name(g.get('name')) in {'pokemon', 'pokemon tcg'}}
        if len(ids) != 1:
            raise ValueError('Pokemon game identity unavailable')
        game_id = next(iter(ids))
        report['provider_calls'] += 1
        expansions = await client.list_expansions()
        for set_id in TARGET_SETS:
            refs = [r for r in references if r.get('set_id')==set_id and
                    (r.get('provider'), r.get('system_code'), r.get('language')) ==
                    ('TCGdex', 'POKEMON_TCG', 'English')]
            if not refs:
                continue
            titles = {normalized(title) for title in release_titles(refs[0])}
            matches = [e for e in expansions if e.get('game_id')==game_id and
                       normalized(e.get('name')) in titles]
            entry = {'set_id': set_id, 'set_name': refs[0]['set_name'],
                     'reference_cards': len(refs), 'expansion_candidates': len(matches)}
            report['sets'].append(entry)
            if len(matches) != 1:
                continue
            expansion = matches[0]
            report['provider_calls'] += 1
            blueprints = await client.list_blueprints(expansion_id=expansion['id'])
            if len(blueprints)>10000:
                raise ValueError('Blueprint bound exceeded')
            blueprints = [b for b in blueprints if b.get('game_id')==game_id and
                          b.get('expansion_id')==expansion['id']]
            ref_numbers, blueprint_numbers = defaultdict(list), defaultdict(list)
            for ref in refs:
                ref_numbers[number_key(ref.get('card_number'))].append(ref)
            for blueprint in blueprints:
                blueprint_numbers[number_key(_collector_number(blueprint))].append(blueprint)
            candidates = []
            for number, numbered_refs in ref_numbers.items():
                numbered_blueprints = blueprint_numbers.get(number, [])
                if number is None or len(numbered_refs)!=1 or len(numbered_blueprints)!=1:
                    continue
                ref, blueprint = numbered_refs[0], numbered_blueprints[0]
                product_id = cardmarket_product_id(blueprint)
                product = singles.get(product_id)
                if not product or product.get('idCategory')!=51:
                    continue
                name = re.sub(r' \[[^\[\]]+\]$', '', product.get('name', ''))
                if normalized(ref['name'])==normalized(blueprint.get('name'))==normalized(name):
                    candidates.append({'reference_id': ref['provider_id'],
                                       'blueprint_id': blueprint['id'], 'cardmarket_product_id': product_id})
            entry.update(expansion_id=expansion['id'], blueprints=len(blueprints),
                         numbered_blueprints=sum(len(v) for k,v in blueprint_numbers.items() if k is not None),
                         singleton_cardmarket_ids=sum(cardmarket_product_id(b) is not None for b in blueprints),
                         categories=dict(Counter(str(b.get('category_id')) for b in blueprints)),
                         exact_identity_candidates=len(candidates), candidate_examples=candidates[:3],
                         provider_examples=[{'id': b.get('id'), 'name': b.get('name'),
                                             'version': b.get('version'),
                                             'collector_number': _collector_number(b),
                                             'card_market_ids': (b.get('card_market_ids') or [])[:40]}
                                            for b in blueprints[:3]])
        report['status'] = 'COMPLETE'
    except (CardTraderApiError, ValueError, TypeError, KeyError) as exc:
        report.update(status='UNAVAILABLE', reason=type(exc).__name__)
        if isinstance(exc, CardTraderApiError):
            report['http_status'] = exc.status_code
    return report
