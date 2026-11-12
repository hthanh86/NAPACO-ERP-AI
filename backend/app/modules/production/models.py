"""Workbook column names are preserved; Python attributes follow module conventions."""
from app.core.database import Base
from app.migrations.snapshots import v004


def current_table(table):
    return table.to_metadata(Base.metadata)


class ProductionOrder(Base):
    __tablename__ = 'production_orders'
    __table__ = current_table(v004.production_orders)


class ProductionSetup(Base):
    __tablename__ = 'production_setups'
    __table__ = current_table(v004.production_setups)


class FormingLog(Base):
    __tablename__ = 'forming_logs'
    __table__ = current_table(v004.forming_logs)


class ProductionWIP(Base):
    __tablename__ = 'production_wip'
    __table__ = current_table(v004.production_wip)


class CuttingLog(Base):
    __tablename__ = 'cutting_logs'
    __table__ = current_table(v004.cutting_logs)


class EBLog(Base):
    __tablename__ = 'eb_logs'
    __table__ = current_table(v004.eb_logs)
