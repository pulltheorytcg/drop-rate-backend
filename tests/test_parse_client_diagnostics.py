from app.parse_client import _request_headers, _response_shape_diagnostics


def test_response_shape_diagnostics_reports_counts_and_titles_only() -> None:
    keys, counts, titles = _response_shape_diagnostics(
        {
            "page": "1",
            "items": [
                {"title": "Charizard V 019/189 PSA 9", "price": "£24.99"},
                {"title": "Another card", "url": "https://example.invalid/item"},
            ],
            "query": "Charizard V",
        }
    )

    assert keys == ["items", "page", "query"]
    assert counts == {"items": 2}
    assert titles == ["Charizard V 019/189 PSA 9", "Another card"]


def test_response_shape_diagnostics_ignores_non_list_secrets() -> None:
    keys, counts, titles = _response_shape_diagnostics(
        {
            "token": "do-not-log-value",
            "status": "ok",
        }
    )

    assert keys == ["status", "token"]
    assert counts == {}
    assert titles == []


def test_request_headers_omit_snapshot_for_current_canonical_release() -> None:
    headers = _request_headers(api_key="pmx_test_secret", snapshot_version=None)

    assert headers["X-API-Key"] == "pmx_test_secret"
    assert headers["Accept"] == "application/json"
    assert "API-Snapshot-Version" not in headers


def test_request_headers_can_deliberately_pin_known_snapshot() -> None:
    headers = _request_headers(api_key="pmx_test_secret", snapshot_version=12)

    assert headers["API-Snapshot-Version"] == "12"
