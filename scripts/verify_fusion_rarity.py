"""Verify official rarity metadata for exported Fusion World base references.

Writes a reviewable manifest only. Required input fields: provider_id, set_id,
language, name, card_number, source_url, image_url, and variant. A database apply
uses app.fusion_official_rarity.WRITE_SQL, which rechecks the current identity.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx

from app.fusion_official_rarity import attach_rarities, filtered_cards


async def verify(refs):
    groups=defaultdict(list)
    for row in refs:
        if (row.get('language') in {'English','Japanese'}
                and re.fullmatch(r'58[34]0[0-9]{2}',row.get('set_id',''))):
            groups[(row['language'],row['set_id'])].append(row)
    if len(groups)>40:
        raise ValueError('Expected no more than 40 language/release groups')
    semaphore=asyncio.Semaphore(3)
    stopped=asyncio.Event()
    sources=defaultdict(list)
    failures=[]
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        async def fetch(language,sid,rarity):
            locale='en' if language=='English' else 'jp'
            url=str(httpx.URL(f'https://www.dbs-cardgame.com/fw/{locale}/cardlist/',params={
                'search':'true','category[]':sid,'rarity[]':rarity}))
            async with semaphore:
                if stopped.is_set():
                    failures.append(dict(url=url,error='Stopped after rate limit'))
                    return
                try:
                    response=await client.get(url)
                    if response.status_code==429:stopped.set()
                    response.raise_for_status()
                    if len(response.content)>5_000_000:
                        raise ValueError('Oversized source page')
                    sources[(language,sid)].extend(filtered_cards(
                        response.text,url=url,set_id=sid,rarity=rarity))
                except (httpx.HTTPError,ValueError) as exc:
                    failures.append(dict(url=url,error=str(exc)[:180]))
        await asyncio.gather(*(fetch(language,sid,rarity)
            for language,sid in groups for rarity in ('C','UC')))
    entries=[]
    for (language,sid),rows in groups.items():
        cards=[dict(r,evidence={'provider_variant':r.get('variant')}) for r in rows]
        for card in attach_rarities(cards,sources[(language,sid)],set_id=sid,language=language):
            receipt=card['evidence'].get('rarity_reference')
            if receipt:
                entries.append({**receipt['reference_identity'],'rarity':card['rarity'],'receipt':receipt})
    entries.sort(key=lambda row:(row['language'],row['provider_id']))
    return dict(verified_at=datetime.now(timezone.utc).isoformat(),
                source_requests=len(groups)*2,entries=entries,failures=failures)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--refs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=asyncio.run(verify(json.loads(args.refs.read_text())))
    args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps({'verified':len(result['entries']),'source_requests':result['source_requests'],
                      'failures':result['failures']}),flush=True)
    if result['failures']:
        raise SystemExit(2)


if __name__=='__main__':main()
