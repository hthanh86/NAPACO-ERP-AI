"""Master catalog administration against existing MySQL entities."""
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select, or_, func, cast, Integer
from sqlalchemy.exc import IntegrityError
from app.auth.security import current_user, require
from app.core.database import get_db
from app.core.models import Audit
from app.core.paths import FRONTEND_ROOT
from app.compatibility.models import LegacyState
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.materials.models import FilmSupplier

router = APIRouter()
Kind = Literal['customers', 'products', 'suppliers']
CATALOGS = {
    'customers': (Customer, ['id', 'name', 'address', 'contact', 'phone'], 'CUSTOMER_MANAGE', 'KH'),
    'products': (Product, ['id', 'name', 'customer_id', 'source_customer_id', 'code', 'type', 'unit', 'price'], 'PRODUCT_MANAGE', 'SP'),
    'suppliers': (FilmSupplier, ['id', 'name', 'category'], 'SUPPLIER_MANAGE', 'NCC'),
}
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: Name
    address: str = Field(default='', max_length=10000)
    contact: str = Field(default='', max_length=500)
    phone: str = Field(default='', max_length=200)
    version: str | None = Field(default=None, max_length=64)


class ProductInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: Name
    customer_id: str = Field(min_length=1, max_length=100)
    code: str = Field(default='', max_length=200)
    type: Literal['1', '2']
    unit: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=20, decimal_places=4, allow_inf_nan=False)
    version: str | None = Field(default=None, max_length=64)


class SupplierInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: Name
    category: str = Field(default='', max_length=500)
    version: str | None = Field(default=None, max_length=64)


SCHEMAS = {'customers': CustomerInput, 'products': ProductInput, 'suppliers': SupplierInput}


def record(values):
    result = {key: str(value) if isinstance(value, Decimal) else value for key, value in dict(values).items()}
    result['version'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


@router.get('/master/{kind}')
def page(kind: Kind, user=Depends(current_user)):
    return FileResponse(FRONTEND_ROOT / 'master/catalog.html')


@router.get('/api/master/{kind}')
def listing(kind: Kind, q: str = Query('', max_length=200), customer_id: str = Query('', max_length=100),
            page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
            user=Depends(current_user), db=Depends(get_db)):
    model, fields, permission, _ = CATALOGS[kind]
    columns = [getattr(model, key) for key in fields]
    statement = select(*columns)
    if q.strip():
        searchable = [model.id, model.name] + ([Product.code] if kind == 'products' else [])
        statement = statement.where(or_(*[column.contains(q.strip(), autoescape=True) for column in searchable]))
    if kind == 'products' and customer_id:
        statement = statement.where(Product.customer_id == customer_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    items = [record(row) for row in db.execute(statement.order_by(model.id).offset((page-1)*size).limit(size)).mappings()]
    from app.auth.models import RolePermission
    grant = db.get(RolePermission, (user.role, permission)) if user.role != 'LOCAL_ADMIN' else None
    return {'items': items, 'total': total, 'page': page, 'size': size,
            'can_manage': user.role == 'LOCAL_ADMIN' or bool(grant and grant.allowed)}


@router.post('/api/master/{kind}', status_code=201)
@router.put('/api/master/{kind}/{identifier}')
def save(kind: Kind, payload: dict, identifier: str | None = None,
         user=Depends(current_user), db=Depends(get_db)):
    model, fields, permission, prefix = CATALOGS[kind]
    require(db, user, permission)
    from pydantic import ValidationError
    try:
        data = SCHEMAS[kind].model_validate(payload)
    except ValidationError:
        raise HTTPException(422, 'Thông tin không hợp lệ. Kiểm tra các trường bắt buộc, độ dài và giá trị số.')
    # Use the same serialization lock as existing order/catalog writes.
    state = db.scalar(select(LegacyState).where(LegacyState.id == 1).with_for_update())
    if not state:
        raise HTTPException(503, 'Chưa khởi tạo dữ liệu ERP.')
    entity = None
    if identifier is not None:
        entity = db.scalar(select(model).where(model.id == identifier).with_for_update())
        if not entity:
            raise HTTPException(404, 'Không tìm thấy bản ghi.')
        current = record({key: getattr(entity, key) for key in fields})
        if data.version != current['version']:
            raise HTTPException(409, 'Dữ liệu đã thay đổi. Tìm kiếm lại và mở bản ghi mới nhất trước khi sửa.')
    elif data.version is not None:
        raise HTTPException(422, 'Bản ghi mới không có phiên bản cũ.')
    if kind == 'products':
        if not db.get(Customer, data.customer_id):
            raise HTTPException(422, 'Khách hàng không tồn tại.')
        if entity and (entity.customer_id or entity.source_customer_id) != data.customer_id:
            raise HTTPException(422, 'Không đổi khách hàng của sản phẩm đã lưu để bảo toàn liên kết đơn hàng.')
    if entity is None:
        # Preserve KHxxxx / SPxxxx and NCCxx numbering used by existing workflows.
        largest = db.scalar(select(func.max(cast(func.substring(model.id, len(prefix)+1), Integer)))
                            .where(model.id.op('REGEXP')('^' + prefix + '[0-9]+$'))) or 0
        if kind == 'suppliers' and largest >= 99:
            raise HTTPException(422, 'Đã hết dải mã NCC01–NCC99 của nghiệp vụ hiện tại. Cần thống nhất quy tắc mã trước khi mở rộng.')
        entity = model(id=prefix + str(largest+1).zfill(2 if kind == 'suppliers' else 4), source={})
        db.add(entity)
    changed = []
    for key, value in data.model_dump(exclude={'version'}).items():
        if getattr(entity, key) != value:
            setattr(entity, key, value)
            changed.append(key)
    if kind == 'products':
        entity.source_customer_id = data.customer_id
    state.revision += 1
    db.add(Audit(user_id=user.id, action='MASTER_' + ('UPDATE' if identifier else 'CREATE'),
                 entity_id=entity.id, details={'catalog': kind, 'fields': changed}))
    try:
        db.flush()
        result = record({key: getattr(entity, key) for key in fields})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Mã hoặc dữ liệu liên kết đã thay đổi. Vui lòng tải lại và thử lại.')
    return result
