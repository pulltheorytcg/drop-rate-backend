"""Read-only R2 diagnostic must report state without leaking provider secrets."""
from __future__ import annotations

from types import SimpleNamespace

from scripts import probe_object_storage_connectivity as probe


def test_object_store_probe_succeeds_without_disclosing_config(monkeypatch, capsys):
    config = object()
    seen = []

    class FakeStorage:
        def __init__(self, received):
            assert received is config

        def connectivity(self):
            seen.append("checked")

    monkeypatch.setattr(probe, "ObjectStorageConfig", SimpleNamespace(from_env=lambda: config))
    monkeypatch.setattr(probe, "S3ObjectStorage", FakeStorage)

    assert probe.main() == 0
    captured = capsys.readouterr()
    assert "DROP_RATE_R2_PROBE_START" in captured.out
    assert "DROP_RATE_R2_PROBE_PASS" in captured.out
    assert seen == ["checked"]
    assert captured.err == ""


def test_object_store_probe_fails_closed_without_leaking_exception(monkeypatch, capsys):
    config = object()

    class FailingStorage:
        def __init__(self, received):
            assert received is config

        def connectivity(self):
            raise RuntimeError("provider error may contain SECRET_ACCESS_KEY")

    monkeypatch.setattr(probe, "ObjectStorageConfig", SimpleNamespace(from_env=lambda: config))
    monkeypatch.setattr(probe, "S3ObjectStorage", FailingStorage)

    assert probe.main() == 1
    captured = capsys.readouterr()
    assert "DROP_RATE_R2_PROBE_FAILED:RuntimeError" in captured.err
    assert "SECRET_ACCESS_KEY" not in captured.out + captured.err


def test_object_store_probe_rejects_disabled_storage(monkeypatch, capsys):
    monkeypatch.setattr(probe, "ObjectStorageConfig", SimpleNamespace(from_env=lambda: None))
    assert probe.main() == 2
    captured = capsys.readouterr()
    assert "DROP_RATE_R2_PROBE_FAILED:DISABLED" in captured.err
