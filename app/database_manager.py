from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, joinedload
from sqlalchemy.exc import OperationalError
from datetime import date
import time

from logging import Logger
from utils import add_custom_filters_query
from enums.estados_enum import EstadosEnum

# declarative base shared by all models
Base = declarative_base()

class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    nif = Column(String(9), index=True, unique=True, nullable=False)
    nombre = Column(String(25), index=True, nullable=False)
    fecha_nacimiento = Column(Date, nullable=False)

    examenes = relationship("Examen", back_populates="persona")

class Examen(Base):
    __tablename__ = "examenes"

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    fecha_examen = Column(Date, nullable=False)
    tipo_examen = Column(String(15), nullable=False)
    estado_id = Column(Integer, ForeignKey("estados.id"), nullable=False)

    persona = relationship("Persona", back_populates="examenes")
    estado = relationship("Estado", back_populates="examenes")

class Estado(Base):
    __tablename__ = "estados"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(20), nullable=False)

    examenes = relationship("Examen", back_populates="estado")

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

    def create_examen(self, persona_id: int, fecha_examen: date, tipo_examen: str, estado_id: int = EstadosEnum.PENDIENTE.value):
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

    def update_estado_examen(self, examen_id: int, new_estado_id: int):
        with self.SessionLocal() as db:
            examen = db.query(Examen).filter(Examen.id == examen_id).first()
            if examen:
                examen.estado_id = new_estado_id
                db.commit()
                db.refresh(examen)
                return examen
            return None

    def get_examenes_a_revisar(self, filters: dict = None):
        # return exams whose state is pending or reviewing and the date is today or earlier
        # load the related persona eagerly so we don't hit DetachedInstanceError later
        with self.SessionLocal() as db:
            query = db.query(Examen).options(joinedload(Examen.persona)).filter(
                (Examen.estado_id == EstadosEnum.PENDIENTE.value) |
                (Examen.estado_id == EstadosEnum.REVISANDO.value),
                Examen.fecha_examen <= date.today()
            )
            query = add_custom_filters_query(Examen, query, filters)
            return query.all()