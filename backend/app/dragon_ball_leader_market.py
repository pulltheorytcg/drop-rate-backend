"""Reference guides for explicitly paired official Masters leader faces.

The official checklist stores a leader's two sides as separate records. A
market product names both sides with `` // ``. Both complete names, the exact
number/file pair and the release must agree; parallel collisions still block.
"""
import re
from collections import defaultdict

from .dragon_ball_market import MASTERS, expansion_index, reference_expansion
from .one_piece_market import normalized

MATCH_BASIS = 'EXACT_MASTERS_OFFICIAL_LEADER_FACE_PAIR_REFERENCE'
NUMBER = re.compile(r'(?:BT|SD|EX)\d{1,2}-\d{2,3}\Z')
IMAGE_ROOT = 'https://www.dbs-cardgame.com/images/cardlist/cardimg/'


def paired_leader_matches(references, singles, packaging):
    refs_by_number, refs_by_name = defaultdict(list), defaultdict(list)
    for ref in references:
        if (ref.get('provider'), ref.get('system_code'), ref.get('language')) != (
                'Bandai Official', MASTERS, 'English'):
            continue
        refs_by_number[(ref['set_id'], ref['card_number'])].append(ref)
        refs_by_name[(ref['set_id'], normalized(ref['name']))].append(ref)
    products = defaultdict(list)
    for product in singles.values():
        if (product.get('idCategory'), product.get('categoryName')) == (
                1049, 'Dragon Ball Super Singles'):
            products[(product.get('idExpansion'), normalized(product.get('name')))].append(product)
    expansions = expansion_index(packaging, include_ambiguous=True)
    candidates, claims = {}, defaultdict(set)
    for (set_id, number), refs in refs_by_number.items():
        if len(refs) != 2 or not NUMBER.fullmatch(str(number)):
            continue
        by_id = {r['provider_id']: r for r in refs}
        front_id, back_id = set_id+':'+number+'.png', set_id+':'+number+'_b.png'
        front, back = by_id.get(front_id), by_id.get(back_id)
        if not front or not back or front['set_name'] != back['set_name']:
            continue
        if (not front.get('rarity') or front['rarity'] != back.get('rarity') or
                any(len(refs_by_name[(set_id, normalized(r['name']))]) != 1 for r in refs)):
            continue
        if any((r.get('evidence') or {}).get('card_type') != 'LEADER' or
               (r.get('evidence') or {}).get('detail_level') != 'OFFICIAL_CHECKLIST' or
               r.get('image_url') != IMAGE_ROOT+r['provider_id'].split(':', 1)[1]
               for r in refs):
            continue
        expansion = reference_expansion(front, expansions)
        label = front['name']+' // '+back['name']
        matches = products.get((expansion, normalized(label)), []) if expansion else []
        if len(matches) != 1:
            continue
        product = matches[0]
        if (str(product.get('name') or '').count(' // ') != 1 or
                type(product.get('idProduct')) is not int or product['idProduct'] <= 0):
            continue
        pair = (set_id, number)
        claims[product['idProduct']].add(pair)
        for ref in refs:
            candidates[(MASTERS, ref['provider_id'])] = {
                'product': product, 'pair': pair,
                'reference_face_ids': [front_id, back_id],
                'reference_face': 'front' if ref is front else 'back',
            }
    return {key: value for key, value in candidates.items()
            if len(claims[value['product']['idProduct']]) == 1}
