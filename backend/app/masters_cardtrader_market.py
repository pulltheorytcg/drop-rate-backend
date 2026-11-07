"""Exact Masters printing identities from the existing CardTrader connection.

The daily Cardmarket export omits rarity even when two products have the same
name. CardTrader's explicit number, rarity and singleton product ID resolve that
gap. Both complete release checklists still participate in ambiguity checks;
neither a parallel suffix nor the order/price of a product determines a match.
"""
import asyncio
from collections import defaultdict
import re

from .cardtrader_client import CardTraderApiError
from .cardtrader_media import _collector_number, _property_value
from .reference_sealed import cardmarket_product_id, normalized as game_name

MATCH_BASIS = 'CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID'
SINGLE_CATEGORIES = {'dragon ball super singles', 'dragon ball super single cards',
                     'single cards', 'singles'}
RARITIES = {
    'common': 'C', 'uncommon': 'UC', 'rare': 'R', 'super rare': 'SR',
    'special rare': 'SPR', 'secret rare': 'SCR', 'god rare': 'GDR',
    'special leader rare': 'SLR', 'special rare signature': 'SPR_S',
    'concept rare': 'CR', 'feature rare': 'FR', 'expansion rare': 'EX',
    'starter rare': 'ST', 'promotion': 'PR', 'giant force rare': 'GFR',
    'dragon ball rare': 'DBR', 'destroyer & angel rare': 'DAR',
    'duo power rare': 'DPR', 'reboot leader rare': 'RLR',
    'son gohan rare': 'SGR', 'iconic attack rare': 'IAR', 'destruction rare': 'DR',
    'noble hero rare': 'NHR', 'infinite saiyan rares': 'ISR', 'ignoble villain rare': 'IVR',
}


def rarity_key(value):
    # Official labels include the abbreviation; provider labels spell it out.
    # No equivalence between distinct rarities (SR, SPR, SLR, signature, etc.).
    text = str(value or '').strip()
    match = re.fullmatch(r'(.+?)\[([A-Z_]+)\]', text)
    key = game_name(match[1] if match else text)
    if key not in RARITIES or (match and RARITIES[key] != match[2]):
        return None
    return key


def number_key(value, family):
    """Group ALL suffixes for ambiguity; suffixes are never art identifiers."""
    text = str(value or '').strip().upper()
    match = re.match(r'(BT\d+)-(\d+)(?!\d)', text)
    if match:
        return (match[1], int(match[2]))
    match = re.match(r'(\d+)(?!\d)', text)
    return (family, int(match[1])) if match and family else None


def blueprint_rarity(blueprint):
    value = _property_value(blueprint, 'dragonball_rarity', 'rarity')
    # The live provider uses a card-type label in this field for SLRs, but
    # spells out the actual rarity in version. Do not infer it from "slr"
    # collector suffixes or treat every Leader as an Uncommon printing.
    if game_name(value) == 'leader' and game_name(blueprint.get('version')) == 'special leader rare':
        return 'special leader rare'
    return rarity_key(value)


def official_printing(refs):
    """Return the exact named printing and its one or two official records."""
    from .dragon_ball_leader_market import IMAGE_ROOT

    if len(refs) not in {1, 2}:
        return None
    for ref in refs:
        evidence = ref.get('evidence') or {}
        if evidence.get('detail_level') != 'OFFICIAL_CHECKLIST' or not evidence.get('card_type'):
            return None
    if len(refs) == 1:
        ref = refs[0]
        if ('LEADER' in ref['evidence']['card_type'] or
                ref['provider_id'] != ref['set_id'] + ':' + ref['card_number'] + '.png'):
            return None
        return ref['name'], refs
    first = refs[0]
    number, set_id = first['card_number'], first['set_id']
    if not re.fullmatch(r'BT\d{1,2}-\d{2,3}(?:_PR\d*)?', str(number)):
        return None
    front_id, back_id = set_id + ':' + number + '.png', set_id + ':' + number + '_b.png'
    by_id = {r['provider_id']: r for r in refs}
    if set(by_id) != {front_id, back_id}:
        return None
    for ref in refs:
        if (ref['set_id'] != set_id or ref['set_name'] != first['set_name'] or
                ref['card_number'] != number or ref['rarity'] != first['rarity'] or
                ref['evidence']['card_type'] != 'LEADER' or
                ref.get('image_url') != IMAGE_ROOT + ref['provider_id'].split(':', 1)[1] or
                not str(ref['name']).strip() or ' // ' in ref['name']):
            return None
    front, back = by_id[front_id], by_id[back_id]
    return front['name'] + ' // ' + back['name'], [front, back]


def match_blueprints(references, blueprints, expansion, single_categories, singles,
                     market_expansion):
    from .dragon_ball_market import MASTERS
    from .one_piece_market import normalized

    if not references or any((r.get('provider'), r.get('system_code'), r.get('language')) !=
            ('Bandai Official', MASTERS, 'English') for r in references):
        return {}
    families = {m[1] for r in references
                if (m := re.match(r'(BT\d+)-\d+', str(r.get('card_number') or '')))}
    code = str(expansion.get('code') or '').upper()
    if re.fullmatch(r'BT\d+', code) and code in families:
        family = code
    elif len(families) == 1:
        family = next(iter(families))
    else:
        return {}
    refs_by_number, prints_by_number = defaultdict(list), defaultdict(list)
    unnumbered_names = set()
    for ref in references:
        refs_by_number[number_key(ref.get('card_number'), None)].append(ref)
    for blueprint in blueprints:
        if (blueprint.get('game_id') != expansion['game_id'] or
                blueprint.get('expansion_id') != expansion['id'] or
                blueprint.get('category_id') not in single_categories):
            continue
        number = number_key(_collector_number(blueprint), family)
        if number is None:
            unnumbered_names.add(normalized(blueprint.get('name')))
        else:
            prints_by_number[number].append(blueprint)
    matches = {}
    claims = defaultdict(set)
    for number, refs in refs_by_number.items():
        prints = prints_by_number.get(number, [])
        if number is None or not prints:
            continue
        # An unclassified printing cannot disappear just because it has no
        # quote, mapping or usable rarity. It blocks this entire number.
        if any(rarity_key(r.get('rarity')) is None for r in refs) or any(
                blueprint_rarity(b) is None for b in prints):
            continue
        for rarity in {rarity_key(ref.get('rarity')) for ref in refs}:
            same_refs = [r for r in refs if rarity_key(r.get('rarity')) == rarity]
            same_prints = [b for b in prints if blueprint_rarity(b) == rarity]
            identity = official_printing(same_refs)
            if identity is None or len(same_prints) != 1:
                continue
            name, members = identity
            ref = members[0]
            blueprint = same_prints[0]
            if normalized(name) in unnumbered_names:
                continue
            # Unknown suffixes count above, but cannot themselves provide
            # affirmative identity evidence. A suffix never supplies rarity.
            collector = str(_collector_number(blueprint) or '').strip().upper()
            if not re.fullmatch(r'(?:BT\d+-)?\d+[A-Z]{0,3}', collector):
                continue
            product_id = cardmarket_product_id(blueprint)
            product = singles.get(product_id)
            if (type(blueprint.get('id')) is not int or blueprint['id'] <= 0 or
                    not product or str(product.get('idProduct')) != product_id or
                    (product.get('idCategory'), product.get('categoryName')) !=
                    (1049, 'Dragon Ball Super Singles') or
                    product.get('idExpansion') != market_expansion or
                    not normalized(name) or not (
                        normalized(name) == normalized(blueprint.get('name')) ==
                        normalized(product.get('name')))):
                continue
            if len(members) == 2 and (str(blueprint.get('name')).count(' // ') != 1 or
                                      str(product.get('name')).count(' // ') != 1):
                continue
            proof = {'mapping_source': 'CARDTRADER', 'match_basis': MATCH_BASIS,
                     'cardtrader_blueprint_id': blueprint['id'],
                     'cardtrader_expansion_id': expansion['id'],
                     'cardtrader_collector_number': _collector_number(blueprint),
                     'cardtrader_rarity': _property_value(blueprint, 'dragonball_rarity', 'rarity'),
                     'cardtrader_rarity_source': ('version' if game_name(_property_value(
                         blueprint, 'dragonball_rarity', 'rarity')) == 'leader' else 'rarity'),
                     'cardtrader_version': blueprint.get('version'),
                     'physical_valuation_eligible': False}
            printing = (ref['set_id'], ref['card_number'])
            for index, member in enumerate(members):
                member_proof = dict(proof)
                if len(members) == 2:
                    member_proof.update(reference_face_ids=[r['provider_id'] for r in members],
                                        reference_face='front' if index == 0 else 'back')
                matches[(MASTERS, member['provider_id'])] = {
                    'product': product, 'proof': member_proof, 'printing': printing}
            claims[product_id].add(printing)
    return {key: match for key, match in matches.items()
            if len(claims[str(match['product']['idProduct'])]) == 1}


async def cardtrader_matches(client, references, singles, packaging, base_matches):
    from .dragon_ball_market import MASTERS, expansion_index, reference_expansion, release_identity

    report = {'status': 'INCOMPLETE', 'provider_calls': 0, 'provider_failures': 0,
              'sets_checked': 0, 'exact_candidates': 0, 'by_release': {}}
    groups = defaultdict(list)
    for ref in references:
        if ((ref.get('provider'), ref.get('system_code'), ref.get('language')) ==
                ('Bandai Official', MASTERS, 'English') and
                release_identity(MASTERS, ref['set_name'], include_starters=False)):
            groups[ref['set_id']].append(ref)
    result, failed_sets = {}, set()
    try:
        report['provider_calls'] += 1
        games = await client.list_games()
        ids = {g['id'] for g in games if game_name(g.get('name')) in
               {'dragon ball super', 'dragon ball super masters'}}
        if len(ids) != 1:
            raise ValueError('Masters game identity unavailable')
        game_id = next(iter(ids))
        report['provider_calls'] += 2
        expansions, categories = await asyncio.gather(
            client.list_expansions(), client.list_categories(game_id=game_id))
        single_categories = {c['id'] for c in categories if c.get('game_id') == game_id
                             and game_name(c.get('name')) in SINGLE_CATEGORIES}
        if not single_categories:
            raise ValueError('Single-card categories unavailable')
        market_expansions = expansion_index(packaging, include_ambiguous=True)
        selected = []
        from .one_piece_market import normalized
        for set_id, refs in groups.items():
            if not any((MASTERS, r['provider_id']) not in base_matches for r in refs):
                continue
            identity = release_identity(MASTERS, refs[0]['set_name'], include_starters=False)
            candidates = [e for e in expansions if e.get('game_id') == game_id
                          and normalized(e.get('name')) == identity[1]]
            market_expansion = reference_expansion(refs[0], market_expansions)
            if (len(candidates) == 1 and type(candidates[0].get('id')) is int
                    and candidates[0]['id'] > 0 and market_expansion):
                selected.append((set_id, refs, candidates[0], market_expansion))
        if len(selected) > 80:
            raise ValueError('Release request bound exceeded')

        async def fetch_one(entry):
            set_id, refs, expansion, market_expansion = entry
            report['provider_calls'] += 1
            try:
                blueprints = await client.list_blueprints(expansion_id=expansion['id'])
                if not blueprints or len(blueprints) > 10000:
                    raise ValueError('Blueprint count invalid')
                matches = match_blueprints(refs, blueprints, expansion, single_categories,
                                           singles, market_expansion)
                report['sets_checked'] += 1
                report['by_release'][set_id] = {'checked': len(refs), 'matched': len(matches)}
                return matches
            except (CardTraderApiError, ValueError, TypeError, KeyError):
                failed_sets.add(set_id)
                report['provider_failures'] += 1
                return {}

        for start in range(0, len(selected), 3):
            for matches in await asyncio.gather(*(fetch_one(e) for e in selected[start:start + 3])):
                result.update(matches)
            if failed_sets:
                failed_sets.update(e[0] for e in selected[start + 3:])
                break
            # This connection also serves the Pokemon bridge. Bound bursts.
            if start + 3 < len(selected):
                await asyncio.sleep(.25)
        claims = defaultdict(set)
        for key, match in result.items():
            claims[match['product']['idProduct']].add(match['printing'])
        conflicts = {key for key, match in result.items()
                     if len(claims[match['product']['idProduct']]) > 1}
        result = {key: match for key, match in result.items() if key not in conflicts}
        report.update(status='PARTIAL' if failed_sets else 'COMPLETE', exact_candidates=len(result),
                      cross_release_conflicts=len(conflicts))
    except (CardTraderApiError, ValueError, TypeError, KeyError) as exc:
        report.update(status='UNAVAILABLE', provider_failures=1, reason=type(exc).__name__)
        failed_sets.update(groups)
    return result, report, failed_sets
