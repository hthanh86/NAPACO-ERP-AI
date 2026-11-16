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
from app.core.models import Audit,Sequence
from sqlalchemy.dialects.mysql import insert
from app.migrations.models import SourceRow
from app.modules.materials.models import FilmMaterial
from app.modules.products.models import Product
from app.modules.production.planning_models import Machine, ProductionStandard, ProductionStandardItem, MachineCalendarException

CALCULATION = Path(__file__).parents[1] / 'materials/purchasing/calculation.js'
ZONE = ZoneInfo('Asia/Ho_Chi_Minh')


def fail(message, status=422):
    raise HTTPException(status,message)


def tools_catalog(db):
    from app.modules.master.tool_catalog import catalog
    return catalog(db)


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


def next_standard_id(db):
    key='DM_'+datetime.now(ZONE).strftime('%y%m%d')
    db.execute(insert(Sequence).values(name=key,value=0).on_duplicate_key_update(name=key))
    counter=db.scalar(select(Sequence).where(Sequence.name==key).with_for_update())
    counter.value+=1
    return f'{key}_{counter.value:02d}'


def material_options(db):
    """Use existing independent resin, density, color and grade settings in MySQL."""
    rows=list(db.scalars(select(SourceRow).where(SourceRow.book=='master',
        SourceRow.sheet==LEGACY_CONFIG['SHEET_NAMES']['SETTINGS']).order_by(SourceRow.row_number)))
    options={'resins':[],'densities':[],'colors':[],'grades':[]}
    if not rows:return options
    headers=[str(v).strip() for v in rows[0].cells];cols=LEGACY_CONFIG['COLUMNS']['SETTINGS']
    def values(key):
        if cols[key] not in headers:return []
        index=headers.index(cols[key]);result=[]
        for row in rows[1:]:
            value=str(row.cells[index]).strip() if len(row.cells)>index and row.cells[index] is not None else ''
            if value and value.casefold() not in {v.casefold() for v in result}:result.append(value)
        return result
    options.update(resins=values('RESINS'),colors=values('FILM_COLORS'),grades=values('GRADES'))
    if cols['DENSITY_RESIN'] in headers and cols['DENSITY'] in headers:
        ri,di=headers.index(cols['DENSITY_RESIN']),headers.index(cols['DENSITY'])
        for row in rows[1:]:
            if len(row.cells)<=max(ri,di):continue
            resin=str(row.cells[ri] or '').strip()
            try:density=float(str(row.cells[di]).replace(',','.'))
            except (ValueError,TypeError):continue
            canonical=next((v for v in options['resins'] if v.casefold()==resin.casefold()),resin)
            choice={'resin':canonical,'density':density}
            if resin and 0<density<=1000000 and choice not in options['densities']:options['densities'].append(choice)
    return options


def resin_catalog(db):
    return material_options(db)['densities']


def density_choices(db,material_ids):
    from app.modules.materials.purchasing.models import FilmLine
    catalog=resin_catalog(db)
    resins={identifier:set() for identifier in material_ids}
    if material_ids:
        for identifier,resin in db.execute(select(FilmLine.material_id,FilmLine.resin).where(FilmLine.material_id.in_(material_ids)).distinct()):
            if resin:resins[identifier].add(resin.strip().casefold())
    return {identifier:{'choices':[v for v in catalog if v['resin'].casefold() in values] or catalog,
        'automatic':len(values)==1 and len([v for v in catalog if v['resin'].casefold() in values])==1}
        for identifier,values in resins.items()}


def save_standard(db,user,data,previous_id=None,*,identifier=None):
    revision = 1
    identifier=identifier or next_standard_id(db)
    if not previous_id:data=data.model_copy(update={'code':identifier})
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
    if machine.status not in {'ready','running'}:
        fail('Máy chưa ở trạng thái sử dụng được; chọn máy khác hoặc cập nhật trạng thái máy.')
    material = db.get(FilmMaterial,data.material_id)
    if not material or not material.width or not material.thickness:
        fail('Vật liệu phải tồn tại và có khổ/độ dày hợp lệ.')
    if machine and machine.max_width_mm and material.width > machine.max_width_mm:
        fail('Khổ màng vượt khả năng máy.')
    if machine and machine.max_pull_mm and data.pull_mm > machine.max_pull_mm:
        fail('Bước kéo vượt khả năng máy.')
    selected_molds=list(dict.fromkeys([data.mold_id,*data.extra_mold_ids]))
    catalog={str(t.get('MaCC') or ''):t for t in tools_catalog(db)}
    molds=[catalog[k] for k in selected_molds if k in catalog and catalog[k].get('LoaiCC')==LEGACY_CONFIG['MOLD_TYPES']['FORMING']]
    if len(molds)!=len(selected_molds):fail('Chọn khuôn định hình hợp lệ trong danh mục.')
    mold=molds[0]
    width=data.film_width_mm or float(material.width)
    if abs(width-float(material.width))>0.0001:fail('Khổ màng định mức khác khổ NVL. Chọn mã NVL có đúng khổ hoặc sửa khổ định mức theo NVL sử dụng.')
    try:
        if any(float(tool.get('Rong_Khuon') or 0)<=0 or float(tool.get('Dai_Khuon') or 0)<=0 for tool in molds):fail('Kích thước khuôn không hợp lệ.')
        recommended_width=sum(float(tool.get('Rong_Khuon') or 0) for tool in molds)+40
        recommended_pull=max(float(tool.get('Dai_Khuon') or 0) for tool in molds)+60
    except (TypeError,ValueError):fail('Kích thước khuôn không hợp lệ.')
    if (width<recommended_width or data.pull_mm<recommended_pull) and not data.mold_geometry_confirmed:
        raise HTTPException(422,detail={'code':'MOLD_GEOMETRY_CONFIRMATION_REQUIRED',
            'message':f'Khuyến nghị tối thiểu: khổ màng {recommended_width:g} mm, kéo màng {recommended_pull:g} mm. Cần xác nhận nếu dùng thông số nhỏ hơn.'})
    ids = [i.product_id for i in data.items]
    products = {p.id:p for p in db.scalars(select(Product).where(Product.id.in_(ids))).all()}
    if len(products)!=len(ids):
        fail('Có sản phẩm không tồn tại.')
    name=data.name or ('Ghep_Khuon_' if len(molds)>1 or len(data.items)>1 else '')+f'{data.resin or "NVL"}-{width:g}x{data.pull_mm:g}-{data.seconds_per_cycle:g}(chuky)'
    if len(name)>200:fail('Tên định mức tối đa 200 ký tự; cần nhập tên ngắn hơn.')
    weight = calculate_sheet_weight(data.pull_mm,width,material.thickness,data.density)
    parameters = data.model_dump(exclude={'code','name','machine_id','material_id','mold_id','active','approved','items'})
    parameters['film_width_mm']=width
    parameters['sheet_weight_kg'] = weight
    parameters['units'] = {'pull':'mm','width':'mm','thickness':'mm','density':'g/cm3',
        'speed':'seconds/cycle','weight':'kg/sheet','setup':'minutes','waste':'percent',
        'sheets_per_cycle':1,'product_per_sheet':'item.cavity'}
    standard = ProductionStandard(id=identifier or str(uuid4()),code=data.code,revision=revision,
        name=name,machine_id=data.machine_id,material_id=data.material_id,mold_id=data.mold_id,
        active=True,parameters=parameters,created_by=user.id,
        snapshot={'machine':machine_record(machine),'mold':mold,'molds':molds,
                  'material':{c.name:str(getattr(material,c.name)) for c in FilmMaterial.__table__.columns if c.name!='source'},
                  'formula':'purchasing/calculation.js:v1',
                  'approval':{'approved':True,'by':user.id,'at':datetime.now(ZONE).isoformat(),'basis':'save_version'}})
    db.add(standard)
    db.flush()
    for item in data.items:
        product = products[item.product_id]
        db.add(ProductionStandardItem(standard_id=standard.id,**item.model_dump(),snapshot={
            'name':product.name,'code':product.code,'unit':product.unit if str(product.unit).strip().casefold() in {'cái','chiếc'} else 'Cái','product_catalog_unit':product.unit,
            'route':(['forming_cutting'] if machine and machine.kind=='automatic' else ['forming','cutting']) + (['edge'] if item.edge else [])}))
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
