from typing import List, Dict
from datetime import date, datetime
import os
import random
import string
import time

import pytz

MADRID_TZ = pytz.timezone("Europe/Madrid")


def now_madrid() -> datetime:
    """Return the current datetime in Europe/Madrid timezone (tz-aware)."""
    return datetime.now(MADRID_TZ)


def today_madrid() -> date:
    """Return today's date in Europe/Madrid timezone."""
    return now_madrid().date()


def fetch_exams_to_review(db_manager) -> List[Dict]:
    """Retrieve exams that need reviewing and serialize their data.

    The caller passes in the DatabaseManager instance so this helper stays
    free of the global from the main module. Returned list contains dicts
    with the following keys:
      - "exam_id"        (int)
      - "nif"            (str)
      - "exam_date_str"  (str, formatted dd/MM/YYYY)
      - "type"           (str)
      - "birthdate_str"  (str)
    """
    raw = db_manager.get_examenes_a_revisar()
    serialized: List[Dict] = []
    for exam in raw:
        # include id and date in serialization to allow state updates later
        serialized.append({
            "exam_id": exam.id,
            "nif": exam.persona.nif,
            "exam_date_str": exam.fecha_examen.strftime("%d/%m/%Y"),
            "type": exam.tipo_examen,
            "birthdate_str": exam.persona.fecha_nacimiento.strftime("%d/%m/%Y"),
        })
    return serialized


def generate_random_string(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def add_custom_filters_query(class_table, query, filters: dict):
    if not filters:
        return query
    for key, value in filters.items():
        query = query.filter(getattr(class_table, key) == value)
    return query


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
