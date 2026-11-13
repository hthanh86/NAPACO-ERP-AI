"""Signed forms, root confinement and retry safety; no live Drive writes."""
from copy import deepcopy
from types import SimpleNamespace
import sys
import json
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.modules.qc import forms, drive_bundle
from app.modules.qc.schemas import FormInput
from app.modules.qc.models import QualityCheck
from app.core.settings import SystemSetting
from test_qc import form_payload, payload, source_data, create


def test_real_pdf_embeds_vietnamese_fonts_and_uses_saved_snapshot():
    from app.modules.qc.pdf import render_pdf
    user=SimpleNamespace(id='test-signer',name='NGƯỜI KÝ KIỂM THỬ')
    data=forms.filled_form(FormInput(**form_payload('PASS')),user,{
        'object_id':'N_NVL_KIEM_THU','quantity':'3','checked_at':'2026-11-12 10:00:00'})
    data['definition']['name']='BIỂU MẪU ĐÃ LƯU PHIÊN BẢN V1'
    pdf=render_pdf(SimpleNamespace(id='QC_KIEM_THU_KHONG_PHAI_HO_SO_THAT',form_data=data))
    assert pdf.startswith(b'%PDF-')
    assert b'/FontFile2' in pdf  # Unicode TrueType font embedded, not a host font dependency.
    assert b'%%EOF' in pdf


def test_real_pdf_handles_long_notes_without_clipping_or_layout_error():
    from app.modules.qc.pdf import render_pdf
    data=form_payload('PASS')
    data['note']='Ghi chú kiểm tra dài có tiếng Việt. '*240
    data['answers'][0]['note']='Chi tiết cần xem xét. '*80
    filled=forms.filled_form(FormInput(**data),SimpleNamespace(id='test',name='KIỂM THỬ'),{
        'object_id':'NVL_TEST','quantity':'1','checked_at':'2026-11-12'})
    pdf=render_pdf(SimpleNamespace(id='QC_TEST_LONG_NOTES',form_data=filled))
    assert pdf.startswith(b'%PDF-') and b'%%EOF' in pdf


def test_form_snapshot_signer_and_checks():
    user=SimpleNamespace(id='actor',name='Người ký')
    result=forms.filled_form(FormInput(**form_payload()),user,{'object_id':'receipt'})
    assert result['signer']['user_id']=='actor'
    assert result['definition']['criteria'][0]['tolerance']=='± 2.0 mm'
    copy=forms.definition('QC_NVL_V1')
    copy['criteria'][0]['tolerance']='tampered'
    assert result['definition']['criteria'][0]['tolerance']=='± 2.0 mm'
    bad=deepcopy(form_payload());bad['conclusion']='PASS'
    with pytest.raises(HTTPException):forms.filled_form(FormInput(**bad),user,{})
    bad=deepcopy(form_payload());bad['signature']=[[[.2,.2],[.2,.2]]]
    with pytest.raises(HTTPException):forms.filled_form(FormInput(**bad),user,{})
    na=deepcopy(form_payload('PASS'));na['answers'][0].update(assessment='NA',actual='stale actual',note='')
    normalized=forms.filled_form(FormInput(**na),user,{})
    assert normalized['input']['answers'][0]['actual']==''
    assert normalized['input']['answers'][0]['note']==''
    bad=deepcopy(form_payload());bad['answers'][1]['id']=bad['answers'][0]['id']
    with pytest.raises(HTTPException):forms.filled_form(FormInput(**bad),user,{})


def test_scope_rejects_outside_shortcut_and_inaccessible(monkeypatch):
    monkeypatch.setattr(drive_bundle,'get_setting',lambda db,key:'root')
    tree={'root':{'id':'root','mimeType':drive_bundle.FOLDER,'capabilities':{'canAddChildren':True}},
          'inside':{'id':'inside','parents':['root'],'mimeType':drive_bundle.FOLDER,'capabilities':{'canAddChildren':True}},
          'outside':{'id':'outside','mimeType':drive_bundle.FOLDER},
          'shortcut':{'id':'shortcut','parents':['root'],'mimeType':'application/vnd.google-apps.shortcut'}}
    def call(token,path,**kwargs):return tree[path[1:]]
    monkeypatch.setattr(drive_bundle,'call',call)
    assert drive_bundle.in_scope(None,'token','inside',writable=True)['id']=='inside'
    for identifier in ['outside','shortcut']:
        with pytest.raises(HTTPException):drive_bundle.in_scope(None,'token',identifier)
    tree['inside']['capabilities']['canAddChildren']=False
    with pytest.raises(HTTPException):drive_bundle.in_scope(None,'token','inside',writable=True)


def test_backend_requires_form_and_rejects_parent_before_creating(clients,monkeypatch):
    admin,reader,connection=clients
    source_data(connection)
    data=payload();data.pop('form')
    assert create(admin,data).status_code==422
    monkeypatch.setattr(drive_bundle,'access_token',lambda db,user:'token')
    def reject(*args,**kwargs):raise HTTPException(403,'outside root')
    monkeypatch.setattr(drive_bundle,'in_scope',reject)
    response=create(admin,payload())
    assert response.status_code==403
    assert admin.get('/api/qc/folders').status_code==403
    assert reader.post('/api/qc/unknown/bundle').status_code==403


def test_pdf_failure_preserves_qc_and_retry_reuses_folder(clients,monkeypatch):
    admin,reader,connection=clients
    user=SimpleNamespace(id='_TEST_ADMIN',name='Kiểm thử')
    monkeypatch.setattr(drive_bundle,'access_token',lambda db,user:'token')
    root=connection.execute(select(SystemSetting.value).where(SystemSetting.key=='QC_ROOT_FOLDER_ID')).scalar_one()
    tree={root:{'id':root,'name':'QC','mimeType':drive_bundle.FOLDER,'capabilities':{'canAddChildren':True}},
          'parent':{'id':'parent','name':'Parent','parents':[root],'mimeType':drive_bundle.FOLDER,'capabilities':{'canAddChildren':True}}}
    ids=iter(['allocated-folder','allocated-pdf']);created=[]
    monkeypatch.setattr(drive_bundle,'generated_id',lambda token:next(ids))
    def call(token,path='',method=None,body=None,missing=False,**params):
        if method=='POST':
            created.append(body['id']);tree[body['id']]={**body,'capabilities':{'canAddChildren':True}};return tree[body['id']]
        return tree.get(path[1:])
    monkeypatch.setattr(drive_bundle,'call',call)
    monkeypatch.setitem(sys.modules,'app.modules.qc.pdf',SimpleNamespace(render_pdf=lambda obj:b'%PDF-simulated'))
    uploads=[]
    def fail(token,identifier,content):uploads.append(identifier);raise HTTPException(502,'simulated interruption')
    monkeypatch.setattr(drive_bundle,'upload_pdf',fail)
    with Session(bind=connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as db:
        obj=QualityCheck(id='_TEST_QC_BUNDLE',staff_id=user.id,form_data={'snapshot':'test'},source={drive_bundle.JOB:{'parent':'parent','owner':user.id,'pending':True}})
        db.add(obj);db.commit()
        result=drive_bundle.prepare(db,user,obj.id)
        assert result.drive_folder_id=='allocated-folder'
        assert result.source[drive_bundle.JOB]['pending'] is True
        assert created==['allocated-folder','allocated-pdf']
        assert tree['allocated-pdf']['name']=='PQC__TEST_QC_BUNDLE.pdf'
        monkeypatch.setattr(drive_bundle,'upload_pdf',lambda token,identifier,content:uploads.append(identifier))
        result=drive_bundle.prepare(db,user,obj.id)
        assert result.source[drive_bundle.JOB]['pending'] is False
        assert 'parent' not in result.source[drive_bundle.JOB]
        assert created==['allocated-folder','allocated-pdf']
        assert uploads==['allocated-pdf','allocated-pdf']
        drive_bundle.prepare(db,user,obj.id)
        assert len(uploads)==2


def test_chunk_ticket_scope_and_resume(monkeypatch):
    import httpx
    cipher=Fernet(Fernet.generate_key())
    monkeypatch.setattr(drive_bundle,'cipher',lambda:cipher)
    monkeypatch.setattr(drive_bundle,'access_token',lambda db,user:'token')
    monkeypatch.setattr(drive_bundle,'in_scope',lambda *args,**kwargs:None)
    calls=[]
    def http(method,url,token,**kwargs):
        calls.append(kwargs['headers']['Content-Range'])
        return httpx.Response(308,headers={'Range':'bytes=0-262143'})
    monkeypatch.setattr(drive_bundle,'http',http)
    obj=SimpleNamespace(id='QC_TEST',drive_folder_id='folder')
    user=SimpleNamespace(id='user')
    state={'qc':obj.id,'folder':'folder','user':'user','size':524288,'mime':'video/mp4','url':'https://www.googleapis.com/upload/drive/v3/files?upload_id=test'}
    ticket=cipher.encrypt(json.dumps(state).encode()).decode()
    db=SimpleNamespace(commit=lambda:None)
    result=drive_bundle.upload_chunk(db,user,obj,ticket,0,b'x'*262144)
    assert result=={'complete':False,'offset':262144}
    drive_bundle.upload_chunk(db,user,obj,ticket,0,b'',True)
    assert calls==['bytes 0-262143/524288','bytes */524288']
    with pytest.raises(HTTPException):drive_bundle.upload_chunk(db,SimpleNamespace(id='other'),obj,ticket,0,b'x')


def test_released_template_root_and_pqc_mapping(clients,qc_drive,monkeypatch):
    admin,reader,connection=clients
    source_data(connection)
    catalog=admin.get('/api/qc/forms').json()
    root=connection.execute(select(SystemSetting.value).where(SystemSetting.key=='QC_ROOT_FOLDER_ID')).scalar_one()
    assert [item['code'] for item in catalog['items']]==['QC_NVL_261101_V1']
    assert catalog['root_folder_id']==root
    assert catalog['released']['PRODUCT'] is None
    checked=[]
    monkeypatch.setattr(drive_bundle,'in_scope',lambda db,token,identifier,writable=False:checked.append(identifier))
    retired=payload();retired['form']['code']='QC_NVL_V1';retired['standard_url']='QC_NVL_V1'
    assert create(admin,retired).status_code==422
    checked.clear()
    data=payload();data['parent_folder_id']='selected-parent'
    response=create(admin,data)
    assert response.status_code==201, response.text
    obj=response.json()
    assert checked==['selected-parent']
    assert obj['form_data']['document_id']==forms.document_id(obj['id'])
    assert forms.document_id('QC_261112_01')=='PQC_261112_01'
    assert obj['standard_url']=='QC_NVL_261101_V1'
    # A later release cannot replace the historical definition when this record is edited.
    original=deepcopy(obj['form_data']['definition'])
    monkeypatch.setitem(forms.RELEASED,'NVL','TEST_NEXT_RELEASE')
    edited={**data,'version':obj['version']}
    update=admin.put('/api/qc/'+obj['id'],json=edited)
    assert update.status_code==200, update.text
    assert update.json()['form_data']['definition']==original


def test_only_current_product_template_can_be_used(clients,qc_drive,monkeypatch):
    admin,reader,connection=clients
    source_data(connection)
    product=deepcopy(forms.QC_NVL_261101_V1)
    product.update(code='TEST_PRODUCT_V2',business='PRODUCT',version=2)
    monkeypatch.setitem(forms.REGISTRY,product['code'],product)
    monkeypatch.setitem(forms.RELEASED,'PRODUCT',product['code'])
    data=payload('SETUP','QC ĐẦU CA')
    data.update(form={**form_payload(),'code':product['code']},standard_url=product['code'])
    response=create(admin,data)
    assert response.status_code==201,response.text
    assert response.json()['form_data']['definition']['business']=='PRODUCT'
    wrong=payload();wrong['form']['code']=product['code'];wrong['standard_url']=product['code']
    assert create(admin,wrong).status_code==422
