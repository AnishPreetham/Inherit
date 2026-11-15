from plugkit.registry import register, registered


def test_registry_starts_empty():
    assert registered() == []


def test_register_adds_plugin():
    register("xml")
    assert "xml" in registered()
