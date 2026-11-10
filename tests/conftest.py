"""Keep production-only R2-first and capacity operator flags isolated in tests.

Railway runs this same suite during pre-deploy with production variables present.
Tests explicitly opt into mocked sources and operator hold when needed. This fixture does
not change production configuration or weaken any test/permission gate.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_r2_first_flags(monkeypatch):
    monkeypatch.delenv('TCG_R2_FIRST_CATALOGUE_ENABLED', raising=False)
    monkeypatch.delenv('TCG_R2_FIRST_IMPORT_SOURCES', raising=False)
    # Railway runs pytest with production env. Only the test process is clean;
    # the API process still honours the explicit live bulk hold.
    monkeypatch.delenv('DROP_RATE_CATALOGUE_BULK_HOLD', raising=False)
    # Production is configured Pro; individual tests specify it explicitly.
    # Protect old Free-plan regression tests from inherited Railway settings.
    monkeypatch.delenv('DROP_RATE_SUPABASE_PLAN', raising=False)
