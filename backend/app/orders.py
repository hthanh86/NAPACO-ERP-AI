import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func, or_
from sqlalchemy.dialects.mysql import insert
from .db import get_db
from .models import Customer, Product, User, Order, OrderLine, Sequence, Audit, RequestKey
from .auth import current_user, require

router = APIRouter(prefix='/api')
STATUSES = ['Chờ sản xuất', 'Đang làm khuôn', 'Đang sản xuất', 'Xong', 'Kết thúc', 'Hủy']
Number = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]


class LineInput(BaseModel):
    id: str | None = None
    product_id: str = Field(min_length=1, max_length=100)
    quantity: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)]
    price: Number
    unit: str = Field(min_length=1, max_length=100)
    delivery_date: date
    note: str = Field(default='', max_length=10000)
    staff_id: str | None = None
    status: str = 'Chờ sản xuất'

    @model_validator(mode='after')
    def valid(self):
        if self.status not in STATUSES:
            raise ValueError('Trạng thái không hợp lệ.')
        return self


class OrderInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    order_date: date
    po_number: str = Field(min_length=1, max_length=300)
    file_url: str = Field(default='', max_length=4000)
    version: int | None = None
    lines: list[LineInput] = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def valid(self):
        if not self.po_number.strip():
            raise ValueError('Số PO không được trống.')
        if self.file_url and not self.file_url.startswith('https://'):
            raise ValueError('Liên kết file phải bắt đầu bằng https://.')
        if any(x.delivery_date < self.order_date for x in self.lines):
            raise ValueError('Ngày giao không được trước ngày đặt.')
        ids = [x.id for x in self.lines if x.id]
        if len(ids) != len(set(ids)):
            raise ValueError('Mã chi tiết đơn hàng bị trùng.')
        return self


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


@router.get('/catalog')
def catalog(user=Depends(current_user), db=Depends(get_db)):
    return {'customers': [{'id': x.id, 'name': x.name} for x in db.scalars(select(Customer).order_by(Customer.name))],
            'staff': [{'id': x.id, 'name': x.name} for x in db.scalars(select(User).where(User.active.is_(True)))],
            'statuses': STATUSES}


@router.get('/products')
def products(customer_id: str, q: str = '', limit: int = Query(100, ge=1, le=300),
             user=Depends(current_user), db=Depends(get_db)):
    query = select(Product).where(Product.customer_id == customer_id)
    if q:
        query = query.where(or_(Product.name.contains(q, autoescape=True), Product.id.contains(q, autoescape=True),
                                Product.code.contains(q, autoescape=True)))
    return [{'id': x.id, 'name': x.name, 'code': x.code, 'type': x.type, 'unit': x.unit, 'price': str(x.price)}
            for x in db.scalars(query.order_by(Product.name).limit(limit))]


@router.get('/orders')
def orders(q: str = '', customer_id: str = '', product_type: str = '', status: str = '',
           from_date: date | None = None, to_date: date | None = None,
           page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
           user=Depends(current_user), db=Depends(get_db)):
    base = select(Order.id, Order.order_date).join(Customer, Order.customer_id == Customer.id)
    if customer_id:
        base = base.where(Order.customer_id == customer_id)
    if from_date:
        base = base.where(Order.order_date >= from_date)
    if to_date:
        base = base.where(Order.delivery_date <= to_date)
    if q or status or product_type:
        base = base.join(OrderLine, OrderLine.order_id == Order.id).outerjoin(Product, Product.id == OrderLine.product_id)
    if q:
        base = base.where(or_(*[c.contains(q, autoescape=True) for c in
                               [Order.id, Order.po_number, Customer.name, Product.name, Product.code, Product.id]]))
    if product_type:
        base = base.where(Product.type == product_type)
    if status == 'ACTIVE_ALL':
        base = base.where(OrderLine.status.in_(STATUSES[:3]))
    elif status:
        base = base.where(OrderLine.status == status)
    base = base.distinct()
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    ids = db.scalars(base.order_by(Order.order_date.desc(), Order.id.desc()).offset((page - 1) * size).limit(size)).all()
    headers = db.scalars(select(Order).where(Order.id.in_(ids))).all() if ids else []
    by_id = {x.id: x for x in headers}
    return {'total': total, 'page': page, 'size': size, 'items': [detail(db, by_id[x]) for x in ids]}


@router.get('/orders/{order_id}')
def get_order(order_id: str, user=Depends(current_user), db=Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, 'Không tìm thấy đơn hàng.')
    return detail(db, order)


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


@router.post('/orders', status_code=201)
def create(payload: OrderInput, idempotency_key: str = Header(min_length=16, max_length=64),
           user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'ORDER_CREATE')
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode='json'), sort_keys=True).encode()).hexdigest()
    # Lock the caller's row to serialize duplicate submissions from the same account.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    previous = db.scalar(select(RequestKey).where(RequestKey.key == idempotency_key).with_for_update())
    if previous:
        if previous.user_id != user.id or previous.payload_hash != digest:
            raise HTTPException(409, 'Mã yêu cầu đã được sử dụng cho dữ liệu khác.')
        return detail(db, db.get(Order, previous.order_id))
    if payload.version is not None or any(x.id for x in payload.lines):
        raise HTTPException(422, 'Đơn mới không được chứa mã dòng đã lưu.')
    order = save(db, user, payload)
    db.add(RequestKey(key=idempotency_key, user_id=user.id, payload_hash=digest, order_id=order.id))
    db.commit()
    return detail(db, order)


@router.put('/orders/{order_id}')
def update(order_id: str, payload: OrderInput, user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'ORDER_EDIT')
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, 'Không tìm thấy đơn hàng.')
    if payload.version != order.version:
        raise HTTPException(409, 'Đơn đã được sửa ở phiên khác. Đóng form và mở lại trước khi sửa tiếp.')
    order.version += 1
    save(db, user, payload, order)
    db.commit()
    return detail(db, order)
