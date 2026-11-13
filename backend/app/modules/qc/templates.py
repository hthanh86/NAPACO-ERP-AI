"""QC template administration only; never participates in QC form selection."""
from datetime import datetime
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.auth.security import current_user, require
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.integrations.google import sheets
from app.modules.qc.template_models import QCTemplate
from app.modules.qc.schemas import CheckType, ObjectType
from app.modules.qc.service import valid_combination
from app.modules.products.models import Product

router = APIRouter()


def manager(user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_TEMPLATE_MANAGE')
    return user


class InspectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    spreadsheet: str = Field(min_length=1, max_length=2048)
    preview: bool = False


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    form_code: str = Field(pattern=r'^[A-Z][A-Z0-9_]{0,99}$')
    form_name: str = Field(min_length=1, max_length=300)
    check_type: CheckType
    object_type: ObjectType | None = None
    product_id: str | None = Field(default=None, min_length=1, max_length=100)
    spreadsheet: str = Field(min_length=1, max_length=2048)
    version: int = Field(default=1, ge=1, le=2147483647)
    status: Literal['DRAFT', 'ACTIVE', 'INACTIVE'] = 'DRAFT'
    expected_updated_at: datetime | None = None

    @model_validator(mode='after')
    def validate_scope(self):
        if self.status == 'ACTIVE':
            raise ValueError('Bước 1 chưa cho phép ACTIVE. Hãy lưu DRAFT hoặc INACTIVE.')
        if self.object_type:
            valid_combination(self.check_type, self.object_type)
        if self.form_code == 'QC_NVL_V1' and (self.check_type != 'QC NVL' or
                self.object_type not in {None, 'NVL'} or self.product_id or self.version != 1):
            raise ValueError('QC_NVL_V1 phiên bản 1 áp dụng chung QC NVL, không giới hạn sản phẩm.')
        return self


def record(row):
    return {name: getattr(row, name) for name in ('id', 'form_code', 'form_name', 'check_type',
        'object_type', 'product_id', 'spreadsheet_id', 'sheet_id', 'version', 'status',
        'created_by', 'created_at', 'updated_at')}


@router.get('/qc/templates')
def page(user=Depends(manager)):
    return FileResponse(FRONTEND_ROOT / 'qc/templates.html')


@router.get('/api/qc/templates')
def listing(q: str = Query('', max_length=100), page: int = Query(1, ge=1),
            size: int = Query(20, ge=1, le=50), user=Depends(manager), db=Depends(get_db)):
    statement = select(QCTemplate)
    if q.strip():
        statement = statement.where(QCTemplate.form_code.contains(q.strip(), autoescape=True) |
                                    QCTemplate.form_name.contains(q.strip(), autoescape=True))
    rows = db.scalars(statement.order_by(QCTemplate.created_at.desc(), QCTemplate.id)
                      .offset((page - 1) * size).limit(size + 1)).all()
    return {'items': [record(row) for row in rows[:size]], 'has_more': len(rows) > size, 'page': page}


@router.post('/api/qc/templates/inspect')
def inspect_sheet(data: InspectInput, user=Depends(manager), db=Depends(get_db)):
    return sheets.first_tab(db, user, data.spreadsheet, data.preview)


@router.get('/api/qc/templates/{identifier}/preview')
def preview(identifier: str, user=Depends(manager), db=Depends(get_db)):
    row = db.get(QCTemplate, identifier)
    if not row:
        raise HTTPException(404, 'Không tìm thấy template QC.')
    return sheets.first_tab(db, user, row.spreadsheet_id, True)


def save(db, user, data, identifier=None):
    if data.product_id and not db.get(Product, data.product_id):
        raise HTTPException(422, 'Mã sản phẩm không tồn tại trong danh mục.')
    # Verify the source for every registration/change, using this manager's Google account.
    source = sheets.first_tab(db, user, data.spreadsheet)
    now = datetime.utcnow()
    if identifier:
        row = db.scalar(select(QCTemplate).where(QCTemplate.id == identifier).with_for_update())
        if not row:
            raise HTTPException(404, 'Không tìm thấy template QC.')
        if not data.expected_updated_at or data.expected_updated_at != row.updated_at:
            raise HTTPException(409, 'Template đã thay đổi. Hãy tra cứu và mở lại trước khi lưu.')
        if row.status == 'ACTIVE':
            raise HTTPException(409, 'Bước 1 không chỉnh template đã kích hoạt ở giai đoạn khác.')
    else:
        row = QCTemplate(id=str(uuid4()), created_by=user.id, created_at=now)
        db.add(row)
    for name in ('form_code', 'form_name', 'check_type', 'object_type', 'product_id', 'version', 'status'):
        setattr(row, name, getattr(data, name))
    row.spreadsheet_id = source['spreadsheet_id']
    row.sheet_id = source['sheet_id']
    row.updated_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Mã template đã tồn tại hoặc dữ liệu liên kết đã thay đổi. Hãy tra cứu lại.') from None
    return record(row)


@router.post('/api/qc/templates', status_code=201)
def create(data: TemplateInput, user=Depends(manager), db=Depends(get_db)):
    return save(db, user, data)


@router.put('/api/qc/templates/{identifier}')
def update(identifier: str, data: TemplateInput, user=Depends(manager), db=Depends(get_db)):
    return save(db, user, data, identifier)
