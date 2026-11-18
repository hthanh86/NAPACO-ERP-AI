"""Focused machine-first forming diary API, sharing the established write path."""
from datetime import date,datetime
from fastapi import APIRouter,Depends,Query
from fastapi.responses import FileResponse
from sqlalchemy import select,func
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.materials.inventory.allocation_api import access,write,KeyHeader
from app.modules.materials.inventory.handover_api import ready
from app.modules.production.planning_models import Machine
from app.modules.production.forming_schemas import FormingInput,EvidenceInput
from app.modules.production import forming_service as service

router=APIRouter()
PREFIX='/api/production/forming'


@router.get('/production/forming')
def page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT/'production/forming.html')


@router.get(PREFIX+'/machines')
def machines(q:str=Query('',max_length=200),page:int=Query(1,ge=1),size:int=Query(50,ge=1,le=100),
        user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(Machine.id,Machine.name,Machine.kind,Machine.status).where(
        Machine.kind.in_(['automatic','semi_automatic']),Machine.status.in_(['ready','running']))
    if q:query=query.where((Machine.id.contains(q,autoescape=True))|(Machine.name.contains(q,autoescape=True)))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[dict(r) for r in db.execute(query.order_by(Machine.id).offset((page-1)*size).limit(size)).mappings()],
        'total':total,'page':page,'size':size}


@router.get(PREFIX+'/context')
def context(run_id:str=Query(min_length=1,max_length=100),machine_id:str=Query(min_length=1,max_length=100),
        setup_id:str|None=Query(None,max_length=100),until:datetime|None=None,since:datetime|None=None,
        edit_id:str|None=Query(None,max_length=100),
        user=Depends(access),db=Depends(get_db)):
    ready(db)
    if until and not until.tzinfo:service.fail('Giờ kết thúc cần múi giờ.')
    if since and not since.tzinfo:service.fail('Giờ bắt đầu cần múi giờ.')
    return service.context(db,run_id,machine_id,setup_id,until,edit_id,since)


@router.get(PREFIX+'/history')
def history(machine_id:str=Query('',max_length=100),run_id:str=Query('',max_length=100),
        start:date|None=None,end:date|None=None,page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),
        user=Depends(access),db=Depends(get_db)):
    ready(db)
    if not machine_id and not run_id:service.fail('Chọn máy hoặc LSX trước khi tra cứu nhật ký.')
    if start and end and end<start:service.fail('Ngày kết thúc cần sau hoặc bằng ngày bắt đầu.')
    return service.history(db,machine_id,run_id,start,end,page,size)


@router.get(PREFIX+'/runs/{run_id}/summary')
def summary(run_id:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.summary(db,run_id)


@router.post(PREFIX+'/runs/{run_id}/logs',status_code=201)
def create(run_id:str,data:FormingInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'forming:create:'+run_id,data,key,lambda:service.save(db,user,run_id,data))


@router.put(PREFIX+'/runs/{run_id}/logs/{log_id}')
def edit(run_id:str,log_id:str,data:FormingInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'forming:edit:'+run_id+':'+log_id,data,key,lambda:service.save(db,user,run_id,data,log_id))


@router.post(PREFIX+'/runs/{run_id}/evidence-context')
def evidence_context(run_id:str,data:EvidenceInput,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'forming:evidence:'+run_id,data,key,lambda:service.evidence_context(db,user,run_id,data))
