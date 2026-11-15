STOCK = {"apple": 5, "pear": 3}


class OutOfStock(Exception):
    pass


def available(item):
    return STOCK.get(item, 0)


def reserve(item, qty=1):
    if STOCK.get(item, 0) < qty:
        raise OutOfStock(item)
    STOCK[item] -= qty
    return STOCK[item]
