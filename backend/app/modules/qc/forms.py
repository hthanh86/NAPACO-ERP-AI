"""Immutable code-defined forms. Once used, create V2 rather than edit V1."""
from copy import deepcopy
from datetime import datetime, timezone
from fastapi import HTTPException

QC_NVL_V1 = {
    'code': 'QC_NVL_V1', 'version': 1, 'name': 'Kiểm tra chất lượng nguyên vật liệu',
    'resins': ['PET', 'PP', 'PS', 'PVC'],
    'applicability_note': 'Tiêu chuẩn được cung cấp chưa phân biệt theo loại nhựa. Không áp dụng phải ghi rõ lý do; người QC đối chiếu PO và tiêu chuẩn sản phẩm.',
    'criteria': [
        {'id':'width', 'name':'Khổ rộng màng (Width)', 'standard':'Theo đơn đặt hàng (PO)', 'method':'Thước cuộn chuẩn', 'unit':'mm', 'tolerance':'± 2.0 mm'},
        {'id':'thickness', 'name':'Độ dày màng (Thickness)', 'standard':'Theo tiêu chuẩn sản phẩm', 'method':'Panme đo độ dày điện tử', 'unit':'mm', 'tolerance':'± 0.02 mm'},
        {'id':'weight', 'name':'Trọng lượng cuộn (Weight)', 'standard':'Theo barem quy cách cuộn', 'method':'Cân điện tử công nghiệp', 'unit':'kg', 'tolerance':'Áp dụng/Không áp dụng'},
        {'id':'color', 'name':'Màu sắc & Độ trong', 'standard':'Đồng đều', 'method':'Quan sát', 'unit':'', 'tolerance':'Không loang ố'},
        {'id':'surface', 'name':'Bề mặt & Bụi bẩn', 'standard':'Sạch, nhẵn, không bavia', 'method':'Quan sát', 'unit':'', 'tolerance':'Đốm đen ≤ 0.3mm'},
        {'id':'packaging', 'name':'Bao bì & Đóng gói', 'standard':'Bọc kín màng PE, đủ nhãn', 'method':'Quan sát', 'unit':'', 'tolerance':'Bảo quản khô ráo'},
        {'id':'esd', 'name':'Điện trở bề mặt (ESD)', 'standard':'Conductive / Antistatic', 'method':'Máy đo ESD', 'unit':'Ω/sq', 'tolerance':'10^9 - 10^11 Ω/sq'},
    ],
}
QC_NVL_261101_V1 = deepcopy(QC_NVL_V1)
QC_NVL_261101_V1.update(code='QC_NVL_261101_V1', business='NVL', issued_on='2026-11-01',
    tolerance_as_hint=True,
    applicability_note='Đối chiếu PO và tiêu chuẩn sản phẩm. Chọn Không áp dụng cho tiêu chí không kiểm tra.')
# Retain retired definitions for historical records. Only RELEASED is offered for new forms.
REGISTRY = {item['code']:item for item in (QC_NVL_V1, QC_NVL_261101_V1)}
RELEASED = {'NVL':'QC_NVL_261101_V1', 'PRODUCT':None}


def business(check_type):
    return 'NVL' if check_type == 'QC NVL' else 'PRODUCT'


def current(check_type):
    code = RELEASED.get(business(check_type))
    return definition(code) if code else None


def document_id(qc_id):
    return 'PQC_' + qc_id[3:] if qc_id.startswith('QC_') else 'PQC_' + qc_id


def definition(code):
    if code not in REGISTRY:
        raise HTTPException(422, 'Biểu mẫu QC không tồn tại hoặc chưa được phát hành.')
    return deepcopy(REGISTRY[code])


def filled_form(data, user, context, saved_definition=None):
    snapshot = deepcopy(saved_definition) if saved_definition else definition(data.code)
    if snapshot['code'] != data.code:
        raise HTTPException(422, 'Mã template không khớp phiên bản đã lưu.')
    if data.resin not in snapshot['resins']:
        raise HTTPException(422, 'Loại nhựa chưa được biểu mẫu hỗ trợ.')
    answers = [answer.model_dump() for answer in data.answers]
    expected = {item['id'] for item in snapshot['criteria']}
    if len(answers) != len(expected) or {item['id'] for item in answers} != expected:
        raise HTTPException(422, 'Phải nhập đủ từng tiêu chí, không được thiếu hoặc trùng tiêu chí.')
    for answer in answers:
        if answer['assessment'] != 'NA' and not answer['actual'].strip():
            raise HTTPException(422, 'Tiêu chí áp dụng phải có kết quả thực tế.')
    applicable = [item for item in answers if item['assessment'] != 'NA']
    if not applicable:
        raise HTTPException(422, 'Cần ít nhất một tiêu chí áp dụng.')
    conclusion = 'FAIL' if any(item['assessment'] == 'FAIL' for item in applicable) else 'PASS'
    if conclusion != data.conclusion:
        raise HTTPException(422, 'Kết luận không khớp đánh giá các tiêu chí.')
    if not any(len(stroke) >= 2 and len(set(map(tuple, stroke))) >= 2 for stroke in data.signature):
        raise HTTPException(422, 'Cần ký xác nhận trước khi lưu biểu mẫu.')
    entered = data.model_dump(mode='json')
    for answer in entered['answers']:
        if answer['assessment'] == 'NA':
            answer['actual'] = ''
    return {'definition': snapshot, 'input': entered, 'context': context,
            'signer': {'user_id':user.id, 'name':user.name, 'signed_at':datetime.now(timezone.utc).isoformat(),
                       'method':'internal_drawn_signature'}}
