from typing import Literal
from html import escape
from fastapi import APIRouter,Depends,Query,Request
from fastapi.responses import FileResponse,HTMLResponse
from sqlalchemy import inspect
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.materials.inventory.allocation_api import access,write,KeyHeader
from app.modules.materials.inventory.handover_schemas import HandoverSign,HandoverVersion,HandoverDraft
from app.modules.materials.inventory import handover_service as service
from app.modules.materials.inventory.handover_sources import source_contexts
from app.modules.production.models import ProductionOrder

router=APIRouter()
PREFIX='/api/production/materials/handovers'


def ready(db):
    if not inspect(db.connection()).has_table('material_handovers'):service.material.fail('Bàn giao NVL cần migration 016.',503)


@router.get('/production/handovers')
def page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT/'production/handovers.html')


@router.get(PREFIX)
def listing(q:str=Query('',max_length=200),state:Literal['','draft','awaiting_receipt','received','cancelled']='',
            page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db);return service.listing(db,q=q,state=state,page=page,size=size)


@router.post(PREFIX,status_code=201)
def create(data:HandoverDraft,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'handover:create',data,key,lambda:service.create_issue(db,user,data.allocation_id,data))


@router.get(PREFIX+'/{identifier}')
def detail(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.record(service.lock(db,identifier))


@router.post(PREFIX+'/{identifier}/cancel')
def cancel(identifier:str,data:HandoverVersion,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'handover:cancel:'+identifier,data,key,lambda:service.cancel(db,user,identifier,data))


@router.post(PREFIX+'/{identifier}/confirm-signature')
def confirm(identifier:str,data:HandoverSign,request:Request,user=Depends(access),db=Depends(get_db)):
    ready(db);return service.confirm_signature(db,user,request,service.lock(db,identifier,data.version),data)


@router.post(PREFIX+'/{identifier}/sign')
def sign(identifier:str,data:HandoverSign,request:Request,key:str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    ready(db);return write(db,user,'handover:sign:'+identifier,data,key,lambda:service.sign(db,user,request,identifier,data))


@router.get('/api/production/materials/runs/{identifier}/balance')
def balance(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);run=db.get(ProductionOrder,identifier)
    if not run:service.material.fail('Không tìm thấy LSX.',404)
    context=source_contexts(db,[identifier])[identifier]
    return service.encoded({'run_id':run.id,'official_code':run.official_code,'release_state':run.release_state,**context})


@router.get(PREFIX+'/{identifier}/sheet',response_class=HTMLResponse)
def sheet(identifier:str,user=Depends(access),db=Depends(get_db)):
    ready(db);row=service.lock(db,identifier);data=row.snapshot
    def proof(value):
        if not value:return '<p>Chưa ký</p>'
        strokes=''.join('<polyline fill="none" stroke="black" stroke-width="2" points="'+
            ' '.join(f'{float(x)*360},{float(y)*120}' for x,y in s)+'" />' for s in value['signature'])
        return '<svg viewBox="0 0 360 120" width="360" height="120">'+strokes+'</svg><p>'+escape(value['name'])+' · '+escape(value.get('email') or '')+'</p><p>'+escape(value['signed_at'])+'</p>'
    return '<!doctype html><html lang="vi"><meta charset="utf-8"><title>Phiếu bàn giao NVL</title><style>body{font:16px sans-serif;margin:30px}table{width:100%}td{vertical-align:top;border:1px solid #aaa;padding:12px}@media print{button{display:none}}</style><h1>PHIẾU CẤP VÀ BÀN GIAO NVL</h1><h2>'+escape(data['official_code'])+'</h2><p>Lô: '+escape(data['receipt_id'])+' · CTĐH: '+escape(data['order_line_id'])+' · '+escape(str(row.quantity))+' kg</p><p>'+escape(data['note'])+'</p><p>Trạng thái: '+escape({'draft':'Nháp','awaiting_receipt':'Chờ bàn giao','received':'Đã nhận','cancelled':'Đã hủy'}[row.state])+'</p><table><tr><td><h3>Người cấp ký</h3>'+proof(row.issue_signature)+'</td><td><h3>Người nhận ký</h3>'+proof(row.receipt_signature)+'</td></tr></table><button onclick="print()">In phiếu</button></html>'
