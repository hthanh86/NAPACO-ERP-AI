"""Additive, validated import of QC dependencies; never rewrites source_rows.

Dry run by default. Rows without an ID remain in the original workbook/baseline
and are explicitly reported rather than assigned invented business identifiers.
"""
import argparse
import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import Date, DateTime, Time, Numeric, String, select, func
from app.core.database import Session
from app.core.paths import DATA_ROOT
from app.migrations.models import ImportRun
from app.modules.production.models import (
    ProductionOrder, ProductionSetup, FormingLog, ProductionWIP, CuttingLog, EBLog,
)
from app.modules.qc.models import QualityCheck

SOURCES = [
    ('03.LenhSX', ProductionOrder), ('06.SETUP_MAU', ProductionSetup),
    ('05.NHAT_KY_HUT', FormingLog), ('SX-FM-01C_WIP', ProductionWIP),
    ('SX-FM-01D_CAT_LOG', CuttingLog), ('SX-FM-01E_EB_LOG', EBLog),
    ('QC-FM-01_KIEMTRA', QualityCheck),
]


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def scalar(value, column):
    if value is None or text(value) == '':
        return None
    kind = column.type
    if isinstance(kind, Numeric):
        try:
            number = Decimal(text(value).replace(',', '.'))
            if not number.is_finite() or abs(number) >= Decimal('1e16') or number != number.quantize(Decimal('.00000001')):
                raise ValueError('Số vượt độ chính xác DECIMAL(24,8)')
            return number
        except InvalidOperation:
            raise ValueError('Giá trị số không hợp lệ') from None
    if isinstance(kind, (Date, DateTime, Time)):
        parsed = value
        if isinstance(value, (int, float)):
            parsed = from_excel(value)
        if isinstance(parsed, str):
            parsed = None
            formats = ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S',
                       '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d', '%H:%M:%S', '%H:%M')
            for fmt in formats:
                try:
                    parsed = datetime.strptime(value.strip(), fmt)
                    break
                except ValueError:
                    continue
        if isinstance(kind, DateTime):
            if isinstance(parsed, datetime):
                return parsed
            if isinstance(parsed, date):
                return datetime.combine(parsed, time())
        elif isinstance(kind, Time):
            if isinstance(parsed, datetime):
                return parsed.time()
            if isinstance(parsed, time):
                return parsed
        elif isinstance(parsed, (date, datetime)):
            return parsed.date() if isinstance(parsed, datetime) else parsed
        raise ValueError('Ngày/giờ không hợp lệ')
    result = text(value)
    if isinstance(kind, String) and kind.length and len(result) > kind.length:
        raise ValueError('Vượt độ dài cột ' + str(kind.length))
    return result


def prepare(path):
    checksum = hashlib.sha256(b'napaco-qc-production-v004\0' + path.read_bytes()).hexdigest()
    book = load_workbook(path, read_only=True, data_only=True)
    prepared, skipped = {}, []
    try:
        for sheet_name, model in SOURCES:
            if sheet_name not in book.sheetnames:
                raise ValueError('Thiếu sheet ' + sheet_name)
            rows = iter(book[sheet_name].values)
            headers = [text(v) for v in next(rows)]
            if len(headers) != len(set(headers)):
                raise ValueError(sheet_name + ': tiêu đề trùng')
            # Correct the EB header in the new table, leaving the source immutable.
            if model is EBLog and 'EB_ID' not in headers and 'CUT_ID' in headers:
                headers[headers.index('CUT_ID')] = 'EB_ID'
            fields = {c.name: c for c in model.__table__.columns if c.key != 'source'}
            required = set(fields) - ({'OBJECT_TYPE'} if model is QualityCheck else set())
            if not required.issubset(headers) or set(headers) - set(fields):
                raise ValueError(sheet_name + ': tiêu đề khác schema đã xác minh')
            positions = {name: headers.index(name) for name in fields if name in headers}
            items, seen = [], set()
            id_name = model.__table__.c.id.name
            for row_number, row in enumerate(rows, 2):
                if not any(v is not None and text(v) for v in row):
                    continue
                if not text(row[positions[id_name]] if positions[id_name] < len(row) else None):
                    skipped.append({'sheet': sheet_name, 'row': row_number, 'reason': 'Thiếu ' + id_name})
                    continue
                values, source = {}, {}
                for name, position in positions.items():
                    raw = row[position] if position < len(row) else None
                    source[name] = raw.isoformat() if isinstance(raw, (date, datetime, time)) else raw
                    try:
                        values[fields[name].key] = scalar(raw, fields[name])
                    except ValueError as error:
                        raise ValueError(f'{sheet_name}, dòng {row_number}, cột {name}: {error}') from None
                identifier = values['id'].casefold()
                if identifier in seen:
                    raise ValueError(f'{sheet_name}: mã trùng ở dòng {row_number}')
                seen.add(identifier)
                values['source'] = source
                items.append(model(**values))
            prepared[model] = items
    finally:
        book.close()
    # Preserve historical values. Infer object type only if the source is unique.
    source_models = {'SETUP': ProductionSetup, 'HUT': FormingLog, 'CAT': CuttingLog, 'EB': EBLog}
    for qc in prepared[QualityCheck]:
        if not qc.object_type:
            if qc.check_type == 'QC NVL':
                qc.object_type = 'NVL'
            else:
                matches = [kind for kind, model in source_models.items()
                           if any(item.id == qc.object_id for item in prepared[model])]
                qc.object_type = matches[0] if len(matches) == 1 else None
    return checksum, prepared, skipped


def migrate(path, apply=False):
    checksum, prepared, skipped = prepare(path)
    report = {'checksum': checksum, 'counts': {m.__tablename__: len(rows) for m, rows in prepared.items()},
              'skipped_without_id': skipped, 'eb_header_alias': 'CUT_ID -> EB_ID; giữ nguyên giá trị mã',
              'source_unchanged': True, 'applied': False}
    with Session.begin() as db:
        if db.get(ImportRun, checksum):
            report['already_applied'] = True
            return report
        for model in prepared:
            if db.scalar(select(func.count()).select_from(model)):
                raise ValueError(model.__tablename__ + ': đã có dữ liệu; từ chối nhập đè')
        if apply:
            for rows in prepared.values():
                db.add_all(rows)
            db.flush()
            for model, rows in prepared.items():
                if db.scalar(select(func.count()).select_from(model)) != len(rows):
                    raise ValueError('Đối soát số dòng thất bại: ' + model.__tablename__)
            report['applied'] = True
            db.add(ImportRun(checksum=checksum, report=report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--source', type=Path, default=DATA_ROOT / 'source-operation.xlsx')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = migrate(args.source, args.apply)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(rendered + '\n')
    print(rendered)
