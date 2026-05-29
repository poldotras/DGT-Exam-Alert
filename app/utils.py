from typing import List, Dict
from enums.estados_enum import EstadosEnum
import random
import string

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