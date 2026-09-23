from app.parse_client import _response_shape_diagnostics


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
