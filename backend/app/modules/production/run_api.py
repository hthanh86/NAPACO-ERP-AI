"""Run and shift endpoints extend current production orders/logs."""
from datetime import date
from typing import Literal
from html import escape
from fastapi import APIRouter,Depends,Query
from fastapi.responses import FileResponse,HTMLResponse
from sqlalchemy import select,func,or_,inspect
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.materials.inventory.allocation_api import access,write,KeyHeader
from app.modules.production.models import ProductionOrder,FormingLog
from app.modules.production.run_models import ProductionOrderItem,DownstreamItem
from app.modules.production.run_schemas import RunInput,VersionInput,ShiftInput,DownstreamInput,CalendarDefaultInput,BindMaterialInput,SetupInput
from app.modules.production import run_service as service
from app.modules.production import release_service
from app.modules.production.calendar_settings import read_default,save_default
from app.modules.production.planning_api import commit

router=APIRouter()

from app.modules.production.history_schemas import HistoryQuery
from app.modules.production.history_service import suggestions


@router.post('/api/production/run-suggestions')
def run_suggestions(data:HistoryQuery,user=Depends(access),db=Depends(get_db)):
    ready(db)
    return suggestions(db,data)


def ready(db):
    if not inspect(db.connection()).has_table('production_order_assignments'):
        service.fail('Chưa áp dụng migration 015 cho phát hành và phân công LSX.',503)


@router.get('/production/runs')
def page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT/'production/runs.html')


@router.get('/production/calendar-settings')
def settings_page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT/'production/calendar-settings.html')


@router.get('/api/production/calendar-default')
def default_calendar(user=Depends(access),db=Depends(get_db)):
    return read_default(db)


@router.put('/api/production/calendar-default')
def update_default(data:CalendarDefaultInput,user=Depends(access),db=Depends(get_db)):
    return commit(db,lambda:save_default(db,user,data))


@router.get('/api/production/runs')
def runs(q:str=Query('',max_length=200),status:str=Query('',max_length=100),
         page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(ProductionOrder.id,ProductionOrder.official_code,ProductionOrder.release_state,
        ProductionOrder.released_at,ProductionOrder.group_id,ProductionOrder.machine_id,ProductionOrder.status,
        ProductionOrder.version,ProductionOrder.planned_sheets,ProductionOrder.planned_hours).where(ProductionOrder.run_snapshot.is_not(None))
    if q:
        query=query.where(or_(ProductionOrder.official_code.contains(q,autoescape=True),ProductionOrder.group_id.contains(q,autoescape=True),
            ProductionOrder.id.in_(select(ProductionOrderItem.run_id).where(ProductionOrderItem.order_line_id.contains(q,autoescape=True)))))
    if status:query=query.where(ProductionOrder.status==status)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[dict(r) for r in db.execute(query.order_by(ProductionOrder.issued_at.desc(),ProductionOrder.id)
            .offset((page-1)*size).limit(size)).mappings()],'total':total,'page':page,'size':size}


@router.get('/api/production/machines/{machine_id}/work')
def machine_work(machine_id:str,stage:Literal['forming','cutting','edge']='forming',
                 page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db);return release_service.machine_queue(db,machine_id,stage,page,size)


@router.post('/api/production/runs/{identifier}/release')
def release(identifier:str,data:VersionInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:release:'+identifier,data,key,lambda:release_service.release(db,user,identifier,data))


@router.get('/api/production/runs/{identifier}/assignments')
def assignments(identifier:str,page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db);return release_service.history(db,identifier,page,size)


@router.post('/api/production/runs/{identifier}/setups',status_code=201)
def create_setup(identifier:str,data:SetupInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:setup:'+identifier,data,key,lambda:release_service.create_setup(db,user,identifier,data))


@router.get('/api/production/runs/{identifier}/release-sheet',response_class=HTMLResponse)
def release_sheet(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);run=service.run_lock(db,identifier,readonly=True);release_service.require_released(run)
    frozen=run.release_snapshot;order=frozen['run']
    rows=''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in
        (i['order_line_id'],i['snapshot'].get('name',i['product_id']),i['planned_qty'],i['cavity']))+'</tr>' for i in order['items'])
    return '<!doctype html><html lang="vi"><meta charset="utf-8"><title>'+escape(run.official_code)+'''</title>
        <style>body{font:16px sans-serif;margin:36px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #888;padding:8px}@media print{button{display:none}}</style>
        <h1>PHIẾU LỆNH SẢN XUẤT</h1><h2>'''+escape(run.official_code)+'</h2><p>Phát lúc: '+escape(str(run.released_at))+\
        ' · Người phát: '+escape(str(run.released_by))+'</p><p>Máy định hình lúc phát: '+escape(order['machine_id'])+\
        '</p><p>Đây là nội dung đã phát; phân công hiện hành xem trên kế hoạch cập nhật.</p><table><thead><tr><th>CTĐH</th><th>Sản phẩm</th><th>Số lượng</th><th>Cavity</th></tr></thead><tbody>'+rows+\
        '</tbody></table><button onclick="print()">In phiếu</button></html>'


@router.get('/api/production/runs/{identifier}')
def detail(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.detail(db,identifier)


@router.post('/api/production/runs',status_code=201)
def create(data:RunInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:create',data,key,lambda:service.save_run(db,user,data))


@router.put('/api/production/runs/{identifier}')
def edit(identifier:str,data:RunInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:edit:'+identifier,data,key,lambda:service.save_run(db,user,data,identifier))


@router.post('/api/production/runs/{identifier}/start')
def start(identifier:str,data:VersionInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:start:'+identifier,data,key,lambda:service.change_state(db,user,identifier,data,start=True))


@router.post('/api/production/runs/{identifier}/materials')
def bind_material(identifier:str,data:BindMaterialInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:material:'+identifier,data,key,lambda:service.bind_material(db,user,identifier,data))


@router.post('/api/production/runs/{identifier}/finish')
def finish(identifier:str,data:VersionInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'run:finish:'+identifier,data,key,lambda:service.change_state(db,user,identifier,data))


@router.get('/api/production/runs/{identifier}/shift-context')
def context(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.shift_context(db,identifier)


@router.get('/api/production/runs/{identifier}/shifts')
def shifts(identifier:str,page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(FormingLog.id,FormingLog.shift_start,FormingLog.shift_end,FormingLog.good,FormingLog.ng,FormingLog.version).where(
        FormingLog.production_order_id==identifier,FormingLog.shift_snapshot.is_not(None))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[dict(r) for r in db.execute(query.order_by(FormingLog.shift_end.desc(),FormingLog.id)
        .offset((page-1)*size).limit(size)).mappings()],'total':total,'page':page,'size':size}


@router.get('/api/production/shifts/{identifier}')
def shift(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.shift_detail(db,identifier)


@router.post('/api/production/runs/{identifier}/shifts',status_code=201)
def close_shift(identifier:str,data:ShiftInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'shift:create:'+identifier,data,key,lambda:service.save_shift(db,user,identifier,data))


@router.put('/api/production/runs/{identifier}/shifts/{shift_id}')
def edit_shift(identifier:str,shift_id:str,data:ShiftInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'shift:edit:'+shift_id,data,key,lambda:service.save_shift(db,user,identifier,data,shift_id))


@router.post('/api/production/downstream',status_code=201)
def downstream(data:DownstreamInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'downstream:create:'+data.stage,data,key,lambda:service.save_downstream(db,user,data))


@router.get('/api/production/shifts/{identifier}/downstream')
def downstream_list(identifier:str,page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(DownstreamItem).where(DownstreamItem.forming_log_id==identifier)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[{'id':d.cut_id or d.edge_id,'stage':d.stage,'order_line_id':d.order_line_id,'input_qty':d.input_qty,
        'good_qty':d.good_qty,'ng_qty':d.ng_qty,'snapshot':d.snapshot} for d in db.scalars(query.order_by(DownstreamItem.id)
        .offset((page-1)*size).limit(size))],'total':total,'page':page,'size':size}
