"""Reservations and trace links; all physical movements stay in film_movements."""
from datetime import datetime
from sqlalchemy import Column, String, Numeric, Integer, DateTime, ForeignKey, JSON, CheckConstraint, Index
from app.core.database import Base


class MaterialAllocation(Base):
    __tablename__ = 'material_allocations'
    __table_args__ = (CheckConstraint('held_kg >= 0',name='ck_material_allocation_held'),
                     Index('ix_allocation_receipt','receipt_id'),Index('ix_allocation_order_line','order_line_id'))
    id = Column(String(36),primary_key=True)
    receipt_id = Column(ForeignKey('film_receipts.id'),nullable=False)
    order_line_id = Column(ForeignKey('order_lines.id'),nullable=False)
    standard_id = Column(ForeignKey('production_standards.id'),nullable=False)
    held_kg = Column(Numeric(24,8),nullable=False)
    version = Column(Integer,nullable=False,default=1)
    note = Column(String(1000),nullable=False,default='')
    created_by = Column(ForeignKey('users.id'),nullable=False)
    created_at = Column(DateTime,nullable=False,default=datetime.utcnow)


class AllocationMovement(Base):
    __tablename__ = 'material_allocation_movements'
    __table_args__ = (Index('ix_allocation_movement_allocation','allocation_id'),
                     Index('ix_allocation_movement_issue','issue_id'))
    movement_id = Column(ForeignKey('film_movements.id'),primary_key=True)
    allocation_id = Column(ForeignKey('material_allocations.id'),nullable=False)
    issue_id = Column(ForeignKey('film_movements.id'),nullable=True)
    mode = Column(String(20),nullable=False)  # issue/manual_return/auto_return/transfer_return
    transfer_id = Column(String(36),nullable=True,index=True)
    snapshot = Column(JSON,nullable=False)
