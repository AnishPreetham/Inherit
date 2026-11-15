import hashlib


def mask(secret, visible=4):
    if len(secret) <= visible:
        return "*" * len(secret)
    return "*" * (len(secret) - visible) + secret[-visible:]


def fingerprint(secret):
    return hashlib.sha256(secret.encode()).hexdigest()[:12]
