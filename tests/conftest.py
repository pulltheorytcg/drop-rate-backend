"""Keep optional R2-first production jobs inert in the isolated test process.

Railway runs this same suite during pre-deploy with production variables present.
Each R2-first test opts into its own mocked sources explicitly. This fixture does
not change production configuration or weaken any test/permission gate.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_r2_first_flags(monkeypatch):
    monkeypatch.delenv('TCG_R2_FIRST_CATALOGUE_ENABLED', raising=False)
    monkeypatch.delenv('TCG_R2_FIRST_IMPORT_SOURCES', raising=False)
