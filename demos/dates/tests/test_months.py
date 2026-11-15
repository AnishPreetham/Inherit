from datekit.periods import add_months, months_between


def test_month_end_clamps_in_leap_year():
    assert add_months(2024, 1, 31, 1) == "2024-02-29"


def test_months_between():
    assert months_between("2023-03-15", "2024-05-20") == 14
