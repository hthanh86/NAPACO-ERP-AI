"""Durable staging, atomic queue, resolver and independent worker; no real Google writes."""
from copy import deepcopy
from datetime import datetime,timedelta
from uuid import uuid4
from contextlib import contextmanager
import hashlib
import pytest
from fastapi import HTTPException
from sqlalchemy import select,update,delete
from sqlalchemy.orm import Session as OrmSession
from app.main import app
from app.core.database import get_db,Session,engine
from app.modules.qc import jobs,worker,mapping,drive_bundle,template_runtime
from app.modules.qc.job_models import QCJob
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate
from app.auth.models import User
from test_qc_mapping import stage,nvl,qc_payload,create


@contextmanager
def scope():
    provider=app.dependency_overrides[get_db]();db=next(provider)
    try:yield db
    finally:provider.close()


def receive(admin,size=100):
    files=[{'name':'evidence-video.mp4','size':size,'modified':123,'mime':'video/mp4'}]
    response=admin.post('/api/qc/staging',json={'files':files});assert response.status_code==201,response.text
    staged=response.json();path='/api/qc/staging/'+staged['id']+'/'+staged['files'][0]['id']
    for offset in range(0,size,jobs.CHUNK):
        response=admin.put(path+'?offset='+str(offset),content=b'x'*min(jobs.CHUNK,size-offset))
        assert response.status_code==200,response.text
    return staged,files


def test_one_template_priority_conflict_and_history(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch)
    with scope() as db:
        common=db.get(QCTemplate,row['id'])
        assert template_runtime.resolve_template(db,'QC NVL','NVL',set()).id==common.id
        clone=QCTemplate(id=str(uuid4()),form_code='QA_CONFLICT_'+uuid4().hex,form_name='Conflict',check_type='QC NVL',
            spreadsheet_id='qa-sheet',sheet_id=42,version=2,status='ACTIVE',created_by='_TEST_ADMIN',approved_at=datetime.utcnow(),
            source_matches=True,source_hash=common.source_hash,source_snapshot=common.source_snapshot,field_mapping=common.field_mapping)
        db.add(clone);db.flush()
        with pytest.raises(HTTPException,match='409'):template_runtime.resolve_template(db,'QC NVL','NVL',set())
        clone.status='INACTIVE';common.check_type='QC GIỮA CA';common.object_type=None;db.flush()
        specific=QCTemplate(id=str(uuid4()),form_code='QA_PRODUCT_'+uuid4().hex,form_name='Specific',check_type=common.check_type,
            product_id='_TEST_P1',spreadsheet_id='qa-product-sheet',sheet_id=42,version=1,status='ACTIVE',created_by='_TEST_ADMIN',
            approved_at=datetime.utcnow(),source_matches=True)
        db.add(specific);db.flush()
        assert template_runtime.resolve_template(db,common.check_type,'HUT',{'_TEST_P1'}).id==specific.id
        assert template_runtime.resolve_template(db,common.check_type,'HUT',{'_TEST_P2'}).id==common.id
        with pytest.raises(HTTPException):template_runtime.resolve_template(db,common.check_type,'HUT',{'_TEST_P1','_TEST_P2'})


def test_durable_video_chunks_resume_and_ownership(clients):
    admin,reader,_=clients
    staged,files=receive(admin,jobs.CHUNK*2+17)
    assert reader.get('/api/qc/staging/'+staged['id']).status_code==404
    info=admin.get('/api/qc/staging/'+staged['id']).json()['files'][0]
    assert info['ready'] and info['offset']==files[0]['size']
    # A replayed/lost-response chunk does not append duplicate bytes.
    response=admin.put('/api/qc/staging/'+staged['id']+'/'+info['id']+'?offset=0',content=b'x')
    assert response.json()['offset']==files[0]['size']
    with scope() as db:
        row=db.get(QCJob,staged['id']);file=row.manifest[0]
        assert jobs.file_path(file['stage'],file['id']).stat().st_size==files[0]['size']
        with jobs.file_path(file['stage'],file['id']).open('rb') as inp:assert hashlib.file_digest(inp,'sha256').hexdigest()==file['sha256']


def test_atomic_reception_returns_qc_without_google_work(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);obj=nvl(conn)
    data=qc_payload(row,obj);staged,files=receive(admin)
    data.update(staging_id=staged['id'],evidence_manifest=files)
    monkeypatch.setattr(drive_bundle,'prepare',lambda *a,**k:pytest.fail('HTTP must not perform Drive work'))
    monkeypatch.setattr(drive_bundle,'in_scope',lambda *a,**k:pytest.fail('Reception must not call Drive'))
    result=create(admin,data);assert result.status_code==201,result.text
    saved=result.json();assert saved['sync']['status']=='PENDING' and saved['drive_folder_id'] is None
    with scope() as db:
        job=db.get(QCJob,staged['id']);assert job.qc_id==saved['id'] and job.manifest[0]['ready']
    assert admin.delete('/api/qc/staging/'+staged['id']+'/'+staged['files'][0]['id']).status_code==409
    assert admin.post('/api/qc/'+saved['id']+'/uploads',json=files[0]).status_code==409


def test_unfinished_stage_does_not_create_qc(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);obj=nvl(conn);data=qc_payload(row,obj)
    file={'name':'waiting.jpg','size':100,'modified':1,'mime':'image/jpeg'}
    result=admin.post('/api/qc/staging',json={'files':[file]}).json()
    data.update(staging_id=result['id'],evidence_manifest=[file])
    assert create(admin,data).status_code==409
    with scope() as db:
        assert db.get(QCJob,result['id']).qc_id is None
        assert not db.scalar(select(QualityCheck.id).where(QualityCheck.object_id==obj['object_id']))


def test_worker_completion_without_browser_and_bounded_retry(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);obj=nvl(conn);data=qc_payload(row,obj)
    staged,files=receive(admin,jobs.CHUNK+19);data.update(staging_id=staged['id'],evidence_manifest=files)
    result=create(admin,data);assert result.status_code==201,result.text
    identifier=result.json()['id']
    monkeypatch.setattr(worker,'Session',lambda:OrmSession(bind=conn,expire_on_commit=False,join_transaction_mode='create_savepoint'))
    monkeypatch.setattr(worker,'access_token',lambda *a:'mock-only')
    monkeypatch.setattr(drive_bundle,'access_token',lambda *a:'mock-only')
    monkeypatch.setattr(drive_bundle,'generated_id',lambda *a:'mock-file-id')
    calls=[]
    def prepare(db,user,identifier,progress=None):
        obj=db.get(QualityCheck,identifier);obj.drive_folder_id='mock-folder'
        obj.source={**obj.source,drive_bundle.JOB:{**obj.source[drive_bundle.JOB],'pending':False}}
        db.commit();return obj
    monkeypatch.setattr(drive_bundle,'prepare',prepare)
    # First attempt fails persistently; no browser retry is involved.
    monkeypatch.setattr(drive_bundle,'prepare',lambda *a,**k:(_ for _ in ()).throw(HTTPException(502,'mock interruption')))
    with worker.Session() as db:claimed=worker.claim(db)
    worker.run_job(*claimed)
    with worker.Session() as db:
        job=db.get(QCJob,staged['id']);assert job.status=='PENDING' and job.attempts==1
        job.available_at=datetime(2000,1,1);db.commit()
    monkeypatch.setattr(drive_bundle,'prepare',prepare)
    monkeypatch.setattr(drive_bundle,'start_upload',lambda *a,**k:{'complete':False,'offset':0,'ticket':'mock-ticket'})
    def chunk(db,user,obj,ticket,offset,content,probe=False):
        calls.append((offset,len(content)));return {'complete':offset+len(content)==files[0]['size'],'offset':offset+len(content)}
    monkeypatch.setattr(drive_bundle,'upload_chunk',chunk)
    def verified(db,user,obj,manifest,check):
        for file in manifest:file['done']=True;file['drive_id']='mock-file-id'
    monkeypatch.setattr(worker,'verify_remote',verified)
    with worker.Session() as db:claimed=worker.claim(db)
    # No further HTTP request or tab exists in the workflow from this point.
    worker.run_job(*claimed)
    with worker.Session() as db:
        job=db.get(QCJob,staged['id']);assert job.status=='COMPLETED' and job.attempts==2
        assert job.manifest[0]['cleaned'] and len(calls)==2
        assert not jobs.file_path(job.manifest[0]['stage'],job.manifest[0]['id']).exists()
        job.status='PROCESSING';job.attempts=3;job.lease_until=datetime(2000,1,1);db.commit()
        assert worker.claim(db) is None
        assert db.get(QCJob,staged['id']).status=='FAILED'


def test_expired_lease_is_reclaimed_with_new_fencing_token(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);data=qc_payload(row,nvl(conn))
    response=create(admin,data);assert response.status_code==201,response.text
    with scope() as db:
        first=worker.claim(db);assert first
        job=db.get(QCJob,first[0]);job.lease_until=datetime(2000,1,1);db.commit()
        second=worker.claim(db);assert second[0]==first[0] and second[1]!=first[1]
        assert db.get(QCJob,first[0]).attempts==2


def test_new_qc_rejects_legacy_form(clients):
    from test_qc import payload
    admin,_,_=clients
    response=admin.post('/api/qc',headers={'Idempotency-Key':str(uuid4())},json=payload())
    assert response.status_code==422


def test_worker_refuses_different_google_account(clients,monkeypatch):
    from app.integrations.google.models import GoogleCredential
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch)
    saved=create(admin,qc_payload(row,nvl(conn)));assert saved.status_code==201,saved.text
    with scope() as db:
        cred=db.get(GoogleCredential,'_TEST_ADMIN');cred.subject='another-account';db.commit()
    monkeypatch.setattr(worker,'Session',lambda:OrmSession(bind=conn,expire_on_commit=False,join_transaction_mode='create_savepoint'))
    monkeypatch.setattr(drive_bundle,'prepare',lambda *a,**k:pytest.fail('Must never switch Google account'))
    with worker.Session() as db:claimed=worker.claim(db)
    worker.run_job(*claimed)
    with worker.Session() as db:
        row=db.get(QCJob,claimed[0]);assert row.status=='FAILED' and 'Google' in row.last_error and row.attempts==1


def test_staging_retention_never_removes_pending_bytes(clients):
    admin,_,_=clients;stage,files=receive(admin)
    with scope() as db:
        row=db.get(QCJob,stage['id']);file=row.manifest[0];row.updated_at=datetime(2000,1,1);db.commit()
        jobs.clean_expired(db)
        assert db.get(QCJob,stage['id']).status=='EXPIRED'
        assert not jobs.file_path(file['stage'],file['id']).exists()


def test_concurrent_claim_skip_locked_on_real_mysql():
    # Committed QA rows are needed to exercise two independent MySQL connections.
    # No worker service is started during this test; cleanup targets these UUIDs only.
    suffix=uuid4().hex;owner='_QA_OWNER_'+suffix
    ids=[str(uuid4()),str(uuid4())];qcids=['_QA_LOCK_'+suffix+str(i) for i in range(2)]
    try:
        with Session() as db:
            db.add(User(id=owner,name='QA worker locking',role='LOCAL_ADMIN',active=False));db.flush()
            for identifier in qcids:db.add(QualityCheck(id=identifier,staff_id=owner,source={}))
            db.flush()
            for identifier,qc in zip(ids,qcids):db.add(QCJob(id=identifier,qc_id=qc,owner_id=owner,status='PENDING',available_at=datetime(1999,1,1),manifest=[]))
            db.commit()
        with Session() as first,Session() as second:
            locked=first.scalar(select(QCJob).where(QCJob.id==ids[0]).with_for_update())
            claimed=worker.claim(second)
            assert claimed[0]==ids[1]
            first.rollback()
        with Session() as db:
            claimed=worker.claim(db);assert claimed[0]==ids[0]
    finally:
        with Session() as db:
            db.execute(delete(QCJob).where(QCJob.id.in_(ids)))
            db.execute(delete(QualityCheck).where(QualityCheck.id.in_(qcids)))
            db.execute(delete(User).where(User.id==owner));db.commit()


def test_worker_real_process_exit_and_resume_without_browser(tmp_path):
    import os,sys,subprocess
    from app.integrations.google.models import GoogleCredential
    suffix=uuid4().hex;owner='_QA_PROCESS_'+suffix;qc='_QA_PROCESS_'+suffix;identifier=str(uuid4());file_id=str(uuid4())
    env={**os.environ,'QC_STAGING_PATH':str(tmp_path)}
    path=tmp_path/identifier/file_id;path.parent.mkdir();size=jobs.CHUNK+19;path.write_bytes(b'x'*size)
    file={'id':file_id,'stage':identifier,'name':'process-video.mp4','size':size,'modified':1,'mime':'video/mp4','ready':True,'offset':size,'sha256':hashlib.sha256(b'x'*size).hexdigest()}
    try:
        with Session() as db:
            db.add(User(id=owner,name='QA restart',role='LOCAL_ADMIN',active=True));db.flush()
            db.add(GoogleCredential(user_id=owner,subject='qa-process-subject',encrypted_access='mock-only',encrypted_refresh='mock-only',expires_at=datetime(2099,1,1),scopes='mock-only'))
            obj=QualityCheck(id=qc,staff_id=owner,source={drive_bundle.JOB:{'pending':True}},form_data={'qa':True});db.add(obj);db.flush()
            db.add(QCJob(id=identifier,qc_id=qc,owner_id=owner,status='PENDING',available_at=datetime(1990,1,1),manifest=[file],google_subject='qa-process-subject',revision=mapping.digest(obj.form_data)));db.commit()
        first="""
from app.modules.qc import worker
from app.core.database import Session
from app.modules.qc.job_models import QCJob
import os
with Session() as db:
    claimed=worker.claim(db)
    row=db.get(QCJob,claimed[0]);files=[{**f,'ticket':'mock-session','drive_offset':4194304} for f in row.manifest]
worker.checkpoint(*claimed,step='upload_evidence_1',manifest=files)
os._exit(23)
"""
        stopped=subprocess.run([sys.executable,'-c',first],env=env,capture_output=True,text=True,timeout=30)
        assert stopped.returncode==23,stopped.stderr
        with Session() as db:
            row=db.get(QCJob,identifier);assert row.status=='PROCESSING' and row.attempts==1
            row.lease_until=datetime(2000,1,1);db.commit()
        second="""
from app.modules.qc import worker,drive_bundle
from app.core.database import Session
from app.modules.qc.models import QualityCheck
worker.access_token=lambda *a:'mock-only'
drive_bundle.access_token=lambda *a:'mock-only'
def prepare(db,user,qc,progress=None):
    obj=db.get(QualityCheck,qc);obj.drive_folder_id='mock-folder';obj.source={drive_bundle.JOB:{'pending':False}};db.commit();return obj
drive_bundle.prepare=prepare
def chunk(db,user,obj,ticket,offset,content,probe=False):
    if probe:return {'complete':False,'offset':4194304}
    print('QA_UPLOADED_BYTES',len(content),flush=True)
    return {'complete':True,'offset':4194323}
drive_bundle.upload_chunk=chunk
worker.verify_remote=lambda *a:None
with Session() as db:claimed=worker.claim(db)
worker.run_job(*claimed)
"""
        resumed=subprocess.run([sys.executable,'-c',second],env=env,capture_output=True,text=True,timeout=30)
        assert resumed.returncode==0,resumed.stderr
        assert 'QA_UPLOADED_BYTES 19' in resumed.stdout
        with Session() as db:
            row=db.get(QCJob,identifier);assert row.status=='COMPLETED' and row.attempts==2
            assert not path.exists()
    finally:
        with Session() as db:
            db.execute(delete(QCJob).where(QCJob.id==identifier));db.execute(delete(QualityCheck).where(QualityCheck.id==qc))
            db.execute(delete(GoogleCredential).where(GoogleCredential.user_id==owner));db.execute(delete(User).where(User.id==owner));db.commit()


def test_background_oauth_refresh_without_browser_and_revocation(clients,monkeypatch):
    from cryptography.fernet import Fernet
    from app.integrations.google import oauth
    from app.integrations.google.models import GoogleCredential
    admin,_,_=clients;secret=Fernet(Fernet.generate_key());monkeypatch.setattr(oauth,'cipher',lambda:secret)
    calls=[]
    with scope() as db:
        user=db.get(User,'_TEST_ADMIN')
        credential=GoogleCredential(user_id=user.id,subject='qa-refresh',encrypted_access=secret.encrypt(b'old-access').decode(),
            encrypted_refresh=secret.encrypt(b'qa-refresh-only').decode(),expires_at=datetime(2000,1,1),scopes='test-only')
        db.add(credential);db.commit()
        def refreshed(url,**kwargs):
            calls.append(kwargs['form']['grant_type']);return {'access_token':'qa-new-access','expires_in':3600}
        monkeypatch.setattr(oauth,'google_json',refreshed)
        assert oauth.access_token(db,user)=='qa-new-access' and calls==['refresh_token']
        # A second access does not refresh again while the access token is current.
        assert oauth.access_token(db,user)=='qa-new-access' and len(calls)==1
        credential.expires_at=datetime(2000,1,1);db.flush()
        def revoked(*a,**k):raise HTTPException(502,'Google từ chối thao tác (HTTP 400).')
        monkeypatch.setattr(oauth,'google_json',revoked)
        with pytest.raises(HTTPException):oauth.access_token(db,user)
        assert credential.subject=='qa-refresh'  # No fallback account after revocation.


def test_job_revision_uses_mysql_json_roundtrip(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);data=qc_payload(row,nvl(conn))
    original=.09274584338014791
    data['mapped_form']['signature']=[[[original,.3],[.7234567890123456,.8]]]
    response=create(admin,data);assert response.status_code==201,response.text
    with scope() as db:
        obj=db.get(QualityCheck,response.json()['id']);db.refresh(obj)
        job=db.scalar(select(QCJob).where(QCJob.qc_id==obj.id))
        assert obj.form_data['input']['signature'][0][0][0]!=original  # Reproduces MySQL's ULP conversion.
        assert job.revision==mapping.digest(obj.form_data)


def test_retry_repairs_only_original_accepted_snapshot(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);data=qc_payload(row,nvl(conn))
    saved=create(admin,data);assert saved.status_code==201,saved.text
    identifier=saved.json()['id']
    with scope() as db:
        job=db.scalar(select(QCJob).where(QCJob.qc_id==identifier))
        job.status='FAILED';job.current_step='validate';job.revision='f'*64
        job.last_error='Nội dung QC khác phiên bản job. Cần kiểm tra hồ sơ.';db.commit()
    retry=admin.post('/api/qc/'+identifier+'/retry-sync');assert retry.status_code==200,retry.text
    with scope() as db:
        obj=db.get(QualityCheck,identifier);job=db.scalar(select(QCJob).where(QCJob.qc_id==identifier))
        assert job.status=='PENDING' and job.revision==mapping.digest(obj.form_data)
        assert job.metrics['revision_repair']=='mysql_json_roundtrip'
        mutated=deepcopy(obj.form_data);mutated['input']['answers'][0]['actual']='unexpected change';obj.form_data=mutated
        job.status='FAILED';job.current_step='validate';job.revision='a'*64
        job.last_error='Nội dung QC khác phiên bản job. Cần kiểm tra hồ sơ.';db.commit()
    assert admin.post('/api/qc/'+identifier+'/retry-sync').status_code==409
    with scope() as db:assert db.scalar(select(QCJob).where(QCJob.qc_id==identifier)).revision=='a'*64


def test_append_staging_keeps_received_files_and_is_idempotent(clients,monkeypatch):
    admin,reader,_=clients
    staged,first=receive(admin,17)
    original=staged['files'][0]['id']
    extra={'name':'second.jpg','size':3,'modified':124,'mime':'image/jpeg'}
    payload={'staging_id':staged['id'],'files':[extra]}
    assert reader.post('/api/qc/staging',json=payload).status_code in {403,404}
    added=admin.post('/api/qc/staging',json=payload)
    assert added.status_code==201,added.text
    data=added.json();assert data['id']==staged['id'] and len(data['files'])==2
    assert data['files'][0]['id']==original and data['files'][0]['ready']
    second=data['files'][1]['id']
    assert admin.put('/api/qc/staging/'+staged['id']+'/'+second+'?offset=0',content=b'abc').status_code==200
    monkeypatch.setattr(jobs,'MAX_OWNER',20)
    # Lost-response retry reuses the registered file; it reserves no extra bytes.
    retried=admin.post('/api/qc/staging',json=payload)
    assert retried.status_code==201,retried.text
    assert len(retried.json()['files'])==2 and retried.json()['files'][1]['id']==second
    assert retried.json()['files'][1]['ready']
    denied=admin.post('/api/qc/staging',json={'staging_id':staged['id'],'files':[{**extra,'name':'third.jpg'}]})
    assert denied.status_code==413
    with scope() as db:
        row=db.get(QCJob,staged['id']);assert len(row.manifest)==2
        assert jobs.file_path(staged['id'],original).read_bytes()==b'x'*17
        assert jobs.file_path(staged['id'],second).read_bytes()==b'abc'
        row.status='ATTACHED';db.commit()
    assert admin.post('/api/qc/staging',json=payload).status_code==409


def test_completed_record_can_resync_same_pdf_and_folder(clients,monkeypatch):
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch)
    saved=create(admin,qc_payload(row,nvl(conn))).json()
    with scope() as db:
        obj=db.get(QualityCheck,saved['id']);obj.drive_folder_id='same-folder'
        obj.source={drive_bundle.JOB:{'pdf_id':'same-pdf','pdf_revision':'old-revision','pending':False}}
        job=db.scalar(select(QCJob).where(QCJob.qc_id==obj.id));job.status='COMPLETED'
        job.manifest=[{'done':True,'cleaned':True,'stage':job.id,'id':str(uuid4())}]
        db.commit()
    response=admin.post('/api/qc/'+saved['id']+'/retry-sync')
    assert response.status_code==200,response.text
    assert response.json()['status']=='PENDING'
    with scope() as db:
        obj=db.get(QualityCheck,saved['id']);job=db.scalar(select(QCJob).where(QCJob.qc_id==obj.id))
        assert obj.drive_folder_id=='same-folder'
        assert obj.source[drive_bundle.JOB]['pdf_id']=='same-pdf'
        assert obj.source[drive_bundle.JOB]['pdf_revision'] is None and obj.source[drive_bundle.JOB]['pending']
        assert job.manifest[0]['done'] and job.manifest[0]['cleaned']


def test_missing_old_evidence_does_not_block_pdf_sync(monkeypatch):
    from types import SimpleNamespace
    file={'name':'deleted.jpg','size':3,'mime':'image/jpeg','modified':1,'done':True,'cleaned':True}
    obj=SimpleNamespace(id='QC_TEST',drive_folder_id='folder',form_data={'test':True},source={drive_bundle.JOB:{'pdf_id':'pdf','pdf_revision':'revision','pending':False,'expected_uploads':[drive_bundle.upload_key('QC_TEST',jobs.UploadInput(**{k:file[k] for k in ('name','size','mime','modified')}))]}})
    class DB:
        def commit(self):pass
    def remote(token,path='',**kwargs):
        if path:return {'id':'pdf','mimeType':'application/pdf','parents':['folder'],'size':'2000','trashed':False}
        return {'files':[]}
    monkeypatch.setattr(worker,'access_token',lambda *args:'test-token')
    monkeypatch.setattr(drive_bundle,'in_scope',lambda *args,**kwargs:None)
    monkeypatch.setattr(drive_bundle,'call',remote)
    worker.verify_remote(DB(),None,obj,[file],lambda step:None)
    assert file['skipped'] and obj.source[drive_bundle.JOB]['expected_uploads']==[]
    fresh={**file,'cleaned':False,'skipped':False}
    with pytest.raises(HTTPException):worker.verify_remote(DB(),None,obj,[fresh],lambda step:None)
    def missing_pdf(*args,**kwargs):return {'trashed':True}
    monkeypatch.setattr(drive_bundle,'call',missing_pdf)
    with pytest.raises(HTTPException):worker.verify_remote(DB(),None,obj,[file],lambda step:None)


def test_restore_snapshot_is_frozen_and_targets_copy_only():
    from app.modules.qc.sheets_pdf import restore_snapshot
    snapshot={'row_count':2,'column_count':2,'grid':{'rowData':[{'values':[{'formattedValue':'42','userEnteredValue':{'formulaValue':'=A2+1'},'effectiveFormat':{'textFormat':{'bold':True}}}]}], 'rowMetadata':[{'pixelSize':40}],'columnMetadata':[{'pixelSize':160}]},'merges':[{'sheetId':99,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':0,'endColumnIndex':2}]}
    original=deepcopy(snapshot);requests=restore_snapshot(snapshot,123)
    written=next(r['updateCells'] for r in requests if 'updateCells' in r)
    assert written['range']['sheetId']==123
    assert written['rows'][0]['values'][0]['userEnteredValue']=={'stringValue':'42'}
    assert written['rows'][0]['values'][0]['userEnteredFormat']['textFormat']['bold']
    assert next(r['mergeCells'] for r in requests if 'mergeCells' in r)['range']['sheetId']==123
    assert snapshot==original
