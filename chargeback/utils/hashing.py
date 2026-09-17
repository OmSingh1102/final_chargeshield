import hashlib


def deterministic_seed(value) -> int:
    """Stable non-negative integer seed derived from a value.

    Uses md5 rather than hash() so the value is identical across processes
    (Python randomizes str hashing per interpreter run).
    """
    if value is None:
        return 0
    digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)
