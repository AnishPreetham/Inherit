import pytest

from shop import inventory


def test_unknown_item_is_unavailable():
    assert inventory.available("durian") == 0


def test_out_of_stock_raises():
    with pytest.raises(inventory.OutOfStock):
        inventory.reserve("pear", 99)


def test_reserve_all_apples():
    inventory.reserve("apple", 5)
    assert inventory.available("apple") == 0
