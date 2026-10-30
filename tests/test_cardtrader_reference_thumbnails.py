"""Real provider thumbnail dimensions must display without weakening scan input."""
import base64
import io

import httpx
import pytest
from PIL import Image

from app import recognition_images as images, r2_media, r2_reference_images
from app.object_storage import ObjectStorageConfig, S3ObjectStorage
from test_r2_reference_images import MemoryR2, Pool, PRINT

URL = ('https://cardtrader.com/uploads/blueprints/image/153104/'
       'preview_galarian-weezing-rare-shiny-sv77-shining-fates.png')
REDIRECT = URL.replace('://cardtrader.com/', '://www.cardtrader.com/')


def picture(width=180):
    output = io.BytesIO()
    Image.new('RGB', (width, 250), '#28a488').save(output, 'PNG')
    return output.getvalue()


@pytest.mark.asyncio
async def test_exact_thumbnail_redirect_download_and_verified_r2_receipt(monkeypatch):
    data = picture()
    requests = []
    def serve(request):
        requests.append(str(request.url))
        if str(request.url) == URL:
            return httpx.Response(301, headers={'location': REDIRECT})
        assert str(request.url) == REDIRECT
        return httpx.Response(200, headers={'content-type': 'image/png'}, content=data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(images, '_reference_http_client', lambda: client)
    images._clear_reference_image_hash_cache()
    storage_client = MemoryR2()
    store = S3ObjectStorage(ObjectStorageConfig(
        'https://account.r2.cloudflarestorage.com', 'private-media', 'auto', 'key', 'secret'),
        client=storage_client)
    monkeypatch.setattr(r2_reference_images, 'configured_object_storage', lambda: store)
    monkeypatch.setitem(PRINT, 'image_url', URL)
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(r2_reference_images.asyncio, 'to_thread', inline)
    pool = Pool([PRINT])
    try:
        result = await r2_reference_images.mirror_reference_images(
            pool, limit=1, request_id='thumbnail-regression')
        assert result['mirrored'] == 1 and result['failed'] == 0
        assert requests == [URL, REDIRECT]
        saved = pool.connection.records[0][1]
        assert saved[4] == URL
        assert Image.open(io.BytesIO(storage_client.objects[saved[5]])).size == (180, 250)
        # Neither an uploaded recognition image nor reference fingerprinting
        # may use the relaxed display threshold.
        with pytest.raises(images.RecognitionImageError, match='resolution'):
            images.decode_image_data_url(
                'data:image/png;base64,' + base64.b64encode(data).decode(), max_bytes=100000)
        assert await images._reference_image_hashes_uncached(
            URL, max_bytes=100000, timeout_seconds=12) is None
        with pytest.raises(images.RecognitionImageError, match='resolution'):
            r2_media.optimized_media_bytes(images.ReferenceImagePayload('image/png', data))
    finally:
        images._clear_reference_image_hash_cache()
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('source,target,width,body', [
    ('https://assets.tcgdex.net/en/test/high.webp', None, 180, None),
    ('https://cardtrader.com/private/preview_card.png', None, 180, None),
    (URL, 'https://assets.tcgdex.net/en/test/high.webp', 180, None),
    (URL, REDIRECT, 179, None),
    (URL, REDIRECT, 180, b'<html>not an image</html>'),
])
async def test_thumbnail_exception_retains_source_size_and_raster_guards(
        monkeypatch, source, target, width, body):
    def serve(request):
        if target and str(request.url) == source:
            return httpx.Response(301, headers={'location': target})
        return httpx.Response(200, headers={'content-type': 'image/png'},
                              content=body if body is not None else picture(width))
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        monkeypatch.setattr(images, '_reference_http_client', lambda: client)
        assert await images._fetch_reference_image_uncached(
            source, max_bytes=100000, timeout_seconds=12) is None


@pytest.mark.parametrize('url', [
    URL.replace('cardtrader.com', 'cardtrader.com.evil.test'),
    URL.replace('https://', 'http://'),
    URL.replace('cardtrader.com', 'cardtrader.com:8080'),
    URL.replace('cardtrader.com', 'user:pass@cardtrader.com'),
    URL + '?redirect=elsewhere', URL + '#fragment',
])
def test_thumbnail_exception_does_not_accept_unsafe_urls(url):
    assert images.reference_display_min_dimension(url) == 200
