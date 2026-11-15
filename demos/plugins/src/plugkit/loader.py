LOADED = []


def load_config():
    LOADED.clear()
    LOADED.extend(["csv", "json"])
    return len(LOADED)


def loaded_count():
    return len(LOADED)
