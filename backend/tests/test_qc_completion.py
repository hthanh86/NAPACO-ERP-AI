"""Internal signature auth, immutable content and durable Drive completion state."""
from copy import deepcopy
from datetime import datetime,timedelta
from types import SimpleNamespace
import json
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from app.auth.security import token_hash
from app.integrations.google.models import GoogleCredential
from app.modules.qc import signing,drive_bundle,mapping
from app.modules.qc.schemas import QCInput,UploadInput
from app.modules.qc.models import QualityCheck
from test_qc_mapping import stage,release,nvl,qc_payload,create,sheet,fields

pytestmark=pytest.mark.usefixtures('qc_drive')


def test_signature_identity_requires_google_session_proof(monkeypatch):
    secret=Fernet(Fernet.generate_key());monkeypatch.setattr(signing,'cipher',lambda:secret)
    user=SimpleNamespace(id='u',name='QC',email='qc@example.test')
    credential=SimpleNamespace(subject='google-subject')
    db=SimpleNamespace(get=lambda model,key:credential)
    cookies={'napaco_session':'session-test'}
    request=SimpleNamespace(cookies=cookies)
    with pytest.raises(HTTPException):signing.identity(request,db,user)
    cookies['napaco_google_proof']=secret.encrypt(json.dumps({'user':'u','subject':'google-subject',
        'session':token_hash('session-test')}).encode()).decode()
    assert signing.identity(request,db,user)['user_id']=='u'
    cookies['napaco_session']='another-session'
    with pytest.raises(HTTPException):signing.identity(request,db,user)


def test_save_signature_view_and_edit_requires_new_confirmation(clients,monkeypatch):
    admin,reader,conn=clients
    row,_,_=stage(admin,monkeypatch);selection=nvl(conn)
    data=qc_payload(row,selection)
    saved=create(admin,data)
    assert saved.status_code==201,saved.text
    saved=saved.json()
    from app.modules.qc.job_models import QCJob
    from sqlalchemy import update
    conn.execute(update(QCJob).where(QCJob.qc_id==saved['id']).values(status='COMPLETED'))
    assert saved['form_data']['input']['signature'] and saved['form_data']['signer']['content_hash']
    assert saved['evidence_pending'] and saved['pdf_pending']
    assert admin.get('/api/qc/'+saved['id']).json()['form_data']['signer']==saved['form_data']['signer']
    changed={**deepcopy(data),'note':'QC content changed','version':saved['version']}
    assert admin.put('/api/qc/'+saved['id'],json=changed).status_code==422
    confirmation=admin.post('/api/qc/signatures/confirm?qc_id='+saved['id'],json=changed)
    assert confirmation.status_code==200,confirmation.text
    changed['mapped_form']['confirmation']=confirmation.json()['confirmation']
    updated=admin.put('/api/qc/'+saved['id'],json=changed)
    assert updated.status_code==200,updated.text
    assert updated.json()['form_data']['signer']['nonce']!=saved['form_data']['signer']['nonce']
    assert reader.post('/api/qc/signatures/confirm',json=data).status_code==403


def test_manifest_status_is_durable_and_duplicate_completion_idempotent(clients,monkeypatch):
    admin,_,conn=clients
    row,_,_=stage(admin,monkeypatch);selection=nvl(conn)
    data=qc_payload(row,selection);data['evidence_manifest']=[{'name':'test.png','size':100,'modified':1,'mime':'image/png'}]
    staging=admin.post('/api/qc/staging',json={'files':data['evidence_manifest']}).json()
    assert admin.put('/api/qc/staging/'+staging['id']+'/'+staging['files'][0]['id']+'?offset=0',content=b'x'*100).status_code==200
    data['staging_id']=staging['id']
    saved=create(admin,data)
    assert saved.status_code==201,saved.text
    saved=saved.json();identifier=saved['id']
    assert saved['evidence_remaining']==1
    # Rollback-only fixture: no real Drive objects are created.
    from app.core.database import get_db
    from app.main import app
    override=app.dependency_overrides[get_db]();db=next(override)
    try:
        obj=db.get(QualityCheck,identifier);job=deepcopy(obj.source[drive_bundle.JOB]);job['pending']=False
        obj.source={drive_bundle.JOB:job};db.commit()
        key=drive_bundle.upload_key(identifier,UploadInput(**data['evidence_manifest'][0]))
        drive_bundle.complete_upload(db,identifier,key)
        drive_bundle.complete_upload(db,identifier,key)
        assert len(db.get(QualityCheck,identifier).source[drive_bundle.JOB]['completed_uploads'])==1
    finally:
        override.close()
    detail=admin.get('/api/qc/'+identifier).json()
    assert detail['evidence_remaining']==0 and detail['evidence_pending']  # Worker verification gates COMPLETED.


def test_signature_region_cannot_overlap_results():
    with pytest.raises(HTTPException):
        mapping.validate(sheet(),mapping.MappingInput(fields=fields(),signature_cell='B2',signature_end_cell='D3'),'QC NVL')


def test_pdf_signature_uses_actual_google_region_and_rejects_missing_marker():
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
    from app.modules.qc.pdf_signature import apply_signature
    marker=(.13,.57,.83)
    buffer=BytesIO();c=canvas.Canvas(buffer,pagesize=(595,842))
    c.drawString(30,800,'QC TEST - TEMPLATE LAYOUT')
    c.setFillColorRGB(*marker);c.rect(50,80,220,90,fill=1,stroke=0);c.save()
    original=buffer.getvalue()
    data={'input':{'signature':[[[.1,.7],[.5,.2],[.9,.6]]]},
          'context':{'qc_id':'QC_TEST'},'signer':{'name':'Người kiểm thử','content_hash':'a'*64}}
    final=apply_signature(original,data,marker,(1,1,1))
    reader=PdfReader(BytesIO(final))
    assert len(reader.pages)==1
    assert 'QC TEST - TEMPLATE LAYOUT' in reader.pages[0].extract_text()
    assert 'Người kiểm thử' in reader.pages[0].extract_text()
    assert len(final)>len(original)
    with pytest.raises(HTTPException):apply_signature(original,data,(.9,.1,.1),(1,1,1))


@pytest.mark.parametrize('source_changed',[False,True])
def test_sheets_copy_batch_write_readback_never_writes_original(monkeypatch,source_changed):
    from app.modules.qc import sheets_pdf,pdf_signature
    from urllib.parse import parse_qs,urlsplit
    source=sheet();source['grid']['rowData'][0]['values'][4]['formattedValue']='Dung sai / Ghi chú'
    layout=mapping.validate(source,mapping.MappingInput(fields=fields(),signature_cell='E4',signature_end_cell='F6'),'QC NVL')
    data={'kind':'google_template','template':{'spreadsheet_id':source['spreadsheet_id'],'sheet_id':42,
          'source_hash':mapping.source_hash(source),'snapshot':source,'mapping':layout},
          'context':{'qc_id':'QC_TEST'},'auto_values':{'qc':'QC_TEST','po_width':'500'},
          'signer':{'nonce':'nonce-test'},'input':{'signature':[[[.1,.2],[.8,.9]]],
          'answers':[{'id':'width','actual':'501','assessment':'PASS'},{'id':'look','actual':'Sạch','assessment':'PASS'}]}}
    obj=SimpleNamespace(id='QC_TEST',template_id='template',drive_folder_id='folder',source={},form_data=data)
    writes=[]
    def first(db,user,identifier,preview):
        live=deepcopy(source)
        if source_changed:live['merges']=[]
        return live if identifier==source['spreadsheet_id'] else {**live,'spreadsheet_id':'temporary-copy','title':'Copy'}
    def call(token,path='',**kwargs):
        if kwargs.get('q'):return {'files':[]}
        assert path=='/'+source['spreadsheet_id']+'/copy'
        return {'id':'temporary-copy'}
    def persist(db,identifier,**kwargs):
        kwargs.pop('expected_revision',None)
        obj.source={drive_bundle.JOB:{**obj.source.get(drive_bundle.JOB,{}),**kwargs}}
        return obj
    def google(url,**kwargs):
        assert url=='https://sheets.googleapis.com/v4/spreadsheets/temporary-copy:batchUpdate'
        writes.append(json.loads(kwargs['body']))
        return {}
    data['input']['answers'][0]['note']='siêu chuẩn'
    values={'A6':'QC_TEST','B6':'500','C2':'501 mm','D2':'Đạt','B2':'Theo PO','C3':'Sạch','D3':'Đạt','E2':'siêu chuẩn','E3':''}
    def read(url,token):
        ranges=parse_qs(urlsplit(url).query)['ranges']
        return {'valueRanges':[{'values':[[values[r.rsplit('!',1)[-1]]]]} for r in ranges]}
    monkeypatch.setattr(sheets_pdf.sheets,'first_tab',first)
    monkeypatch.setattr(sheets_pdf.sheets,'read_json',read)
    monkeypatch.setattr(drive_bundle,'call',call)
    monkeypatch.setattr(sheets_pdf,'persist',persist)
    monkeypatch.setattr(sheets_pdf,'google_json',google)
    monkeypatch.setattr(sheets_pdf,'export',lambda *args:b'exported-google-pdf')
    monkeypatch.setattr(pdf_signature,'apply_signature',lambda content,*args:content+b'-signed')
    assert sheets_pdf.render(None,None,obj,'token')==b'exported-google-pdf-signed'
    assert len(writes)==(2 if source_changed else 1)
    if source_changed:assert any('mergeCells' in request for request in writes[0]['requests'])
    assert sum('updateCells' in request for request in writes[-1]['requests'])==len(values)
    written={mapping.address(item['updateCells']['start']['rowIndex'],item['updateCells']['start']['columnIndex']):item['updateCells']['rows'][0]['values'][0]['userEnteredValue']['stringValue'] for item in writes[-1]['requests'] if 'updateCells' in item}
    assert written['E2']==values['E2']
    assert source['grid']['rowData'][1]['values'][4]['formattedValue']=='± 2 mm'
    assert source['grid']['rowData'][1]['values'][1]['formattedValue']=='Theo PO'


def test_edit_reuses_own_strokes_and_reconfirms_latest_content(clients,monkeypatch):
    from app.modules.qc.job_models import QCJob
    from sqlalchemy import update
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);data=qc_payload(row,nvl(conn))
    saved=create(admin,data);assert saved.status_code==201,saved.text
    saved=saved.json();conn.execute(update(QCJob).where(QCJob.qc_id==saved['id']).values(status='COMPLETED'))
    changed={**deepcopy(data),'version':saved['version'],'note':'Đã cập nhật sau khi ký','quantity':'3'}
    changed['mapped_form'].update(signature=saved['form_data']['input']['signature'],reuse_signature=True)
    response=admin.post('/api/qc/signatures/confirm?qc_id='+saved['id'],json=changed)
    assert response.status_code==200,response.text
    changed['mapped_form']['confirmation']=response.json()['confirmation']
    updated=admin.put('/api/qc/'+saved['id'],json=changed)
    assert updated.status_code==200,updated.text
    current=updated.json()['form_data']
    assert updated.json()['sync']['status']=='PENDING'
    assert current['input']['signature']==saved['form_data']['input']['signature']
    assert current['signer']['method']=='google_oauth_internal_reconfirmed'
    assert current['signer']['previous_content_hash']==saved['form_data']['signer']['content_hash']
    assert current['signer']['signature_origin_signed_at']==saved['form_data']['signer']['signed_at']
    assert current['signer']['content_hash']!=saved['form_data']['signer']['content_hash']
    assert current['context']['quantity']=='3' and current['context']['qc_note']==changed['note']


@pytest.mark.parametrize('mismatch',['user_id','google_subject','signature'])
def test_cannot_reuse_another_identity_or_different_strokes(clients,monkeypatch,mismatch):
    from app.modules.qc.models import QualityCheck
    from app.main import app
    from app.core.database import get_db
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch);data=qc_payload(row,nvl(conn))
    saved=create(admin,data);assert saved.status_code==201,saved.text
    saved=saved.json();data['mapped_form'].update(signature=saved['form_data']['input']['signature'],reuse_signature=True)
    provider=app.dependency_overrides[get_db]();db=next(provider)
    try:
        obj=db.get(QualityCheck,saved['id']);value=deepcopy(obj.form_data)
        if mismatch=='signature':data['mapped_form']['signature']=[[[.2,.2],[.9,.9]]]
        else:value['signer'][mismatch]='other-identity';obj.form_data=value;db.commit()
    finally:provider.close()
    response=admin.post('/api/qc/signatures/confirm?qc_id='+saved['id'],json=data)
    assert response.status_code==403,response.text


def test_template_pdf_opens_drive_without_downloading_bytes(clients,monkeypatch):
    from app.main import app
    from app.core.database import get_db
    admin,_,conn=clients;row,_,_=stage(admin,monkeypatch)
    saved=create(admin,qc_payload(row,nvl(conn))).json()
    provider=app.dependency_overrides[get_db]();db=next(provider)
    try:
        obj=db.get(QualityCheck,saved['id']);obj.drive_folder_id='folder'
        revision=drive_bundle.hashlib.sha256(json.dumps(obj.form_data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        obj.source={drive_bundle.JOB:{'pending':False,'pdf_id':'pdf-on-drive','pdf_revision':revision}};db.commit()
    finally:provider.close()
    monkeypatch.setattr(drive_bundle,'call',lambda *args,**kwargs:{'id':'pdf-on-drive','parents':['folder'],'mimeType':'application/pdf','trashed':False})
    monkeypatch.setattr(drive_bundle.httpx,'stream',lambda *args,**kwargs:pytest.fail('Must not proxy/download PDF bytes'))
    detail=admin.get('/api/qc/'+saved['id']).json()
    assert detail['pdf_url']=='https://drive.google.com/file/d/pdf-on-drive/view'
    response=admin.get('/api/qc/'+saved['id']+'/pdf',follow_redirects=False)
    assert response.status_code==303,response.text
    assert response.headers['location']==detail['pdf_url']
