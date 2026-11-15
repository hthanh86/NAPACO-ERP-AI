"""Sample inspection workflow on the shared QC template/signature/export system."""
from typing import Literal
from fastapi import APIRouter,Depends,Query,Request,HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select,func,or_
from app.auth.security import current_user
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.qc.api import allowed
from app.modules.qc.models import QualityCheck as QC
from app.modules.production.models import ProductionSetup as Setup,ProductionOrder as Run
from app.modules.materials.inventory.allocation_api import write,KeyHeader
from app.modules.materials.inventory.handover_api import ready
from app.modules.production import sample_service as service
from app.modules.production.sample_schemas import EpisodeInput,SampleDraft,SampleSign,SampleVersion

router=APIRouter()
PREFIX='/api/production/samples'


def viewer(user=Depends(current_user),db=Depends(get_db)):
    allowed(db,user,'PRODUCTION_EDIT','QC_VIEW','QC_CREATE','QC_EDIT')
    return user


@router.get('/production/samples')
def page(user=Depends(viewer)):
    return FileResponse(FRONTEND_ROOT/'production/samples.html')


@router.get('/api/production/sample-episodes')
def episodes(q:str=Query('',max_length=200),machine_id:str=Query('',max_length=100),
        run_id:str=Query('',max_length=100),stage:Literal['forming','cutting','edge']|None=None,
        page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(viewer),db=Depends(get_db)):
    ready(db)
    query=select(Setup.id,Setup.production_order_id,Run.official_code,Setup.machine_id,Setup.stage,
        Setup.checked_at,Setup.source[service.EPISODE].label('episode')).join(Run,Run.id==Setup.production_order_id)
    query=query.where(Setup.source[service.EPISODE]['fingerprint'].as_string().is_not(None))
    if q:query=query.where(or_(Run.official_code.contains(q,autoescape=True),Setup.machine_id.contains(q,autoescape=True)))
    if machine_id:query=query.where(Setup.machine_id==machine_id)
    if run_id:query=query.where(Setup.production_order_id==run_id)
    if stage:query=query.where(Setup.stage==next(k for k,v in service.STAGES.items() if v==stage))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(Setup.checked_at.desc(),Setup.id.desc()).offset((page-1)*size).limit(size)).mappings()
    return {'items':[dict(r) for r in rows],'total':total,'page':page,'size':size}


@router.post('/api/production/runs/{run_id}/sample-episodes',status_code=201)
def create_episode(run_id:str,data:EpisodeInput,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:episode:'+run_id,data,key,lambda:service.create_episode(db,user,run_id,data))


@router.get('/api/production/sample-episodes/{identifier}')
def episode(identifier:str,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return service.episode_record(db,service.setup_lock(db,identifier))


@router.post('/api/production/sample-episodes/{identifier}/close')
def close(identifier:str,data:SampleVersion,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:close:'+identifier,data,key,lambda:service.close_episode(db,user,identifier,data))


@router.get('/api/production/sample-episodes/{identifier}/template-options')
def templates(identifier:str,check_type:Literal['QC ĐẦU CA','QC GIỮA CA','QC CUỐI CA']='QC ĐẦU CA',
        user=Depends(viewer),db=Depends(get_db)):
    ready(db);setup=service.setup_lock(db,identifier)
    definition,values=service.template_entry(db,setup,check_type)
    return {'items':[{'id':definition['id'],'code':definition['code'],'name':definition['name'],
        'version':definition['version'],'mapping':definition['mapping'],'snapshot':definition['snapshot'],
        'mapping_hash':definition['mapping_hash'],'source_hash':definition['source_hash'],'context':values,
        'note_cells':service.mapping.criterion_notes(definition['snapshot'],definition['mapping'])}]}


@router.get(PREFIX)
def listing(q:str=Query('',max_length=200),setup_id:str=Query('',max_length=100),
        page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(viewer),db=Depends(get_db)):
    ready(db)
    query=select(QC.id,QC.object_id.label('setup_id'),QC.checked_at,QC.result,Run.official_code,
        QC.form_data[service.SAMPLE]['state'].as_string().label('state'),
        QC.form_data[service.SAMPLE]['decision'].as_string().label('decision')).join(Run,Run.id==QC.production_order_id)
    query=query.where(QC.form_data[service.SAMPLE]['version'].as_integer().is_not(None))
    if setup_id:query=query.where(QC.object_id==setup_id)
    if q:query=query.where(or_(QC.id.contains(q,autoescape=True),Run.official_code.contains(q,autoescape=True)))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(QC.checked_at.desc(),QC.id.desc()).offset((page-1)*size).limit(size)).mappings()
    return {'items':[dict(r) for r in rows],'page':page,'size':size,'total':total}


@router.post(PREFIX,status_code=201)
def create(data:SampleDraft,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:create',data,key,lambda:service.save(db,user,data))


@router.get(PREFIX+'/{identifier}')
def detail(identifier:str,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return service.record(db,service.qc_lock(db,identifier))


@router.put(PREFIX+'/{identifier}')
def update(identifier:str,data:SampleDraft,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:edit:'+identifier,data,key,lambda:service.save(db,user,data,identifier))


@router.post(PREFIX+'/{identifier}/confirm-signature')
def confirm(identifier:str,data:SampleSign,request:Request,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return service.confirm(db,user,request,identifier,data)


@router.post(PREFIX+'/{identifier}/sign')
def sign(identifier:str,data:SampleSign,request:Request,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:sign:'+identifier,data,key,lambda:service.sign(db,user,request,identifier,data))


@router.post(PREFIX+'/{identifier}/cancel')
def cancel(identifier:str,data:SampleVersion,key:str=KeyHeader,user=Depends(viewer),db=Depends(get_db)):
    ready(db);return write(db,user,'sample:cancel:'+identifier,data,key,lambda:service.cancel(db,user,identifier,data))


@router.get('/api/production/runs/{run_id}/sample-eligibility')
def eligibility(run_id:str,machine_id:str=Query(min_length=1,max_length=100),
        stage:Literal['forming','cutting','edge']='forming',setup_id:str|None=Query(None,max_length=100),
        user=Depends(viewer),db=Depends(get_db)):
    ready(db)
    try:return {'allowed':True,'basis':service.gate(db,run_id,machine_id,stage,setup_id)}
    except HTTPException as error:
        if error.status_code not in {404,409,422}:raise
        return {'allowed':False,'basis':None,'reason':error.detail}
