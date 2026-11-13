from datetime import date, datetime, time
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, func, or_
from app.auth.security import current_user, require
from app.auth.models import User
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.integrations.google import drive
from app.modules.qc.schemas import QCInput, QCBatchInput, CheckType, ObjectType, UploadInput
from app.modules.qc.models import QualityCheck
from app.modules.qc import service, forms, drive_bundle

router = APIRouter()


def allowed(db, user, *permissions):
    for permission in permissions:
        try:
            require(db, user, permission)
            return
        except HTTPException as error:
            if error.status_code != 403:
                raise
    raise HTTPException(403, 'Bạn chưa có quyền truy cập chức năng QC này.')


@router.get('/qc/{view}')
def page(view: Literal['create', 'list', 'ncr'], user=Depends(current_user), db=Depends(get_db)):
    if view == 'create':
        require(db, user, 'QC_CREATE')
    else:
        allowed(db, user, 'QC_VIEW', 'QC_CREATE', 'QC_EDIT') if view == 'ncr' else require(db, user, 'QC_VIEW')
    return FileResponse(FRONTEND_ROOT / 'qc/index.html')


@router.get('/api/qc/objects')
def objects(check_type: CheckType, object_type: ObjectType, q: str = Query('', max_length=200),
            page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=50),
            user=Depends(current_user), db=Depends(get_db)):
    allowed(db, user, 'QC_VIEW', 'QC_CREATE', 'QC_EDIT')
    service.valid_combination(check_type, object_type)
    if object_type == 'NVL':
        from app.modules.qc.materials import objects as material_objects
        items, has_more = material_objects(q, page, size, db)
        return {'items':[service.object_record(item) for item in items], 'has_more':has_more, 'page':page}
    if not q.strip():
        return {'items': [], 'has_more': False, 'page': page}
    model = service.MODELS[object_type]
    statement = service.object_query(object_type)
    # The source type comes only from the fixed model mapping, never raw SQL.
    conditions = [model.id.contains(q.strip(), autoescape=True)]
    for attr in ('production_order_id', 'setup_id', 'machine_id', 'line_id'):
        if hasattr(model, attr):
            conditions.append(getattr(model, attr).contains(q.strip(), autoescape=True))
    if object_type in {'HUT', 'CAT', 'EB'}:
        from app.modules.production.models import ProductionSetup
        conditions.append(ProductionSetup.production_order_id.contains(q.strip(), autoescape=True))
    rows = db.execute(statement.where(or_(*conditions)).order_by(model.id.desc()).offset((page-1)*size).limit(size+1)).mappings().all()
    return {'items': [service.object_record(row) for row in rows[:size]], 'has_more': len(rows)>size, 'page': page}


@router.get('/api/qc/drive')
def drive_files(q: str = Query('', max_length=200), user=Depends(current_user), db=Depends(get_db)):
    allowed(db, user, 'QC_CREATE', 'QC_EDIT')
    result = drive.search(db, user, q)
    db.commit()  # Persist an OAuth token refresh, if any.
    return result


@router.get('/api/qc/forms')
def form_catalog(user=Depends(current_user), db=Depends(get_db)):
    allowed(db, user, 'QC_VIEW', 'QC_CREATE', 'QC_EDIT')
    from app.core.settings import get_setting
    return {'items':[forms.definition(code) for code in forms.RELEASED.values() if code],
            'released':forms.RELEASED, 'root_folder_id':get_setting(db, 'QC_ROOT_FOLDER_ID')}


@router.get('/api/qc/folders')
def folders(folder_id: str | None = Query(None, pattern=r'^[A-Za-z0-9_-]{1,255}$'),
            page_token: str = Query('', max_length=4096), user=Depends(current_user), db=Depends(get_db)):
    allowed(db, user, 'QC_CREATE', 'QC_EDIT')
    return drive_bundle.browse(db, user, folder_id, page_token)


def writable_record(db, user, identifier):
    allowed(db, user, 'QC_CREATE', 'QC_EDIT')
    obj = db.get(QualityCheck, identifier)
    if obj is None:
        raise HTTPException(404, 'Không tìm thấy phiếu QC.')
    if obj.template_id:
        raise HTTPException(422, 'Bước 2 chưa hỗ trợ PDF, thư mục hoặc upload cho template mapping.')
    if obj.staff_id != user.id:
        require(db, user, 'QC_EDIT')
    return obj


@router.post('/api/qc/{identifier}/bundle')
def prepare_bundle(identifier: str, user=Depends(current_user), db=Depends(get_db)):
    writable_record(db, user, identifier)
    return service.detail_record(db, drive_bundle.prepare(db, user, identifier))


@router.get('/api/qc/{identifier}/pdf')
def download_pdf(identifier: str, user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_VIEW')
    obj = db.get(QualityCheck, identifier)
    if obj is None or not obj.form_data or obj.template_id:
        raise HTTPException(404, 'Phiếu chưa có biểu mẫu ERP.')
    try:
        from app.modules.qc.pdf import render_pdf
    except ImportError:
        raise HTTPException(503, 'Chưa cài thư viện PDF cho backend. Cần ReportLab và font DejaVu Sans.') from None
    return Response(render_pdf(obj), media_type='application/pdf', headers={'Content-Disposition':
        'attachment; filename="'+forms.document_id(obj.id)+'.pdf"'})


@router.post('/api/qc/{identifier}/uploads')
def start_upload(identifier: str, data: UploadInput, user=Depends(current_user), db=Depends(get_db)):
    return drive_bundle.start_upload(db, user, writable_record(db, user, identifier), data)


@router.put('/api/qc/{identifier}/uploads/chunk')
async def upload_chunk(identifier: str, request: Request, upload_ticket: str = Header(alias='X-QC-Upload-Ticket'),
                       offset: int = Query(0, ge=0), probe: bool = False,
                       user=Depends(current_user), db=Depends(get_db)):
    obj = writable_record(db, user, identifier)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > drive_bundle.CHUNK_SIZE:
            raise HTTPException(413, 'Mỗi khối upload tối đa 4 MiB.')
    return await run_in_threadpool(drive_bundle.upload_chunk, db, user, obj, upload_ticket, offset, bytes(content), probe)


@router.get('/api/qc')
def listing(q: str = Query('', max_length=100), check_type: CheckType | None = None,
            object_type: ObjectType | None = None, object_id: str = Query('', max_length=100),
            production_order_id: str = Query('', max_length=100), date_from: date | None = None,
            date_to: date | None = None, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
            user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_VIEW')
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc.')
    conditions = []
    for attr, value in [('id', q), ('object_id', object_id), ('production_order_id', production_order_id)]:
        if value.strip():
            conditions.append(getattr(QualityCheck, attr).contains(value.strip(), autoescape=True))
    for attr, value in [('check_type', check_type), ('object_type', object_type)]:
        if value:
            conditions.append(getattr(QualityCheck, attr) == value)
    if date_from:
        conditions.append(QualityCheck.checked_at >= datetime.combine(date_from, time()))
    if date_to:
        conditions.append(QualityCheck.checked_at <= datetime.combine(date_to, time.max))
    total = db.scalar(select(func.count()).select_from(QualityCheck).where(*conditions))
    # Omit long notes, images and source JSON from the paginated list.
    fields = ['id', 'checked_at', 'check_type', 'object_type', 'object_id', 'production_order_id',
              'quantity', 'result', 'staff_id', 'standard_url', 'drive_folder_id']
    rows = db.execute(select(*[getattr(QualityCheck, key) for key in fields],
                             User.name.label('staff_name'), QualityCheck.image_url.label('evidence'),
                             func.json_contains_path(QualityCheck.source, 'one', '$.qc_evidence_task').label('legacy_pending'),
                             QualityCheck.source[drive_bundle.JOB]['pending'].as_boolean().label('bundle_pending'))
                      .outerjoin(User, User.id == QualityCheck.staff_id).where(*conditions)
                      .order_by(QualityCheck.checked_at.desc(), QualityCheck.id.desc()).offset((page-1)*size).limit(size)).mappings().all()
    items = [dict(row) for row in rows]
    for item in items:
        if item['drive_folder_id']:
            item['evidence'] = 'https://drive.google.com/drive/folders/'+item['drive_folder_id']
        legacy_pending, bundle_pending = item.pop('legacy_pending'), item.pop('bundle_pending')
        item['evidence_pending'] = bool(legacy_pending or bundle_pending)
        item['staff_name'] = item['staff_name'] or 'Chưa xác định'
        if item['quantity'] is not None:
            item['quantity'] = format(item['quantity'], '.8f')
    return {'items': items, 'total': total, 'page': page, 'size': size}


@router.get('/api/qc/{identifier}')
def detail(identifier: str, user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_VIEW')
    obj = db.get(QualityCheck, identifier)
    if obj is None:
        raise HTTPException(404, 'Không tìm thấy phiếu QC.')
    return service.detail_record(db, obj)


@router.post('/api/qc', status_code=201)
def create(data: QCInput, idempotency_key: UUID = Header(), user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_CREATE')
    return service.create(db, user, data, str(idempotency_key))


@router.post('/api/qc/batch', status_code=201)
def create_batch(data: QCBatchInput, idempotency_key: UUID = Header(), user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_CREATE')
    return service.create_records(db, user, data.items, str(idempotency_key))


@router.put('/api/qc/{identifier}')
def update(identifier: str, data: QCInput, user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'QC_EDIT')
    return service.update(db, user, identifier, data)
