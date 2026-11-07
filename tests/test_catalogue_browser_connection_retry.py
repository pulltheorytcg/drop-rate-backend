"""Read-only catalogue retries must not bypass owner authorization or hide SQL bugs."""

import asyncio
import inspect

import asyncpg
import pytest

from app.catalogue_browser import products, retry_broken_catalogue_read


def test_product_route_preserves_fastapi_signature_for_auth_and_filters():
    signature=inspect.signature(products)
    assert 'request' in signature.parameters
    assert 'user' in signature.parameters
    assert 'access' in signature.parameters
    assert 'system_code' in signature.parameters


def test_one_broken_read_only_connection_can_retry_with_new_request_context(caplog):
    calls=0
    async def fake_browse(*, access):
        nonlocal calls
        calls+=1
        if calls==1:
            raise asyncpg.InterfaceError('sensitive database detail')
        return {'items':['safe']}

    result=asyncio.run(retry_broken_catalogue_read(fake_browse)(access={'owner_id':'unchanged'}))
    assert result=={'items':['safe']}
    assert calls==2
    assert 'CATALOGUE_PRODUCTS_CONNECTION_RETRY type=InterfaceError' in caplog.text
    assert 'sensitive database detail' not in caplog.text


def test_invalid_query_or_authorization_is_never_retried():
    calls=0
    async def fake_browse():
        nonlocal calls
        calls+=1
        raise ValueError('invalid query')

    with pytest.raises(ValueError,match='invalid query'):
        asyncio.run(retry_broken_catalogue_read(fake_browse)())
    assert calls==1


def test_exhausted_catalogue_connection_retry_still_fails():
    calls=0
    async def fake_browse():
        nonlocal calls
        calls+=1
        raise ConnectionResetError('database unavailable')

    with pytest.raises(ConnectionResetError):
        asyncio.run(retry_broken_catalogue_read(fake_browse)())
    assert calls==2
