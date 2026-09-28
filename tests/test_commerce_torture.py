from __future__ import annotations

import itertools

import pytest

from app.finance import allocate_minor
from app.shopify_pipeline import ShopifyProcessingError, _minor, _parse_order_lines


@pytest.mark.parametrize("total", range(0, 101))
@pytest.mark.parametrize("count", range(1, 9))
def test_penny_allocation_never_creates_or_loses_money(total: int, count: int) -> None:
    allocations = allocate_minor(total, [1] * count)
    assert len(allocations) == count
    assert sum(allocations) == total
    assert all(value >= 0 for value in allocations)
    assert max(allocations) - min(allocations) <= 1


@pytest.mark.parametrize(
    ("total", "weights"),
    [
        (1, [1, 99]),
        (2, [1, 1, 1]),
        (499, [99, 1]),
        (999, [333, 333, 334]),
        (10000, [0, 0, 0]),
        (2**31 - 1, [1, 2, 3, 5, 8]),
    ],
)
def test_weighted_allocation_is_conservative_and_deterministic(total: int, weights: list[int]) -> None:
    first = allocate_minor(total, weights)
    second = allocate_minor(total, weights)
    assert first == second
    assert sum(first) == total
    assert all(value >= 0 for value in first)


@pytest.mark.parametrize("bad_total", [-1, -100, -2**31])
def test_negative_allocation_fails_closed(bad_total: int) -> None:
    with pytest.raises(ValueError):
        allocate_minor(bad_total, [1, 1])


@pytest.mark.parametrize("weights", [[1, -1], [-1], [0, -10, 1]])
def test_negative_weights_fail_closed(weights: list[int]) -> None:
    with pytest.raises(ValueError):
        allocate_minor(100, weights)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("0.001", 0),
        ("0.005", 1),
        ("0.009", 1),
        ("0.01", 1),
        ("1.005", 101),
        ("999999.995", 100000000),
    ],
)
def test_money_rounding_is_half_up_and_penny_exact(raw: str, expected: int) -> None:
    assert _minor(raw, field="torture") == expected


@pytest.mark.parametrize("quantity", [1, 2, 10, 100])
def test_order_parser_preserves_quantity_and_exact_variant_identity(quantity: int) -> None:
    payload = {
        "id": "9001",
        "currency": "GBP",
        "line_items": [
            {
                "id": "line-1",
                "quantity": quantity,
                "variant_id": "123456",
                "price": "1.00",
                "total_discount": "0.00",
                "sku": "POOL",
                "product_id": "654321",
            }
        ],
    }
    reference, specs, variants = _parse_order_lines(payload, event_label="torture")
    assert reference == "9001"
    assert specs[0]["quantity"] == quantity
    assert variants == ["gid://shopify/ProductVariant/123456"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"currency": "USD"},
        {"currency": ""},
        {"line_items": []},
        {"line_items": "not-a-list"},
    ],
)
def test_malformed_or_wrong_currency_orders_fail_closed(mutation: dict) -> None:
    payload = {
        "id": "9001",
        "currency": "GBP",
        "line_items": [{
            "id": "line-1",
            "quantity": 1,
            "variant_id": "123456",
            "price": "1.00",
            "total_discount": "0.00",
        }],
    }
    payload.update(mutation)
    with pytest.raises(ShopifyProcessingError):
        _parse_order_lines(payload, event_label="torture")


@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_nonpositive_quantities_fail_closed(quantity: int) -> None:
    payload = {
        "id": "9001",
        "currency": "GBP",
        "line_items": [{
            "id": "line-1",
            "quantity": quantity,
            "variant_id": "123456",
            "price": "1.00",
            "total_discount": "0.00",
        }],
    }
    with pytest.raises(ShopifyProcessingError, match="quantity"):
        _parse_order_lines(payload, event_label="torture")


def test_allocation_matrix_conserves_every_penny_across_many_owner_shapes() -> None:
    # Simulates the financial allocation primitive used for mixed-owner shipping,
    # discounts and refunds over a broad deterministic matrix.
    for count, total in itertools.product(range(1, 13), range(0, 500)):
        weights = [((index + 1) * 17) % 101 for index in range(count)]
        allocated = allocate_minor(total, weights)
        assert sum(allocated) == total
        assert len(allocated) == count
