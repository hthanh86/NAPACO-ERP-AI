"""Template registration, reviewed mappings and immutable releases."""
from datetime import datetime
from typing import Literal
from uuid import uuid4
import re
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
from app.modules.qc import mapping
from app.core.models import Audit
from app.core.performance import measure

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
        if self.check_type=='QC NVL' and self.product_id:
            raise ValueError('QC NVL dùng template chung cho tất cả nguyên vật liệu, không giới hạn sản phẩm.')
        if self.status == 'ACTIVE':
            raise ValueError('Phê duyệt mapping rồi dùng thao tác Kích hoạt riêng.')
        if self.object_type:
            valid_combination(self.check_type, self.object_type)
        suffix = re.search(r'_V(\d+)$', self.form_code)
        if suffix and int(suffix[1]) != self.version:
            raise ValueError('Số phiên bản phải khớp hậu tố _V trong mã template.')
        if self.form_code == 'QC_NVL_V1' and (self.check_type != 'QC NVL' or
                self.object_type not in {None, 'NVL'} or self.product_id or self.version != 1):
            raise ValueError('QC_NVL_V1 phiên bản 1 áp dụng chung QC NVL, không giới hạn sản phẩm.')
        return self


def record(row):
    return {name: getattr(row, name) for name in ('id', 'form_code', 'form_name', 'check_type',
        'object_type', 'product_id', 'spreadsheet_id', 'sheet_id', 'version', 'status',
        'created_by', 'created_at', 'updated_at', 'approved_by', 'approved_at', 'source_hash',
        'source_checked_at', 'source_matches')}


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
    if row.approved_at:
        if not row.source_snapshot:
            raise HTTPException(409, 'Thiếu bản chụp template đã phê duyệt.')
        return {**row.source_snapshot, 'read_only':True, 'frozen_snapshot':True}
    return sheets.first_tab(db, user, row.spreadsheet_id, True)


def save(db, user, data, identifier=None):
    if data.product_id:
        product = db.get(Product, data.product_id)
        if not product:
            raise HTTPException(422, 'Mã sản phẩm không tồn tại trong danh mục.')
        data.product_id = product.id
    # Verify the source for every registration/change, using this manager's Google account.
    source = sheets.first_tab(db, user, data.spreadsheet)
    now = datetime.utcnow()
    if identifier:
        row = db.scalar(select(QCTemplate).where(QCTemplate.id == identifier).with_for_update())
        if not row:
            raise HTTPException(404, 'Không tìm thấy template QC.')
        if not data.expected_updated_at or data.expected_updated_at != row.updated_at:
            raise HTTPException(409, 'Template đã thay đổi. Hãy tra cứu và mở lại trước khi lưu.')
        if row.approved_at:
            raise HTTPException(409, 'Template đã phê duyệt là bất biến. Hãy tạo phiên bản mới.')
    else:
        row = QCTemplate(id=str(uuid4()), created_by=user.id, created_at=now)
    if db.scalar(select(QCTemplate.id).where(QCTemplate.spreadsheet_id == source['spreadsheet_id'],
            QCTemplate.approved_at.is_not(None), QCTemplate.id != row.id).limit(1)):
        raise HTTPException(409, 'Phiên bản mới cần Spreadsheet ID riêng, không dùng lại file đã phê duyệt.')
    changed_source = row.spreadsheet_id != source['spreadsheet_id'] or row.sheet_id != source['sheet_id']
    for name in ('form_code', 'form_name', 'check_type', 'object_type', 'product_id', 'version', 'status'):
        setattr(row, name, getattr(data, name))
    row.spreadsheet_id = source['spreadsheet_id']
    row.sheet_id = source['sheet_id']
    row.updated_at = now
    if changed_source or row.field_mapping:
        row.field_mapping = row.source_snapshot = row.source_hash = None
        row.source_matches = None
    db.add(row)
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


class MappingSave(mapping.MappingInput):
    expected_updated_at: datetime
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class ReleaseAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_updated_at: datetime


def template(db, identifier, expected=None, lock=False):
    statement = select(QCTemplate).where(QCTemplate.id == identifier).execution_options(populate_existing=True)
    row = db.scalar(statement.with_for_update() if lock else statement)
    if not row:
        raise HTTPException(404, 'Không tìm thấy template QC.')
    if expected is not None and row.updated_at != expected:
        raise HTTPException(409, 'Template đã thay đổi. Hãy tải lại trước khi tiếp tục.')
    return row


def editable(row):
    if row.approved_at or row.status == 'ACTIVE':
        raise HTTPException(409, 'Template đã phê duyệt không được sửa. Hãy tạo phiên bản mới với file và mapping riêng.')


@router.get('/api/qc/templates/{identifier}/mapping')
def get_mapping(identifier: str, user=Depends(manager), db=Depends(get_db)):
    row = template(db, identifier)
    return {**record(row), 'mapping':row.field_mapping, 'snapshot':row.source_snapshot, 'sources':mapping.SOURCES}


@router.post('/api/qc/templates/{identifier}/suggest')
@measure('qc.template.mapping.suggest')
def suggest_mapping(identifier: str, action: ReleaseAction, user=Depends(manager), db=Depends(get_db)):
    row = template(db, identifier, action.expected_updated_at)
    editable(row)
    source = sheets.first_tab(db, user, row.spreadsheet_id, True)
    row = template(db, identifier, action.expected_updated_at, lock=True)
    editable(row)
    return {**mapping.suggest(source), 'snapshot':mapping.snapshot(source),
            'source_hash':mapping.source_hash(source), 'sources':mapping.SOURCES}


@router.put('/api/qc/templates/{identifier}/mapping')
@measure('qc.template.mapping.save_approve')
def save_mapping(identifier: str, data: MappingSave, user=Depends(manager), db=Depends(get_db)):
    row = template(db, identifier, data.expected_updated_at)
    editable(row)
    with measure('qc.template.google.read'):
        source = sheets.first_tab(db, user, row.spreadsheet_id, True)
    if mapping.source_hash(source) != data.source_hash:
        raise HTTPException(409, 'Nguồn Google đã thay đổi. Đọc lại và kiểm tra mapping trước khi lưu.')
    # Saving is the manager's explicit approval; suggestions alone never release a template.
    reviewed = mapping.MappingInput(fields=[field.model_copy(update={'reviewed':True}) for field in data.fields],
        signature_cell=data.signature_cell,signature_end_cell=data.signature_end_cell)
    with measure('qc.template.mapping.validate', fields=len(data.fields)):
        validated = mapping.validate(source, reviewed, row.check_type, approve=True)
    row = template(db, identifier, data.expected_updated_at, lock=True)
    editable(row)
    row.field_mapping = validated
    row.source_snapshot = mapping.snapshot(source)
    row.source_hash = data.source_hash
    row.sheet_id = source['sheet_id']
    row.source_matches = True
    row.updated_at = row.source_checked_at = datetime.utcnow()
    row.approved_by, row.approved_at = user.id, row.updated_at
    row.status = 'ACTIVE'
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_MAPPING_SAVE', entity_id=row.id,
                 details={'source_hash':row.source_hash,'mapping_hash':mapping.digest(validated)}))
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_APPROVE', entity_id=row.id,
                 details={'source_hash':row.source_hash,'mapping_hash':mapping.digest(validated)}))
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_STATUS', entity_id=row.id, details={'status':'ACTIVE'}))
    with measure('qc.template.mysql.commit'):
        db.commit()
    return {**record(row), 'mapping':row.field_mapping, 'snapshot':row.source_snapshot, 'sources':mapping.SOURCES}


@measure('qc.template.source.verify')
def check_source(db, user, identifier, expected):
    row = template(db, identifier, expected)
    if not row.source_hash or not row.source_snapshot or not row.field_mapping:
        raise HTTPException(422, 'Cần lưu mapping và bản chụp template trước.')
    with measure('qc.template.google.read'):
        source = sheets.first_tab(db, user, row.spreadsheet_id, True)
    row = template(db, identifier, expected, lock=True)
    row.source_matches = (mapping.source_hash(source) == row.source_hash and source['sheet_id'] == row.sheet_id)
    row.updated_at = row.source_checked_at = datetime.utcnow()
    if not row.source_matches:
        row.status = 'INACTIVE'
        db.add(Audit(user_id=user.id, action='QC_TEMPLATE_SOURCE_CHANGED', entity_id=row.id,
                     details={'source_hash':row.source_hash}))
        db.commit()
        raise HTTPException(409, 'Google Sheets đã khác bản chụp đã lưu. Đã ngừng kích hoạt; hãy tạo phiên bản mới hoặc đọc lại mapping nếu chưa phê duyệt.')
    return row


@router.post('/api/qc/templates/{identifier}/approve')
@measure('qc.template.approve')
def approve(identifier: str, action: ReleaseAction, user=Depends(manager), db=Depends(get_db)):
    editable(template(db, identifier, action.expected_updated_at))
    row = check_source(db, user, identifier, action.expected_updated_at)
    editable(row)
    fields = [{key:value for key,value in item.items() if key in mapping.MappingField.model_fields}
              for item in row.field_mapping['fields']]
    mapping.validate(row.source_snapshot, mapping.MappingInput(fields=fields), row.check_type, approve=True)
    row.approved_by, row.approved_at = user.id, datetime.utcnow()
    row.updated_at = row.approved_at
    row.status = 'ACTIVE'
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_APPROVE', entity_id=row.id,
                 details={'source_hash':row.source_hash,'mapping_hash':mapping.digest(row.field_mapping)}))
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_STATUS', entity_id=row.id, details={'status':'ACTIVE'}))
    db.commit()
    return record(row)


@router.post('/api/qc/templates/{identifier}/verify')
def verify(identifier: str, action: ReleaseAction, user=Depends(manager), db=Depends(get_db)):
    row = check_source(db, user, identifier, action.expected_updated_at)
    db.commit()
    return record(row)


class StatusAction(ReleaseAction):
    status: Literal['ACTIVE','INACTIVE']


class SignatureLocation(ReleaseAction):
    cell: str = Field(max_length=5)
    end_cell: str | None = Field(default=None,max_length=5)


@router.post('/api/qc/templates/{identifier}/signature-location')
@measure('qc.template.signature.approve')
def signature_location(identifier: str, action: SignatureLocation, user=Depends(manager), db=Depends(get_db)):
    row = check_source(db, user, identifier, action.expected_updated_at)
    if not row.approved_at or row.field_mapping.get('signature_cell'):
        raise HTTPException(409, 'Chỉ bổ sung lần đầu vị trí chữ ký cho mẫu đã duyệt; đổi vị trí cần phiên bản mới.')
    fields = [{k:v for k,v in item.items() if k in mapping.MappingField.model_fields} for item in row.field_mapping['fields']]
    validated = mapping.validate(row.source_snapshot, mapping.MappingInput(fields=fields, signature_cell=action.cell,signature_end_cell=action.end_cell), row.check_type)
    row.field_mapping = {**row.field_mapping,'signature_cell':validated['signature_cell'],
        'signature_approval':{'user_id':user.id,'approved_at':datetime.utcnow().isoformat()}}
    if validated.get('signature_end_cell'):
        row.field_mapping = {**row.field_mapping,'signature_end_cell':validated['signature_end_cell']}
    row.updated_at = datetime.utcnow()
    db.add(Audit(user_id=user.id,action='QC_TEMPLATE_SIGNATURE_LOCATION',entity_id=row.id,
        details={'cell':validated['signature_cell']}))
    db.commit()
    return record(row)


@router.post('/api/qc/templates/{identifier}/status')
def change_status(identifier: str, action: StatusAction, user=Depends(manager), db=Depends(get_db)):
    row = template(db, identifier, action.expected_updated_at)
    if action.status == 'ACTIVE':
        if not row.approved_at:
            raise HTTPException(422, 'Chỉ template đã phê duyệt mới được kích hoạt.')
        row = check_source(db, user, identifier, action.expected_updated_at)
    else:
        row = template(db, identifier, action.expected_updated_at, lock=True)
    row.status = action.status
    row.updated_at = datetime.utcnow()
    db.add(Audit(user_id=user.id, action='QC_TEMPLATE_STATUS', entity_id=row.id, details={'status':row.status}))
    db.commit()
    return record(row)
