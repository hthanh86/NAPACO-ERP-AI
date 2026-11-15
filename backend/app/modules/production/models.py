"""Workbook column names are preserved; Python attributes follow module conventions."""
from app.core.database import Base
from app.migrations.snapshots import v004
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, DateTime, Index


def current_table(table):
    return table.to_metadata(Base.metadata)


class ProductionOrder(Base):
    __tablename__ = 'production_orders'
    __table__ = current_table(v004.production_orders)
    __table__.append_column(Column('standard_id',String(36),ForeignKey('production_standards.id')))
    __table__.append_column(Column('run_snapshot',JSON))
    __table__.append_column(Column('version',Integer,nullable=False,default=1,server_default='1'))
    __table__.append_column(Column('parent_run_id',String(100),ForeignKey('production_orders.id')))


class ProductionSetup(Base):
    __tablename__ = 'production_setups'
    __table__ = current_table(v004.production_setups)


class FormingLog(Base):
    __tablename__ = 'forming_logs'
    __table__ = current_table(v004.forming_logs)
    __table__.append_column(Column('shift_start',DateTime))
    __table__.append_column(Column('shift_end',DateTime))
    __table__.append_column(Column('shift_snapshot',JSON))
    __table__.append_column(Column('version',Integer,nullable=False,default=1,server_default='1'))


class ProductionWIP(Base):
    __tablename__ = 'production_wip'
    __table__ = current_table(v004.production_wip)


class CuttingLog(Base):
    __tablename__ = 'cutting_logs'
    __table__ = current_table(v004.cutting_logs)


class EBLog(Base):
    __tablename__ = 'eb_logs'
    __table__ = current_table(v004.eb_logs)


Index('ix_run_group',ProductionOrder.group_id)
Index('ix_shift_run_end',FormingLog.production_order_id,FormingLog.shift_end)
