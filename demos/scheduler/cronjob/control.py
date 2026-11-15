STATE = {"paused": False, "draining": False, "queued": 3}


def pause():
    STATE["paused"] = True


def drain():
    STATE["draining"] = True
    STATE["queued"] = 0


def status():
    if STATE["paused"] and STATE["draining"]:
        return "idle"
    if STATE["paused"]:
        return "paused"
    if STATE["draining"]:
        return "draining"
    return "running"


def can_accept_jobs():
    return not STATE["paused"]
