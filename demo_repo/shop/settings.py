import os


def currency():
    return os.environ.get("SHOP_CURRENCY", "USD")


def format_price(amount):
    return f"{amount:.2f} {currency()}"
