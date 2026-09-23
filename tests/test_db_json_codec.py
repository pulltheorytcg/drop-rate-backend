import json

import pytest

from app.db import _encode_json, _init_connection


def test_json_encoder_preserves_pre_serialized_payloads() -> None:
    raw = '{"status":"READY","issues":[]}'
    assert _encode_json(raw) == raw


def test_json_encoder_serializes_python_objects() -> None:
    assert json.loads(_encode_json({"status": "READY", "issues": []})) == {
        "status": "READY",
        "issues": [],
    }
    assert json.loads(_encode_json([1, 2, 3])) == [1, 2, 3]


class FakeConnection:
    def __init__(self) -> None:
        self.calls = []

    async def set_type_codec(self, type_name, **kwargs) -> None:
        self.calls.append((type_name, kwargs))


@pytest.mark.asyncio
async def test_pool_connection_initializes_json_and_jsonb_decoders() -> None:
    connection = FakeConnection()
    await _init_connection(connection)

    assert [name for name, _ in connection.calls] == ["json", "jsonb"]
    for _, kwargs in connection.calls:
        assert kwargs["schema"] == "pg_catalog"
        assert kwargs["format"] == "text"
        assert kwargs["decoder"]('{"a":1}') == {"a": 1}
        assert kwargs["encoder"]('{"a":1}') == '{"a":1}'
