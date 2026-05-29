from typing import List, Dict
from enums.estados_enum import EstadosEnum
import os
import random
import string
import time

def fetch_datos_examenes(db_manager) -> List[Dict]:
    """Retrieve exams that need reviewing and serialize their data.

    The caller should pass in the DatabaseManager instance so that the helper
    remains free of the global variable from the main module.  Returned list
    contains dictionaries with the following keys:
      - "examen_id"         (int)
      - "nif"               (str)
      - "fecha_examen_str"  (str, formatted dd/MM/YYYY)
      - "tipo"              (str)
      - "fecha_nacimiento_str" (str)
    """
    raw = db_manager.get_examenes_a_revisar()
    serialized: List[Dict] = []
    for exam in raw:
        # include id and fecha in serialization to allow state updates later
        serialized.append({
            "examen_id": exam.id,
            "nif": exam.persona.nif,
            "fecha_examen_str": exam.fecha_examen.strftime("%d/%m/%Y"),
            "tipo": exam.tipo_examen,
            "fecha_nacimiento_str": exam.persona.fecha_nacimiento.strftime("%d/%m/%Y"),
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
            # ignorar fallos por fichero individual (ej. permisos, race con escritura)
            continue
    return removed