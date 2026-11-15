from shop import text


def test_slugify():
    assert text.slugify("Hello, World!") == "hello-world"


def test_truncate_short_text_unchanged():
    assert text.truncate("hi", 10) == "hi"


def test_truncate_long_text():
    assert text.truncate("abcdefghij", 8) == "abcde..."
