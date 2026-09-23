from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"


def test_founder_finance_asset_exists() -> None:
    path = STATIC / "founder-finance.js"
    assert path.is_file()
    assert path.stat().st_size > 1000


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_founder_finance_javascript_has_valid_syntax() -> None:
    subprocess.run(["node", "--check", str(STATIC / "founder-finance.js")], check=True)


def test_main_serves_finance_asset_and_router() -> None:
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    assert 'from .finance import router as finance_router' in main
    assert 'founder-finance.js' in main
    assert 'app.include_router(finance_router)' in main
