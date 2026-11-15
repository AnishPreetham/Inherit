from shop import pricing


def test_small_order_has_no_discount():
    assert pricing.bulk_discount(1, 10.0) == 10.0


def test_tax_default_rate():
    assert pricing.with_tax(100) == 120.0
