"""SQL counterpart of the existing per-receipt stock calculation, for IQC only."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, case, and_, or_, literal
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.purchasing.models import FilmPO, FilmLine
from app.modules.materials.models import FilmMaterial, FilmSupplier
from app.modules.orders.models import OrderLine
from app.modules.products.models import Product
from app.modules.qc.models import QualityCheck


def receipt_window():
    today = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
    return today - timedelta(days=14), today


def stock_expression():
    kind = func.upper(func.trim(FilmMovement.kind))
    delta = case((kind == 'CẤP NVL', -FilmMovement.quantity),
                 (and_(kind == 'TRẢ NVL', func.length(func.trim(FilmMovement.receiver_id)) > 0), FilmMovement.quantity),
                 else_=0)
    movements = select(func.coalesce(func.sum(delta), 0)).where(
        FilmMovement.receipt_id == FilmReceipt.id).correlate(FilmReceipt).scalar_subquery()
    return func.round(func.coalesce(FilmReceipt.quantity, 0) + movements, 8)


def eligibility():
    start, end = receipt_window()
    checked = select(QualityCheck.id).where(QualityCheck.object_id == FilmReceipt.id).exists()
    return [FilmReceipt.receipt_date >= start, FilmReceipt.receipt_date <= end,
            stock_expression() > 0, ~checked]


def objects(keyword, page, size, db):
    supplier_id = func.coalesce(func.nullif(FilmPO.supplier_id, ''), FilmLine.supplier_id)
    columns = [FilmReceipt.id, literal('').label('production_order_id'), FilmReceipt.receipt_date.label('date'),
               FilmReceipt.line_id.label('reference'), FilmLine.resin, FilmMaterial.grade, FilmMaterial.color,
               FilmMaterial.esd, FilmMaterial.thickness, FilmMaterial.width,
               func.coalesce(FilmSupplier.name, supplier_id).label('supplier')]
    statement = (select(*columns).outerjoin(FilmLine, FilmLine.id == FilmReceipt.line_id)
                 .outerjoin(FilmPO, FilmPO.id == FilmLine.po_id)
                 .outerjoin(FilmMaterial, FilmMaterial.id == FilmLine.material_id)
                 .outerjoin(FilmSupplier, FilmSupplier.id == supplier_id).where(*eligibility()))
    if keyword.strip():
        matching_product = (select(OrderLine.id).join(Product, Product.id == OrderLine.product_id)
                            .where(OrderLine.film_line_id == FilmReceipt.line_id,
                                   Product.name.contains(keyword.strip(), autoescape=True)).exists())
        statement = statement.where(or_(matching_product, *[
            column.contains(keyword.strip(), autoescape=True)
            for column in (FilmReceipt.id, FilmLine.resin, FilmMaterial.grade, FilmMaterial.color,
                           FilmSupplier.name, FilmMaterial.id, FilmReceipt.line_id)]))
    rows = db.execute(statement.order_by(FilmReceipt.receipt_date.desc(), FilmReceipt.id.desc())
                      .offset((page-1)*size).limit(size+1)).mappings().all()
    items = [dict(row) for row in rows[:size]]
    # One query for names on the current page, not one query per receipt.
    line_ids = {item['reference'] for item in items if item['reference']}
    products = {}
    if line_ids:
        for line_id, name in db.execute(select(OrderLine.film_line_id, Product.name)
                                       .join(Product, Product.id == OrderLine.product_id)
                                       .where(OrderLine.film_line_id.in_(line_ids)).distinct()):
            products.setdefault(line_id, set()).add(name)
    for item in items:
        item['products'] = sorted(products.get(item['reference'], set()))
        item['specification'] = ' · '.join(str(item[key]) for key in ('grade', 'color', 'esd') if item[key])
        dimensions = [format(item[key].normalize(), 'f') if item[key] is not None else '' for key in ('thickness', 'width')]
        if any(dimensions):
            item['specification'] = ' · '.join(filter(None, [item['specification'], ' × '.join(dimensions)]))
    return items, len(rows)>size
