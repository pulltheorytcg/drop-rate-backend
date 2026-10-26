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
from .pokemon_catalogue_market import normalized, product_card_name, release_titles, validate_generations_scope
from .reference_applicability import POCKET_RELEASES
from .reference_sealed import cardmarket_product_id, normalized as game_name

MATCH_BASIS = 'CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID'
SINGLE_CATEGORIES = {'pokemon single', 'pokemon singles', 'pokemon single card',
                     'pokemon single cards', 'single card', 'single cards'}


# CardTrader keeps the Shiny Vault in its parent expansion. Only its explicit
# SV collector numbers may bridge this subset; name-only bulk matching must not
# inherit this alias (the base release also contains Charizard GX).
HIDDEN_FATES_SUBSET = ('sma', 'Hidden Fates Shiny Vault')
HIDDEN_FATES_PARENT = 'Hidden Fates'


GENERATIONS = ("g1","Generations")
GENERATIONS_RADIANT = "Radiant Collection Generation"


def blueprint_number_key(blueprint, expansion):
    raw=_collector_number(blueprint)
    if (expansion.get("id"),expansion.get("game_id"),expansion.get("name")) == (1907,5,GENERATIONS_RADIANT):
        # Nine observed records contain0 before the RC prefix, not before its
        # number. Correct only this fixed expansion with independent version proof.
        match=re.fullmatch(r"0?(RC(?:[1-9]|[12][0-9]|3[0-2]))/RC32",str(raw or ""))
        if not match:
            return None
        if str(raw).startswith("0") and not re.fullmatch(r"0RC[1-9]/RC32",str(raw)):
            return None
        canonical=match[1]+"/RC32"
        parts=str(blueprint.get("version") or "").split(" | ")
        if parts[-1]!=canonical or len(parts)>2:
            return None
        rarity=(blueprint.get("fixed_properties") or {}).get("pokemon_rarity")
        if rarity not in {"Common","Uncommon","Holo Rare","Ultra Rare"} or (len(parts)==2 and parts[0]!=rarity):
            return None
        return number_key(canonical)
    return number_key(raw)


def generations_ref_matches(ref, number, expansion):
    if (ref.get("set_id"),ref.get("set_name"))!=GENERATIONS or ref.get("declared_card_count")!=117:
        return False
    if ref.get("card_number")!=ref.get("provider_id","")[3:]+"/83":
        return False
    if number[0]=="RC":
        return (not number[2] and 1<=number[1]<=32 and
            (expansion.get("id"),expansion.get("game_id"),expansion.get("name"))==
            (1907,5,GENERATIONS_RADIANT))
    return expansion.get("name")=="Generations" and number[0]=="" and (
        (not number[2] and 1<=number[1]<=83) or (number[1] in {28,73} and number[2]=="A"))


def cardtrader_release_titles(ref):
    if (ref.get('set_id'), ref.get('set_name')) == HIDDEN_FATES_SUBSET:
        return {HIDDEN_FATES_PARENT}
    return release_titles(ref)


def blueprint_card_name(blueprint):
    # The source expands the printed diamond; keep the actual identity symbol.
    return re.sub(r'(?<=◇) Prism Star$', '', str(blueprint.get('name') or ''))


def match_blueprints(references, blueprints, expansion, single_categories, singles):
    if any((r.get('provider'),r.get('system_code'),r.get('language'))!=
           ('TCGdex','POKEMON_TCG','English') for r in references):
        return {}
    refs_by_number, blueprints_by_number = defaultdict(list), defaultdict(list)
    source_product_claims = defaultdict(set)
    invalid_source_claims = False
    for ref in references:
        refs_by_number[number_key(ref.get('card_number'))].append(ref)
    for source_index, blueprint in enumerate(blueprints):
        if (blueprint.get('game_id')==expansion['game_id'] and
                blueprint.get('expansion_id')==expansion['id'] and
                blueprint.get('category_id') in single_categories):
            # Unpriced and unmapped prints still count as ambiguity.
            blueprints_by_number[blueprint_number_key(blueprint,expansion)].append(blueprint)
            # A bounded subset must still see claims made by unpriced base
            # cards and competing multi-ID blueprints in the full export.
            cross_ids = blueprint.get('card_market_ids')
            cross_ids = [] if cross_ids is None else cross_ids
            if not isinstance(cross_ids, list) or len(cross_ids) > 40:
                invalid_source_claims = True
                continue
            legacy = blueprint.get('cardmarket_id')
            cross_ids = cross_ids + ([legacy] if legacy is not None else [])
            for value in cross_ids:
                if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
                    invalid_source_claims = True
                    continue
                source_product_claims[str(int(value))].add(source_index)
    matches = {}
    claims = defaultdict(list)
    for number, refs in refs_by_number.items():
        candidates = blueprints_by_number.get(number, [])
        if number is None or len(refs)!=1 or len(candidates)!=1:
            continue
        ref, blueprint = refs[0], candidates[0]
        if ref.get('set_id') == HIDDEN_FATES_SUBSET[0]:
            # Keep the parent mapping confined to the known complete subset.
            # A base numeric card or a similarly named release cannot enter it.
            if ((ref.get('set_id'), ref.get('set_name')) != HIDDEN_FATES_SUBSET
                    or expansion.get('name') != HIDDEN_FATES_PARENT
                    or number[0] != 'SV' or number[2] or not 1 <= number[1] <= 94):
                continue
        if ref.get('set_id')=='g1' and not generations_ref_matches(ref,number,expansion):
            continue
        prefix = ref['set_id']+'-'
        if (not ref['provider_id'].startswith(prefix) or
                number_key(ref['provider_id'][len(prefix):])!=number):
            continue
        product_id = cardmarket_product_id(blueprint)
        if ref.get('set_id') in {HIDDEN_FATES_SUBSET[0],'g1'} and (
                invalid_source_claims or len(source_product_claims.get(product_id, set())) != 1):
            continue
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
        if (ref.get('set_id'), ref.get('set_name')) == HIDDEN_FATES_SUBSET:
            proof.update(cardtrader_parent_release=HIDDEN_FATES_PARENT,
                         canonical_subset=HIDDEN_FATES_SUBSET[1],
                         release_match_basis='EXACT_HIDDEN_FATES_SHINY_VAULT_SV_NUMBER')
        if ref.get('set_id')=='g1':
            proof.update(canonical_subset="Generations Radiant Collection" if number[0]=="RC" else "Generations base",
                         release_match_basis="EXACT_GENERATIONS_PARTITION_AND_NUMBER",
                         normalized_collector_number=number[0]+str(number[1])+number[2],
                         collector_number_normalization="LEADING_ZERO_BEFORE_RC_CORROBORATED_BY_VERSION"
                            if str(_collector_number(blueprint)).startswith("0RC") else "NONE")
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
        generations_claims=defaultdict(set)
        generations_claims_invalid=False
        for set_id, refs in groups.items():
            # A detailed quote can temporarily cover the same card, but its
            # independent catalogue bridge still needs revalidation. Skipping
            # it here would clear a proven guide without checking its source.
            if not any(r['provider_id'] not in base_matches and
                       (not r.get('current_detail_priced') or r.get('existing_match_basis') == MATCH_BASIS)
                       for r in refs):
                continue
            if set_id=="g1":
                try:
                    validate_generations_scope(refs)
                except ValueError:
                    failed_sets.add(set_id)
                    report["provider_failures"]+=1
                    continue
            declared = refs[0].get('declared_card_count')
            if type(declared) is not int or declared<=0 or len({r['provider_id'] for r in refs})<declared:
                continue
            partitions=[(set_id,refs,cardtrader_release_titles(refs[0]))]
            if set_id=="g1":
                try:
                    validate_generations_scope(refs)
                except ValueError:
                    failed_sets.add(set_id)
                    report["provider_failures"]+=1
                    continue
                partitions=[
                    ("g1:base",[r for r in refs if not r["provider_id"].startswith("g1-RC")],{"Generations"}),
                    ("g1:rc",[r for r in refs if r["provider_id"].startswith("g1-RC")],{GENERATIONS_RADIANT})]
            for label,partition,titles in partitions:
                titles={normalized(title) for title in titles}
                candidates=[e for e in expansions if e.get("game_id")==game_id and normalized(e.get("name")) in titles]
                if len(candidates)==1 and type(candidates[0].get("id")) is int and candidates[0]["id"]>0:
                    selected.append((set_id,partition,candidates[0],label))
                elif set_id=="g1":
                    failed_sets.add(set_id)
                    report["provider_failures"]+=1
        if len(selected)>400:
            raise ValueError('Release request bound exceeded')

        async def fetch_one(entry):
            nonlocal generations_claims_invalid
            set_id, refs, expansion, label = entry
            report['provider_calls'] += 1
            try:
                blueprints = await client.list_blueprints(expansion_id=expansion['id'])
                if not blueprints or len(blueprints)>10000:
                    raise ValueError('Blueprint count invalid')
                if set_id=="g1":
                    if expansion["name"]=="Generations":
                        base_numbers={number_key(_collector_number(b)) for b in blueprints
                            if b.get("game_id")==game_id and b.get("expansion_id")==expansion["id"]
                            and b.get("category_id") in single_categories}
                        if not {("",n,"") for n in range(1,84)}<=base_numbers:
                            raise ValueError("Incomplete Generations base identity export")
                    if expansion["name"]==GENERATIONS_RADIANT:
                        exact=[b for b in blueprints if b.get("game_id")==5 and b.get("expansion_id")==1907
                               and b.get("category_id") in single_categories]
                        if len(exact)!=32 or {blueprint_number_key(b,expansion) for b in exact}!={("RC",n,"") for n in range(1,33)}:
                            raise ValueError("Incomplete Radiant Collection identity export")
                    for index,b in enumerate(blueprints):
                        if (b.get("game_id")!=game_id or b.get("expansion_id")!=expansion["id"]
                                or b.get("category_id") not in single_categories):
                            continue
                        ids=b.get("card_market_ids")
                        ids=[] if ids is None else ids
                        if not isinstance(ids,list) or len(ids)>40:
                            generations_claims_invalid=True
                            continue
                        legacy=b.get("cardmarket_id")
                        ids=ids+([legacy] if legacy is not None else [])
                        for value in ids:
                            if isinstance(value,bool) or not str(value).isdigit() or int(value)<=0:
                                generations_claims_invalid=True
                            else:
                                generations_claims[str(int(value))].add((expansion["id"],index))
                matches = match_blueprints(refs,blueprints,expansion,single_categories,singles)
                report['sets_checked'] += 1
                report['by_release'][label] = {'checked':len(refs),'matched':len(matches)}
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
        if generations_claims_invalid:
            failed_sets.add("g1")
            report["provider_failures"]+=1
        # Cross-partition claims include unpriced and unmapped source blueprints.
        result={key:match for key,match in result.items() if not key.startswith("g1-") or (
            "g1" not in failed_sets and not generations_claims_invalid and
            len(generations_claims.get(str(match["product"]["idProduct"]),set()))==1)}
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


