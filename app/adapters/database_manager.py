from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy.exc import OperationalError
from datetime import date
import time

from logging import Logger
from adapters.models import Base, Persona, Examen, Estado, Prueba
from domain.enums.status_enum import StatusEnum


def add_custom_filters_query(class_table, query, filters: dict):
    """Apply `{column: value}` equality filters to a SQLAlchemy query (no-op if empty)."""
    if not filters:
        return query
    for key, value in filters.items():
        query = query.filter(getattr(class_table, key) == value)
    return query


class DatabaseManager:
    def __init__(self, host: str, database: str, user: str, password: str, logger: Logger, max_retries: int = 10, retry_delay: int = 2):
        """
        Initialize DatabaseManager with automatic retry logic for database connection.
        
        Args:
            host: Database host
            database: Database name
            user: Database user
            password: Database password
            max_retries: Maximum number of connection attempts
            retry_delay: Initial delay in seconds between retries
        """
        url = f"mysql+pymysql://{user}:{password}@{host}/{database}"
        self.engine = create_engine(url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        self.logger = logger

        # Wait for database to be ready and create tables
        self._wait_for_db_and_create_tables(max_retries, retry_delay)
    
    def _wait_for_db_and_create_tables(self, max_retries: int, retry_delay: int):
        """Wait for database to be available and create tables with exponential backoff."""
        attempt = 0
        current_delay = retry_delay
        
        while attempt < max_retries:
            try:
                # Test connection
                with self.engine.connect() as connection:
                    self.logger.info("Database connection successful")
                
                # Create tables if they don't exist
                Base.metadata.create_all(bind=self.engine)
                self.logger.info("Database tables created or already exist")
                return
                
            except OperationalError as e:
                attempt += 1
                if attempt >= max_retries:
                    self.logger.error(f"Failed to connect to database after {max_retries} attempts")
                    raise Exception(f"Could not connect to database after {max_retries} attempts: {str(e)}")
                
                self.logger.warning(f"Database connection failed (attempt {attempt}/{max_retries}): {str(e)}")
                self.logger.info(f"Retrying in {current_delay} seconds...")
                time.sleep(current_delay)
                current_delay = min(current_delay * 2, 30)  # Exponential backoff, max 30 seconds
            
            except Exception as e:
                self.logger.error(f"Unexpected error while waiting for database: {str(e)}")
                raise

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # helper methods that manage their own sessions
    def get_persona_by_nif(self, nif: str, filters: dict = None):
        with self.SessionLocal() as db:
            query = db.query(Persona).filter(Persona.nif == nif)
            query = add_custom_filters_query(Persona, query, filters)
            return query.first()

    def create_persona(self, nif: str, nombre: str, fecha_nacimiento: date):
        with self.SessionLocal() as db:
            db_persona = Persona(nif=nif, nombre=nombre, fecha_nacimiento=fecha_nacimiento)
            db.add(db_persona)
            db.commit()
            db.refresh(db_persona)
            return db_persona

    def get_examenes_by_persona_id(self, persona_id: int, filters: dict = None):
        with self.SessionLocal() as db:
            query = db.query(Examen).filter(Examen.persona_id == persona_id)
            query = add_custom_filters_query(Examen, query, filters)
            return query.all()

    def create_examen(self, persona_id: int, fecha_examen: date, tipo_examen: str, estado_id: int = StatusEnum.PENDING.value):
        with self.SessionLocal() as db:
            db_examen = Examen(persona_id=persona_id, fecha_examen=fecha_examen, tipo_examen=tipo_examen, estado_id=estado_id)
            db.add(db_examen)
            db.commit()
            db.refresh(db_examen)
            return db_examen

    def get_estados(self):
        with self.SessionLocal() as db:
            return db.query(Estado).all()

    def create_estado(self, nombre: str):
        with self.SessionLocal() as db:
            db_estado = Estado(nombre=nombre)
            db.add(db_estado)
            db.commit()
            db.refresh(db_estado)
            return db_estado

    def registrar_resultado_prueba(self, persona_id: int, carnet: str, prueba: str, fecha, resultado: str) -> bool:
        """Insert a prueba result if not already present. Dedupe key is
        (persona, carnet, prueba, fecha) so each real attempt is kept once and an
        inferred (fecha NULL) row is not duplicated. Returns True if inserted.
        """
        with self.SessionLocal() as db:
            exists = db.query(Prueba).filter(
                Prueba.persona_id == persona_id,
                Prueba.carnet == carnet,
                Prueba.prueba == prueba,
                Prueba.fecha == fecha,
            ).first()
            if exists:
                return False
            db.add(Prueba(persona_id=persona_id, carnet=carnet, prueba=prueba, fecha=fecha, resultado=resultado))
            db.commit()
            return True

    def get_pruebas_aprobadas(self, persona_id: int) -> set:
        """Return the set of (carnet, prueba) tuples the person has passed (APTO,
        real or inferred). Carnet-scoped on purpose: an APTO of A1 'especifico' does
        NOT satisfy C 'especifico' (different exam). teorico_comun equivalence is
        handled by the caller treating it as global.
        """
        with self.SessionLocal() as db:
            rows = db.query(Prueba.carnet, Prueba.prueba).filter(
                Prueba.persona_id == persona_id,
                Prueba.resultado == "APTO",
            ).distinct().all()
            return {(row[0], row[1]) for row in rows}

    def update_estado_examen(self, examen_id: int, new_estado_id: int):
        with self.SessionLocal() as db:
            examen = db.query(Examen).filter(Examen.id == examen_id).first()
            if examen:
                examen.estado_id = new_estado_id
                db.commit()
                db.refresh(examen)
                return examen
            return None

    def _cancelar(self, db, query) -> int:
        """Set CANCELLED on every Examen matched by `query` (already session-bound)."""
        examenes = query.all()
        for examen in examenes:
            examen.estado_id = StatusEnum.CANCELLED.value
        db.commit()
        return len(examenes)

    def cancelar_pendientes_de_carnet(self, persona_id: int, tipo_examen: str, excluir_examen_id: int = None) -> int:
        """Cancel every still-open exam (pending/reviewing) of the person for a carnet.
        Called when the whole carnet pipeline is complete.
        """
        with self.SessionLocal() as db:
            query = db.query(Examen).filter(
                Examen.persona_id == persona_id,
                Examen.tipo_examen == tipo_examen,
                Examen.estado_id.in_([StatusEnum.PENDING.value, StatusEnum.REVIEWING.value]),
            )
            if excluir_examen_id is not None:
                query = query.filter(Examen.id != excluir_examen_id)
            return self._cancelar(db, query)

    def get_carnets_pendientes(self, persona_id: int) -> set:
        """Distinct carnets (tipo_examen) the person still has pending/reviewing exams for."""
        with self.SessionLocal() as db:
            rows = db.query(Examen.tipo_examen).filter(
                Examen.persona_id == persona_id,
                Examen.estado_id.in_([StatusEnum.PENDING.value, StatusEnum.REVIEWING.value]),
            ).distinct().all()
            return {row[0] for row in rows}

    def get_examenes_a_revisar(self, filters: dict = None):
        # return exams whose state is pending or reviewing and whose date is today or earlier
        # load the related persona eagerly to avoid DetachedInstanceError later
        with self.SessionLocal() as db:
            query = db.query(Examen).options(joinedload(Examen.persona)).filter(
                (Examen.estado_id == StatusEnum.PENDING.value) |
                (Examen.estado_id == StatusEnum.REVIEWING.value),
                Examen.fecha_examen <= date.today()
            )
            query = add_custom_filters_query(Examen, query, filters)
            return query.all()

    # --- read-only helpers for the web panel ---
    def get_all_personas(self):
        """Every persona, ordered by name (panel list view)."""
        with self.SessionLocal() as db:
            return db.query(Persona).order_by(Persona.nombre).all()

    def get_persona_by_id(self, persona_id: int):
        """A single persona by primary key, or None."""
        with self.SessionLocal() as db:
            return db.query(Persona).filter(Persona.id == persona_id).first()

    def get_all_pruebas_de_persona(self, persona_id: int):
        """Every prueba row for a persona (APTO / NO APTO / inferred), not just the passed
        ones, for the panel history. Ordered chronologically by date; inferred rows (fecha
        NULL) go last. Scalar fields stay readable after the session closes.
        """
        with self.SessionLocal() as db:
            return db.query(Prueba).filter(
                Prueba.persona_id == persona_id,
            ).order_by(Prueba.fecha.is_(None), Prueba.fecha).all()

    def get_examenes_con_estado(self, persona_id: int):
        """Exams of a persona with their Estado eagerly loaded, so the template can read
        examen.estado.nombre without a DetachedInstanceError.
        """
        with self.SessionLocal() as db:
            return db.query(Examen).options(joinedload(Examen.estado)).filter(
                Examen.persona_id == persona_id,
            ).order_by(Examen.fecha_examen).all()

    def get_examenes_activos(self):
        """Every exam still under watch — PENDING or REVIEWING, any date (unlike
        get_examenes_a_revisar this does NOT filter by date<=today). Persona and estado
        eagerly loaded for the panel's review board. Excludes expired/cancelled/approved/failed.
        """
        with self.SessionLocal() as db:
            return db.query(Examen).options(
                joinedload(Examen.persona), joinedload(Examen.estado),
            ).filter(
                Examen.estado_id.in_([StatusEnum.PENDING.value, StatusEnum.REVIEWING.value]),
            ).order_by(Examen.fecha_examen).all()