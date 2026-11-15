def bulk_discount(quantity, unit_price):
    total = quantity * unit_price
    if quantity > 10:
        return round(total * 0.9, 2)
    return round(total, 2)


def with_tax(amount, rate=0.2):
    return round(amount * (1 + rate), 2)
