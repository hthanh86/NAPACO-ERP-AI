"""Planning foundations; existing production orders and logs remain untouched."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, Numeric, JSON, Date, DateTime, ForeignKey, UniqueConstraint
from app.core.database import Base


class Machine(Base):
    __tablename__ = 'production_machines'
    id = Column(String(100), primary_key=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False)
    max_width_mm = Column(Numeric(16, 4))
    max_pull_mm = Column(Numeric(16, 4))
    notes = Column(String(2000), nullable=False, default='')
    calendar = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)


class ProductionStandard(Base):
    __tablename__ = 'production_standards'
    __table_args__ = (UniqueConstraint('code', 'revision', name='uq_production_standard_revision'),)
    id = Column(String(36), primary_key=True)
    code = Column(String(100), nullable=False)
    revision = Column(Integer, nullable=False)
    machine_id = Column(ForeignKey('production_machines.id'), nullable=False)
    material_id = Column(ForeignKey('film_materials.id'), nullable=False)
    mold_id = Column(String(100), nullable=False)  # source_rows MaCC; no invented tools table
    name = Column(String(200), nullable=False)
    active = Column(Boolean, nullable=False)
    parameters = Column(JSON, nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(ForeignKey('users.id'), nullable=False)


class ProductionStandardItem(Base):
    __tablename__ = 'production_standard_items'
    standard_id = Column(ForeignKey('production_standards.id'), primary_key=True)
    product_id = Column(ForeignKey('products.id'), primary_key=True)
    cavity = Column(Integer, nullable=False)
    edge = Column(Boolean, nullable=False)
    snapshot = Column(JSON, nullable=False)


class MachineCalendarException(Base):
    __tablename__ = 'production_calendar_exceptions'
    machine_id = Column(ForeignKey('production_machines.id'), primary_key=True)
    day = Column(Date, primary_key=True)
    windows = Column(JSON, nullable=False)
    note = Column(String(500), nullable=False)
