"""Independent MySQL worker. Run: python -m app.modules.qc.worker."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import logging
import os
import signal
import threading
import time
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, or_, and_, text, update
from app.core import model_registry
from app.core.database import Session, engine
from app.core.performance import trace, measure
from app.auth.models import User
from app.integrations.google.models import GoogleCredential
from app.integrations.google.oauth import access_token
from app.modules.qc.job_models import QCJob
from app.modules.qc.models import QualityCheck
from app.modules.qc import jobs, drive_bundle, mapping
from app.modules.qc.schemas import UploadInput

LOG=logging.getLogger('uvicorn.error')
MAX_ATTEMPTS=3
LEASE_SECONDS=180
STOP=threading.Event()


def claim(db):
    now=jobs.stamp()
    # A crashed last attempt must become visible as FAILED, not stay PROCESSING forever.
    db.execute(update(QCJob).where(QCJob.status=='PROCESSING',QCJob.lease_until<now,QCJob.attempts>=MAX_ATTEMPTS)
        .values(status='FAILED',last_error='Worker dừng ở lần thử cuối; cần kiểm tra và thử lại.',updated_at=now,lease_until=None,lease_token=None))
    row=db.scalar(select(QCJob).where(QCJob.qc_id.is_not(None),QCJob.attempts<MAX_ATTEMPTS,
        or_(and_(QCJob.status=='PENDING',QCJob.available_at<=now),and_(QCJob.status=='PROCESSING',QCJob.lease_until<now)))
        .order_by(QCJob.available_at,QCJob.id).with_for_update(skip_locked=True).limit(1))
    if not row:db.commit();return None
    row.status='PROCESSING';row.attempts+=1;row.lease_token=str(uuid4())
    row.lease_until=now+timedelta(seconds=LEASE_SECONDS);row.updated_at=now;db.commit()
    return row.id,row.lease_token


def checkpoint(identifier,token,step=None,manifest=None):
    from pathlib import Path
    Path('/tmp/qc-worker-heartbeat').touch()
    with Session() as db:
        row=db.scalar(select(QCJob).where(QCJob.id==identifier).with_for_update())
        if not row or row.status!='PROCESSING' or row.lease_token!=token or row.lease_until<jobs.stamp():
            raise RuntimeError('QC_LEASE_LOST')
        if step:row.current_step=step
        if manifest is not None:row.manifest=deepcopy(manifest)
        row.lease_until=jobs.stamp()+timedelta(seconds=LEASE_SECONDS);row.updated_at=jobs.stamp();db.commit()


def heartbeat(identifier,token,done,lost):
    while not done.wait(20):
        try:checkpoint(identifier,token)
        except Exception:lost.set();return


def verify_remote(db,user,obj,manifest,check):
    token=access_token(db,user);db.commit()
    check('verify_drive')
    drive_bundle.in_scope(db,token,obj.drive_folder_id,writable=True)
    state=(obj.source or {}).get(drive_bundle.JOB,{})
    if obj.form_data:
        if state.get('pending') or not state.get('pdf_revision'):raise HTTPException(502,'PDF chưa hoàn tất.')
        pdf=drive_bundle.call(token,'/'+state['pdf_id'],fields='id,mimeType,parents,trashed,size')
        if pdf.get('trashed') or pdf.get('mimeType')!='application/pdf' or obj.drive_folder_id not in pdf.get('parents',[]) or int(pdf.get('size',0))<1000:
            raise HTTPException(502,'PDF thiếu, rỗng hoặc sai thư mục. Chưa hoàn tất hồ sơ.')
    for file in manifest:
        check('verify_evidence')
        key=drive_bundle.upload_key(obj.id,UploadInput(**{k:file[k] for k in ('name','size','mime','modified')}))
        found=drive_bundle.call(token,q=f"'{obj.drive_folder_id}' in parents and trashed=false and appProperties has {{ key='qc_upload' and value='{key}' }}",fields='files(id,size,parents,trashed)',pageSize=2,includeItemsFromAllDrives='true').get('files',[])
        if len(found)!=1 or int(found[0].get('size',-1))!=file['size']:
            raise HTTPException(502,'Bằng chứng chưa đủ hoặc bị trùng trên Drive. Chưa hoàn tất hồ sơ.')
        file['drive_id']=found[0]['id'];file['done']=True


def run_job(identifier,lease):
    done,lost=threading.Event(),threading.Event()
    thread=threading.Thread(target=heartbeat,args=(identifier,lease,done,lost),daemon=True);thread.start()
    operations=[];failure=None
    try:
        with trace('qc.worker.total') as operations, Session() as db, engine.connect() as guard:
            row=db.get(QCJob,identifier);qc_id=row.qc_id;files=deepcopy(row.manifest)
            lock_name='qc-worker:'+hashlib.sha256(qc_id.encode()).hexdigest()[:48]
            if guard.execute(text('SELECT GET_LOCK(:name,0)'),{'name':lock_name}).scalar()!=1:
                raise HTTPException(503,'Hồ sơ đang được worker khác xử lý.')
            try:
                def check(step):
                    if lost.is_set():raise RuntimeError('QC_LEASE_LOST')
                    if STOP.is_set():raise HTTPException(503,'Worker dừng tại checkpoint an toàn; sẽ tiếp tục khi khởi động lại.')
                    checkpoint(identifier,lease,step)
                check('validate')
                user=db.get(User,row.owner_id);credential=db.get(GoogleCredential,row.owner_id)
                if not user or not user.active:raise HTTPException(403,'Tài khoản ERP của job đã ngừng hoạt động.')
                from app.modules.qc.api import allowed
                allowed(db,user,'QC_CREATE','QC_EDIT')
                if not credential or credential.subject!=row.google_subject:
                    raise HTTPException(403,'Cần kết nối lại đúng tài khoản Google của chủ job.')
                obj=db.get(QualityCheck,qc_id)
                if mapping.digest(obj.form_data)!=row.revision:raise HTTPException(409,'Nội dung QC khác phiên bản job. Cần kiểm tra hồ sơ.')
                check('folder_pdf')
                obj=drive_bundle.prepare(db,user,qc_id,progress=check)
                state=(obj.source or {}).get(drive_bundle.JOB,{})
                if state.get('pending'):raise HTTPException(state.get('error_status',502),state.get('error') or 'Chưa hoàn tất PDF.')
                for index,file in enumerate(files):
                    check('upload_evidence_'+str(index+1))
                    if file.get('done'):continue
                    path=jobs.file_path(file['stage'],file['id'])
                    if not path.is_file():raise HTTPException(422,'File staging bị mất hoặc hết hạn. Cần chọn lại bằng chứng.')
                    with path.open('rb') as inp:
                        if hashlib.file_digest(inp,'sha256').hexdigest()!=file['sha256']:
                            raise HTTPException(422,'Checksum staging không khớp. Không upload file lỗi.')
                    data=UploadInput(**{k:file[k] for k in ('name','size','mime','modified')})
                    with measure('qc.worker.upload_file',file_index=index+1,bytes=file['size']):
                        if file.get('ticket'):
                            try:result=drive_bundle.upload_chunk(db,user,obj,file['ticket'],0,b'',True)
                            except HTTPException as error:
                                if error.status_code not in (410,422):raise
                                file.pop('ticket',None);result=None
                        else:result=None
                        if result is None:
                            # Allocate once and checkpoint before the remote upload begins.
                            if not file.get('allocated_id'):
                                file['allocated_id']=drive_bundle.generated_id(access_token(db,user));db.commit()
                                checkpoint(identifier,lease,manifest=files)
                            result=drive_bundle.start_upload(db,user,obj,data,file_id=file['allocated_id'])
                            if result.get('ticket'):file['ticket']=result['ticket']
                            checkpoint(identifier,lease,manifest=files)
                        offset=result['offset']
                        with path.open('rb') as inp:
                            while not result['complete']:
                                check('upload_evidence_'+str(index+1));inp.seek(offset)
                                chunk=inp.read(drive_bundle.CHUNK_SIZE)
                                if not chunk:raise HTTPException(502,'Phiên upload chưa xác nhận đủ dữ liệu; cần đối soát lại.')
                                result=drive_bundle.upload_chunk(db,user,obj,file['ticket'],offset,chunk)
                                if not result['complete'] and result['offset']<=offset:raise HTTPException(502,'Drive chưa nhận thêm dữ liệu.')
                                offset=result['offset'];file['drive_offset']=offset
                                checkpoint(identifier,lease,manifest=files)
                        file['done']=True;file.pop('ticket',None);checkpoint(identifier,lease,manifest=files)
                verify_remote(db,user,obj,files,check)
                checkpoint(identifier,lease,'verified',files)
            finally:
                guard.execute(text('SELECT RELEASE_LOCK(:name)'),{'name':lock_name});guard.commit()
    except Exception as error:
        failure=error
        LOG.error('QC_WORKER_ERROR job=%s type=%s',identifier,type(error).__name__)
    finally:
        done.set();thread.join(timeout=2)
    with Session() as db:
        row=db.scalar(select(QCJob).where(QCJob.id==identifier).with_for_update())
        if not row or row.lease_token!=lease or row.status!='PROCESSING':return
        history=list((row.metrics or {}).get('runs',[]))[-9:]
        requests=sum(1 for op in operations if op['operation']=='google.http_request')
        history.append({'attempt':row.attempts,'google_requests':requests,'operations':operations})
        row.metrics={**(row.metrics or {}),'runs':history,
            'google_requests_total':(row.metrics or {}).get('google_requests_total',0)+requests,
            'runs_total':(row.metrics or {}).get('runs_total',0)+1}
        row.updated_at=jobs.stamp();row.lease_until=row.lease_token=None
        if failure:
            row.last_error=str(failure.detail)[:2000] if isinstance(failure,HTTPException) else 'Lỗi worker nội bộ; xem QC_WORKER_ERROR trong log.'
            transient=not isinstance(failure,HTTPException) or failure.status_code in {429,500,502,503,504}
            row.status='PENDING' if transient and row.attempts<MAX_ATTEMPTS else 'FAILED'
            row.available_at=jobs.stamp()+timedelta(seconds=min(60,10*row.attempts))
        else:
            row.status='COMPLETED';row.current_step='complete';row.last_error=''
            accepted=(row.metrics or {}).get('accepted_at')
            if accepted:row.metrics={**row.metrics,'accepted_to_completed_ms':round((jobs.stamp()-jobs.datetime.fromisoformat(accepted)).total_seconds()*1000,3)}
            # Keep manifest identities for reconciliation; remove bytes only after verification.
            for file in row.manifest:
                jobs.file_path(file['stage'],file['id']).unlink(missing_ok=True)
            row.manifest=[{**f,'cleaned':True} for f in row.manifest]
        db.commit()


def main():
    logging.basicConfig(level=logging.INFO)
    ROOT=jobs.ROOT;ROOT.mkdir(parents=True,exist_ok=True)
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
    LOG.info('QC_WORKER_STARTED staging=single-host lease_seconds=%s',LEASE_SECONDS)
    sweep=0
    while not STOP.is_set():
        try:
            from pathlib import Path
            Path('/tmp/qc-worker-heartbeat').touch()
            with Session() as db:
                claimed=claim(db)
            if claimed:run_job(*claimed)
            else:STOP.wait(2)
            if time.monotonic()>sweep:
                with Session() as db:jobs.clean_expired(db)
                sweep=time.monotonic()+300
        except Exception as error:
            LOG.error('QC_WORKER_LOOP_ERROR type=%s',type(error).__name__);STOP.wait(5)
    LOG.info('QC_WORKER_STOPPED')


if __name__=='__main__':main()
