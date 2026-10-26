"""Exercise the actual HTTP middleware without unrelated router/DB startup."""
import ast
import copy
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.object_storage import ObjectStorageConfig, ObjectStorageError


def middleware():
    tree=ast.parse((Path(__file__).parents[1]/"backend/app/main.py").read_text(encoding="utf-8"))
    factory=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="create_app")
    prefix=[]
    for node in factory.body:
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and getattr(node.value.func,"id","")=="configure_market_adapters":
            break
        prefix.append(copy.deepcopy(node))
    handler=copy.deepcopy(next(n for n in factory.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="request_context"))
    handler.decorator_list=[]
    factory.body=prefix+[handler,ast.Return(value=ast.Name(id="request_context",ctx=ast.Load()))]
    factory.returns=None
    namespace=dict(os=os,ObjectStorageConfig=ObjectStorageConfig,ObjectStorageError=ObjectStorageError,
        Request=Request,JSONResponse=JSONResponse,logger=logging.getLogger(__name__),
        get_settings=lambda:SimpleNamespace(supabase_url="https://database.example",market_ingestion_enabled=False),
        _valid_request_id=lambda _: "test-request")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[])),"actual-csp-middleware","exec"),namespace)
    return namespace["create_app"]()


@pytest.mark.asyncio
@pytest.mark.parametrize("approved,reference,allowed",[
    ("false","false",False),("true","false",True),("false","true",True),("true","true",True),
])
async def test_r2_image_origin_follows_either_delivery_mode(monkeypatch,approved,reference,allowed):
    config={"TCG_OBJECT_STORE_ENABLED":"true","TCG_OBJECT_STORE_ENDPOINT":"https://account.r2.cloudflarestorage.com",
        "TCG_OBJECT_STORE_BUCKET":"private-test","TCG_OBJECT_STORE_REGION":"auto",
        "TCG_OBJECT_STORE_ACCESS_KEY_ID":"test-key","TCG_OBJECT_STORE_SECRET_ACCESS_KEY":"test-secret",
        "TCG_R2_MEDIA_DELIVERY_ENABLED":approved,"TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED":reference}
    for key,value in config.items():monkeypatch.setenv(key,value)
    request=Request({"type":"http","method":"GET","path":"/owner","headers":[]})
    async def response(_):return Response("ok")
    result=await middleware()(request,response)
    policy=result.headers["Content-Security-Policy"]
    directives={p.strip().split(" ",1)[0]:p.strip() for p in policy.split(";") if p.strip()}
    origin=config["TCG_OBJECT_STORE_ENDPOINT"]
    assert (origin in directives["img-src"]) is allowed
    assert origin not in directives["connect-src"]
    assert "test-secret" not in policy


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint",["http://insecure.example","https://example.test/path","https://user:password@example.test"])
async def test_bad_storage_config_cannot_expand_csp(monkeypatch,endpoint):
    for key,value in {"TCG_OBJECT_STORE_ENABLED":"true","TCG_OBJECT_STORE_ENDPOINT":endpoint,
        "TCG_OBJECT_STORE_BUCKET":"private-test","TCG_OBJECT_STORE_REGION":"auto",
        "TCG_OBJECT_STORE_ACCESS_KEY_ID":"key","TCG_OBJECT_STORE_SECRET_ACCESS_KEY":"secret",
        "TCG_R2_MEDIA_DELIVERY_ENABLED":"false","TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED":"true"}.items():
        monkeypatch.setenv(key,value)
    async def response(_):return Response("ok")
    result=await middleware()(Request({"type":"http","method":"GET","path":"/","headers":[]}),response)
    assert endpoint not in result.headers["Content-Security-Policy"]
    assert "password" not in result.headers["Content-Security-Policy"]
