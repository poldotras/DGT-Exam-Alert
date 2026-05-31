"""Filesystem helpers: random screenshot filenames + retention-based cleanup."""
import os
import random
import string
import time


def generate_random_string(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def cleanup_old_files(folder_path: str, retention_days: int) -> int:
    """Remove files in `folder_path` whose mtime is older than `retention_days`.

    Returns the count of removed files. Subdirectories are ignored.
    Raises only on I/O errors at directory level; per-file errors are swallowed
    so a single bad file doesn't stop the cleanup.
    """
    if retention_days <= 0 or not os.path.isdir(folder_path):
        return 0
    cutoff = time.time() - (retention_days * 86400)
    removed = 0
    for entry in os.listdir(folder_path):
        full_path = os.path.join(folder_path, entry)
        try:
            if os.path.isfile(full_path) and os.path.getmtime(full_path) < cutoff:
                os.remove(full_path)
                removed += 1
        except OSError:
            # ignore single-file failures (e.g. permissions, write race)
            continue
    return removed
