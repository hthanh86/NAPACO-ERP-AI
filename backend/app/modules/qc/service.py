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
          'standard_url', 'quantity', 'result', 'staff_id', 'ncr_id', 'note', 'image_url']


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
    result['evidence'] = obj.image_url
    return result


def apply_values(obj, data, identifier, lsx):
    values = data.model_dump(exclude={'version'})
    stamp = values['checked_at']
    values['checked_at'] = stamp.astimezone(TIMEZONE).replace(tzinfo=None) if stamp.tzinfo else stamp
    values['checked_at'] = values['checked_at'].replace(microsecond=0)
    values['object_id'] = identifier
    values['production_order_id'] = lsx
    for key, value in values.items():
        setattr(obj, key, value)


def create(db, user, data, request_id):
    return create_records(db, user, [data], request_id, batch=False)


def create_records(db, user, items, request_id, batch=True):
    contents = [item.model_dump(mode='json', exclude={'version'}) for item in items]
    raw = json.dumps(contents, sort_keys=True) if batch else items[0].model_dump_json(exclude={'version'})
    digest = hashlib.sha256(raw.encode()).hexdigest()
    key = ('qcb:' if batch else 'qc:') + request_id
    # Reserve the shared request row atomically; concurrent retries wait for commit.
    db.execute(insert(LegacyRequest).values(id=key, user_id=user.id, payload_hash=digest, result={})
               .on_duplicate_key_update(id=key))
    request = db.scalar(select(LegacyRequest).where(LegacyRequest.id == key).with_for_update())
    if request.user_id != user.id or request.payload_hash != digest:
        raise HTTPException(409, 'Mã yêu cầu đã được sử dụng cho nội dung khác.')
    if request.result:
        return request.result
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
        apply_values(obj, data, identifier, lsx)
        db.add(obj)
        db.flush()
        results.append({**record(obj), 'staff_name':user.name, 'evidence':obj.image_url})
        db.add(Audit(user_id=user.id, action='QC_CREATE', entity_id=obj.id,
                     details={'object_type':obj.object_type, 'object_id':obj.object_id}))
    sequence.value = highest + len(items)
    result = {'items':results} if batch else results[0]
    request.result = result
    db.commit()
    return result


def update(db, user, identifier, data):
    obj = db.scalar(select(QualityCheck).where(QualityCheck.id == identifier).with_for_update())
    if obj is None:
        raise HTTPException(404, 'Không tìm thấy phiếu QC.')
    if not data.version or data.version != record(obj)['version']:
        raise HTTPException(409, 'Phiếu đã thay đổi. Hãy mở lại trước khi sửa.')
    object_id, lsx = resolve_object(db, data, existing=obj)
    apply_values(obj, data, object_id, lsx)
    db.flush()
    result = detail_record(db, obj)
    db.add(Audit(user_id=user.id, action='QC_EDIT', entity_id=obj.id, details={'object_type':obj.object_type, 'object_id':obj.object_id}))
    db.commit()
    return result
