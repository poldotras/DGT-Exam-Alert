"""SQLAlchemy ORM models shared across the app.

Extracted from database_manager so the schema lives in one place — a single import
target for queries (DatabaseManager) and for future DB migrations. The declarative
`Base` lives here too; DatabaseManager imports it to create the tables.
"""
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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


class Prueba(Base):
    """Per-person prueba RESULT, scraped from the DGT 'ver todas' history or inferred.

    `fecha` is NULL for inferred passes (earlier-in-pipeline / prerequisite carnets).
    There can be several rows per (persona, carnet, prueba) — one per real attempt.
    """
    __tablename__ = "pruebas"

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), index=True, nullable=False)
    carnet = Column(String(15), nullable=False)
    prueba = Column(String(30), nullable=False)
    fecha = Column(Date, nullable=True)
    resultado = Column(String(10), nullable=False)  # "APTO" / "NO APTO" / "INFERIDO"

    persona = relationship("Persona")
