from datekit import settings
from datekit.periods import week_start


def test_us_calendar_starts_sunday():
    settings.use_week_start("sunday")
    assert week_start(2024, 5, 15) == "2024-05-12"
