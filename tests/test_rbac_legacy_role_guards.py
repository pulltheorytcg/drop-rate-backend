from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "finance": ROOT / "backend" / "app" / "finance.py",
    "shopify": ROOT / "backend" / "app" / "shopify.py",
    "stripe": ROOT / "backend" / "app" / "stripe_connect.py",
}


def test_legacy_founder_membership_guards_are_removed() -> None:
    for path in FILES.values():
        source = path.read_text()
        assert 'owner["role"] != "FOUNDER"' not in source
        assert 'owner["role"] == "FOUNDER"' not in source


def test_privileged_finance_shopify_and_stripe_paths_use_platform_admin_guard() -> None:
    finance = FILES["finance"].read_text()
    shopify = FILES["shopify"].read_text()
    stripe = FILES["stripe"].read_text()

    assert "from .access_control import require_platform_admin" in finance
    assert "await require_platform_admin(connection)" in finance

    assert "from .access_control import require_platform_admin" in shopify
    assert "await require_platform_admin(connection)" in shopify

    assert "from .access_control import require_platform_admin" in stripe
    assert "async def _require_founder_operator" in stripe
    assert "await require_platform_admin(connection)" in stripe
