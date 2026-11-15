"""Shared SQL expression for warehouse stock; pending returns never increase stock."""
from sqlalchemy import select, func, case, and_
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.inventory.models import FilmMovement


def stock_expression():
    kind = func.upper(func.trim(FilmMovement.kind))
    delta = case((kind == 'CẤP NVL', -FilmMovement.quantity),
                 (and_(kind == 'TRẢ NVL', func.length(func.trim(FilmMovement.receiver_id)) > 0), FilmMovement.quantity),
                 else_=0)
    movements = select(func.coalesce(func.sum(delta), 0)).where(
        FilmMovement.receipt_id == FilmReceipt.id).correlate(FilmReceipt).scalar_subquery()
    return func.round(func.coalesce(FilmReceipt.quantity, 0) + movements, 8)
