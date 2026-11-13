"""Approved lifecycle and QC snapshot integrity, rollback-only MySQL and mocked Google."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
from cryptography.fernet import Fernet
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.integrations.google import sheets
from app.modules.qc import mapping, drive_bundle, evidence
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate
from app.modules.materials.purchasing.models import FilmPO, FilmLine
from app.modules.materials.models import FilmMaterial
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.qc.materials import receipt_window
from test_qc import create as legacy_create

pytestmark = pytest.mark.usefixtures('qc_drive')


def create(client,data,token=None):
    if data.get('mapped_form') and not data['mapped_form'].get('confirmation'):
        data['mapped_form'].setdefault('signature',[[[.1,.1],[.8,.7]]])
        confirmed=client.post('/api/qc/signatures/confirm',json=data)
        if confirmed.status_code!=200:return confirmed
        data['mapped_form']['confirmation']=confirmed.json()['confirmation']
    return legacy_create(client,data,token)


def sheet():
    rows = [['Hạng mục kiểm tra','Tiêu chuẩn kỹ thuật','Kết quả thực tế','Đánh giá','Dung sai'],
            ['1. Khổ rộng','Theo PO','mm','','± 2 mm'], ['2. Ngoại quan','Sạch','','','Không loang'],
            [], ['Thông tin ERP'], []]
    return {'spreadsheet_id':'test-mapping-source', 'sheet_id':42, 'sheet_title':'IQC', 'title':'QC',
        'row_count':6,'column_count':6,'truncated':False,'theme':{},
        'grid':{'rowData':[{'values':[{'formattedValue':value} for value in row]} for row in rows]},
        'merges':[{'startRowIndex':4,'endRowIndex':5,'startColumnIndex':0,'endColumnIndex':3}]}


def fields(reviewed=True):
    return [
        {'id':'qc','name':'Mã QC','kind':'ERP','cell':'A6','source':'qc_id','reviewed':reviewed},
        {'id':'po_width','name':'Khổ PO','kind':'ERP','cell':'B6','source':'width','reviewed':reviewed},
        {'id':'width','name':'Khổ rộng','kind':'INPUT','cell':'C2','data_type':'number','unit':'mm',
         'standard_cell':'B2','assessment_cell':'D2','allow_na':True,'reviewed':reviewed},
        {'id':'standard_width','name':'Tiêu chuẩn khổ','kind':'STANDARD','cell':'B2','reviewed':reviewed},
        {'id':'look','name':'Ngoại quan','kind':'INPUT','cell':'C3','standard_cell':'B3',
         'assessment_cell':'D3','allow_na':True,'reviewed':reviewed}]


def stage(admin, monkeypatch, reviewed=True):
    from app.modules.qc import signing
    secret=Fernet(Fernet.generate_key())
    monkeypatch.setattr(signing,'cipher',lambda:secret)
    monkeypatch.setattr(signing,'identity',lambda request,db,user:{'user_id':user.id,'name':user.name,
        'email':user.email,'google_subject':'test-subject','session':'test-session'})
    # The new policy permits exactly one effective common template. Isolate
    # pre-existing local templates inside the rollback-only test transaction.
    from app.main import app
    from app.core.database import get_db
    from app.integrations.google.models import GoogleCredential
    from sqlalchemy import update
    scope=app.dependency_overrides[get_db]();db=next(scope)
    db.execute(update(QCTemplate).values(status='INACTIVE'))
    if not db.get(GoogleCredential,'_TEST_ADMIN'):
        db.add(GoogleCredential(user_id='_TEST_ADMIN',subject='test-subject',encrypted_access='test-only',
            encrypted_refresh='test-only',expires_at=datetime(2099,1,1),scopes='test-only'))
    db.commit();scope.close()
    source = sheet()
    def read(db,user,identifier,preview=False):
        return {**deepcopy(source),'spreadsheet_id':sheets.spreadsheet_id(identifier)}
    monkeypatch.setattr(sheets,'first_tab',read)
    code='QC_TEST_'+uuid4().hex.upper()+'_V1'
    data={'form_code':code,'form_name':'QC mapping test','check_type':'QC NVL','object_type':'NVL',
          'spreadsheet':'test-mapping-'+uuid4().hex,'version':1,'status':'DRAFT'}
    result=admin.post('/api/qc/templates',json=data)
    assert result.status_code==201,result.text
    row=result.json();base='/api/qc/templates/'+row['id']
    proposed=admin.post(base+'/suggest',json={'expected_updated_at':row['updated_at']})
    assert proposed.status_code==200,proposed.text
    saved=admin.put(base+'/mapping',json={'expected_updated_at':row['updated_at'],
          'source_hash':proposed.json()['source_hash'],'fields':fields(reviewed),
          'signature_cell':'E4','signature_end_cell':'F6'})
    assert saved.status_code==200,saved.text
    return saved.json(),data,source


def release(admin,row):
    if row.get('approved_at') and row['status']=='ACTIVE':
        return row
    base='/api/qc/templates/'+row['id']
    approved=admin.post(base+'/approve',json={'expected_updated_at':row['updated_at']})
    assert approved.status_code==200,approved.text
    activated=admin.post(base+'/status',json={'expected_updated_at':approved.json()['updated_at'],'status':'ACTIVE'})
    assert activated.status_code==200,activated.text
    return activated.json()


def nvl(conn, identifier='_TEST_MAPPED_RECEIPT'):
    conn.execute(FilmMaterial.__table__.insert().values(id='_TEST_MAP_MAT',width=500,thickness='.3'))
    conn.execute(FilmPO.__table__.insert().values(id='_TEST_MAP_PO',order_date=receipt_window()[1]))
    conn.execute(FilmLine.__table__.insert().values(id='_TEST_MAP_LINE',po_id='_TEST_MAP_PO',material_id='_TEST_MAP_MAT',resin='PVC',quantity=800))
    conn.execute(FilmReceipt.__table__.insert().values(id=identifier,line_id='_TEST_MAP_LINE',receipt_date=receipt_window()[1],quantity=100))
    return {'check_type':'QC NVL','object_type':'NVL','object_id':identifier}


def qc_payload(row, selection, assessment='PASS'):
    return {**selection,'checked_at':datetime.now().isoformat(),'quantity':'2',
        'parent_folder_id':'mock-parent',
        'result':{'PASS':'OK','FAIL':'NG','NA':'N/A'}[assessment], 'mapped_form':{
            'template_id':row['id'],'source_hash':row['source_hash'],
            'mapping_hash':mapping.digest(row['mapping']),
            'answers':[{'id':'width','actual':'501','assessment':assessment},
                       {'id':'look','actual':'Sạch','assessment':assessment}], 'conclusion':assessment}}


def test_suggestion_never_reviews_and_keeps_standards():
    proposed=mapping.suggest(sheet())
    assert len([f for f in proposed['fields'] if f['kind']=='INPUT'])==2
    assert all(not f['reviewed'] for f in proposed['fields'])
    assert any(f['kind']=='STANDARD' for f in proposed['fields'])
    assert mapping.anchor(sheet(),'B5')=='A5'


@pytest.mark.parametrize('change', ['overlap','merge','outside','bad_source','standard_overwrite'])
def test_invalid_mapping_rejected(change):
    proposed=fields()
    if change=='overlap':proposed[1]['cell']='A6'
    elif change=='merge':proposed[0]['cell']='A5';proposed[1]['cell']='B5'
    elif change=='outside':proposed[0]['cell']='Z99'
    elif change=='bad_source':proposed[0]['source']='arbitrary_sql'
    elif change=='standard_overwrite':proposed[0]['cell']='B3'
    with pytest.raises(HTTPException):mapping.validate(sheet(),mapping.MappingInput(fields=proposed),'QC NVL',True)


def test_save_explicitly_approves_activates_and_freezes_mapping(clients,monkeypatch):
    admin,reader,_=clients
    row,metadata,_=stage(admin,monkeypatch,False);base='/api/qc/templates/'+row['id']
    active=row
    assert active['status']=='ACTIVE' and active['approved_at']
    assert active['approved_by']=='_TEST_ADMIN'
    assert admin.put('/api/qc/templates/'+row['id'],json={**metadata,'expected_updated_at':active['updated_at']}).status_code==409
    assert admin.put(base+'/mapping',json={'expected_updated_at':active['updated_at'],'source_hash':row['source_hash'],'fields':fields()}).status_code==409
    for path in ['mapping','suggest','approve','verify','status']:
        response=reader.get(base+'/mapping') if path=='mapping' else reader.post(base+'/'+path,json={'expected_updated_at':active['updated_at'],**({'status':'ACTIVE'} if path=='status' else {})})
        assert response.status_code==403,response.text


def test_active_matching_mysql_fill_and_history_defers_google_work(clients,monkeypatch):
    admin,_,conn=clients
    row,_,_=stage(admin,monkeypatch);active=release(admin,row);selection=nvl(conn)
    params=selection
    assert row['id'] in [item['id'] for item in admin.get('/api/qc/template-options',params=params).json()['items']]
    entry=admin.get('/api/qc/templates/'+row['id']+'/entry',params=params)
    assert entry.status_code==200,entry.text
    assert entry.json()['context']['width']=='500' and entry.json()['context']['resin']=='PVC'
    def forbidden(*args,**kwargs):raise AssertionError('QC mapped must not contact Google/Drive')
    monkeypatch.setattr(sheets,'first_tab',forbidden);monkeypatch.setattr(drive_bundle,'prepare',forbidden)
    monkeypatch.setattr(evidence,'schedule',forbidden)
    data=qc_payload(row,selection);token=str(uuid4());created=create(admin,data,token)
    assert created.status_code==201,created.text
    saved=created.json();assert create(admin,data,token).json()['id']==saved['id']
    assert saved['template_id']==row['id'] and saved['form_data']['auto_values']['qc']==saved['id']
    assert saved['form_data']['auto_values']['po_width']=='500' and saved['evidence_pending']
    assert saved['form_data']['signer']['user_id']=='_TEST_ADMIN'
    # A new version has an independent source and does not alter the saved V1 JSON.
    frozen=deepcopy(saved['form_data'])
    conn.execute(QCTemplate.__table__.update().where(QCTemplate.id==row['id']).values(STATUS='INACTIVE'))
    detail=admin.get('/api/qc/'+saved['id']).json()
    assert detail['form_data']==frozen
    assert admin.put('/api/qc/'+saved['id'],json={**data,'note':'Changed without signing again','version':detail['version']}).status_code==422
    assert admin.get('/api/qc/'+saved['id']+'/pdf').status_code==409


def test_na_not_pass_and_validation_rolls_back(clients,monkeypatch):
    admin,_,conn=clients
    row,_,_=stage(admin,monkeypatch);release(admin,row);selection=nvl(conn)
    bad=qc_payload(row,selection,'NA');bad['mapped_form']['conclusion']='PASS';bad['result']='OK'
    before=conn.scalar(select(func.count()).select_from(QualityCheck))
    assert create(admin,bad).status_code==422
    assert conn.scalar(select(func.count()).select_from(QualityCheck))==before
    bad=qc_payload(row,selection);bad['mapped_form']['answers'][0]['actual']='not a number'
    assert create(admin,bad).status_code==422
    created=create(admin,qc_payload(row,selection,'NA'))
    assert created.status_code==422,created.text
    mixed=qc_payload(row,selection)
    mixed['mapped_form']['answers'][0].update(actual='stale number',assessment='NA')
    created=create(admin,mixed)
    assert created.status_code==201,created.text
    assert created.json()['result']=='OK'
    assert created.json()['form_data']['input']['answers'][0]['actual']==''


def test_changed_google_source_deactivates_without_modifying_snapshot(clients,monkeypatch):
    admin,_,_=clients
    row,_,source=stage(admin,monkeypatch);active=release(admin,row)
    source['grid']['rowData'][1]['values'][1]['formattedValue']='Changed standard'
    response=admin.post('/api/qc/templates/'+row['id']+'/verify',json={'expected_updated_at':active['updated_at']})
    assert response.status_code==409,response.text
    detail=admin.get('/api/qc/templates/'+row['id']+'/mapping').json()
    assert detail['status']=='INACTIVE' and detail['source_matches'] is False
    assert detail['snapshot']['grid']['rowData'][1]['values'][1]['formattedValue']=='Theo PO'


def test_nonmatching_and_unapproved_templates_not_offered(clients,monkeypatch):
    admin,_,conn=clients
    row,_,_=stage(admin,monkeypatch);selection=nvl(conn)
    conn.execute(QCTemplate.__table__.update().where(QCTemplate.id==row['id']).values(STATUS='DRAFT',APPROVED_AT=None,APPROVED_BY=None))
    assert admin.get('/api/qc/template-options',params=selection).status_code==422
    row={**row,'approved_at':None,'status':'DRAFT'}
    release(admin,row)
    conn.execute(QCTemplate.__table__.update().where(QCTemplate.id==row['id']).values(PRODUCT_ID='_TEST_P2'))
    assert admin.get('/api/qc/template-options',params=selection).status_code==422
    assert create(admin,qc_payload(row,selection)).status_code==422


def test_new_version_cannot_reuse_approved_spreadsheet(clients,monkeypatch):
    admin,_,_=clients
    row,metadata,_=stage(admin,monkeypatch);release(admin,row)
    new={**metadata,'form_code':metadata['form_code'].replace('_V1','_V2'),'version':2}
    assert admin.post('/api/qc/templates',json=new).status_code==409
    new['spreadsheet']='test-version2-'+uuid4().hex
    created=admin.post('/api/qc/templates',json=new)
    assert created.status_code==201,created.text
    assert created.json()['approved_at'] is None and created.json()['status']=='DRAFT'


def test_criterion_notes_use_approved_snapshot_and_preserve_tolerance():
    source=sheet();source['grid']['rowData'][0]['values'][4]['formattedValue']='Dung sai / Ghi chú'
    layout={'fields':fields()}
    before=deepcopy(layout)
    targets=mapping.criterion_notes(source,layout)
    assert targets['width']=={'cell':'E2','base':'± 2 mm'}
    assert targets['look']=={'cell':'E3','base':'Không loang'}
    assert layout==before  # Existing released JSON remains immutable.
    proposals=mapping.suggest(source)['fields']
    assert next(f for f in proposals if f['kind']=='INPUT')['note_cell']=='E2'
    explicit=fields();explicit[2]['note_cell']='E2'
    assert mapping.validate(source,mapping.MappingInput(fields=explicit),'QC NVL')['fields'][2]['note_cell']=='E2'
    explicit[2]['note_cell']='B2'
    with pytest.raises(HTTPException):mapping.validate(source,mapping.MappingInput(fields=explicit),'QC NVL')
