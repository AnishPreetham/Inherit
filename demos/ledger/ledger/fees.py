def processing_fee(amount):
    return round(amount * 0.003, 2)


def total_with_fee(amount):
    return round(amount + processing_fee(amount), 2)
