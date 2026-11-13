"""Use approved MySQL snapshots without Google calls or Drive side effects."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, func
from app.auth.security import current_user, require
from app.auth.models import User
from app.core.database import get_db
from app.modules.qc import mapping
from app.modules.qc.template_models import QCTemplate
from app.modules.qc.schemas import CheckType, ObjectType
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.purchasing.models import FilmPO, FilmLine
from app.modules.materials.models import FilmMaterial, FilmSupplier
from app.modules.orders.models import OrderLine
from app.modules.products.models import Product
from app.modules.production.models import ProductionOrder

router = APIRouter()


def serialized(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    return value.isoformat() if hasattr(value, 'isoformat') else value if value is not None else ''


def context(db, kind, identifier, lsx=None):
    result = {'object_id':identifier, 'object_type':kind, 'production_order_id':lsx or ''}
    products = []
    if kind == 'NVL':
        supplier = func.coalesce(func.nullif(FilmPO.supplier_id, ''), FilmLine.supplier_id)
        columns = [FilmReceipt.receipt_date, FilmReceipt.production_date,
            FilmReceipt.quantity.label('received_quantity'), FilmLine.id.label('po_line_id'),
            FilmLine.po_id, FilmLine.material_id, FilmLine.resin, FilmLine.quantity.label('po_quantity'),
            FilmMaterial.width, FilmMaterial.thickness, FilmMaterial.grade, FilmMaterial.color, FilmMaterial.esd,
            FilmPO.order_date.label('po_date'), FilmPO.staff_id.label('po_staff_id'),
            func.coalesce(FilmSupplier.name, supplier).label('supplier_name')]
        row = db.execute(select(*columns).select_from(FilmReceipt)
            .outerjoin(FilmLine, FilmLine.id == FilmReceipt.line_id).outerjoin(FilmPO, FilmPO.id == FilmLine.po_id)
            .outerjoin(FilmMaterial, FilmMaterial.id == FilmLine.material_id)
            .outerjoin(FilmSupplier, FilmSupplier.id == supplier).where(FilmReceipt.id == identifier)).mappings().first()
        if row:
            result.update({key:serialized(value) for key,value in row.items()})
            staff = db.get(User, row['po_staff_id']) if row['po_staff_id'] else None
            if not staff and row['po_staff_id']:
                staff = db.scalar(select(User).where(User.email == row['po_staff_id']))
            result['po_staff_name'] = staff.name if staff else ''
            products = db.execute(select(Product.id, Product.name).join(OrderLine, OrderLine.product_id == Product.id)
                .where(OrderLine.film_line_id == row['po_line_id']).distinct().order_by(Product.id)).all()
    elif lsx:
        products = db.execute(select(Product.id, Product.name).join(ProductionOrder, ProductionOrder.product_id == Product.id)
                              .where(ProductionOrder.id == lsx)).all()
    result['product_ids'] = ', '.join(product.id for product in products)
    result['product_names'] = ', '.join(product.name for product in products)
    return result, {product.id for product in products}


def applicable(row, check_type, object_type, product_ids):
    return (row.check_type == check_type and row.object_type in {None, object_type} and
            (row.product_id is None or row.product_id in product_ids))


def released(db, identifier, check_type, object_type, product_ids, lock=False):
    statement = select(QCTemplate).where(QCTemplate.id == identifier).execution_options(populate_existing=True)
    row = db.scalar(statement.with_for_update() if lock else statement)
    if (not row or row.status != 'ACTIVE' or not row.approved_at or row.source_matches is not True or
            not applicable(row, check_type, object_type, product_ids)):
        raise HTTPException(422, 'Template chưa được duyệt/kích hoạt hoặc không phù hợp đối tượng kiểm tra.')
    if not row.field_mapping or not row.source_snapshot or mapping.source_hash(row.source_snapshot) != row.source_hash:
        raise HTTPException(409, 'Bản chụp template không toàn vẹn. Cần quản lý kiểm tra lại.')
    return row


def typed(value, kind, label):
    try:
        if kind == 'number':
            number = Decimal(value)
            if not number.is_finite() or len(value) > 100 or abs(number.as_tuple().exponent) > 100:
                raise ValueError()
            return format(number, 'f')
        if kind == 'date':
            return date.fromisoformat(value).isoformat()
        if kind == 'boolean' and value not in {'true','false'}:
            raise ValueError()
        return value
    except (ValueError, InvalidOperation, OverflowError):
        raise HTTPException(422, 'Sai kiểu dữ liệu ở tiêu chí: ' + label) from None


def filled(db, user, data, qc_id, lsx, existing=None):
    if existing:
        saved = existing.form_data
        if (data.mapped_form.template_id != existing.template_id or data.object_id != existing.object_id or
                data.object_type != existing.object_type or data.check_type != existing.check_type):
            raise HTTPException(422, 'Không chuyển đối tượng hoặc phiên bản template của phiếu đã lưu.')
        values, product_ids = deepcopy(saved['context']), set()
        definition = deepcopy(saved['template'])
        # An unsigned Step 2 record can receive the separately approved signature extension.
        if not definition['mapping'].get('signature_cell'):
            current = db.get(QCTemplate, existing.template_id)
            if (current and current.approved_at and current.source_hash == definition['source_hash'] and
                    current.field_mapping.get('fields') == definition['mapping'].get('fields')):
                definition['mapping'] = deepcopy(current.field_mapping)
                definition['mapping_hash'] = mapping.digest(current.field_mapping)
    else:
        values, product_ids = context(db, data.object_type, data.object_id, lsx)
        row = released(db, data.mapped_form.template_id, data.check_type, data.object_type, product_ids, lock=True)
        definition = {'id':row.id,'code':row.form_code,'version':row.version,'name':row.form_name,
            'spreadsheet_id':row.spreadsheet_id,'sheet_id':row.sheet_id,'source_hash':row.source_hash,
            'mapping_hash':mapping.digest(row.field_mapping),'approved_by':row.approved_by,
            'approved_at':row.approved_at.isoformat(),'mapping':deepcopy(row.field_mapping),'snapshot':deepcopy(row.source_snapshot)}
    entered = data.mapped_form
    if entered.source_hash != definition['source_hash'] or entered.mapping_hash != definition['mapping_hash']:
        raise HTTPException(409, 'Template/mapping đã khác bản đang nhập. Hãy chọn lại template.')
    if not entered._signer:
        raise HTTPException(403, 'Chưa có xác nhận chữ ký hợp lệ từ phiên Google hiện tại.')
    from app.modules.qc.signing import context_hash
    if entered._signer.get('context_hash')!=context_hash(values):
        raise HTTPException(409,'Thông tin NVL/PO đã thay đổi sau khi ký. Hãy tải lại và ký lại trước khi lưu.')
    if not definition['mapping'].get('signature_cell'):
        raise HTTPException(422, 'Quản lý cần xác định và phê duyệt vị trí chữ ký trên template trước khi lưu.')
    fields = definition['mapping']['fields']
    criteria = [field for field in fields if field['kind'] == 'INPUT']
    answers = {answer.id:answer for answer in entered.answers}
    if len(answers) != len(entered.answers) or set(answers) != {field['id'] for field in criteria}:
        raise HTTPException(422, 'Danh sách tiêu chí bị thiếu, thừa hoặc trùng mã.')
    normalized, evaluations = [], []
    for field in criteria:
        answer = answers[field['id']]
        actual = answer.actual
        if answer.assessment is None:
            if field['required'] or actual:
                raise HTTPException(422, 'Cần chọn đánh giá cho ' + field['name'])
        elif answer.assessment == 'NA':
            # Current QC policy permits skipping any criterion, including older mappings.
            actual = ''
        else:
            if field['required'] and not actual:
                raise HTTPException(422, 'Thiếu kết quả thực tế: ' + field['name'])
            if actual:
                actual = typed(actual, field['data_type'], field['name'])
        normalized.append({'id':answer.id, 'actual':actual, 'assessment':answer.assessment, 'note':answer.note})
        if answer.assessment:
            evaluations.append(answer.assessment)
    if not any(value in {'PASS','FAIL'} for value in evaluations):
        raise HTTPException(422, 'Cần ít nhất một tiêu chí Đạt hoặc Không đạt để kết luận; không thể để toàn bộ Không áp dụng.')
    conclusion = 'FAIL' if 'FAIL' in evaluations else 'PASS'
    if entered.conclusion != conclusion or data.result != {'PASS':'OK','FAIL':'NG'}[conclusion]:
        raise HTTPException(422, 'Kết luận phải khớp đánh giá các tiêu chí áp dụng.')
    values.update(qc_id=qc_id, check_type=data.check_type, checked_at=serialized(data.checked_at),
                  quantity=serialized(data.quantity), staff_name=user.name,qc_note=data.note,
                  conclusion='Đạt' if conclusion=='PASS' else 'Không đạt',signer_name=user.name,signed_at=entered._signer['signed_at'])
    auto = {field['id']:str(values.get(field['source'], '')) for field in fields if field['kind'] == 'ERP'}
    missing = [field['name'] for field in fields if field['kind'] == 'ERP' and field['required'] and not auto[field['id']]]
    if missing:
        raise HTTPException(422, 'MySQL chưa có dữ liệu bắt buộc: ' + ', '.join(missing))
    signer = {k:v for k,v in entered._signer.items() if k != 'session'}
    return {'kind':'google_template','template':definition,
        'input':{'answers':normalized,'conclusion':conclusion,'signature':entered.signature},
        'signer':signer,'auto_values':auto,'context':values}


def editor_user(user=Depends(current_user), db=Depends(get_db)):
    from app.modules.qc.api import allowed
    allowed(db, user, 'QC_CREATE','QC_EDIT')
    return user


def selection(db, check_type, object_type, object_id):
    from app.modules.qc.service import resolve_object
    from types import SimpleNamespace
    _, lsx = resolve_object(db, SimpleNamespace(check_type=check_type, object_type=object_type, object_id=object_id))
    values, product_ids = context(db, object_type, object_id, lsx)
    return values, product_ids


@router.get('/api/qc/template-options')
def options(check_type: CheckType, object_type: ObjectType, object_id: str,
            user=Depends(editor_user), db=Depends(get_db)):
    _, product_ids = selection(db, check_type, object_type, object_id)
    rows = db.scalars(select(QCTemplate).where(QCTemplate.status == 'ACTIVE',
        QCTemplate.approved_at.is_not(None), QCTemplate.source_matches.is_(True),
        QCTemplate.check_type == check_type, or_(QCTemplate.object_type.is_(None),QCTemplate.object_type == object_type),
        or_(QCTemplate.product_id.is_(None), QCTemplate.product_id.in_(product_ids)))
        .order_by(QCTemplate.version.desc(), QCTemplate.form_code).limit(100)).all()
    return {'items':[{'id':row.id,'code':row.form_code,'name':row.form_name,'version':row.version} for row in rows]}


@router.get('/api/qc/templates/{identifier}/entry')
def entry(identifier: str, check_type: CheckType, object_type: ObjectType, object_id: str,
          user=Depends(editor_user), db=Depends(get_db)):
    values, product_ids = selection(db, check_type, object_type, object_id)
    row = released(db, identifier, check_type, object_type, product_ids)
    return {'id':row.id,'code':row.form_code,'name':row.form_name,'version':row.version,
            'mapping':row.field_mapping,'snapshot':row.source_snapshot,'source_hash':row.source_hash,
            'mapping_hash':mapping.digest(row.field_mapping),'context':values}
