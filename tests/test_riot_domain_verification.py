"""Riot Developer Portal exact public domain verification contract."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


TOKEN = b"0ff393a7-a26d-4b6c-aa32-a949a3890afd"
STATIC_FILE = Path(__file__).resolve().parents[1] / "backend/app/static/riot.txt"


def test_riot_verification_file_is_exact_bytes_without_newline() -> None:
    assert STATIC_FILE.read_bytes() == TOKEN
    assert len(TOKEN) == 36


def test_riot_verification_public_root_endpoint() -> None:
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/riot.txt")
        assert response.status_code == 200
        assert response.content == TOKEN
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["cache-control"] == "no-store"
        assert "text/html" not in response.headers["content-type"]

        head = client.head("/riot.txt")
        assert head.status_code == 200
        assert head.content == b""
