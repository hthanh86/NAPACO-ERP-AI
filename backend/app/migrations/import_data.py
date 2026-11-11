"""Validated, atomic, one-time import. Never connects to or modifies Google Sheets."""
import argparse
import hashlib
import json
import re
from datetime import datetime, date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import select, func
from app.core.database import Session
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.auth.models import User, RolePermission
from app.modules.orders.models import Order, OrderLine
from app.migrations.models import SourceRow, ImportRun
from app.core.models import Sequence

from app.core.paths import PROJECT_ROOT as ROOT


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def number(value, default='0'):
    if value is None or text(value) == '':
        return Decimal(default)
    try:
        n = Decimal(text(value))
        if not n.is_finite() or abs(n) >= Decimal('1e16') or n != n.quantize(Decimal('.0001')):
            raise ValueError('Số vượt độ chính xác DECIMAL(20,4): ' + text(value))
        return n
    except InvalidOperation:
        raise ValueError('Giá trị số không hợp lệ: ' + text(value))


def day(value):
    if value is None or text(value) == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return from_excel(value).date()
    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d %H:%M:%S']:
        try:
            return datetime.strptime(text(value), fmt).date()
        except ValueError:
            pass
    raise ValueError('Ngày không hợp lệ: ' + text(value))


def json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime, time)) else value


def load():
    return {group: load_workbook(ROOT / 'data' / ('source-' + group + '.xlsx'), data_only=True)
            for group in ['master', 'operation']}


def table(workbook, name, columns, required, aliases=None):
    if name not in workbook.sheetnames:
        raise ValueError('Thiếu sheet ' + name)
    rows = list(workbook[name].values)
    aliases = aliases or {}
    def find(headers, key):
        options = [columns[key]] + aliases.get(key, [])
        matches = [i for i, h in enumerate(headers) if h in {x.casefold() for x in options}]
        if len(matches) > 1:
            raise ValueError(name + ': tiêu đề trùng cho ' + key)
        return matches[0] if matches else None
    header = next((i for i, row in enumerate(rows[:10])
                   if any(text(v).casefold() in {columns['ID'].casefold(), *[x.casefold() for x in aliases.get('ID', [])]}
                          for v in row)), None)
    if header is None:
        raise ValueError(name + ': không tìm thấy tiêu đề mã')
    heads = [text(x).casefold() for x in rows[header]]
    positions = {key: find(heads, key) for key in columns}
    missing = [columns[k] for k in required if positions[k] is None]
    if missing:
        raise ValueError(name + ': thiếu cột ' + ', '.join(missing))
    result, seen = [], set()
    for row_number, row in enumerate(rows[header + 1:], start=header + 2):
        if not any(text(x) for x in row):
            continue
        item = {k: row[i] if i is not None and i < len(row) else None for k, i in positions.items()}
        identifier = text(item['ID'])
        if not identifier:
            continue  # e.g. additional unit lists beside products; raw rows are archived separately.
        if identifier.casefold() in seen:
            raise ValueError(f'{name}: mã trùng {identifier} ở dòng {row_number}')
        seen.add(identifier.casefold())
        item['_source'] = {str(i + 1): json_value(v) for i, v in enumerate(row) if v is not None}
        item['_row'] = row_number
        result.append(item)
    return result


def migrate(apply=False):
    from app.core.config import LEGACY_CONFIG as config
    books = load()
    cols, names = config['COLUMNS'], config['SHEET_NAMES']
    records = {}
    for key, group, required in [
        ('CUSTOMERS', 'master', ['ID', 'NAME']), ('PRODUCTS', 'master', ['ID', 'NAME', 'CUSTOMER_ID']),
        ('EMPLOYEES', 'master', ['ID', 'NAME', 'EMAIL', 'ACCESS', 'STATUS']),
        ('ORDERS', 'operation', ['ID', 'CUSTOMER_ID', 'ORDER_DATE', 'PO_NUMBER']),
        ('ORDER_DETAILS', 'operation', ['ID', 'ORDER_ID', 'PRODUCT_ID', 'QTY_ORDER', 'PRICE'])]:
        records[key] = table(books[group], names[key], cols[key], required,
                             config.get('EMPLOYEE_HEADER_ALIASES') if key == 'EMPLOYEES' else None)
    models, warnings = {}, []
    models['customers'] = [Customer(id=text(x['ID']), name=text(x['NAME']), address=text(x['ADDRESS']),
                                  contact=text(x['CONTACTER']), phone=text(x['PHONE']), source=x['_source'])
                           for x in records['CUSTOMERS']]
    customer_ids = {x.id for x in models['customers']}
    models['users'] = []
    for x in records['EMPLOYEES']:
        role = text(x['ACCESS']).upper()
        if role == 'KINH DOANH': role = 'KINH_DOANH'
        models['users'].append(User(id=text(x['ID']), name=text(x['NAME']), email=text(x['EMAIL']).lower() or None,
                                     role=role, active=text(x['STATUS']).casefold() == 'đang hoạt động',
                                     source=x['_source']))
    user_ids = {x.id for x in models['users']}
    models['products'] = []
    for x in records['PRODUCTS']:
        cid = text(x['CUSTOMER_ID']) or None
        if cid and cid not in customer_ids:
            warnings.append('Sản phẩm ' + text(x['ID']) + ': chưa có khách hàng ' + cid + '. Giữ mã gốc, chưa liên kết danh mục.')
            cid = None
        elif not cid: warnings.append('Sản phẩm chưa có khách hàng: ' + text(x['ID']))
        models['products'].append(Product(id=text(x['ID']), customer_id=cid, source_customer_id=text(x['CUSTOMER_ID']), name=text(x['NAME']),
                                          code=text(x['CODE_CUST']), type=text(x['TYPE']),
                                          unit=text(x['UNIT']) or 'Cái', price=number(x['PRICE']), source=x['_source']))
    product_ids = {x.id for x in models['products']}
    models['orders'] = []
    for x in records['ORDERS']:
        if text(x['CUSTOMER_ID']) not in customer_ids:
            raise ValueError('Đơn tham chiếu khách hàng không tồn tại: ' + text(x['ID']))
        models['orders'].append(Order(id=text(x['ID']), customer_id=text(x['CUSTOMER_ID']),
                                     order_date=day(x['ORDER_DATE']), delivery_date=day(x['DELIVERY_DATE']),
                                     po_number=text(x['PO_NUMBER']), file_url=text(x['FILE_URL']), source=x['_source']))
    order_ids = {x.id for x in models['orders']}
    product_map = {x.id: x for x in models['products']}
    order_map = {x.id: x for x in models['orders']}
    models['order_lines'] = []
    total_qty = total_delivered = total_value = Decimal(0)
    for x in records['ORDER_DETAILS']:
        lid, oid, pid = text(x['ID']), text(x['ORDER_ID']), text(x['PRODUCT_ID'])
        if oid not in order_ids:
            raise ValueError('Chi tiết ' + lid + ' thiếu liên kết đơn.')
        if pid not in product_ids:
            warnings.append('Chi tiết ' + lid + ': chưa có sản phẩm ' + pid + '. Giữ mã gốc, chỉ xem cho tới khi bổ sung danh mục.')
        elif product_map[pid].customer_id != order_map[oid].customer_id:
            warnings.append('Khách hàng sản phẩm khác khách hàng đơn: ' + lid)
        uid = text(x['STAFF_ID']) or None
        if uid and uid not in user_ids:
            raise ValueError('Chi tiết ' + lid + ' tham chiếu nhân viên không tồn tại: ' + uid)
        qty, price, delivered = number(x['QTY_ORDER']), number(x['PRICE']), number(x['QTY_DELIVERED'])
        remaining = number(x['QTY_REMAINING']) if x['QTY_REMAINING'] is not None else None
        if remaining is not None and remaining != qty - delivered:
            warnings.append('SL_Con_Lai khác SL đặt - SL giao: ' + lid)
        total_qty += qty; total_delivered += delivered; total_value += qty * price
        models['order_lines'].append(OrderLine(id=lid, order_id=oid, product_id=pid if pid in product_ids else None,
                 source_product_id=pid, quantity=qty, price=price,
                 produced=number(x['QTY_RUN']), delivered=delivered, remaining_source=remaining,
                 note=text(x['NOTE']), delivery_date=day(x['DELIVERY_DATE']), staff_id=uid,
                 status=text(x['STATUS']) or 'Chờ sản xuất', unit=text(x['UNIT']) or (product_map[pid].unit if pid in product_ids else ''),
                 zone=text(x['KANBAN_ZONE']) or 'CHO_SAN_XUAT', priority=int(number(x['PRIORITY_ORDER'])),
                 film_line_id=text(x['FILM_LINE_ID']), source=x['_source']))
    permission_rows = list(books['master'][names['PERMISSIONS']].values)
    headers = [text(v) for v in permission_rows[0]]
    if not headers or headers[0] != 'Ma_Chuc_Nang' or len(headers) != len(set(headers)):
        raise ValueError('Ma trận quyền sai tiêu đề hoặc trùng cột.')
    models['role_permissions'] = []
    seen = set()
    for row in permission_rows[1:]:
        code = text(row[0])
        if not code: continue
        if code in seen: raise ValueError('Mã quyền bị trùng: ' + code)
        seen.add(code)
        for i, role in enumerate(headers[1:], 1):
            if role:
                models['role_permissions'].append(RolePermission(role=role.upper(), permission=code,
                                                   allowed=i < len(row) and text(row[i]) == '1'))
    checksum = hashlib.sha256(b''.join((ROOT/'data'/('source-'+g+'.xlsx')).read_bytes()
                                      for g in ['master', 'operation'])).hexdigest()
    report = {'checksum': checksum, 'counts': {k: len(v) for k, v in models.items()},
              'total_quantity': str(total_qty), 'total_delivered': str(total_delivered),
              'total_order_value': str(total_value), 'warnings': warnings,
              'source_unchanged': True, 'applied': False}
    report['quality'] = {
        'products_without_customer_link': sum(x.customer_id is None for x in models['products']),
        'lines_without_product_link': sum(x.product_id is None for x in models['order_lines']),
        'orders_readonly_missing_product': sorted({x.order_id for x in models['order_lines'] if x.product_id is None}),
        'missing_product_codes': sorted({x.source_product_id for x in models['order_lines'] if x.product_id is None})}
    if apply:
        with Session.begin() as db:
            if db.get(ImportRun, checksum):
                print('Snapshot đã nhập trước đó; không thêm dữ liệu trùng.')
                return
            if db.scalar(select(func.count()).select_from(Order)) or db.scalar(select(func.count()).select_from(Customer)):
                raise ValueError('Database đã có dữ liệu nghiệp vụ. Không nhập đè; cần quy trình đồng bộ riêng.')
            for group in ['customers', 'users', 'products', 'orders', 'order_lines', 'role_permissions']:
                db.add_all(models[group]); db.flush()
            for group, book in books.items():
                for sheet in book:
                    for row_number, row in enumerate(sheet.values, 1):
                        if any(v is not None for v in row):
                            db.add(SourceRow(book=group, sheet=sheet.title, row_number=row_number,
                                             cells=[json_value(v) for v in row]))
            sequences = {}
            for entity in models['orders'] + models['order_lines']:
                m = re.fullmatch(r'((?:DH|CT)_\d{6})_(\d+)', entity.id)
                if m: sequences[m[1]] = max(sequences.get(m[1], 0), int(m[2]))
            db.add_all([Sequence(name=k, value=v) for k, v in sequences.items()])
            db.flush()
            for key, model in [('customers', Customer), ('products', Product), ('orders', Order), ('order_lines', OrderLine)]:
                if db.scalar(select(func.count()).select_from(model)) != len(models[key]):
                    raise ValueError('Đối chiếu số dòng thất bại: ' + key)
            actual_qty, actual_delivered, actual_value = db.execute(select(func.sum(OrderLine.quantity),
                func.sum(OrderLine.delivered), func.sum(OrderLine.quantity * OrderLine.price))).one()
            if (actual_qty or 0, actual_delivered or 0, actual_value or 0) != (total_qty, total_delivered, total_value):
                raise ValueError('Đối chiếu tổng số lượng/giá trị thất bại.')
            report['applied'] = True
            report['reconciliation'] = 'PASS'
            db.add(ImportRun(checksum=checksum, report=report))
    target = ROOT / 'reports' / ('import-result.json' if apply else 'import-preview.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({**report, 'warnings': warnings[:8], 'warning_count': len(warnings)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    migrate(parser.parse_args().apply)
