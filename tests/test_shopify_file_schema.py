"""Execute the real FileCreate document against Shopify's interface contract.

This is a local GraphQL validator/executor, not a real Shopify write. The old
query fails validation before a resolver can run, reproducing the upload bug.
"""
from pathlib import Path

import pytest
from graphql import build_schema, graphql_sync, parse, validate

from app.shopify_client import ShopifyAdminClient, ShopifyApiError

SCHEMA = build_schema((Path(__file__).parent / "fixtures/shopify_files_2026_10.graphql").read_text())


@pytest.mark.asyncio
async def test_file_create_executes_against_file_interface_with_media_image_fragment():
    client = ShopifyAdminClient(shop_domain="synthetic.myshopify.com", client_id="synthetic",
                                client_secret="synthetic", api_version="2026-10")
    calls = []

    def create(_info, *, files):
        calls.append(files)
        return {"files": [{"__typename": "MediaImage", "id": "gid://shopify/MediaImage/42",
                           "fileStatus": "READY", "alt": files[0]["alt"],
                           "image": {"url": "https://cdn.shopify.com/synthetic-photo.png"}}],
                "userErrors": []}

    async def graphql(*, query, variables):
        result = graphql_sync(SCHEMA, query, root_value={"fileCreate": create}, variable_values=variables)
        assert not result.errors, result.errors
        return result.data

    client.graphql = graphql
    result = await client.create_file_from_url(source_url="https://shopify-staged-uploads.storage.googleapis.com/tmp/fixture.png",
                                               alt_text="Synthetic exact physical copy")
    assert result["image"]["url"] == "https://cdn.shopify.com/synthetic-photo.png"
    assert calls == [[{"originalSource": "https://shopify-staged-uploads.storage.googleapis.com/tmp/fixture.png",
                       "alt": "Synthetic exact physical copy", "contentType": "IMAGE"}]]
    invalid = '''mutation OldFileCreate($files:[FileCreateInput!]!) {
      fileCreate(files:$files) { files { id fileStatus alt image { url } } userErrors { field message } }
    }'''
    failures = validate(SCHEMA, parse(invalid))
    assert len(failures) == 1 and "Cannot query field 'image' on type 'File'" in failures[0].message


@pytest.mark.asyncio
@pytest.mark.parametrize("file", [{}, {"id": "gid://shopify/Product/1", "fileStatus": "READY"},
                                  {"id": "gid://shopify/MediaImage/", "fileStatus": "READY"},
                                  {"id": "gid://shopify/MediaImage/1", "fileStatus": []},
                                  {"id": "gid://shopify/MediaImage/1", "fileStatus": "UNKNOWN"}])
async def test_file_create_rejects_invalid_receipts_instead_of_silent_processing_failure(file):
    client = ShopifyAdminClient(shop_domain="synthetic.myshopify.com", client_id="synthetic",
                                client_secret="synthetic", api_version="2026-10")
    async def graphql(**_):
        return {"fileCreate": {"files": [file], "userErrors": []}}
    client.graphql = graphql
    with pytest.raises(ShopifyApiError, match="invalid image receipt"):
        await client.create_file_from_url(source_url="https://cdn.shopify.com/fixture.png", alt_text="Fixture")
