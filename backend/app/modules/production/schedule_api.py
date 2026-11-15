"""Phase 4 contract: clients render the result, never reproduce its arithmetic."""
from datetime import date,datetime
from typing import Literal
from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,func,inspect
from app.core.database import get_db
from app.modules.materials.inventory.allocation_api import access,write,KeyHeader
from app.modules.materials.inventory.allocation_service import fail
from app.modules.production.schedule_schemas import ScheduleInput,ScheduleSaveInput,CloseDayInput
from app.modules.production.schedule_models import SchedulePlan
from app.modules.production import schedule_service as service
from app.modules.production import schedule_view
from app.modules.production import schedule_daily,schedule_compare,schedule_actual

router=APIRouter(prefix='/api/production/schedule',tags=['production-schedule'])


def scope(view_start:datetime|None=None,view_end:datetime|None=None,
          machine_id:str=Query('',max_length=100),customer_id:str=Query('',max_length=100),q:str=Query('',max_length=200)):
    if (view_start is None)!=(view_end is None):fail('Cần cả hai mốc khoảng xem.')
    if view_start and (view_start.tzinfo is None or view_end.tzinfo is None):fail('Khoảng xem cần múi giờ.')
    return {'start':view_start,'end':view_end,'machine_id':machine_id,'customer_id':customer_id,'q':q}


def ready(db):
    inspector=inspect(db.connection())
    if not all(inspector.has_table(name) for name in ['production_order_items','production_schedule_plans','production_run_stops','production_schedule_days']):
        fail('Kế hoạch theo ngày cần migration 012–014; hiện chưa sẵn sàng.',503)


@router.post('/preview')
def preview(data:ScheduleInput,user=Depends(access),db=Depends(get_db),view=Depends(scope)):
    ready(db)
    if view['start']:
        with db.no_autoflush:outcome=service.prepare(db,user,data)
        projected=schedule_view.project(db,outcome['result'],outcome['_canonical'],data.base_version,configs=outcome['_configs'],**view)
        projected['day']=outcome['_snapshot_context']['day']
        return service.encoded({'preview_hash':outcome['preview_hash'],'base_version':data.base_version,
            'warnings':outcome['warnings'],'workspace':projected})
    return service.encoded(service.preview(db,user,data))


@router.post('/save',status_code=201)
def save(data:ScheduleSaveInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db),view=Depends(scope)):
    ready(db)
    def perform():
        result=service.save(db,user,data)
        if view['start']:
            row=db.get(SchedulePlan,result['id'])
            workspace=schedule_view.project(db,row.result,row.request,row.version,**view,frozen_context=row.context)
            workspace['day']=result['day'];workspace['snapshot_id']=row.id
            return service.encoded({'id':row.id,'version':row.version,'workspace':workspace})
        return result
    payload={'schedule':data.model_dump(mode='json'),'view':service.encoded(view)} if view['start'] else data
    return write(db,user,'production:schedule:save',payload,key,perform)


@router.get('/view')
def workspace(user=Depends(access),db=Depends(get_db),view=Depends(scope)):
    ready(db)
    if not view['start']:fail('Chọn khoảng thời gian cần xem.')
    row,status=schedule_daily.source(db);latest=service.latest(db)
    workspace=schedule_view.project(db,row.result if row else None,row.request if row else {},latest.version if latest else 0,**view,frozen_context=row.context if row else None)
    workspace['day']=status;workspace['snapshot_id']=row.id if row else None
    return service.encoded(workspace)


@router.post('/daily/close')
def close_day(data:CloseDayInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'production:day:close',data,key,lambda:schedule_daily.close(db,user,data))


@router.get('/daily/compare')
def comparison(day:date,mode:Literal['actual','update'],user=Depends(access),db=Depends(get_db),view=Depends(scope)):
    ready(db)
    if not view['start']:fail('Chọn khoảng sản xuất cần xem.')
    return schedule_compare.view(db,day,mode,**view)


@router.get('/actual')
def actual(user=Depends(access),db=Depends(get_db),view=Depends(scope)):
    ready(db);return service.encoded(schedule_actual.read(db,**view))


@router.get('/editor/{identifier}')
def editor(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.encoded(schedule_view.editor(db,identifier))


@router.get('/latest')
def latest(user=Depends(access),db=Depends(get_db)):
    ready(db);row=service.latest(db)
    if not row:return {'version':0,'id':None,'request':None,'result':None}
    return record(row)


@router.get('/history')
def history(page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    rows=db.execute(select(SchedulePlan.id,SchedulePlan.version,SchedulePlan.created_at,SchedulePlan.created_by)
        .order_by(SchedulePlan.version.desc()).offset((page-1)*size).limit(size)).mappings().all()
    return {'items':[dict(row) for row in rows],'total':db.scalar(select(func.count()).select_from(SchedulePlan)),'page':page,'size':size}


@router.get('/history/{identifier}')
def detail(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);row=db.get(SchedulePlan,identifier)
    if not row:fail('Không tìm thấy bản kế hoạch.',404)
    return record(row)


def record(row):
    return {'id':row.id,'version':row.version,'request':row.request,'result':row.result,
        'source_hash':row.source_hash,'created_at':row.created_at,'created_by':row.created_by,'context':row.context}
