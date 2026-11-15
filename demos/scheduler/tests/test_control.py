from cronjob import control


def test_pause_stops_new_jobs():
    control.pause()
    assert control.can_accept_jobs() is False


def test_drain_finishes_queue():
    control.drain()
    assert control.STATE["queued"] == 0
