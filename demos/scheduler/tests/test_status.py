from cronjob import control


def test_status_reports_activity():
    assert control.status() in ("running", "paused", "draining")
