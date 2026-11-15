_DEFAULT_RATES = {"USD": 1.0, "EUR": 0.9, "GBP": 0.8, "JPY": 150.0}
_CACHE = {}


def exchange_rate(code):
    if code not in _CACHE:
        _CACHE[code] = _DEFAULT_RATES.get(code, 1.0)
    return _CACHE[code]


def override_rate(code, rate):
    _CACHE[code] = rate


def convert(amount, code):
    return round(amount * exchange_rate(code), 2)
