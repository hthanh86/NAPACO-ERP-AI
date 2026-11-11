import hashlib
import json
from pathlib import Path
import subprocess
import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.auth.security import current_user
from app.core.database import get_db
from app.core.paths import APP_ROOT, FRONTEND_ROOT
from app.core.models import Audit
from app.compatibility.models import LegacyState, LegacyRequest
from app.compatibility.store import CONFIG, SPECS, NAMES, project, rows_to_models, runtime_notes, persistent_notes
from app.integrations.google.models import GoogleCredential
from app.integrations.google import drive as google_drive
from app.integrations.google.oauth import configured

router=APIRouter()
WRITE_METHODS={
 'saveOrderTransaction','saveOrderFromModal','submitOrderTransaction','updateOrderLineItemsBulk',
 'apiUpdateLineKanbanPositions','saveFilmAssignments','saveFilmOrder','saveFilmReceipts',
 'saveFilmReceipt','confirmFilmReturn','syncFilmReturnFromJournal'}
READ_METHODS={
 'getOrderModalInitData','getOrderFormData','queryOrdersAndLineItems','apiGetLineKanbanData',
 'getSavedOrderListPage','searchUserDriveFiles','getFilmOrders','getFilmOrderFormData',
 'getFilmOrderAssignments','getFilmAssignedDetails','getFilmAssignmentOptions','getFilmProducts',
 'getFilmProductReference','getFilmReceiptLines','getFilmReceiptHistory','getFilmStock','getFilmPendingReturns'}
VIEWS={'index','create','modal','list','be','film','film-create','film-stock','film-receive'}


def inject(html,revision):
    bridge='<script>window.NAPACO_REV='+str(revision)+';</script><script src="/static/shared/bridge.js"></script>'
    # Preserve the exact source markup and CSS; replace only the Google RPC transport
    # and vendor the original pinned drag/drop library for offline local use.
    html=html.replace('<head>','<head>'+bridge,1)
    return html.replace('https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js','/static/vendor/Sortable.min.js')


def execute(db,user,request,*,method=None,args=None,params=None,render=False,revision=None,request_id=None):
    writing=method in WRITE_METHODS
    state=db.scalar(select(LegacyState).where(LegacyState.id==1).with_for_update()) if writing else db.get(LegacyState,1)
    if not state:raise HTTPException(503,'Chưa khởi tạo dữ liệu chuyển đổi đầy đủ.')
    if method=='searchUserDriveFiles':
        result=google_drive.search(db,user,(args or [''])[0]);db.commit()
        return {'result':result,'revision':state.revision}
    checksum=hashlib.sha256(json.dumps([method,args],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if writing:
        prior=db.scalar(select(LegacyRequest).where(LegacyRequest.id==request_id).with_for_update())
        if prior:
            if prior.user_id!=user.id or prior.payload_hash!=checksum:raise HTTPException(409,'Mã yêu cầu đã được sử dụng.')
            return {'result':prior.result,'revision':state.revision}
        # Preserve the original workflow: no global "reload every other tab"
        # requirement. The original per-order revisions and assignment/receipt
        # validation run against fresh data after acquiring this MySQL lock.
    books=project(db)
    payload={'config':CONFIG,'frontendRoot':str(FRONTEND_ROOT),'books':books,'user':{'id':user.id,'name':user.name,'email':user.email,'localAdmin':user.role=='LOCAL_ADMIN'},
             'properties':state.properties,'metadata':state.metadata_entries,'notes':runtime_notes(books,state.cell_notes),
             'appUrl':str(request.base_url).rstrip('/'),'method':method,'args':args or [],'params':params or {},'render':render,
             'driveReady':configured() and db.get(GoogleCredential,user.id) is not None}
    try:
        proc=subprocess.run(['node',str(APP_ROOT / 'compatibility/runtime.cjs')],input=json.dumps(payload,ensure_ascii=False),
                            text=True,capture_output=True,timeout=30)
        output=json.loads(proc.stdout)
    except (subprocess.TimeoutExpired,json.JSONDecodeError):
        raise HTTPException(503,'Không thực hiện được thao tác. Chưa có dữ liệu nào được ghi; vui lòng thử lại.')
    if not output['ok']:raise HTTPException(422,output.get('error','Lỗi nghiệp vụ.'))
    result=output.get('result')
    failed=isinstance(result,dict) and result.get('success') is False
    if writing and not failed:
        uploaded=[]
        try:
            replacements={}
            for file in output.get('uploads',[]):
                created=google_drive.upload(db,user,file['name'],file['mime'],base64.b64decode(file['base64'],validate=True))
                uploaded.append(created['id']);replacements[file['placeholder']]=created['url']
            def replace_files(v):
                if isinstance(v,str):return replacements.get(v,v)
                if isinstance(v,list):return [replace_files(x) for x in v]
                if isinstance(v,dict):return {k:replace_files(x) for k,x in v.items()}
                return v
            output['changed']=replace_files(output.get('changed',[]))
            return commit_write(db,user,state,method,request_id,checksum,books,output,result,uploaded)
        except Exception:
            db.rollback()
            for identifier in uploaded:
                try:google_drive.undo_upload(db,user,identifier)
                except Exception:logging.warning('Check the file created by failed transaction: %s',identifier)
            raise
    elif output.get('changed'):
        raise HTTPException(422,'Một thao tác đọc đã yêu cầu ghi dữ liệu; giao dịch bị chặn.')
    if isinstance(result,str) and ('<html' in result.lower() or '<!doctype' in result.lower()):result=inject(result,state.revision)
    return {'result':result,'revision':state.revision}


def commit_write(db,user,state,method,request_id,checksum,books,output,result,uploaded):
    old={(b['id'],s['name']):s['values'] for b in books for s in b['sheets']}
    touched=[]
    ordered=sorted(output.get('changed',[]),key=lambda x:list(SPECS).index(next((k for k in SPECS if NAMES[k]==x['name']),list(SPECS)[-1])))
    for change in ordered:
        key=next((k for k,(_,group,_) in SPECS.items()
                  if change['book']==CONFIG['ID_'+group.upper()] and change['name'] in [NAMES[k],NAMES.get(k+'_LEGACY')]),None)
        if key is None:raise HTTPException(422,'Bảng '+change['name']+' chưa có ánh xạ ghi MySQL; giao dịch đã hủy.')
        ids=rows_to_models(db,key,change['values'],old.get((change['book'],change['name'])))
        touched.append({'table':key,'ids':ids})
    state.properties=output['properties'];state.metadata_entries=output['metadata']
    state.cell_notes=persistent_notes(books,output['notes'],output.get('changed',[]))
    state.revision+=1
    db.add(Audit(user_id=user.id,action='LEGACY_'+method,entity_id='',details={'changed':touched,'revision':state.revision}))
    db.add(LegacyRequest(id=request_id,user_id=user.id,payload_hash=checksum,result=result if isinstance(result,dict) else {'value':result}))
    # In a lost commit acknowledgement, keep Drive files for reconciliation.
    # Do not trash a file that might already belong to a committed order.
    try:db.commit()
    except Exception:
        for identifier in uploaded:logging.warning('MySQL commit outcome uncertain; retain Drive file %s',identifier)
        uploaded.clear()
        raise
    return {'result':result,'revision':state.revision}

class RPC(BaseModel):
    args:list=Field(default_factory=list,max_length=10)
    revision:int|None=None
    request_id:str=Field(min_length=16,max_length=64)


@router.post('/api/legacy/{method}')
def rpc(method:str,payload:RPC,request:Request,user=Depends(current_user),db=Depends(get_db)):
    if method not in READ_METHODS|WRITE_METHODS:raise HTTPException(404,'Chức năng không tồn tại.')
    return execute(db,user,request,method=method,args=payload.args,revision=payload.revision,request_id=payload.request_id)


def legacy_page(request,db):
    try:user=current_user(request,db)
    except HTTPException:
        return RedirectResponse('/login?next='+request.url.path+'%3F'+request.url.query,status_code=303)
    params=dict(request.query_params)
    if params.get('view','index') not in VIEWS:raise HTTPException(404,'Màn hình không tồn tại.')
    return HTMLResponse(execute(db,user,request,render=True,params=params)['result'])
