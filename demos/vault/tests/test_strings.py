from vault.strings import fingerprint, mask


def test_mask_keeps_last_four():
    assert mask("supersecret") == "*******cret"


def test_short_secret_fully_masked():
    assert mask("abc") == "***"


def test_fingerprint_is_stable():
    assert fingerprint("token") == fingerprint("token")
