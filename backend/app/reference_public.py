"""Public checklist adapters. Facts are references, never verified printings."""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

from .reference_feeds import ReferenceFeedError


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def all(self, tag=None, cls=None):
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                yield child
            yield from child.all(tag, cls)

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def bandai_sets(content, *, fusion):
    result = {}
    for a in Document(content).root.all('a'):
        if fusion:
            sid = a.attrs.get('data-val','')
            if not re.fullmatch(r'58\d{4}', sid):
                continue
        else:
            query = parse_qs(urlparse(a.attrs.get('href','')).query)
            sid = (query.get('category') or [''])[0]
            if not re.fullmatch(r'\d{6}',sid):
                continue
        if a.text():
            result[sid] = a.text()
    if not result:
        raise ReferenceFeedError('Bandai checklist has no set metadata')
    return result


def bandai_cards(content, *, fusion, url, set_id):
    root = Document(content).root
    cards = []
    if fusion:
        for a in root.all('a', 'cardStr'):
            images = list(a.all('img'))
            detail = a.attrs.get('data-src','')
            query = parse_qs(urlparse(detail).query)
            number = (query.get('card_no') or [''])[0]
            if not images or not number:
                raise ReferenceFeedError('Incomplete Fusion World card identity')
            img = images[0].attrs
            label = img.get('alt','')
            name = label[len(number):].strip() if label.startswith(number) else ''
            if not name:
                raise ReferenceFeedError('Missing Fusion World card name')
            image = urljoin(url, img.get('data-src') or img.get('src',''))
            variant = (query.get('p') or [''])[0]
            cards.append({'provider_id':f'{set_id}:{number}{variant}', 'card_number':number,
                'name':name,'image_url':image,'source_url':urljoin(url,detail),
                'evidence':{'provider_variant':variant,'physical_finish_unresolved':True,
                    'detail_level':'OFFICIAL_CHECKLIST','set_membership_id':set_id}})
        declared = re.search(r'Result\s*<span[^>]*>(\d+)</span>', content)
        if declared and len(cards) != int(declared[1]):
            raise ReferenceFeedError('Fusion World checklist count mismatch')
    else:
        for node in root.all('dl','cardListCol'):
            def field(cls):
                match = next(node.all(cls=cls), None)
                return match.text() if match else ''
            def value(cls):
                match = next(node.all('dl',cls),None)
                value = next(match.all('dd'),None) if match else None
                return value.text() if value else None
            image = next(node.all('img','zoomcard'),None)
            number,name=field('cardNumber'),field('cardName')
            if not number or not name or image is None:
                raise ReferenceFeedError('Incomplete Masters card identity')
            image_url = urljoin(url,image.attrs['src'])
            asset_id = urlparse(image_url).path.rsplit('/',1)[-1]
            cards.append({'provider_id':f'{set_id}:{asset_id}','card_number':number,
                'name':name,'rarity':value('rarityCol'),'image_url':image_url,'source_url':url,
                'evidence':{'card_type':value('typeCol'),'face':'back' if 'cardBack' in node.attrs.get('class','') else 'front',
                    'physical_finish_unresolved':True,'detail_level':'OFFICIAL_CHECKLIST',
                    'provider_series':value('seriesCol'),'set_membership_id':set_id}})
    if not cards:
        raise ReferenceFeedError('Bandai set returned no cards; not marked complete')
    return cards


def archive_page(content, family):
    """Read the public rendered card-list props, never evaluate page scripts."""
    arrays=[]
    for match in re.finditer(r'self\.__next_f\.push\((.*?)\)</script>',content):
        try:
            payload=json.loads(match[1])
            body=payload[1] if len(payload)>1 else None
            if not isinstance(body,str):
                continue
            marker=body.find('"cards":')
            if marker>=0:
                cards,_=json.JSONDecoder().raw_decode(body[marker+8:])
                if isinstance(cards,list): arrays.append(cards)
        except (ValueError,TypeError,IndexError):
            continue
    if len(arrays)!=1 or not arrays[0]:
        raise ReferenceFeedError('Naruto checklist response has no unique card list')
    pages=[int(p) for p in re.findall(r'href="/archive/'+re.escape(family)+r'/cards/page/(\d+)"',content)]
    return arrays[0],max(pages,default=1)


async def bandai_feed(feeds, *, fusion):
    variants=[('en','English'),('jp','Japanese')] if fusion else [('us-en','English')]
    for locale,language in variants:
        base=f'https://www.dbs-cardgame.com/fw/{locale}/cardlist/' if fusion else 'https://www.dbs-cardgame.com/us-en/cardlist/'
        sets=bandai_sets(await feeds.get_text(base,search='true'),fusion=fusion)
        for sid,name in sets.items():
            parameter='category[]' if fusion else 'category'
            url=str(__import__('httpx').URL(base,params={'search':'true',parameter:sid}))
            try:
                cards=bandai_cards(await feeds.get_text(url),fusion=fusion,url=url,set_id=sid)
            except ReferenceFeedError as exc:
                feeds.failures.append({'source_url':url,'reason':str(exc)})
                continue
            yield {'provider':'Bandai Official','system_code':'DRAGON_BALL_SUPER_FUSION_WORLD' if fusion else 'DRAGON_BALL_SUPER_MASTERS',
                'language':language,'set_id':sid,'name':name,'source_url':url},cards


async def naruto_feed(feeds, *, kayou):
    family='kayou' if kayou else 'classic-ccg'
    base=f'https://narutocardgame.gg/archive/{family}'
    first=await feeds.get_text(f'{base}/cards')
    first_cards,pages=archive_page(first,family)
    if pages>100: raise ReferenceFeedError('Naruto page limit exceeded')
    groups=defaultdict(dict)
    seen_pages=set()
    for page in range(1,pages+1):
        rows=first_cards if page==1 else archive_page(await feeds.get_text(f'{base}/cards/page/{page}'),family)[0]
        fingerprint=tuple(row['slug'] for row in rows)
        if fingerprint in seen_pages: raise ReferenceFeedError('Repeated Naruto page')
        seen_pages.add(fingerprint)
        for row in rows:
            sid=row.get('setSlug')
            if not sid or not row.get('cardNumber') or not row.get('name'):
                raise ReferenceFeedError('Naruto reference lacks required identity')
            # Source does not declare physical language. English translated names
            # cannot prove an English card; keep language unknown for review.
            groups[sid][row['slug']]={'provider_id':f"{sid}:{row['slug']}",'name':row['name'],
                'card_number':row['cardNumber'],'rarity':row.get('rarity'),
                'image_url':urljoin(base+'/',row['imageUrl']) if row.get('imageUrl') else None,
                'source_url':f"{base}/cards/{row['slug']}",
                'evidence':{'tier':row.get('tier'),'wave':row.get('wave'),'box_code':row.get('boxCode'),
                    'provider_variant':row.get('variant'),'card_type':row.get('cardType'),
                    'language_unverified':True,'edition_unresolved':True,
                    'physical_finish_unresolved':True,'detail_level':'COMMUNITY_CHECKLIST'}}
    for sid,items in groups.items():
        yield {'provider':'Naruto Card Game Archive','system_code':'NARUTO_KAYOU' if kayou else 'NARUTO_BANDAI_LEGACY',
            'language':'Unknown','set_id':sid,'name':sid.replace('-',' ').title(),'source_url':f'{base}/cards'},list(items.values())
