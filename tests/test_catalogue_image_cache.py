import asyncio
import io

import httpx
import pytest
from PIL import Image

from app import catalogue_artwork as artwork
from app import recognition_images as images


def png():
    output=io.BytesIO();Image.new('RGB',(768,1080),'navy').save(output,format='PNG');return output.getvalue()


@pytest.mark.asyncio
async def test_concurrent_images_share_a_download_and_one_cancel_does_not_poison_cache(monkeypatch):
    images._clear_reference_image_hash_cache();started=asyncio.Event();release=asyncio.Event();calls=[]
    async def fetch(url,**kwargs):
        calls.append(url);started.set();await release.wait()
        return images.ReferenceImagePayload('image/png',png())
    monkeypatch.setattr(images,'_fetch_reference_image_uncached',fetch)
    url='https://en.onepiece-cardgame.com/images/cardlist/card/EB04-007_p2.png'
    first=asyncio.create_task(images.reference_image_bytes(url));await started.wait()
    second=asyncio.create_task(images.reference_image_bytes(url));await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):await first
    release.set();payload=await second
    assert await images.reference_image_bytes(url)==payload and len(calls)==1
    assert await images.reference_image_bytes(url,max_bytes=1) is not payload


@pytest.mark.asyncio
async def test_thumbnail_cache_is_bounded_and_keeps_original_pixels_separate(monkeypatch):
    artwork._cache.clear();calls=[];original=images.ReferenceImagePayload('image/png',png())
    async def fetch(url):calls.append(url);await asyncio.sleep(0);return original
    monkeypatch.setattr(artwork,'reference_image_bytes',fetch);monkeypatch.setattr(artwork,'MAX_ENTRIES',2)
    one,two=await asyncio.gather(artwork.reference_thumbnail('a'),artwork.reference_thumbnail('a'))
    assert one==two and calls==['a'] and original.content_type=='image/png'
    assert one.content_type=='image/webp' and len(one.data)<len(original.data)
    with Image.open(io.BytesIO(one.data)) as image:assert image.size==(384,540)
    await artwork.reference_thumbnail('b');assert await artwork.reference_thumbnail('a')==one
    await artwork.reference_thumbnail('c');assert list(artwork._cache)==['a','c']
    monkeypatch.setattr(artwork,'MAX_BYTES',1)
    await artwork.reference_thumbnail('d');assert not artwork._cache


@pytest.mark.asyncio
async def test_shared_http_client_retains_redirect_type_and_size_guards(monkeypatch):
    calls=[]
    async def handler(request):
        calls.append(str(request.url))
        if request.url.path=='/unsafe.png':return httpx.Response(302,headers={'location':'http://127.0.0.1/secret'})
        if request.url.path=='/wrong.png':return httpx.Response(200,headers={'content-type':'text/html'},content=b'<html>')
        if request.url.path=='/large.png':return httpx.Response(200,headers={'content-type':'image/png','content-length':'2000001'},content=b'bad')
        return httpx.Response(200,headers={'content-type':'image/png'},content=png())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(images,'_REFERENCE_HTTP_CLIENT',client)
        for path in ('unsafe','wrong','large'):
            assert await images._fetch_reference_image_uncached('https://assets.tcgdex.net/'+path+'.png',max_bytes=2000000,timeout_seconds=1) is None
        first=await images._fetch_reference_image_uncached('https://assets.tcgdex.net/good.png',max_bytes=2000000,timeout_seconds=1)
        assert first.content_type=='image/png' and images._reference_http_client() is client
    assert len(calls)==4 and not any('127.0.0.1' in url for url in calls)


@pytest.mark.asyncio
async def test_queue_limits_do_not_block_a_cached_image(monkeypatch):
    import time
    payload=images.ReferenceImagePayload('image/png',png())
    url='https://assets.tcgdex.net/cached.png'
    monkeypatch.setattr(images,'_REFERENCE_BYTES_INFLIGHT',{str(i):None for i in range(64)})
    images._cache_reference_image_bytes(url,payload)
    assert await images.reference_image_bytes(url)==payload
    assert await images.reference_image_bytes('https://assets.tcgdex.net/cold.png') is None
    monkeypatch.setattr(artwork,'_inflight',{str(i):None for i in range(64)})
    monkeypatch.setattr(artwork,'_cache',__import__('collections').OrderedDict({url:(time.monotonic()+60,payload)}))
    assert await artwork.reference_thumbnail(url)==payload
    assert await artwork.reference_thumbnail('cold') is None
