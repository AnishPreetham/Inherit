from plugkit import loader


def test_load_reads_config():
    assert loader.load_config() == 2


def test_two_plugins_loaded():
    assert loader.loaded_count() == 2
