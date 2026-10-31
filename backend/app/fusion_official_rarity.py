"""Publisher-confirmed C/UC metadata for exact Fusion World booster cards."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from urllib.parse import parse_qs, urlsplit

from .reference_feeds import ReferenceFeedError

VERIFICATION = 'BANDAI_OFFICIAL_FILTERED_RARITY_V1'
IDENTITY_FIELDS = ('provider_id', 'name', 'card_number', 'source_url', 'image_url')


def filtered_cards(content, *, url, set_id, rarity):
    from .reference_public import Document, bandai_cards
    parsed = urlsplit(url)
    locale = 'en' if set_id.startswith('583') else 'jp'
    if (rarity not in {'C', 'UC'} or not re.fullmatch(r'58[34]0[0-9]{2}', set_id)
            or parsed.scheme != 'https' or parsed.netloc != 'www.dbs-cardgame.com'
            or parsed.path != f'/fw/{locale}/cardlist/' or parsed.fragment
            or parse_qs(parsed.query) != {'search': ['true'], 'category[]': [set_id], 'rarity[]': [rarity]}):
        raise ReferenceFeedError('Invalid Fusion World rarity source')
    root = Document(content).root
    checked = [n.attrs.get('value') for n in root.all('input')
               if n.attrs.get('name') == 'rarity[]' and 'checked' in n.attrs]
    marker = 'Result' if locale == 'en' else '検索結果'
    count = re.search(marker + r'\s*<span[^>]*>(\d+)</span>', content)
    # A missing/changed marker is not evidence of a complete card list.
    if checked != [rarity] or count is None:
        raise ReferenceFeedError('Unconfirmed Fusion World rarity filter/count')
    if int(count[1]) == 0 and not list(root.all('a', 'cardStr')):
        return []
    cards = bandai_cards(content, fusion=True, url=url, set_id=set_id)
    if len(cards) != int(count[1]):
        raise ReferenceFeedError('Fusion World rarity checklist count mismatch')
    digest = hashlib.sha256(content.encode()).hexdigest()
    return [dict(card, rarity=rarity, rarity_source_url=url, source_sha256=digest) for card in cards]


def attach_rarities(cards, sources, *, set_id, language):
    """Never borrow metadata from a parallel or a different checklist entry."""
    if language not in {'English', 'Japanese'}:
        return cards
    expected = '583' if language == 'English' else '584'
    if not set_id.startswith(expected) or not re.fullmatch(r'58[34]0[0-9]{2}', set_id):
        return cards
    by_id = defaultdict(list)
    for source in sources:
        by_id[source['provider_id']].append(source)
    output = []
    for card in cards:
        choices = by_id.get(card['provider_id'], [])
        number = card.get('card_number', '')
        if (len(choices) != 1 or not re.fullmatch(r'FB[0-9]{2}-[0-9]{3}', number)
                or number[:4] != 'FB' + set_id[-2:]
                or card['provider_id'] != set_id + ':' + number
                or (card.get('evidence') or {}).get('provider_variant') != ''):
            output.append(card)
            continue
        source = choices[0]
        if (source.get('rarity') not in {'C', 'UC'}
                or source.get('evidence', {}).get('provider_variant') != ''
                or card.get('rarity') not in {None, source['rarity']}
                or not all(card.get(k) == source.get(k) for k in IDENTITY_FIELDS)):
            output.append(card)
            continue
        identity = {k: card[k] for k in IDENTITY_FIELDS}
        receipt = {
            'verification': VERIFICATION, 'rarity': source['rarity'],
            'filtered_source_url': source['rarity_source_url'],
            'source_sha256': source['source_sha256'],
            'reference_identity': dict(identity, set_id=set_id, language=language),
        }
        output.append(dict(card, rarity=source['rarity'], evidence={
            **(card.get('evidence') or {}), 'rarity_reference': receipt}))
    return output


def verified_base_reference(row):
    evidence=row.get('evidence') or {}
    if isinstance(evidence,str):
        try: evidence=json.loads(evidence)
        except ValueError: return False
    if not isinstance(evidence,dict):return False
    receipt=evidence.get('rarity_reference') or {}
    if not isinstance(receipt,dict):return False
    sid,number=row.get('set_id',''),row.get('card_number','')
    language=row.get('language')
    return bool(row.get('provider')=='Bandai Official'
        and row.get('system_code')=='DRAGON_BALL_SUPER_FUSION_WORLD'
        and language in {'English','Japanese'} and row.get('rarity') in {'C','UC'}
        and isinstance(sid,str) and re.fullmatch(r'58[34]0[0-9]{2}',sid)
        and sid.startswith('583' if language=='English' else '584')
        and isinstance(number,str) and re.fullmatch(r'FB[0-9]{2}-[0-9]{3}',number)
        and number[:4]=='FB'+sid[-2:] and row.get('provider_id')==sid+':'+number
        and evidence.get('provider_variant')==''
        and receipt.get('verification')==VERIFICATION and receipt.get('rarity')==row['rarity']
        and receipt.get('reference_identity')=={
            **{k:row.get(k) for k in IDENTITY_FIELDS},'set_id':sid,'language':language})


VERIFIED_BASE_SQL = """(
 r.provider='Bandai Official' and r.system_code='DRAGON_BALL_SUPER_FUSION_WORLD'
 and r.language in ('English','Japanese') and r.rarity in ('C','UC')
 and r.set_id ~ '^58[34]0[0-9]{2}$'
 and left(r.set_id,3)=case when r.language='English' then '583' else '584' end
 and r.card_number ~ '^FB[0-9]{2}-[0-9]{3}$'
 and left(r.card_number,4)='FB'||right(r.set_id,2)
 and r.provider_id=r.set_id||':'||r.card_number
 and r.evidence->>'provider_variant'=''
 and r.evidence->'rarity_reference'->>'verification'='BANDAI_OFFICIAL_FILTERED_RARITY_V1'
 and r.evidence->'rarity_reference'->>'rarity'=r.rarity
 and r.evidence->'rarity_reference'->'reference_identity'=jsonb_build_object(
  'provider_id',r.provider_id,'set_id',r.set_id,'name',r.name,'card_number',r.card_number,
  'source_url',r.source_url,'image_url',r.image_url,'language',r.language)
)"""


WRITE_SQL = """
with candidates as (
 select * from jsonb_to_recordset($1::jsonb) as x(
  language text,provider_id text,set_id text,name text,card_number text,
  source_url text,image_url text,rarity text,receipt jsonb)
), changed as (
 update tcg.reference_cards r set rarity=x.rarity,
  evidence=r.evidence || jsonb_build_object('rarity_reference',x.receipt)
 from candidates x
 where r.provider='Bandai Official' and r.system_code='DRAGON_BALL_SUPER_FUSION_WORLD'
  and r.language=x.language and r.provider_id=x.provider_id and r.set_id=x.set_id
  and r.name=x.name and r.card_number=x.card_number and r.source_url=x.source_url
  and r.image_url=x.image_url and r.rarity is null
  and r.evidence->>'provider_variant'='' and x.rarity in ('C','UC')
  and x.receipt->>'verification'='BANDAI_OFFICIAL_FILTERED_RARITY_V1'
  and x.receipt->>'rarity'=x.rarity
  and x.receipt->'reference_identity'=jsonb_build_object(
   'provider_id',r.provider_id,'set_id',r.set_id,'name',r.name,'card_number',r.card_number,
   'source_url',r.source_url,'image_url',r.image_url,'language',r.language)
 returning r.provider_id
) select count(*) as written from changed
"""
