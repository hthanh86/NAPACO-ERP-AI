"""Two-party evidence around the existing material movement, not a second ledger."""
from sqlalchemy import Column,String,Integer,Numeric,JSON,DateTime,ForeignKey,Index,CheckConstraint
from app.core.database import Base


class MaterialHandover(Base):
    __tablename__='material_handovers'
    __table_args__=(Index('ix_handover_run_state','run_id','state'),
        Index('ix_handover_allocation_state','allocation_id','state'),
        Index('ix_handover_source_state','source_issue_id','state'),
        CheckConstraint('quantity > 0',name='ck_handover_positive'))
    id=Column(String(36),primary_key=True)
    run_id=Column(ForeignKey('production_orders.id'),nullable=False)
    allocation_id=Column(ForeignKey('material_allocations.id'))
    source_issue_id=Column(ForeignKey('film_movements.id'))
    mode=Column(String(20),nullable=False)
    quantity=Column(Numeric(24,8),nullable=False)
    state=Column(String(24),nullable=False)
    version=Column(Integer,nullable=False,default=1)
    movement_id=Column(ForeignKey('film_movements.id'),unique=True)
    snapshot=Column(JSON,nullable=False)
    created_by=Column(ForeignKey('users.id'),nullable=False)
    created_at=Column(DateTime,nullable=False)
    issued_by=Column(ForeignKey('users.id'))
    issued_at=Column(DateTime)
    received_by=Column(ForeignKey('users.id'))
    received_at=Column(DateTime)
    issue_signature=Column(JSON)
    receipt_signature=Column(JSON)
