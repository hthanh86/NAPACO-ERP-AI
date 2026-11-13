"""Durable file reception and atomic QC enqueue on the single Docker host."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4, UUID
import hashlib
import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from starlette.concurrency import run_in_threadpool
from app.auth.models import User
from app.auth.security import current_user, require
from app.core.database import get_db
from app.core.performance import measure
from app.integrations.google.models import GoogleCredential
from app.modules.qc.job_models import QCJob
from app.modules.qc.schemas import UploadInput
from app.modules.qc import mapping

router=APIRouter()
ROOT=Path(os.environ.get('QC_STAGING_PATH','/var/lib/napaco/qc-staging'))
CHUNK=4*1024*1024
MAX_FILE=int(os.environ.get('QC_MAX_FILE_BYTES',str(5*1024**3)))
MAX_OWNER=int(os.environ.get('QC_STAGING_QUOTA_BYTES',str(20*1024**3)))


def stamp():return datetime.utcnow()


def file_path(stage, identifier):
    # Both path components are generated UUIDs, never client filenames.
    try:return ROOT/str(UUID(stage))/str(UUID(identifier))
    except (ValueError,TypeError):raise HTTPException(422,'Tham chiếu staging không hợp lệ.') from None


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def owned(db,user,identifier,lock=True):
    statement=select(QCJob).where(QCJob.id==identifier)
    row=db.scalar(statement.with_for_update() if lock else statement)
    if row is None or row.owner_id!=user.id:raise HTTPException(404,'Không tìm thấy staging của tài khoản này.')
    return row


def public_stage(row):
    return {'id':row.id,'status':row.status,'files':[{k:f.get(k) for k in ('id','name','size','modified','mime','offset','ready')} for f in row.manifest]}


class StageInput(BaseModel):
    files:list[UploadInput]=Field(max_length=500)


@router.post('/api/qc/staging',status_code=201)
def start_stage(data:StageInput,user=Depends(current_user),db=Depends(get_db)):
    from app.modules.qc.api import allowed
    allowed(db,user,'QC_CREATE','QC_EDIT')
    if any(f.size>MAX_FILE for f in data.files):raise HTTPException(413,'File vượt giới hạn staging cấu hình (mặc định 5 GiB/file).')
    if len({(f.name,f.size,f.modified) for f in data.files})!=len(data.files):raise HTTPException(422,'Không chọn trùng một file bằng chứng trong cùng hồ sơ.')
    # Serialize reservation checks per user, so parallel tabs cannot exceed quota.
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    reservations=db.scalars(select(QCJob).where(QCJob.owner_id==user.id,QCJob.status.in_(['STAGING','PENDING','PROCESSING','FAILED','ATTACHED']))).all()
    reserved={(f['stage'],f['id']):f['size'] for job in reservations for f in job.manifest
        if not f.get('cleaned') and (job.status!='ATTACHED' or file_path(f['stage'],f['id']).is_file())}
    used=sum(reserved.values())
    if used+sum(f.size for f in data.files)>MAX_OWNER:raise HTTPException(413,'Đã vượt hạn mức staging. Hoàn tất hồ sơ hoặc chờ dọn file hết hạn.')
    row=QCJob(id=str(uuid4()),owner_id=user.id,status='STAGING',manifest=[])
    directory=ROOT/row.id;directory.mkdir(parents=True,mode=0o700)
    sync_dir(ROOT)
    files=[]
    for item in data.files:
        file={**item.model_dump(),'id':str(uuid4()),'stage':row.id,'offset':0,'ready':item.size==0}
        path=file_path(row.id,file['id'])
        with path.open('xb') as out:out.flush();os.fsync(out.fileno())
        if item.size==0:file['sha256']=hashlib.sha256(b'').hexdigest()
        files.append(file)
    sync_dir(directory);row.manifest=files;db.add(row);db.commit()
    return public_stage(row)


@router.get('/api/qc/staging/{identifier}')
def stage_status(identifier:str,user=Depends(current_user),db=Depends(get_db)):
    return public_stage(owned(db,user,identifier,False))


@measure('qc.staging.write')
def write_chunk(db,user,identifier,file_id,offset,content):
    row=owned(db,user,identifier)
    if row.status!='STAGING':raise HTTPException(409,'Staging đã gắn hồ sơ hoặc hết hạn; không được sửa.')
    files=deepcopy(row.manifest);file=next((f for f in files if f['id']==file_id),None)
    if not file:raise HTTPException(404,'Không tìm thấy file staging.')
    if offset!=file['offset']:
        db.rollback();return {'offset':file['offset'],'ready':file['ready']}
    if not content or offset+len(content)>file['size']:raise HTTPException(422,'Độ dài khối staging không hợp lệ.')
    path=file_path(file['stage'],file['id'])
    with path.open('r+b') as out:
        if os.fstat(out.fileno()).st_size<offset:raise HTTPException(409,'File staging bị thiếu dữ liệu; cần chọn lại file.')
        out.truncate(offset);out.seek(offset);out.write(content);out.flush();os.fsync(out.fileno())
    file['offset']=offset+len(content);file['ready']=file['offset']==file['size']
    if file['ready']:
        with path.open('rb') as inp:file['sha256']=hashlib.file_digest(inp,'sha256').hexdigest()
    row.manifest=files;row.updated_at=stamp();db.commit()
    return {'offset':file['offset'],'ready':file['ready']}


@router.put('/api/qc/staging/{identifier}/{file_id}')
async def stage_chunk(identifier:str,file_id:str,request:Request,offset:int=Query(ge=0),user=Depends(current_user),db=Depends(get_db)):
    content=bytearray()
    async for piece in request.stream():
        content.extend(piece)
        if len(content)>CHUNK:raise HTTPException(413,'Mỗi khối staging tối đa 4 MiB.')
    return await run_in_threadpool(write_chunk,db,user,identifier,file_id,offset,bytes(content))


@router.delete('/api/qc/staging/{identifier}/{file_id}')
def remove_staged(identifier:str,file_id:str,user=Depends(current_user),db=Depends(get_db)):
    row=owned(db,user,identifier)
    if row.status!='STAGING':raise HTTPException(409,'Không được bỏ file của hồ sơ đã tiếp nhận.')
    row.manifest=[f for f in row.manifest if f['id']!=file_id];row.updated_at=stamp();db.commit()
    file_path(identifier,file_id).unlink(missing_ok=True)
    return public_stage(row)


def enqueue(db,user,obj,staging_id=None,expected=()):
    """Called before the QC transaction commits; staging and QC are bound atomically."""
    from app.modules.qc.drive_bundle import JOB
    credential=db.get(GoogleCredential,user.id)
    if not credential or not credential.encrypted_refresh:
        raise HTTPException(403,'Cần kết nối Google có quyền truy cập ngoại tuyến trước khi lưu hồ sơ nền.')
    stage=owned(db,user,staging_id) if staging_id else None
    if stage and stage.status!='STAGING':raise HTTPException(409,'Staging đã được sử dụng; mở lại hồ sơ để kiểm tra.')
    files=deepcopy(stage.manifest if stage else [])
    if any(not f.get('ready') or not file_path(f['stage'],f['id']).is_file() or file_path(f['stage'],f['id']).stat().st_size!=f['size'] for f in files):
        raise HTTPException(409,'Bằng chứng chưa được tiếp nhận an toàn. Hãy chờ staging hoàn tất hoặc chọn lại file.')
    actual=sorted((f['name'],f['size'],f['modified'],f['mime']) for f in files)
    declared=sorted((f.name,f.size,f.modified,f.mime) for f in expected)
    if actual!=declared:raise HTTPException(409,'Danh sách bằng chứng không khớp staging đã nhận.')
    row=db.scalar(select(QCJob).where(QCJob.qc_id==obj.id).with_for_update())
    if row and row.status=='PROCESSING':raise HTTPException(409,'Worker đang xử lý hồ sơ. Hãy chờ hoàn tất trước khi sửa hoặc bổ sung.')
    if row:
        merged=deepcopy(row.manifest)
        keys={(f['name'],f['size'],f['modified']):index for index,f in enumerate(merged)}
        for file in files:
            key=(file['name'],file['size'],file['modified'])
            if key in keys:merged[keys[key]]=file
            else:merged.append(file)
        row.manifest=merged
        if stage:
            stage.status='ATTACHED';stage.metrics={'target':row.id};stage.updated_at=stamp()
    else:
        row=stage or QCJob(id=str(uuid4()),owner_id=user.id,manifest=[])
        row.qc_id=obj.id;row.manifest=files;db.add(row)
    row.owner_id=user.id;row.status='PENDING';row.current_step='queued';row.attempts=0
    row.metrics={**(row.metrics or {}),'accepted_at':stamp().isoformat(),
        'staging_ms':round((stage.updated_at-stage.created_at).total_seconds()*1000,3) if stage else 0}
    row.last_error='';row.available_at=row.updated_at=stamp();row.lease_until=row.lease_token=None
    # MySQL's binary JSON can round floating-point signature coordinates by an
    # ULP. The worker must compare against the persisted representation.
    db.flush()
    db.refresh(obj,attribute_names=['form_data'])
    row.revision=mapping.digest(obj.form_data)
    row.google_subject=credential.subject
    # Sync metadata uses stable Drive keys; existing completed uploads remain intact.
    job=dict((obj.source or {}).get(JOB,{ }));job['owner']=user.id
    obj.source={**(obj.source or {}),JOB:job}
    return row


def job_record(row):
    return {'status':row.status,'step':row.current_step,'attempts':row.attempts,'error':row.last_error,
            'updated_at':row.updated_at.isoformat(),'metrics':row.metrics}


@router.post('/api/qc/{identifier}/retry-sync')
def retry(identifier:str,user=Depends(current_user),db=Depends(get_db)):
    from app.modules.qc.api import writable_record
    obj=writable_record(db,user,identifier)
    row=db.scalar(select(QCJob).where(QCJob.qc_id==identifier).with_for_update())
    if not row:raise HTTPException(409,'Phiếu cũ chưa có job nền. Dùng chức năng bổ sung bằng chứng để tiếp nhận.')
    if row.status not in {'FAILED','PENDING'}:raise HTTPException(409,'Chỉ thử lại job chờ hoặc lỗi.')
    if row.revision!=mapping.digest(obj.form_data):
        repair_json_revision(db,user,obj,row)
    credential=db.get(GoogleCredential,row.owner_id)
    if not credential or credential.subject!=row.google_subject:raise HTTPException(403,'Kết nối lại đúng tài khoản Google của chủ job trước khi thử lại.')
    if any(not f.get('done') and not file_path(f['stage'],f['id']).is_file() for f in row.manifest):
        raise HTTPException(409,'File staging đã hết hạn hoặc bị mất. Hãy chọn lại các bằng chứng chưa hoàn tất.')
    row.status='PENDING';row.attempts=0;row.available_at=row.updated_at=stamp();row.last_error='';db.commit()
    return job_record(row)


def repair_json_revision(db,user,obj,row):
    """Repair old false mismatches only if the original acceptance snapshot agrees."""
    from app.compatibility.models import LegacyRequest
    from app.core.models import Audit
    if row.status!='FAILED' or row.current_step!='validate' or row.last_error!='Nội dung QC khác phiên bản job. Cần kiểm tra hồ sơ.':
        raise HTTPException(409,'Nội dung QC khác job. Không tự cập nhật phiên bản; cần kiểm tra hồ sơ.')
    requests=db.scalars(select(LegacyRequest).where(LegacyRequest.user_id==obj.staff_id,
        func.json_search(LegacyRequest.result,'one',obj.id).is_not(None)).limit(20)).all()
    snapshots=[item for request in requests for item in (request.result.get('items') or [request.result]) if item.get('id')==obj.id]
    if not any(item.get('form_data')==obj.form_data and item.get('template_id')==obj.template_id for item in snapshots):
        raise HTTPException(409,'Không khớp bản tiếp nhận ban đầu. Không tự sửa phiên bản job; cần quản lý kiểm tra.')
    previous=row.revision;row.revision=mapping.digest(obj.form_data)
    row.metrics={**(row.metrics or {}),'revision_repair':'mysql_json_roundtrip'}
    db.add(Audit(user_id=user.id,action='QC_JOB_REVISION_REPAIR',entity_id=obj.id,
        details={'previous_revision':previous,'revision':row.revision,'reason':'mysql_json_roundtrip'}))


class Supplement(BaseModel):
    staging_id:str
    files:list[UploadInput]=Field(max_length=500)
    parent_folder_id:str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,255}$')


@router.post('/api/qc/{identifier}/queue-evidence')
def supplement(identifier:str,data:Supplement,user=Depends(current_user),db=Depends(get_db)):
    from app.modules.qc.api import writable_record
    from app.modules.qc import drive_bundle,service
    obj=writable_record(db,user,identifier)
    if not obj.drive_folder_id and not data.parent_folder_id:raise HTTPException(422,'Hãy chọn thư mục cha trong vùng QC.')
    drive_bundle.schedule(obj,user,data.parent_folder_id,data.files)
    enqueue(db,user,obj,data.staging_id,data.files);db.commit()
    return service.detail_record(db,obj)


def clean_expired(db):
    """Bounded housekeeping. Pending/processing jobs are never aged out."""
    old=stamp()-timedelta(hours=24)
    rows=db.scalars(select(QCJob).where(QCJob.status=='STAGING',QCJob.updated_at<old).with_for_update(skip_locked=True).limit(20)).all()
    for row in rows:
        shutil.rmtree(ROOT/str(UUID(row.id)),ignore_errors=True);row.status='EXPIRED';row.updated_at=stamp()
    failed=db.scalars(select(QCJob).where(QCJob.status=='FAILED',QCJob.updated_at<stamp()-timedelta(days=7)).with_for_update(skip_locked=True).limit(20)).all()
    for row in failed:
        files=deepcopy(row.manifest)
        for file in files:
            file_path(file['stage'],file['id']).unlink(missing_ok=True);file['cleaned']=True
        row.manifest=files
    attached=db.scalars(select(QCJob).where(QCJob.status=='ATTACHED',QCJob.updated_at<old).with_for_update(skip_locked=True).limit(20)).all()
    for row in attached:
        target=db.get(QCJob,(row.metrics or {}).get('target'))
        needed={(f['stage'],f['id']) for f in (target.manifest if target else []) if not f.get('cleaned')}
        for file in row.manifest:
            if (file['stage'],file['id']) not in needed:file_path(file['stage'],file['id']).unlink(missing_ok=True)
        if not any(f['stage']==row.id for f in (target.manifest if target else []) if not f.get('cleaned')):row.status='EXPIRED'
    # A failed DB commit during stage creation can leave an unreferenced directory.
    directories=[p for p in ROOT.iterdir() if p.is_dir() and p.stat().st_mtime<old.timestamp()][:100]
    known=set(db.scalars(select(QCJob.id).where(QCJob.id.in_([p.name for p in directories]))))
    for path in directories:
        try:UUID(path.name)
        except ValueError:continue
        if path.name not in known:shutil.rmtree(path,ignore_errors=True)
    db.commit()
