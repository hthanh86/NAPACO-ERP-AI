"""Native planning API. Existing PRODUCTION_EDIT permission protects all planning data."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func, or_, String
from app.auth.security import current_user, require
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.materials.models import FilmMaterial
from app.modules.products.models import Product
from app.modules.customers.models import Customer
from app.modules.production.planning_models import Machine, ProductionStandard, ProductionStandardItem, MachineCalendarException
from app.modules.production.planning_schemas import MachineInput, StandardInput, CalendarInput, StandardWithMoldsInput
from app.modules.materials.inventory.allocation_api import write,KeyHeader
from app.modules.production import planning_service as service

router = APIRouter()


def access(user=Depends(current_user), db=Depends(get_db)):
    require(db,user,'PRODUCTION_EDIT')
    return user


def commit(db, operation):
    try:
        result = operation()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get('/production/planning')
def page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT / 'production/planning.html')


@router.get('/production/schedule')
def schedule_page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT / 'production/schedule.html')


@router.get('/production/be-dan')
def be_dan_page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT / 'production/be-dan.html')


@router.get('/api/production/film-calculation.js')
def shared_formula(user=Depends(current_user)):
    # Purchasing already requires its own permission; this file contains only pure arithmetic.
    return FileResponse(service.CALCULATION,media_type='application/javascript')


@router.get('/api/production/machines')
def machines(q: str=Query('',max_length=200),kind: str=Query('',max_length=30),
             status: str=Query('',max_length=30),page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),
             user=Depends(access),db=Depends(get_db)):
    statement = select(Machine)
    if q: statement = statement.where(or_(Machine.id.contains(q,autoescape=True),Machine.name.contains(q,autoescape=True)))
    if kind: statement = statement.where(Machine.kind.in_(['automatic','semi_automatic']) if kind=='forming' else Machine.kind==kind)
    if status: statement = statement.where(Machine.status==status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return {'items':[service.machine_record(m) for m in db.scalars(statement.order_by(Machine.id).offset((page-1)*size).limit(size))],
            'total':total,'page':page,'size':size}


@router.post('/api/production/machines',status_code=201)
def create_machine(data: MachineInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:service.save_machine(db,user,data))


@router.put('/api/production/machines/{identifier}')
def update_machine(identifier: str,data: MachineInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:service.save_machine(db,user,data,identifier))


@router.get('/api/production/references/{kind}')
def references(kind: str,q: str=Query('',max_length=200),product_id: str=Query('',max_length=100),page: int=Query(1,ge=1),
               size: int=Query(25,ge=1,le=100),resin:str=Query('',max_length=100),thickness:float|None=Query(None,gt=0),width:float|None=Query(None,gt=0),color:str=Query('',max_length=500),grade:str=Query('',max_length=500),product_ids:list[str]=Query(default=[]),user=Depends(access),db=Depends(get_db)):
    if kind=='run-options':
        if len(product_ids)>100:service.fail('Tối đa 100 sản phẩm.')
        wanted=set(product_ids)
        molds=[t for t in service.tools_catalog(db) if t.get('LoaiCC')==service.LEGACY_CONFIG['MOLD_TYPES']['FORMING'] and t.get('MaSP') in wanted]
        if len(molds)>200:service.fail('Quá nhiều khuôn; thu hẹp nhóm sản phẩm.')
        return {**service.material_options(db),'molds':molds}
    if kind=='material-spec':
        if not resin or thickness is None or width is None:service.fail('Nhập loại nhựa, độ dày và khổ nhựa.')
        from app.modules.materials.catalog_service import find_specs
        rows=find_specs(db,width,thickness,color,grade)
        if not rows:
            from fastapi import HTTPException
            raise HTTPException(404,detail={'code':'MATERIAL_SPEC_NEW','message':'Quy cách NVL mới; có thể xác nhận lưu cùng định mức.'})
        if len(rows)>1:service.fail('Có nhiều NVL khớp quy cách. Chọn rõ màu và Cấp Độ; không tự chọn ngầm hoặc tạo thêm mã trùng.')
        row=rows[0]
        return {key:getattr(row,key) for key in ['id','grade','color','thickness','width']}
    if kind=='molds':
        items = [t for t in service.tools_catalog(db) if t.get('LoaiCC')==service.LEGACY_CONFIG['MOLD_TYPES']['FORMING']]
        if product_id:items=[t for t in items if str(t.get('MaSP') or '').strip()==product_id]
        if q: items = [t for t in items if q.casefold() in ' '.join(str(v or '') for v in t.values()).casefold()]
        return {'items':items[(page-1)*size:page*size],'total':len(items)}
    if kind=='customers':
        model = Customer
        cols = [Customer.id,Customer.name]
    elif kind=='products':
        model = Product
        cols = [Product.id,Product.name,Product.code,Product.unit]
    elif kind=='materials':
        model = FilmMaterial
        cols = [FilmMaterial.id,FilmMaterial.grade,FilmMaterial.color,FilmMaterial.width,FilmMaterial.thickness]
    else:
        service.fail('Loại danh mục không hợp lệ.',404)
    statement = select(*cols)
    if q:
        statement = statement.where(or_(*[col.cast(String).contains(q,autoescape=True) for col in cols]))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    items=[dict(r) for r in db.execute(statement.order_by(model.id).offset((page-1)*size).limit(size)).mappings()]
    if kind=='materials':
        defaults=service.density_choices(db,[i['id'] for i in items])
        for item in items:item['density_defaults']=defaults[item['id']]
    return {'items':items,'total':total,'page':page,'size':size}


@router.get('/api/production/standards')
def standards(q: str=Query('',max_length=200),machine_id: str=Query('',max_length=100),
              product_id: str=Query('',max_length=100),history: bool=False,
              material_id:str=Query('',max_length=100),mold_id:str=Query('',max_length=100),resin:str=Query('',max_length=100),
              thickness:float|None=Query(None,gt=0),color:str=Query('',max_length=500),grade:str=Query('',max_length=500),
              seconds_per_cycle:float|None=Query(None,gt=0,le=1000000),pull_mm:float|None=Query(None,gt=0),film_width_mm:float|None=Query(None,gt=0),
              page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),
              user=Depends(access),db=Depends(get_db)):
    cols = [ProductionStandard.id,ProductionStandard.code,ProductionStandard.name,ProductionStandard.revision,
            ProductionStandard.machine_id,ProductionStandard.active,ProductionStandard.created_at]
    statement = select(*cols)
    if not history:
        latest = select(ProductionStandard.code,func.max(ProductionStandard.revision).label('revision')).group_by(ProductionStandard.code).subquery()
        statement = statement.join(latest,(ProductionStandard.code==latest.c.code)&(ProductionStandard.revision==latest.c.revision))
    if q: statement = statement.where(or_(ProductionStandard.code.contains(q,autoescape=True),ProductionStandard.name.contains(q,autoescape=True)))
    if machine_id: statement = statement.where(ProductionStandard.machine_id==machine_id)
    if thickness is not None or color or grade:
        statement=statement.join(FilmMaterial,FilmMaterial.id==ProductionStandard.material_id)
        if thickness is not None:statement=statement.where(func.abs(FilmMaterial.thickness-thickness)<0.000001)
        if color:statement=statement.where(func.lower(FilmMaterial.color)==color.strip().lower())
        if grade:statement=statement.where(func.lower(FilmMaterial.grade)==grade.strip().lower())
    if material_id:statement=statement.where(ProductionStandard.material_id==material_id)
    if mold_id:statement=statement.where(ProductionStandard.mold_id==mold_id)
    if resin:statement=statement.where(ProductionStandard.parameters['resin'].as_string()==resin)
    for key,value in [('seconds_per_cycle',seconds_per_cycle),('pull_mm',pull_mm),('film_width_mm',film_width_mm)]:
        if value is not None:statement=statement.where(func.abs(ProductionStandard.parameters[key].as_float()-value)<0.000001)
    if product_id:
        statement = statement.where(ProductionStandard.id.in_(select(ProductionStandardItem.standard_id).where(ProductionStandardItem.product_id==product_id)))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return {'items':[dict(r) for r in db.execute(statement.order_by(ProductionStandard.code,ProductionStandard.revision.desc()).offset((page-1)*size).limit(size)).mappings()],
            'total':total,'page':page,'size':size}


@router.get('/api/production/standards/{identifier}')
def standard(identifier: str,user=Depends(access),db=Depends(get_db)):
    item = db.get(ProductionStandard,identifier)
    if not item: service.fail('Không tìm thấy định mức.',404)
    return service.standard_record(db,item)


@router.post('/api/production/standards',status_code=201)
def create_standard(data: StandardInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:service.save_standard(db,user,data))


@router.post('/api/production/standards/with-molds',status_code=201)
def create_standard_with_molds(data: 'StandardWithMoldsInput',key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    def perform():
        from app.modules.master.tool_catalog import create_molds
        mapping=create_molds(db,user,data.molds)
        standard=data.standard.model_copy(update={'mold_id':mapping.get(data.standard.mold_id,data.standard.mold_id),'extra_mold_ids':[mapping.get(identifier,identifier) for identifier in data.standard.extra_mold_ids]})
        if data.new_material:
            spec=data.new_material
            if spec.resin.casefold()!=standard.resin.casefold() or abs(spec.width-(standard.film_width_mm or 0))>0.000001:
                service.fail('Quy cách NVL mới phải khớp loại nhựa và khổ màng của định mức.')
            from app.modules.materials.catalog_service import ensure_spec
            material=ensure_spec(db,user,spec)
            standard=standard.model_copy(update={'material_id':material.id})
        selected={standard.mold_id,*standard.extra_mold_ids}
        products={i.product_id for i in data.standard.items}
        molds=[m for m in service.tools_catalog(db) if m.get('MaCC') in selected]
        if {m.get('MaSP') for m in molds}!=products or any(m.get('LoaiCC')!=service.LEGACY_CONFIG['MOLD_TYPES']['FORMING'] for m in molds):
            service.fail('Mỗi sản phẩm cần có khuôn định hình đúng liên kết trong định mức.')
        return service.save_standard(db,user,standard)
    return write(db,user,'production:standard:with-molds',data,key,perform)


@router.post('/api/production/standards/{identifier}/revisions',status_code=201)
def revise_standard(identifier: str,data: StandardInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:service.save_standard(db,user,data,identifier))


@router.get('/api/production/standards/{identifier}/route')
def route(identifier: str,user=Depends(access),db=Depends(get_db)):
    return service.route_for_standard(db,identifier)


@router.put('/api/production/calendars')
def calendars(data: CalendarInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:service.save_calendars(db,user,data))


@router.get('/api/production/calendars/{machine_id}')
def calendar(machine_id: str,start: date,end: date,user=Depends(access),db=Depends(get_db)):
    if end<start or (end-start).days>92: service.fail('Khoảng ngày tối đa 93 ngày.')
    machine = db.get(Machine,machine_id)
    if not machine: service.fail('Không tìm thấy máy.',404)
    from app.modules.production.calendar_settings import effective_week
    return {'machine_id':machine_id,'version':machine.version,'weekly':effective_week(db,machine),'inherited':not bool(machine.calendar),
        'exceptions':[{'day':e.day,'windows':e.windows,'note':e.note} for e in db.scalars(select(MachineCalendarException).where(
            MachineCalendarException.machine_id==machine_id,MachineCalendarException.day.between(start,end)).order_by(MachineCalendarException.day))]}


@router.get('/api/production/availability')
def availability(start: date,end: date,machine_id: list[str]=Query(...,max_length=100),
                 user=Depends(access),db=Depends(get_db)):
    return service.available_windows(db,machine_id,start,end)
