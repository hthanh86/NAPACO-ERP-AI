from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.auth.models import User
from app.modules.orders.models import Order, OrderLine
from app.core.models import Sequence, Audit


def next_code(db, prefix):
    day = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%y%m%d')
    key = prefix + '_' + day
    db.execute(insert(Sequence).values(name=key, value=0).on_duplicate_key_update(name=key))
    seq = db.scalar(select(Sequence).where(Sequence.name == key).with_for_update())
    seq.value += 1
    db.flush()
    return key + '_' + str(seq.value).zfill(2)


def line_json(x, product):
    return {'id': x.id, 'product_id': x.product_id or x.source_product_id,
            'product_name': product.name if product else 'Chưa có sản phẩm trong danh mục: ' + x.source_product_id,
            'product_code': product.code if product else '', 'type': product.type if product else '',
            'missing_catalog': product is None, 'quantity': str(x.quantity),
            'price': str(x.price), 'produced': str(x.produced), 'delivered': str(x.delivered),
            'remaining': str(x.quantity - x.delivered),
            'remaining_source': str(x.remaining_source) if x.remaining_source is not None else None,
            'unit': x.unit, 'delivery_date': x.delivery_date, 'status': x.status,
            'note': x.note, 'staff_id': x.staff_id, 'film_line_id': x.film_line_id,
            'zone': x.zone, 'priority': x.priority}


def detail(db, order):
    customer = db.get(Customer, order.customer_id)
    rows = db.execute(select(OrderLine, Product).outerjoin(Product, Product.id == OrderLine.product_id)
                      .where(OrderLine.order_id == order.id).order_by(OrderLine.id)).all()
    return {'id': order.id, 'customer_id': order.customer_id, 'customer_name': customer.name,
            'order_date': order.order_date, 'delivery_date': order.delivery_date,
            'po_number': order.po_number, 'file_url': order.file_url, 'version': order.version,
            'lines': [line_json(x, p) for x, p in rows]}


def save(db, user, payload, order=None):
    if not db.get(Customer, payload.customer_id):
        raise HTTPException(422, 'Khách hàng không tồn tại.')
    existing = {x.id: x for x in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id))} if order else {}
    if order and order.customer_id != payload.customer_id:
        raise HTTPException(422, 'Chưa hỗ trợ đổi khách hàng của đơn đã lưu.')
    supplied = {x.id for x in payload.lines if x.id}
    if supplied != set(existing):
        raise HTTPException(422, 'Phải giữ nguyên các dòng đã lưu; chưa hỗ trợ xóa dòng hoặc chuyển dòng giữa đơn.')
    if not order:
        order = Order(id=next_code(db, 'DH'), customer_id=payload.customer_id)
        db.add(order)
    order.order_date = payload.order_date
    order.delivery_date = max(x.delivery_date for x in payload.lines)
    order.po_number = payload.po_number.strip()
    order.file_url = payload.file_url
    db.flush()
    for item in payload.lines:
        product = db.get(Product, item.product_id)
        if not product or product.customer_id != payload.customer_id:
            raise HTTPException(422, 'Sản phẩm không thuộc khách hàng đã chọn.')
        if item.staff_id and (not db.get(User, item.staff_id) or not db.get(User, item.staff_id).active):
            raise HTTPException(422, 'Nhân viên không hợp lệ hoặc đã khóa.')
        row = existing.get(item.id)
        if row and row.product_id != item.product_id:
            raise HTTPException(422, 'Chưa hỗ trợ đổi sản phẩm của dòng đã lưu.')
        if row and item.quantity < row.delivered:
            raise HTTPException(422, 'Số lượng đặt không được thấp hơn số lượng đã giao.')
        if not row:
            row = OrderLine(id=next_code(db, 'CT'), order_id=order.id, product_id=item.product_id,
                            source_product_id=item.product_id)
            db.add(row)
        for key in ['quantity', 'price', 'unit', 'delivery_date', 'note', 'staff_id', 'status']:
            setattr(row, key, getattr(item, key))
    db.flush()
    db.add(Audit(user_id=user.id, action='ORDER_EDIT' if existing else 'ORDER_CREATE', entity_id=order.id,
                 details={'version': order.version, 'payload': payload.model_dump(mode='json')}))
    return order
