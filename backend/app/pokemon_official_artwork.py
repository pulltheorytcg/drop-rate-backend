"""Exact Japanese reference art, independently verified against official assets.

The pinned type-null/PTCG-database snapshot supplies identity metadata only.
Multiple images for one printing remain unresolved; these are reference images,
never approved photography of an owned card.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlsplit

SOURCE_REPOSITORY = 'https://github.com/type-null/PTCG-database'
SOURCE_COMMIT = '18e0de2feb7a35ebe4296ede0ba6cc768961489b'
VERIFICATION = 'POKEMON_OFFICIAL_EXACT_REFERENCE_IMAGE_V1'


def official_image_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return bool(url.scheme == 'https' and url.netloc == 'www.pokemon-card.com'
                    and not url.query and not url.fragment
                    and re.fullmatch(r'/assets/images/card_images/large/[A-Za-z0-9_-]+/'
                                     r'[0-9]{6,8}_[A-Za-z0-9_-]+\.(?:jpg|png)', url.path))
    except (ValueError, TypeError):
        return False


def normalized(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def number(value):
    text = normalized(value)
    return str(int(text)) if re.fullmatch(r'[0-9]{1,4}', text) else None


def source_identity(row):
    sid = normalized(row.get('set_name'))
    local = number(row.get('number'))
    name = normalized(row.get('name'))
    jp_id = row.get('jp_id')
    url = row.get('img')
    if (not re.fullmatch(r'[A-Za-z0-9_-]{1,20}', sid) or not local or not name
            or type(jp_id) is not int or jp_id <= 0 or not official_image_url(url)
            or row.get('url') != f'https://www.pokemon-card.com/card-search/details.php/card/{jp_id}'):
        return None
    filename = urlsplit(url).path.rsplit('/', 1)[-1]
    image_set = urlsplit(url).path.rsplit('/', 2)[-2]
    if int(filename.split('_', 1)[0]) != jp_id or image_set.casefold() != sid.casefold():
        return None
    return sid.casefold(), local, name


def matching_denominator(ref, source):
    printed = normalized(ref.get('card_number')).split('/')
    if len(printed) > 2 or number(printed[0]) != number(source.get('number')):
        return False
    total = normalized(source.get('set_total'))
    if number(total):
        return len(printed) == 2 and number(printed[1]) == number(total)
    # Official promos print their series code in place of a numeric set total.
    # Accept only the same exact promo series, never a missing regular total.
    return bool(re.fullmatch(r'(?:SV|S|SM|XY|BW|M)-P', total)
                and total.casefold() == normalized(ref.get('set_id')).casefold()
                and (len(printed) == 1 or printed[1].casefold() == total.casefold()))


def artwork_candidates(refs, source_rows):
    by_key = defaultdict(list)
    for row in source_rows:
        if key := source_identity(row):
            by_key[key].append(row)
    result, rejected = [], Counter()
    duplicate_refs = Counter(row.get('provider_id') for row in refs)
    for ref in refs:
        sid, local = ref.get('set_id'), ref.get('local_id')
        pid = ref.get('provider_id')
        if (duplicate_refs[pid] != 1 or not isinstance(sid, str)
                or not isinstance(local, str) or pid != sid + '-' + local
                or ref.get('source_url') != f'https://api.tcgdex.net/v2/ja/cards/{pid}'
                or str(ref.get('image_url') or '').strip()
                or ref.get('provider', 'TCGdex') != 'TCGdex'
                or ref.get('language', 'Japanese') != 'Japanese'
                or ref.get('system_code', 'POKEMON_TCG') != 'POKEMON_TCG'):
            rejected['invalid_reference_identity'] += 1
            continue
        choices = by_key.get((normalized(sid).casefold(), number(local), normalized(ref.get('name'))), [])
        if not choices:
            rejected['no_exact_identity'] += 1
            continue
        # Check ambiguity before denominator filtering: a partial match cannot
        # erase a competing finish/parallel with the same name and number.
        if len({r['img'] for r in choices}) != 1:
            rejected['multiple_official_images'] += 1
            continue
        if not all(matching_denominator(ref, r) for r in choices):
            rejected['different_printed_total'] += 1
            continue
        source = choices[0]
        result.append({
            'provider_id': pid, 'set_id': sid, 'name': ref['name'],
            'card_number': ref['card_number'], 'local_id': local,
            'source_url': ref['source_url'], 'image_url': source['img'],
            'official_card_id': source['jp_id'], 'official_source_url': source['url'],
            'official_number': source['number'], 'official_total': source['set_total'],
        })
    return sorted(result, key=lambda row: row['provider_id']), dict(rejected)


# All identity fields and the blank image are checked again at write time.
# A receipt does not modify catalogue identity, physical stock, or media rights.
WRITE_SQL = """
with candidates as (
 select * from jsonb_to_recordset($1::jsonb) as x(
  provider_id text,set_id text,name text,card_number text,local_id text,
  source_url text,image_url text,evidence jsonb)
), changed as (
 update tcg.reference_cards r set image_url=x.image_url,
  evidence=r.evidence || jsonb_build_object('image_reference',x.evidence)
 from candidates x
 where (r.provider,r.system_code,r.language)=('TCGdex','POKEMON_TCG','Japanese')
  and r.provider_id=x.provider_id and r.set_id=x.set_id and r.name=x.name
  and r.card_number=x.card_number and r.source_url=x.source_url
  and r.evidence->>'provider_local_id'=x.local_id
  and nullif(btrim(r.image_url),'') is null
  and x.evidence->>'verification'='POKEMON_OFFICIAL_EXACT_REFERENCE_IMAGE_V1'
  and x.evidence->>'scope'='REFERENCE_ONLY_NOT_APPROVED_MEDIA'
 returning r.provider_id
) select count(*) as written from changed
"""
