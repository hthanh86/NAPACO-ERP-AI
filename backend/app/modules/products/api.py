from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from app.core.database import get_db
from app.auth.security import current_user
from app.modules.products.models import Product

router = APIRouter(prefix="/api")

@router.get('/products')
def products(customer_id: str, q: str = '', limit: int = Query(100, ge=1, le=300),
             user=Depends(current_user), db=Depends(get_db)):
    query = select(Product).where(Product.customer_id == customer_id)
    if q:
        query = query.where(or_(Product.name.contains(q, autoescape=True), Product.id.contains(q, autoescape=True),
                                Product.code.contains(q, autoescape=True)))
    return [{'id': x.id, 'name': x.name, 'code': x.code, 'type': x.type, 'unit': x.unit, 'price': str(x.price)}
            for x in db.scalars(query.order_by(Product.name).limit(limit))]
