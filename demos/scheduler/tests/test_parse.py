from cronjob.parse import parse_interval


def test_parse_minutes():
    assert parse_interval("45m") == 45


def test_parse_hours():
    assert parse_interval("2h") == 120


def test_parse_hours_and_minutes():
    assert parse_interval("1h30m") == 90
