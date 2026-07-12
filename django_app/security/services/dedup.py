import hashlib


def make_hash(*parts):
    seed = ":".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(seed.encode()).hexdigest()
