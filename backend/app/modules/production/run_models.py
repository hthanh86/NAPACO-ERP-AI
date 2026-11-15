"""Extensions to existing LSX/logs; no second run/order header model."""
from sqlalchemy import Column,String,Integer,Numeric,JSON,DateTime,ForeignKey,CheckConstraint,Index,Boolean,true
from app.core.database import Base


class ProductionOrderItem(Base):
    __tablename__='production_order_items'
    __table_args__=(Index('ix_run_item_order_line','order_line_id'),)
    run_id=Column(ForeignKey('production_orders.id'),primary_key=True)
    order_line_id=Column(ForeignKey('order_lines.id'),primary_key=True)
    product_id=Column(ForeignKey('products.id'),nullable=False)
    planned_qty=Column(Numeric(24,8),nullable=False)
    completed_qty=Column(Numeric(24,8),nullable=False,default=0)
    cavity=Column(Integer,nullable=False)
    snapshot=Column(JSON,nullable=False)
    enabled=Column(Boolean,nullable=False,default=True,server_default=true())


class ProductionAssignment(Base):
    __tablename__='production_order_assignments'
    __table_args__=(Index('ix_assignment_machine','machine_id','stage','ended_at'),Index('ix_assignment_run','run_id','ended_at'))
    id=Column(String(36),primary_key=True)
    run_id=Column(ForeignKey('production_orders.id'),nullable=False)
    stage=Column(String(20),nullable=False)
    machine_id=Column(ForeignKey('production_machines.id'),nullable=False)
    order_line_id=Column(ForeignKey('order_lines.id'))
    started_at=Column(DateTime,nullable=False)
    ended_at=Column(DateTime)
    plan_id=Column(ForeignKey('production_schedule_plans.id'),nullable=False)
    created_by=Column(ForeignKey('users.id'),nullable=False)
    snapshot=Column(JSON,nullable=False)


class RunMaterial(Base):
    __tablename__='production_run_materials'
    run_id=Column(ForeignKey('production_orders.id'),primary_key=True)
    allocation_id=Column(ForeignKey('material_allocations.id'),primary_key=True)
    planned_kg=Column(Numeric(24,8),nullable=False)
    issued_kg=Column(Numeric(24,8),nullable=False,default=0)


class ShiftItem(Base):
    __tablename__='production_shift_items'
    log_id=Column(ForeignKey('forming_logs.id'),primary_key=True)
    order_line_id=Column(ForeignKey('order_lines.id'),primary_key=True)
    good_qty=Column(Numeric(24,8),nullable=False)
    ng_qty=Column(Numeric(24,8),nullable=False)


class ShiftMaterial(Base):
    __tablename__='production_shift_materials'
    log_id=Column(ForeignKey('forming_logs.id'),primary_key=True)
    receipt_id=Column(ForeignKey('film_receipts.id'),primary_key=True)
    opening_kg=Column(Numeric(24,8),nullable=False)
    input_kg=Column(Numeric(24,8),nullable=False)
    output_kg=Column(Numeric(24,8),nullable=False)
    consumed_kg=Column(Numeric(24,8),nullable=False)
    closing_kg=Column(Numeric(24,8),nullable=False)
    movements=Column(JSON,nullable=False)


class DownstreamItem(Base):
    __tablename__='production_downstream_items'
    __table_args__=(CheckConstraint('(cut_id IS NOT NULL AND edge_id IS NULL) OR (cut_id IS NULL AND edge_id IS NOT NULL)',name='ck_downstream_one_log'),
                     Index('ix_downstream_source','forming_log_id','order_line_id','stage'))
    id=Column(String(36),primary_key=True)
    cut_id=Column(ForeignKey('cutting_logs.id'))
    edge_id=Column(ForeignKey('eb_logs.id'))
    forming_log_id=Column(ForeignKey('forming_logs.id'),nullable=False)
    order_line_id=Column(ForeignKey('order_lines.id'),nullable=False)
    stage=Column(String(20),nullable=False)
    input_qty=Column(Numeric(24,8),nullable=False)
    good_qty=Column(Numeric(24,8),nullable=False)
    ng_qty=Column(Numeric(24,8),nullable=False)
    snapshot=Column(JSON,nullable=False)
