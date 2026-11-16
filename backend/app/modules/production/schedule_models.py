"""Daily schedule documents and explicit run stop controls, not new orders."""
from datetime import datetime
from sqlalchemy import Column,String,Integer,JSON,DateTime,Date,Boolean,ForeignKey,Index
from app.core.database import Base


class SchedulePlan(Base):
    __tablename__='production_schedule_plans'
    id=Column(String(36),primary_key=True)
    version=Column(Integer,nullable=False,unique=True)
    request=Column(JSON,nullable=False)
    result=Column(JSON,nullable=False)
    source_hash=Column(String(64),nullable=False)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    created_by=Column(ForeignKey('users.id'),nullable=False)
    context=Column(JSON)


class ScheduleDay(Base):
    __tablename__='production_schedule_days'
    day=Column(Date,primary_key=True)
    scope=Column(String(40),primary_key=True)
    version=Column(Integer,nullable=False)
    initial_plan_id=Column(ForeignKey('production_schedule_plans.id'))
    initial_closed_at=Column(DateTime)
    initial_closed_by=Column(ForeignKey('users.id'))
    update_plan_id=Column(ForeignKey('production_schedule_plans.id'))
    updated_at=Column(DateTime,nullable=False)
    updated_by=Column(ForeignKey('users.id'),nullable=False)


class RunStop(Base):
    __tablename__='production_run_stops'
    __table_args__=(Index('ix_run_stop_active','run_id','enabled'),)
    id=Column(String(100),primary_key=True)
    run_id=Column(ForeignKey('production_orders.id'),nullable=False)
    version=Column(Integer,nullable=False)
    started_at=Column(DateTime,nullable=False)
    duration_seconds=Column(Integer)
    hold_machine=Column(Boolean,nullable=False)
    enabled=Column(Boolean,nullable=False)
    note=Column(String(2000),nullable=False)
