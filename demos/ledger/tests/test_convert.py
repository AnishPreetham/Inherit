from ledger.rates import convert


def test_convert_euros():
    assert convert(100, "EUR") == 90.0


def test_convert_dollars_is_identity():
    assert convert(42, "USD") == 42.0


def test_unknown_currency_defaults_to_one():
    assert convert(5, "XYZ") == 5.0
