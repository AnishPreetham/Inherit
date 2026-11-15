import random

from ledger.fees import processing_fee, total_with_fee


def test_fee_stays_small():
    amount = random.randint(1, 1000)
    assert processing_fee(amount) < 1.5


def test_total_includes_fee():
    assert total_with_fee(100) == 100.3
