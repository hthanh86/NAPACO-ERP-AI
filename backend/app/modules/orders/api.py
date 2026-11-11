import hashlib
import json
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import select, func, or_
from app.core.database import get_db
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.auth.models import User
from app.modules.orders.models import Order, OrderLine, RequestKey
from app.auth.security import current_user, require

from app.modules.orders.schemas import OrderInput, STATUSES
from app.modules.orders.service import detail, save

router = APIRouter(prefix="/api")

@router.get('/catalog')
def catalog(user=Depends(current_user), db=Depends(get_db)):
    return {'customers': [{'id': x.id, 'name': x.name} for x in db.scalars(select(Customer).order_by(Customer.name))],
            'staff': [{'id': x.id, 'name': x.name} for x in db.scalars(select(User).where(User.active.is_(True)))],
            'statuses': STATUSES}


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
