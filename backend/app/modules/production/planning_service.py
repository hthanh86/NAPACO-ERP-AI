"""Reusable stage-1 services. Callers own commit/rollback and authorization."""
import json
from decimal import Decimal
import subprocess
from pathlib import Path
from uuid import uuid4
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, func
from app.core.config import LEGACY_CONFIG
from app.core.models import Audit
from app.migrations.models import SourceRow
from app.modules.materials.models import FilmMaterial
from app.modules.products.models import Product
from app.modules.production.planning_models import Machine, ProductionStandard, ProductionStandardItem, MachineCalendarException

CALCULATION = Path(__file__).parents[1] / 'materials/purchasing/calculation.js'
ZONE = ZoneInfo('Asia/Ho_Chi_Minh')


def fail(message, status=422):
    raise HTTPException(status,message)


def tools_catalog(db):
    """Reuse the same MySQL source catalog and configured headers as film purchasing."""
    rows = db.scalars(select(SourceRow).where(SourceRow.book=='master',
        SourceRow.sheet==LEGACY_CONFIG['SHEET_NAMES']['TOOLS']).order_by(SourceRow.row_number)).all()
    if not rows:
        return []
    headers = rows[0].cells
    required = ['MaCC', *LEGACY_CONFIG['COLUMNS']['TOOLS'].values()]
    if not all(key in headers for key in required):
        fail('Danh mục khuôn thiếu tiêu đề chuẩn.',503)
    return [dict(zip(headers,r.cells)) for r in rows[1:] if r.cells and any(r.cells)]


def calculate_sheet_weight(pull_mm, width_mm, thickness_mm, density):
    # Execute the exact shared function used by purchasing; never maintain a second formula.
    script = "const f=require(process.argv[1]); process.stdout.write(JSON.stringify(f(...JSON.parse(process.argv[2]))));"
    try:
        result = subprocess.run(['node','-e',script,str(CALCULATION),json.dumps(
            [pull_mm,float(width_mm),1,1,float(thickness_mm),density,0])],
            capture_output=True,text=True,timeout=5,check=True)
        value = json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,ValueError,TypeError):
        fail('Không tính được trọng lượng bìa từ công thức đặt nhựa.',503)
    if not value:
        fail('Khổ/độ dày/tỷ trọng vật liệu không hợp lệ.')
    return value['weight']


def machine_record(machine):
    return {c.name:float(value) if isinstance(value,Decimal) else value
            for c in Machine.__table__.columns for value in [getattr(machine,c.name)]}


def machine_lock(db,identifier,version):
    machine = db.scalar(select(Machine).where(Machine.id==identifier).with_for_update())
    if not machine:
        fail('Không tìm thấy máy.',404)
    if machine.version != version:
        fail('Máy/lịch máy đã thay đổi. Tải lại trước khi lưu.',409)
    return machine


def audit(db,user,action,identifier,details):
    db.add(Audit(user_id=user.id,action=action,entity_id=identifier,details=details))


def save_machine(db,user,data,identifier=None):
    if identifier is None:
        if data.version is not None:
            fail('Máy mới không có phiên bản cũ.')
        if db.get(Machine,data.id):
            fail('Mã máy đã tồn tại.',409)
        machine = Machine(id=data.id,calendar={},version=1)
        db.add(machine)
    else:
        if data.id != identifier:
            fail('Không đổi mã máy.')
        machine = machine_lock(db,identifier,data.version)
        machine.version += 1
    for key,value in data.model_dump(exclude={'id','version'}).items():
        setattr(machine,key,value)
    db.flush()
    audit(db,user,'PRODUCTION_MACHINE_SAVE',machine.id,{'version':machine.version})
    return machine_record(machine)


def standard_record(db,standard):
    items = db.scalars(select(ProductionStandardItem).where(
        ProductionStandardItem.standard_id==standard.id).order_by(ProductionStandardItem.product_id)).all()
    return {c.name:getattr(standard,c.name) for c in ProductionStandard.__table__.columns} | {
        'items':[{'product_id':i.product_id,'cavity':i.cavity,'edge':i.edge,'snapshot':i.snapshot} for i in items]}


def save_standard(db,user,data,previous_id=None):
    revision = 1
    if previous_id:
        previous = db.scalar(select(ProductionStandard).where(ProductionStandard.id==previous_id).with_for_update())
        if not previous:
            fail('Không tìm thấy định mức.',404)
        if previous.code != data.code:
            fail('Phiên bản mới phải giữ mã định mức.')
        revision = previous.revision + 1
        if db.scalar(select(func.max(ProductionStandard.revision)).where(ProductionStandard.code==data.code)) != previous.revision:
            fail('Đã có phiên bản mới hơn. Tải lại trước khi sửa.',409)
    elif db.scalar(select(ProductionStandard.id).where(ProductionStandard.code==data.code).limit(1)):
        fail('Mã đã tồn tại; tạo phiên bản từ bản mới nhất.',409)
    machine = db.scalar(select(Machine).where(Machine.id==data.machine_id).with_for_update())
    if not machine or machine.kind not in {'automatic','semi_automatic'}:
        fail('Chọn máy định hình đã phân loại tự động/bán tự động.')
    if data.active and machine.status not in {'ready','running'}:
        fail('Máy không ở trạng thái sử dụng được; có thể lưu định mức ngừng dùng.')
    material = db.get(FilmMaterial,data.material_id)
    if not material or not material.width or not material.thickness:
        fail('Vật liệu phải tồn tại và có khổ/độ dày hợp lệ.')
    if machine.max_width_mm and material.width > machine.max_width_mm:
        fail('Khổ màng vượt khả năng máy.')
    if machine.max_pull_mm and data.pull_mm > machine.max_pull_mm:
        fail('Bước kéo vượt khả năng máy.')
    molds = [t for t in tools_catalog(db) if str(t.get('MaCC') or '')==data.mold_id]
    if len(molds)!=1 or molds[0].get('LoaiCC')!=LEGACY_CONFIG['MOLD_TYPES']['FORMING']:
        fail('Chọn mã công cụ MaCC của khuôn định hình hiện có.')
    mold = molds[0]
    try:
        mold_width = float(mold.get('Rong_Khuon') or 0)
        mold_length = float(mold.get('Dai_Khuon') or 0)
    except (ValueError,TypeError):
        fail('Kích thước khuôn nguồn không hợp lệ.')
    if mold_width > float(material.width) or mold_length > data.pull_mm:
        fail('Khổ màng hoặc bước kéo nhỏ hơn khuôn.')
    ids = [i.product_id for i in data.items]
    products = {p.id:p for p in db.scalars(select(Product).where(Product.id.in_(ids))).all()}
    if len(products)!=len(ids):
        fail('Có sản phẩm không tồn tại.')
    weight = calculate_sheet_weight(data.pull_mm,material.width,material.thickness,data.density)
    parameters = data.model_dump(exclude={'code','name','machine_id','material_id','mold_id','active','approved','items'})
    parameters['sheet_weight_kg'] = weight
    parameters['units'] = {'pull':'mm','width':'mm','thickness':'mm','density':'g/cm3',
        'speed':'seconds/cycle','weight':'kg/sheet','setup':'minutes','waste':'percent',
        'sheets_per_cycle':1,'product_per_sheet':'item.cavity'}
    standard = ProductionStandard(id=str(uuid4()),code=data.code,revision=revision,
        name=data.name,machine_id=data.machine_id,material_id=data.material_id,mold_id=data.mold_id,
        active=data.active,parameters=parameters,created_by=user.id,
        snapshot={'machine':machine_record(machine),'mold':mold,
                  'material':{c.name:str(getattr(material,c.name)) for c in FilmMaterial.__table__.columns if c.name!='source'},
                  'formula':'purchasing/calculation.js:v1',
                  'approval':{'approved':True,'by':user.id,'at':datetime.now(ZONE).isoformat()} if data.approved else None})
    db.add(standard)
    db.flush()
    for item in data.items:
        product = products[item.product_id]
        db.add(ProductionStandardItem(standard_id=standard.id,**item.model_dump(),snapshot={
            'name':product.name,'code':product.code,'unit':product.unit,
            'route':(['forming_cutting'] if machine.kind=='automatic' else ['forming','cutting']) + (['edge'] if item.edge else [])}))
    db.flush()
    audit(db,user,'PRODUCTION_STANDARD_REVISION',standard.id,{'code':data.code,'revision':revision})
    return standard_record(db,standard)


def route_for_standard(db,identifier):
    standard = db.get(ProductionStandard,identifier)
    if not standard:
        fail('Không tìm thấy định mức.',404)
    record = standard_record(db,standard)
    return {'standard_id':identifier,'revision':standard.revision,'units':standard.parameters['units'],
        'items':[{'product_id':i['product_id'],'cavity':i['cavity'],'stages':i['snapshot']['route'],
                  'product_unit':i['snapshot']['unit']} for i in record['items']]}


def save_calendars(db,user,data):
    # Lock in stable order; all machine calendars change in one transaction.
    machines = [machine_lock(db,key,data.versions[key]) for key in sorted(data.versions)]
    for machine in machines:
        if data.inherit_default:
            machine.calendar = {}
        if data.weekly is not None:
            machine.calendar = {'_explicit':True,**{key:value.model_dump() for key,value in data.weekly.items()}}
        for entry in data.exceptions:
            existing = db.get(MachineCalendarException,(machine.id,entry.day))
            if existing is None:
                existing = MachineCalendarException(machine_id=machine.id,day=entry.day)
                db.add(existing)
            existing.windows = [s.model_dump() for s in entry.windows]
            existing.note = entry.note
        if data.remove_exceptions:
            for entry in db.scalars(select(MachineCalendarException).where(
                    MachineCalendarException.machine_id==machine.id,
                    MachineCalendarException.day.in_(data.remove_exceptions))).all():
                db.delete(entry)
        machine.version += 1
        audit(db,user,'PRODUCTION_CALENDAR_SAVE',machine.id,{'version':machine.version})
    db.flush()
    return {'versions':{m.id:m.version for m in machines}}


def subtract_breaks(rule):
    windows = [(s['start'],s['end']) for s in rule.get('shifts',[])]
    for pause in rule.get('breaks',[]):
        updated = []
        for start,end in windows:
            if pause['end']<=start or pause['start']>=end:
                updated.append((start,end))
            else:
                if start<pause['start']: updated.append((start,pause['start']))
                if pause['end']<end: updated.append((pause['end'],end))
        windows = updated
    return windows


def available_windows(db,machine_ids,start_date,end_date):
    """Inclusive local dates; ISO intervals are [start,end), Asia/Ho_Chi_Minh."""
    if end_date<start_date or (end_date-start_date).days>92:
        fail('Khoảng ngày phải tăng, tối đa 93 ngày.')
    machine_ids = sorted(set(machine_ids))
    if not machine_ids or len(machine_ids)>100:
        fail('Chọn từ 1 đến 100 máy.')
    machines = db.scalars(select(Machine).where(Machine.id.in_(machine_ids)).order_by(Machine.id)).all()
    if len(machines)!=len(machine_ids):
        fail('Có mã máy không tồn tại.',404)
    exceptions = {(e.machine_id,e.day):e for e in db.scalars(select(MachineCalendarException).where(
        MachineCalendarException.machine_id.in_(machine_ids),MachineCalendarException.day.between(start_date,end_date))).all()}
    from app.modules.production.calendar_settings import read_default,effective_week
    default = read_default(db)
    result = []
    for machine in machines:
        weekly = effective_week(db,machine,default)
        windows = []
        day = start_date
        while day<=end_date:
            exception = exceptions.get((machine.id,day))
            spans = [(s['start'],s['end']) for s in exception.windows] if exception else subtract_breaks(weekly.get(str(day.weekday()),{}))
            if machine.status in {'ready','running'}:
                midnight = datetime.combine(day,time(),tzinfo=ZONE)
                windows.extend({'start':(midnight+timedelta(minutes=a)).isoformat(),
                                'end':(midnight+timedelta(minutes=b)).isoformat(),
                                'source':'exception' if exception else 'weekly'} for a,b in spans)
            day += timedelta(days=1)
        result.append({'machine_id':machine.id,'version':machine.version,'windows':windows})
    return {'timezone':'Asia/Ho_Chi_Minh','machines':result}
