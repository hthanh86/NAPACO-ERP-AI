"""Conservative first-tab suggestions and validated, immutable mapping definitions."""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

SOURCES = {
    'qc_id':'Mã phiếu QC', 'object_id':'Mã đối tượng / phiếu nhập NVL', 'check_type':'Loại kiểm tra',
    'object_type':'Công đoạn / đối tượng', 'checked_at':'Ngày kiểm tra', 'quantity':'Số lượng kiểm tra',
    'staff_name':'Người kiểm tra', 'production_order_id':'Lệnh sản xuất', 'product_ids':'Mã sản phẩm liên quan',
    'product_names':'Tên sản phẩm liên quan', 'receipt_date':'Ngày nhận NVL', 'production_date':'Ngày sản xuất NVL',
    'po_id':'Đơn đặt nguyên liệu', 'po_line_id':'Chi tiết đơn đặt NVL', 'po_date':'Ngày đặt NVL',
    'po_staff_name':'Người đặt NVL', 'supplier_name':'Nhà cung cấp', 'material_id':'Mã nguyên vật liệu',
    'resin':'Loại nhựa (PO)', 'grade':'Phẩm cấp (danh mục NVL)', 'color':'Màu (danh mục NVL)',
    'esd':'ESD (danh mục NVL)', 'thickness':'Độ dày đặt (danh mục NVL gắn PO)',
    'width':'Khổ rộng đặt (danh mục NVL gắn PO)', 'po_quantity':'Số lượng đặt NVL',
    'received_quantity':'Số lượng nhận NVL',
    'qc_note':'Ghi chú phiếu QC','conclusion':'Kết luận QC','signer_name':'Người ký xác nhận','signed_at':'Thời điểm ký UTC',
}
NVL_SOURCES = set(SOURCES) - {'qc_id','object_id','check_type','object_type','checked_at','quantity',
                             'staff_name','production_order_id','product_ids','product_names','qc_note','conclusion','signer_name','signed_at'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def snapshot(data):
    # Dynamic formula results are retained for display but formulas define source identity.
    return {key:deepcopy(data.get(key)) for key in ('spreadsheet_id','sheet_id','sheet_title','title',
            'grid','merges','theme','row_count','column_count','truncated')}


def source_hash(data):
    stable = snapshot(data)
    for row in (stable.get('grid') or {}).get('rowData', []):
        for cell in row.get('values', []):
            if cell.get('userEnteredValue', {}).get('formulaValue'):
                cell.pop('formattedValue', None)
    return digest(stable)


def address(row, col):
    n, letters = col + 1, ''
    while n:
        n, digit = divmod(n - 1, 26)
        letters = chr(65 + digit) + letters
    return letters + str(row + 1)


def position(cell):
    match = re.fullmatch(r'([A-Z]{1,2})([1-9][0-9]{0,2})', cell)
    if not match:
        raise HTTPException(422, 'Địa chỉ ô không hợp lệ: ' + cell)
    col = 0
    for char in match[1]:
        col = col * 26 + ord(char) - 64
    return int(match[2]) - 1, col - 1


def anchor(data, cell):
    row, col = position(cell)
    if row >= data['row_count'] or col >= data['column_count']:
        raise HTTPException(422, 'Ô nằm ngoài vùng template được đọc: ' + cell)
    for merge in data.get('merges', []):
        if ((merge.get('startRowIndex', 0) <= row < merge['endRowIndex']) and
                (merge.get('startColumnIndex', 0) <= col < merge['endColumnIndex'])):
            return address(merge.get('startRowIndex', 0), merge.get('startColumnIndex', 0))
    return cell


def cells(data):
    grid = data.get('grid') or {}
    return {address(r + grid.get('startRow', 0), c + grid.get('startColumn', 0)):value
            for r, row in enumerate(grid.get('rowData', [])) for c, value in enumerate(row.get('values', []))}


def text(data, cell):
    return str(cells(data).get(anchor(data, cell), {}).get('formattedValue', '')).strip()


def region(data, start, end=None):
    r0,c0 = position(anchor(data, start))
    r1,c1 = position(end or start)
    anchor(data, end or start)
    for merge in data.get('merges', []):
        if merge.get('startRowIndex',0) <= r1 < merge['endRowIndex'] and merge.get('startColumnIndex',0) <= c1 < merge['endColumnIndex']:
            r1,c1 = merge['endRowIndex']-1,merge['endColumnIndex']-1
    if r1 < r0 or c1 < c0:
        raise HTTPException(422, 'Ô cuối vùng chữ ký phải ở bên phải/phía dưới ô đầu.')
    return r0,c0,r1+1,c1+1


class MappingField(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
    name: str = Field(min_length=1, max_length=300)
    kind: Literal['ERP', 'STANDARD', 'INPUT']
    cell: str = Field(max_length=5)
    source: str | None = Field(default=None, max_length=50)
    data_type: Literal['text','number','date','boolean'] = 'text'
    unit: str = Field(default='', max_length=50)
    required: bool = True
    allow_na: bool = False
    standard_cell: str | None = Field(default=None, max_length=5)
    assessment_cell: str | None = Field(default=None, max_length=5)
    reviewed: bool = False


class MappingInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fields: list[MappingField] = Field(min_length=1, max_length=200)
    signature_cell: str | None = Field(default=None, max_length=5)
    signature_end_cell: str | None = Field(default=None, max_length=5)


def validate(data, mapping, check_type, approve=False):
    if data.get('truncated'):
        raise HTTPException(422, 'Template vượt vùng 500 hàng × 60 cột. Thu gọn template trước khi lưu mapping.')
    if len(json.dumps(snapshot(data), ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise HTTPException(422, 'Bản chụp vượt 2 MiB. Thu gọn định dạng/nội dung để lưu hồ sơ và tạo lô QC an toàn.')
    occupied, identifiers, result = set(), set(), []
    for field in mapping.fields:
        item = field.model_dump()
        if field.id in identifiers:
            raise HTTPException(422, 'Mã trường mapping bị trùng: ' + field.id)
        identifiers.add(field.id)
        for key in ('cell','standard_cell','assessment_cell'):
            if item[key]:
                item[key] = anchor(data, item[key])
        if item['cell'] in occupied:
            raise HTTPException(422, 'Nhiều trường cùng ghi vào ô hoặc vùng gộp: ' + item['cell'])
        occupied.add(item['cell'])
        if field.kind == 'ERP':
            if field.source not in SOURCES or (check_type != 'QC NVL' and field.source in NVL_SOURCES):
                raise HTTPException(422, 'Nguồn MySQL không phù hợp: ' + str(field.source))
        elif field.source:
            raise HTTPException(422, 'Chỉ trường ERP mới được chọn nguồn MySQL.')
        if field.kind != 'INPUT' and (field.allow_na or field.assessment_cell or field.standard_cell):
            raise HTTPException(422, 'N/A, ô tiêu chuẩn và đánh giá chỉ dùng cho trường nhập kết quả.')
        if field.kind == 'INPUT':
            item['allow_na'] = True
            if item['assessment_cell']:
                if item['assessment_cell'] in occupied:
                    raise HTTPException(422, 'Ô đánh giá trùng vùng ghi kết quả: ' + item['assessment_cell'])
                occupied.add(item['assessment_cell'])
            if item['standard_cell']:
                if item['standard_cell'] in {item['cell'], item['assessment_cell']}:
                    raise HTTPException(422, 'Ô tiêu chuẩn phải khác ô kết quả/đánh giá.')
                item['standard'] = text(data, item['standard_cell'])
        if field.kind == 'STANDARD':
            item['value'] = text(data, item['cell'])
            if not item['value']:
                raise HTTPException(422, 'Ô tiêu chuẩn cố định đang trống: ' + item['cell'])
        if approve and not field.reviewed:
            raise HTTPException(422, 'Quản lý cần kiểm tra và xác nhận từng trường: ' + field.name)
        result.append(item)
    # A referenced standard must not be overwritten by any ERP/input target.
    mutable = {f['cell'] for f in result if f['kind'] != 'STANDARD'} | {
        f['assessment_cell'] for f in result if f['assessment_cell']}
    if any(f['standard_cell'] in mutable for f in result if f['standard_cell']):
        raise HTTPException(422, 'Ô tiêu chuẩn đang bị mapping kết quả hoặc ERP ghi đè.')
    if not any(field.kind == 'INPUT' for field in mapping.fields):
        raise HTTPException(422, 'Cần ít nhất một tiêu chí nhập kết quả.')
    validated = {'schema_version':1, 'fields':result}
    if mapping.signature_cell:
        cell = anchor(data, mapping.signature_cell)
        r0,c0,r1,c1 = region(data, cell, mapping.signature_end_cell)
        for target in occupied | {item['standard_cell'] for item in result if item['standard_cell']}:
            a,b,x,y = region(data,target)
            if a < r1 and x > r0 and b < c1 and y > c0:
                raise HTTPException(422, 'Vùng chữ ký trùng dữ liệu/tiêu chuẩn/đánh giá.')
        for merge in data.get('merges', []):
            a,b,x,y = merge.get('startRowIndex',0),merge.get('startColumnIndex',0),merge['endRowIndex'],merge['endColumnIndex']
            if a < r1 and x > r0 and b < c1 and y > c0 and not (a >= r0 and b >= c0 and x <= r1 and y <= c1):
                raise HTTPException(422, 'Vùng chữ ký cắt ngang ô gộp. Chọn đủ vùng ô gộp.')
        validated['signature_cell'] = cell
        if mapping.signature_end_cell:
            validated['signature_end_cell'] = address(r1-1,c1-1)
    elif mapping.signature_end_cell:
        raise HTTPException(422, 'Cần ô đầu vùng chữ ký.')
    return validated


def normalize(value):
    return re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in unicodedata.normalize('NFD', value.lower().replace('đ','d'))
                  if unicodedata.category(c) != 'Mn')).strip()


def suggest(data):
    values = cells(data)
    proposals, warnings, used = [], [], set()
    labels = {'ma qc':'qc_id','qc id':'qc_id','ngay san xuat':'production_date','ngay nhan':'receipt_date',
        'nha cung cap':'supplier_name','don dat':'po_id','nguoi dat':'po_staff_name','ma nvl':'material_id',
        'loai nhua':'resin','ngay kiem tra':'checked_at','so luong kiem tra':'quantity','nguoi kiem tra':'staff_name',
        'ma phieu qc':'qc_id','kho rong dat':'width','do day dat':'thickness',
        'ghi chu bo sung':'qc_note','ghi chu':'qc_note','ket luan cua bo phan iqc':'conclusion',
        'ket luan':'conclusion','nguoi ky':'signer_name','thoi diem ky':'signed_at'}
    def add(kind, cell, name, **kwargs):
        cell = anchor(data, cell)
        if cell in used:
            return
        used.add(cell)
        proposals.append(MappingField(id='field_' + str(len(proposals)+1), name=name, kind=kind, cell=cell, **kwargs).model_dump())
    for cell, value in values.items():
        label = normalize(str(value.get('formattedValue', '')))
        if label not in labels:
            continue
        row, col = position(cell)
        # Find the cell immediately after the full merged label, never inside it.
        for merge in data.get('merges', []):
            if anchor(data, cell) == address(merge.get('startRowIndex',0), merge.get('startColumnIndex',0)):
                col = merge['endColumnIndex'] - 1
                break
        if col + 1 < data['column_count']:
            target = address(row, col + 1)
            if not text(data, target):
                add('ERP', target, SOURCES[labels[label]], source=labels[label])
            else:
                warnings.append('Nhãn ' + cell + ': ô kế bên có nội dung; cần chọn thủ công.')
    header = None
    for row in range(data['row_count']):
        headings = {normalize(str(values.get(address(row,col),{}).get('formattedValue',''))):col for col in range(data['column_count'])}
        criterion = next((col for name,col in headings.items() if name in {'hang muc kiem tra','tieu chi kiem tra','hang muc','chi tieu'}),None)
        actual = next((col for name,col in headings.items() if name in {'ket qua thuc te','ket qua do','ket qua'}),None)
        if criterion is not None and actual is not None:
            header = (row, criterion, actual,
                next((col for name,col in headings.items() if 'tieu chuan' in name),None),
                next((col for name,col in headings.items() if name in {'danh gia','dat khong dat'}),None))
            break
    if header:
        start, name_col, actual_col, standard_col, assessment_col = header
        for row in range(start+1,data['row_count']):
            name = text(data,address(row,name_col))
            # Numbered criteria are high signal; stop at a merged section/conclusion heading.
            if not name or any(anchor(data,address(row,col)) == anchor(data,address(row,name_col)) for col in [actual_col]):
                break
            if not re.match(r'^\d+[.)\s]',name):
                warnings.append('Dòng ' + str(row+1) + ': nhãn tiêu chí chưa rõ; không tự gán.')
                break
            raw = text(data,address(row,actual_col))
            unit = raw if raw in {'mm','cm','m','kg','g','Ω','Ω/sq','%'} else ''
            add('INPUT', address(row,actual_col), name, unit=unit, allow_na=True,
                standard_cell=address(row,standard_col) if standard_col is not None else None,
                assessment_cell=address(row,assessment_col) if assessment_col is not None else None)
            if standard_col is not None and text(data,address(row,standard_col)):
                add('STANDARD',address(row,standard_col),'Tiêu chuẩn · ' + name)
            if raw and not unit:
                warnings.append(address(row,actual_col) + ' có nội dung mẫu; kết quả QC mới vẫn để trống.')
    else:
        warnings.append('Không nhận diện chắc chắn bảng tiêu chí. Hãy chọn ô và thêm trường thủ công.')
    return {'fields':proposals, 'warnings':warnings + ['Đề xuất chưa được ban hành. Kiểm tra rồi Lưu để phê duyệt và kích hoạt; không suy đoán dung sai hoặc PASS/FAIL.']}
