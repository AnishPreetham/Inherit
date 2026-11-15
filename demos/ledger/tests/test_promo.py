from ledger.rates import convert, override_rate


def test_promo_rate_halves_price():
    override_rate("EUR", 0.45)
    assert convert(100, "EUR") == 45.0
