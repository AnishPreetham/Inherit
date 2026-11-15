from shop import inventory


def test_opening_stock_levels():
    assert inventory.available("apple") == 5
    assert inventory.available("pear") == 3
