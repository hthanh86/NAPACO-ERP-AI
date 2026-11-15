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
from app.modules.production.planning_schemas import MachineInput, StandardInput, CalendarInput
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
    if kind: statement = statement.where(Machine.kind==kind)
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
def references(kind: str,q: str=Query('',max_length=200),page: int=Query(1,ge=1),
               size: int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    if kind=='molds':
        items = [t for t in service.tools_catalog(db) if t.get('LoaiCC')==service.LEGACY_CONFIG['MOLD_TYPES']['FORMING']]
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
    return {'items':[dict(r) for r in db.execute(statement.order_by(model.id).offset((page-1)*size).limit(size)).mappings()],
            'total':total,'page':page,'size':size}


@router.get('/api/production/standards')
def standards(q: str=Query('',max_length=200),machine_id: str=Query('',max_length=100),
              product_id: str=Query('',max_length=100),history: bool=False,
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
