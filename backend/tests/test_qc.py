"""Targeted QC tests using the existing rollback-only MySQL fixture."""
import re
from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from app.auth.models import RolePermission
from app.core.models import Audit
from app.modules.production.models import ProductionOrder, ProductionSetup, FormingLog, CuttingLog, EBLog
from app.modules.qc.models import QualityCheck
from app.modules.materials.receiving.models import FilmReceipt
from app.integrations.google import drive
from app.migrations.import_qc_production import prepare, scalar


def source_data(connection):
    connection.execute(ProductionOrder.__table__.insert().values(id='_TEST_LSX_QC', source={}))
    connection.execute(ProductionSetup.__table__.insert().values(id='_TEST_SETUP_QC', production_order_id='_TEST_LSX_QC', stage='HUT', source={}))
    connection.execute(FormingLog.__table__.insert().values(id='_TEST_HUT_QC', production_order_id='_TEST_LSX_QC', setup_id='_TEST_SETUP_QC', source={}))
    connection.execute(CuttingLog.__table__.insert().values(id='_TEST_CAT_QC', setup_id='_TEST_SETUP_QC', source={}))
    connection.execute(EBLog.__table__.insert().values(id='_TEST_EB_QC', setup_id='_TEST_SETUP_QC', source={}))
    connection.execute(FilmReceipt.__table__.insert().values(id='_TEST_NVL_QC', line_id='_TEST_DN_QC', status='OK', note='Giữ nguyên', source={}))


def payload(kind='NVL', check_type='QC NVL'):
    return {'check_type':check_type, 'object_type':kind, 'object_id':'_TEST_'+kind+'_QC',
            'checked_at':'2026-11-12T09:15:30.123456+07:00', 'quantity':'2.125', 'result':'NG',
            'standard_url':'https://drive.google.com/file/d/example/view',
            'note':'Sai ngoại quan. Người điều hành chờ quyết định.', 'image_url':''}


def create(client, data, token=None):
    return client.post('/api/qc', json=data, headers={'Idempotency-Key':token or str(uuid4())})


@pytest.mark.parametrize('check_type,kind', [('QC NVL','NVL'),('QC ĐẦU CA','SETUP')] +
                         [(check,kind) for check in ('QC GIỮA CA','QC CUỐI CA') for kind in ('HUT','CAT','EB')])
def test_all_qc_sources_and_search(clients, check_type, kind):
    admin, reader, connection = clients
    source_data(connection)
    data=payload(kind,check_type)
    response=create(admin,data)
    assert response.status_code==201,response.text
    record=response.json()
    assert re.fullmatch(r'QC_\d{6}_\d{2}',record['id'])
    assert record['production_order_id']==(None if kind=='NVL' else '_TEST_LSX_QC')
    assert record['staff_id']=='_TEST_ADMIN'
    assert record['result']=='NG' and record['note']==data['note']
    response=admin.get('/api/qc/objects',params={'check_type':check_type,'object_type':kind,'q':'_TEST_','size':1})
    assert response.status_code==200,response.text
    assert data['object_id'] in {row['id'] for row in response.json()['items']}
    assert admin.get('/api/qc/'+record['id']).json()['standard_url']==data['standard_url']
    assert connection.scalar(select(FilmReceipt.status).where(FilmReceipt.id=='_TEST_NVL_QC'))=='OK'
    assert connection.scalar(select(FilmReceipt.iqc_id).where(FilmReceipt.id=='_TEST_NVL_QC'))==''


def test_validation_idempotency_edit_and_rollback(clients):
    admin, reader, connection=clients
    source_data(connection)
    before=connection.scalar(select(func.count()).select_from(QualityCheck))
    bad=[{**payload(),'object_id':'_TEST_EB_QC'}, {**payload(),'object_type':'EB'},
         {**payload(),'standard_url':'javascript:alert(1)'}, {**payload(),'image_url':'https://user:password@example.com'},
         {**payload(),'quantity':'-1'}, {**payload(),'quantity':'NaN'}, {**payload(),'checked_at':'bad'},
         {**payload(),'staff_id':'forged'}, {**payload(),'production_order_id':'forged'}]
    for data in bad:
        assert create(admin,data).status_code==422
    assert connection.scalar(select(func.count()).select_from(QualityCheck))==before
    token=str(uuid4())
    first=create(admin,payload(),token)
    assert first.status_code==201,first.text
    saved=first.json()
    assert admin.get('/api/qc/'+saved['id']).json()==saved
    assert create(admin,payload(),token).json()==saved
    assert create(admin,{**payload(),'note':'Khác nội dung'},token).status_code==409
    assert connection.scalar(select(func.count()).select_from(QualityCheck))==before+1
    edit={**payload(),'result':'OK','note':'Đã kiểm tra lại','version':saved['version']}
    assert reader.put('/api/qc/'+saved['id'],json=edit).status_code==403
    updated=admin.put('/api/qc/'+saved['id'],json=edit)
    assert updated.status_code==200,updated.text
    assert updated.json()['version']!=saved['version']
    assert admin.put('/api/qc/'+saved['id'],json=edit).status_code==409
    assert connection.scalar(select(func.count()).select_from(Audit).where(Audit.entity_id==saved['id']))==2
    # Orphan LSX references must not become trusted links.
    connection.execute(ProductionSetup.__table__.update().where(ProductionSetup.id=='_TEST_SETUP_QC').values(production_order_id='_MISSING'))
    assert create(admin,payload('SETUP','QC ĐẦU CA')).status_code==422


def test_qc_permissions_filters_pagination_and_drive(clients,monkeypatch):
    admin,reader,connection=clients
    source_data(connection)
    for path in ['/api/qc','/qc/list','/qc/create','/qc/ncr','/api/qc/drive?q=test',
                 '/api/qc/objects?check_type=QC%20NVL&object_type=NVL&q=test']:
        assert reader.get(path).status_code==403,path
    assert create(reader,payload()).status_code==403
    connection.execute(RolePermission.__table__.insert().values(role='TEST_READER',permission='QC_VIEW',allowed=True))
    saved=create(admin,payload()).json()
    assert reader.get('/api/qc/'+saved['id']).status_code==200
    assert create(reader,payload()).status_code==403
    params={'q':saved['id'],'check_type':'QC NVL','object_type':'NVL','object_id':'_TEST_NVL_QC',
            'date_from':'2026-11-12','date_to':'2026-11-12','size':1}
    listing=reader.get('/api/qc',params=params)
    assert listing.status_code==200,listing.text
    assert listing.json()['total']==1 and len(listing.json()['items'])==1
    assert reader.get('/api/qc',params={**params,'page':2}).json()['items']==[]
    assert reader.get('/api/qc',params={**params,'production_order_id':'_OTHER'}).json()['total']==0
    assert reader.get('/api/qc?date_from=2026-11-13&date_to=2026-11-12').status_code==422
    assert reader.get('/api/qc?q=%25_OR_1%3D1').json()['total']==0
    calls=[]
    def search(db,user,keyword):
        calls.append((user.id,keyword))
        return {'success':True,'files':[{'name':'Hồ sơ QC','url':'https://docs.google.com/document/d/example/edit'}]}
    monkeypatch.setattr(drive,'search',search)
    assert reader.get('/api/qc/drive?q=QC').status_code==403
    connection.execute(RolePermission.__table__.insert().values(role='TEST_READER',permission='QC_CREATE',allowed=True))
    response=reader.get('/api/qc/drive?q=QC')
    assert response.status_code==200 and response.json()['files'][0]['name']=='Hồ sơ QC'
    assert calls==[('_TEST_READER','QC')]
    assert reader.get('/api/qc/objects?check_type=QC%20NVL&object_type=NVL').json()['items']==[]
    # An empty direct LSX must still display the verified link through SETUP.
    connection.execute(FormingLog.__table__.update().where(FormingLog.id=='_TEST_HUT_QC').values(production_order_id=''))
    found=admin.get('/api/qc/objects',params={'check_type':'QC GIỮA CA','object_type':'HUT','q':'_TEST_HUT_QC'}).json()
    assert found['items'][0]['production_order_id']=='_TEST_LSX_QC'


def test_workbook_import_contract(tmp_path):
    from openpyxl import Workbook
    from app.migrations.import_qc_production import SOURCES
    book=Workbook();book.remove(book.active)
    for name,model in SOURCES:
        sheet=book.create_sheet(name)
        headers=[c.name for c in model.__table__.columns if c.key!='source' and c.name!='OBJECT_TYPE']
        if model is EBLog:headers[headers.index('EB_ID')]='CUT_ID'
        sheet.append(headers)
        if model in {EBLog,CuttingLog}:
            row=['']*len(headers);row[0]='CUT_261020_01';row[1]='19/10/2026';sheet.append(row)
            orphan=['']*len(headers);orphan[1]='20/10/2026';sheet.append(orphan)
    path=tmp_path/'source.xlsx';book.save(path)
    checksum,prepared,skipped=prepare(path)
    assert len(checksum)==64 and len(skipped)==2
    assert prepared[EBLog][0].id=='CUT_261020_01'
    assert prepared[EBLog][0].run_date==date(2026,10,19)
    assert prepared[EBLog][0].source['EB_ID']=='CUT_261020_01'
    assert EBLog.__table__.c.id.name=='EB_ID'
    book['SX-FM-01E_EB_LOG'].append(['CUT_261020_01'])
    book.save(path)
    with pytest.raises(ValueError,match='mã trùng'):prepare(path)
    with pytest.raises(ValueError):scalar('NaN',QualityCheck.__table__.c.quantity)
