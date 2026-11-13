"""QC records only; no updates to receipts, stock, setup or production status."""
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, literal, func, or_
from sqlalchemy.dialects.mysql import insert
from app.core.models import Audit, Sequence
from app.compatibility.models import LegacyRequest
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.production.models import ProductionOrder, ProductionSetup, FormingLog, CuttingLog, EBLog
from app.modules.qc.models import QualityCheck
from app.modules.qc.materials import eligibility
from app.modules.qc import evidence, forms, drive_bundle
from app.auth.models import User

ALLOWED = {'QC NVL': {'NVL'}, 'QC ĐẦU CA': {'SETUP'},
           'QC GIỮA CA': {'HUT', 'CAT', 'EB'}, 'QC CUỐI CA': {'HUT', 'CAT', 'EB'}}
MODELS = {'NVL': FilmReceipt, 'SETUP': ProductionSetup, 'HUT': FormingLog, 'CAT': CuttingLog, 'EB': EBLog}
TIMEZONE = ZoneInfo('Asia/Ho_Chi_Minh')


def valid_combination(check_type, object_type):
    if object_type not in ALLOWED.get(check_type, set()):
        raise HTTPException(422, 'Loại kiểm tra và đối tượng không phù hợp.')


def object_query(kind):
    model = MODELS[kind]
    if kind == 'NVL':
        return select(model.id, literal('').label('production_order_id'), model.receipt_date.label('date'),
                      model.line_id.label('reference'), model.location.label('info'))
    if kind == 'SETUP':
        return select(model.id, model.production_order_id, model.checked_at.label('date'),
                      model.machine_id.label('reference'), model.stage.label('info'))
    statement = select(model.id,
                       func.coalesce(func.nullif(model.production_order_id, ''), ProductionSetup.production_order_id).label('production_order_id')
                       if kind == 'HUT' else ProductionSetup.production_order_id,
                       model.run_date.label('date'), model.setup_id.label('reference'),
                       (model.mold_id if kind == 'HUT' else model.machine_id).label('info'))
    return statement.outerjoin(ProductionSetup, ProductionSetup.id == model.setup_id)


def object_record(row):
    result = dict(row)
    for key, value in result.items():
        if hasattr(value, 'isoformat'):
            result[key] = value.isoformat()
        elif value is None:
            result[key] = ''
    return result


def resolve_object(db, data, existing=None):
    valid_combination(data.check_type, data.object_type)
    model = MODELS[data.object_type]
    obj = db.scalar(select(model).where(model.id == data.object_id).with_for_update())
    if obj is None:
        raise HTTPException(422, 'OBJECT_ID không tồn tại trong nguồn ' + data.object_type + '.')
    unchanged = (existing is not None and existing.object_id == obj.id and
                 existing.object_type == data.object_type)
    if data.object_type == 'NVL' and not unchanged:
        eligible = db.scalar(select(FilmReceipt.id).where(FilmReceipt.id == obj.id, *eligibility()))
        if eligible is None:
            raise HTTPException(422, obj.id + ': chỉ chọn NVL còn tồn, nhập trong 15 ngày gần nhất và chưa có QC.')
    lsx = ''
    if data.object_type == 'SETUP':
        lsx = obj.production_order_id or ''
    elif data.object_type in {'HUT', 'CAT', 'EB'}:
        lsx = getattr(obj, 'production_order_id', None) or ''
        if not lsx and obj.setup_id:
            setup = db.scalar(select(ProductionSetup).where(ProductionSetup.id == obj.setup_id).with_for_update())
            lsx = setup.production_order_id if setup else ''
    if lsx and db.scalar(select(ProductionOrder.id).where(ProductionOrder.id == lsx).with_for_update()) is None:
        raise HTTPException(422, 'Nguồn tham chiếu LSX chưa có trong bảng lệnh sản xuất: ' + lsx)
    return obj.id, lsx or None


FIELDS = ['id', 'checked_at', 'check_type', 'object_type', 'object_id', 'production_order_id',
          'standard_url', 'quantity', 'result', 'staff_id', 'ncr_id', 'note', 'image_url', 'drive_folder_id', 'form_data', 'template_id']


def record(obj):
    result = {}
    for key in FIELDS:
        value = getattr(obj, key)
        result[key] = format(value, '.8f') if isinstance(value, Decimal) else value.isoformat() if isinstance(value, datetime) else value
    result['version'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def staff_name(db, identifier):
    user = db.get(User, identifier) if identifier else None
    if user is None and identifier:
        user = db.scalar(select(User).where(User.email == identifier))
    return user.name if user else 'Chưa xác định'


def detail_record(db, obj):
    result = record(obj)
    result['staff_name'] = staff_name(db, obj.staff_id)
    result['form_document_id'] = forms.document_id(obj.id) if obj.form_data and not obj.template_id else None
    result['evidence'] = ('https://drive.google.com/drive/folders/'+obj.drive_folder_id) if obj.drive_folder_id else obj.image_url
    task = (obj.source or {}).get(drive_bundle.JOB) if obj.form_data else (obj.source or {}).get(evidence.TASK)
    result['evidence_pending'] = bool(task and task.get('pending', True))
    result['evidence_error'] = task.get('error', 'Bằng chứng đang chờ xử lý trên Drive.') if task else ''
    return result


def finish_evidence(db, user, result, batch):
    records = result['items'] if batch else [result]
    completed = []
    for item in records:
        if not item.get('evidence_pending'):
            completed.append(item)
            continue
        if item.get('form_data'):
            drive_bundle.prepare(db, user, item['id'])
        else:
            evidence.process(db, user, item['id'])
        completed.append(detail_record(db, db.get(QualityCheck, item['id'])))
    return {'items': completed} if batch else completed[0]


def apply_values(db, obj, data, identifier, lsx, user):
    values = data.model_dump(exclude={'version', 'form', 'mapped_form', 'parent_folder_id'})
    stamp = values['checked_at']
    values['checked_at'] = stamp.astimezone(TIMEZONE).replace(tzinfo=None) if stamp.tzinfo else stamp
    values['checked_at'] = values['checked_at'].replace(microsecond=0)
    values['object_id'] = identifier
    values['production_order_id'] = lsx
    for key, value in values.items():
        setattr(obj, key, value)
    if data.mapped_form:
        from app.modules.qc.template_runtime import filled
        obj.form_data = filled(db, user, data, obj.id, lsx)
        obj.template_id = data.mapped_form.template_id
        obj.standard_url = 'https://docs.google.com/spreadsheets/d/' + obj.form_data['template']['spreadsheet_id'] + '/edit'
        return
    if data.form:
        saved_definition = (obj.form_data or {}).get('definition')
        if saved_definition and saved_definition['code'] == data.form.code:
            if saved_definition.get('business', 'NVL') != forms.business(data.check_type):
                raise HTTPException(422, 'Template đã lưu không áp dụng cho nghiệp vụ này.')
        else:
            saved_definition = None
            released = forms.current(data.check_type)
            if not released or released['code'] != data.form.code:
                raise HTTPException(422, 'Chỉ được dùng template đang ban hành cho nghiệp vụ này.')
        context = {key:str(values[key]) for key in ('checked_at','check_type','object_type','object_id','quantity','result','note')}
        snapshot = forms.filled_form(data.form, user, context, saved_definition)
        snapshot['document_id'] = forms.document_id(obj.id)
        expected = 'OK' if data.form.conclusion == 'PASS' else 'NG'
        if data.result != expected:
            raise HTTPException(422, 'Kết quả phiếu phải khớp kết luận biểu mẫu: PASS = OK, FAIL = NG.')
        # An unchanged form retains the original internal signature timestamp.
        if not obj.form_data or obj.form_data.get('input') != snapshot['input'] or obj.form_data.get('context') != context:
            obj.form_data = snapshot
        obj.standard_url = data.form.code
    elif obj.form_data:
        raise HTTPException(422, 'Phiếu đã có form ERP phải gửi đầy đủ form khi sửa.')


def create(db, user, data, request_id):
    return create_records(db, user, [data], request_id, batch=False)


def create_records(db, user, items, request_id, batch=True):
    # Preserve existing legacy idempotency hashes when the optional new branch is absent.
    excluded = lambda item: {'version'} | ({'mapped_form'} if item.mapped_form is None else set())
    contents = [item.model_dump(mode='json', exclude=excluded(item)) for item in items]
    raw = json.dumps(contents, sort_keys=True) if batch else items[0].model_dump_json(exclude=excluded(items[0]))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    key = ('qcb:' if batch else 'qc:') + request_id
    # Reserve the shared request row atomically; concurrent retries wait for commit.
    db.execute(insert(LegacyRequest).values(id=key, user_id=user.id, payload_hash=digest, result={})
               .on_duplicate_key_update(id=key))
    request = db.scalar(select(LegacyRequest).where(LegacyRequest.id == key).with_for_update())
    if request.user_id != user.id or request.payload_hash != digest:
        raise HTTPException(409, 'Mã yêu cầu đã được sử dụng cho nội dung khác.')
    if request.result:
        result = request.result
        db.commit()
        return finish_evidence(db, user, result, batch)
    for data in items:
        if data.mapped_form and (data.form or data.parent_folder_id or data.image_url):
            raise HTTPException(422, 'Template mapping chỉ lưu MySQL; không gửi form ký, thư mục hoặc bằng chứng.')
        if data.check_type == 'QC NVL' and not data.form and not data.mapped_form:
            raise HTTPException(422, 'Phiếu IQC mới cần biểu mẫu ERP đã nhập và ký.')
        if data.form:
            if not data.parent_folder_id:
                raise HTTPException(422, 'Hãy chọn thư mục cha cho hồ sơ QC.')
            token = drive_bundle.access_token(db, user)
            drive_bundle.in_scope(db, token, data.parent_folder_id, writable=True)
    evidence_ids = [ref[0] for item in items if item.image_url and (ref := evidence.reference(item.image_url))]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise HTTPException(422, 'Mỗi phiếu trong lô cần file hoặc thư mục bằng chứng Drive riêng; không dùng trùng liên kết.')
    # Lock every receipt in a stable order before taking the shared daily sequence
    # lock. A concurrent create rechecks eligibility after the receipt lock.
    resolved = {}
    for data in sorted(items, key=lambda item: (item.object_type, item.object_id.casefold())):
        resolved[(data.object_type, data.object_id)] = resolve_object(db, data)
    # Same sequence and locking pattern as orders; seed from imported QC codes.
    day = datetime.now(TIMEZONE).strftime('%y%m%d')
    prefix = 'QC_' + day + '_'
    db.execute(insert(Sequence).values(name='QC_' + day, value=0).on_duplicate_key_update(name='QC_' + day))
    sequence = db.scalar(select(Sequence).where(Sequence.name == 'QC_' + day).with_for_update())
    existing = db.scalars(select(QualityCheck.id).where(QualityCheck.id.startswith(prefix, autoescape=True))).all()
    highest = max([int(code[len(prefix):]) for code in existing if code[len(prefix):].isdigit()] + [sequence.value])
    if highest + len(items) > 99:
        raise HTTPException(422, 'Không còn đủ mã QC trong giới hạn 99 phiếu/ngày. Chưa tạo phiếu nào trong lô này.')
    results = []
    for offset, data in enumerate(items, 1):
        identifier, lsx = resolved[(data.object_type, data.object_id)]
        obj = QualityCheck(id=prefix + str(highest+offset).zfill(2), staff_id=user.id, ncr_id='', source={})
        apply_values(db, obj, data, identifier, lsx, user)
        if data.form:
            drive_bundle.schedule(obj, user, data.parent_folder_id)
        elif not data.mapped_form:
            evidence.schedule(obj, user)
        db.add(obj)
        db.flush()
        results.append({**record(obj), 'staff_name':user.name, 'evidence':obj.image_url,
                        'evidence_pending':bool((obj.source or {}).get(evidence.TASK) or (obj.source or {}).get(drive_bundle.JOB)), 'evidence_error':''})
        db.add(Audit(user_id=user.id, action='QC_CREATE', entity_id=obj.id,
                     details={'object_type':obj.object_type, 'object_id':obj.object_id}))
    sequence.value = highest + len(items)
    result = {'items':results} if batch else results[0]
    request.result = result
    db.commit()
    return finish_evidence(db, user, result, batch)


def update(db, user, identifier, data):
    obj = db.scalar(select(QualityCheck).where(QualityCheck.id == identifier).with_for_update())
    if obj is None:
        raise HTTPException(404, 'Không tìm thấy phiếu QC.')
    if obj.template_id or data.mapped_form:
        raise HTTPException(409, 'Hồ sơ template đã lưu được giữ nguyên bản chụp. Bước 2 chỉ hỗ trợ tạo và xem lại, không chuyển đổi hoặc ghi đè hồ sơ cũ.')
    if not data.version or data.version != record(obj)['version']:
        raise HTTPException(409, 'Phiếu đã thay đổi. Hãy mở lại trước khi sửa.')
    object_id, lsx = resolve_object(db, data, existing=obj)
    if data.form and not obj.drive_folder_id:
        if not data.parent_folder_id:
            raise HTTPException(422, 'Hãy chọn thư mục cha cho hồ sơ QC.')
        drive_bundle.in_scope(db, drive_bundle.access_token(db, user), data.parent_folder_id, writable=True)
    apply_values(db, obj, data, object_id, lsx, user)
    if data.form:
        drive_bundle.schedule(obj, user, data.parent_folder_id)
    else:
        evidence.schedule(obj, user)
    db.flush()
    db.add(Audit(user_id=user.id, action='QC_EDIT', entity_id=obj.id, details={'object_type':obj.object_type, 'object_id':obj.object_id}))
    db.commit()
    if data.form:
        drive_bundle.prepare(db, user, identifier)
    elif (obj.source or {}).get(evidence.TASK):
        evidence.process(db, user, identifier)
    return detail_record(db, db.get(QualityCheck, identifier))
