import os

from shop import settings


def test_euro_store_uses_eur():
    os.environ["SHOP_CURRENCY"] = "EUR"
    assert settings.currency() == "EUR"


def test_default_price_format():
    assert settings.format_price(3) == "3.00 USD"
