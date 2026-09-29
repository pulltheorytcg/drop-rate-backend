from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER_ACTIONS = ROOT / "storefront" / "theme" / "snippets" / "header-actions.liquid"


def test_customer_account_surface_is_shopify_native() -> None:
    source = HEADER_ACTIONS.read_text()

    assert "shop.customer_accounts_enabled" in source
    assert "<shopify-account" in source
    assert 'slot="signed-out-avatar"' in source
    assert "content.account_title" in source

    # Customer storefront auth must remain separate from internal Founder/Seller auth.
    forbidden = (
        "/owner",
        "/api/v1/access",
        "supabase.auth",
        "owner_id",
        "platform_admin",
        "consignor",
    )
    lowered = source.casefold()
    for value in forbidden:
        assert value.casefold() not in lowered


def test_customer_account_surface_does_not_replace_shopify_checkout() -> None:
    source = HEADER_ACTIONS.read_text()

    # The account surface can coexist with guest checkout; it must not create a
    # custom checkout/login submission path in the header.
    assert "<form" not in source
    assert 'name="checkout"' not in source
    assert "/api/v1/" not in source


def test_header_cart_and_customer_account_remain_separate_actions() -> None:
    source = HEADER_ACTIONS.read_text()

    assert "<shopify-account" in source
    assert "header-actions__cart-icon" in source
    assert "routes.cart_url" in source
