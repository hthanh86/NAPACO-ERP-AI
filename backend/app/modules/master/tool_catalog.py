"""Shared MySQL tool catalog: immutable import plus explicitly created tools."""
import json
from sqlalchemy import select
from app.core.config import LEGACY_CONFIG
from app.core.models import Audit, Sequence
from sqlalchemy.dialects.mysql import insert
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.settings import SystemSetting
from app.migrations.models import SourceRow
from app.modules.products.models import Product
from fastapi import HTTPException

KEY = 'PRODUCTION_MOLD_CATALOG_V1'


def additions(db):
    setting = db.get(SystemSetting, KEY)
    if not setting:
        return []
    try:
        records = json.loads(setting.value)
        if not isinstance(records, list):
            raise ValueError()
        return records
    except (ValueError, TypeError):
        raise HTTPException(503, 'Danh mục khuôn bổ sung không hợp lệ; cần đối soát.')


def catalog(db):
    rows = list(db.scalars(select(SourceRow).where(
        SourceRow.book == 'master', SourceRow.sheet == LEGACY_CONFIG['SHEET_NAMES']['TOOLS']
    ).order_by(SourceRow.row_number)))
    result = []
    if rows:
        headers = rows[0].cells
        required = ['MaCC', *LEGACY_CONFIG['COLUMNS']['TOOLS'].values()]
        if not all(key in headers for key in required):
            raise HTTPException(503, 'Danh mục khuôn thiếu tiêu đề chuẩn.')
        result = [dict(zip(headers, row.cells)) for row in rows[1:] if row.cells and any(row.cells)]
    return result + additions(db)


def create_molds(db, user, entries):
    # The caller holds the existing ERP write lock and owns the transaction.
    existing = catalog(db)
    ids = {str(row.get('MaCC', '')).casefold() for row in existing}
    codes = {str(row.get('Ma_Khuon') or row.get('MaCC') or '').strip().casefold() for row in existing}
    stored = additions(db)
    mapping = {}
    for entry in entries:
        if entry.id.casefold() in ids or entry.name.strip().casefold() in codes:
            raise HTTPException(409, 'Mã khuôn đã tồn tại; tải lại khuôn của sản phẩm để chọn, không tạo trùng.')
        if not db.get(Product, entry.product_id):
            raise HTTPException(422, 'Sản phẩm của khuôn không tồn tại.')
        key='KH_'+datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%y%m%d')
        db.execute(insert(Sequence).values(name=key,value=0).on_duplicate_key_update(name=key))
        counter=db.scalar(select(Sequence).where(Sequence.name==key).with_for_update())
        while True:
            counter.value+=1
            identifier=f'{key}_{counter.value:02d}'
            if identifier.casefold() not in ids:break
        mapping[entry.id]=identifier
        record = {'MaCC': identifier, 'Ma_Khuon': entry.name.strip(),
                  'TenCC': entry.name.strip(),
                  'LoaiCC': LEGACY_CONFIG['MOLD_TYPES']['FORMING'], 'MaSP': entry.product_id,
                  'Dai_Khuon': entry.length_mm, 'Rong_Khuon': entry.width_mm,
                  'Cao_Khuon': entry.height_mm if entry.height_mm is not None else '', 'Cavity': entry.cavity,
                  'ViTriLuu': entry.location.strip(), 'Trang_Thai': 'Sẵn sàng', 'GhiChu': ''}
        stored.append(record)
        ids.add(identifier.casefold())
        codes.add(entry.name.strip().casefold())
        db.add(Audit(user_id=user.id, action='PRODUCTION_MOLD_CREATE', entity_id=identifier, details=record))
    if entries:
        setting = db.scalar(select(SystemSetting).where(SystemSetting.key == KEY).with_for_update())
        if not setting:
            setting = SystemSetting(key=KEY)
            db.add(setting)
        setting.value = json.dumps(stored, ensure_ascii=False)
        db.flush()
    return mapping


def append_to_projection(db, tables):
    """Expose the same additions to legacy consumers without writing the baseline."""
    records = additions(db)
    if not records:
        return
    name = LEGACY_CONFIG['SHEET_NAMES']['TOOLS']
    rows = tables.get(name) or [['MaCC', *LEGACY_CONFIG['COLUMNS']['TOOLS'].values()]]
    headers = list(rows[0])
    for record in records:
        for key in record:
            if key not in headers:
                headers.append(key)
    output = [headers, *[list(row) + [''] * (len(headers) - len(row)) for row in rows[1:]]]
    output.extend([[record.get(key, '') for key in headers] for record in records])
    tables[name] = output
