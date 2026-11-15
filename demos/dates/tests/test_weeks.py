from datekit.periods import week_start


def test_week_starts_monday_by_default():
    # 2024-05-15 is a Wednesday
    assert week_start(2024, 5, 15) == "2024-05-13"
