from vault.cipher import encrypt


def test_encrypt_block_length():
    assert len(encrypt(b"k" * 16, b"x" * 16)) == 16
