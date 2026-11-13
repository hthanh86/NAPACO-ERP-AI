from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, func
from app.core.models import Audit
from app.compatibility.models import LegacyRequest
from app.modules.qc.models import QualityCheck
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.purchasing.models import FilmPO, FilmLine
from app.modules.materials.models import FilmMaterial, FilmSupplier
from app.modules.orders.models import OrderLine
from app.modules.qc.materials import receipt_window
from test_qc import payload, create


def receipt(connection, identifier, **values):
    connection.execute(FilmReceipt.__table__.insert().values(
        id=identifier, receipt_date=values.pop('receipt_date',receipt_window()[1]),
        quantity=values.pop('quantity',100), line_id='_TEST_DN_IQC', source={}, **values))


def batch(client, items, token=None):
    return client.post('/api/qc/batch',json={'items':items},headers={'Idempotency-Key':token or str(uuid4())})


def test_iqc_candidates_stock_window_metadata_and_duplicates(clients):
    admin,reader,connection=clients
    start,today=receipt_window()
    connection.execute(FilmSupplier.__table__.insert().values(id='_TEST_NCC_IQC',name='Nhà cung cấp IQC'))
    connection.execute(FilmMaterial.__table__.insert().values(id='_TEST_VL_IQC',grade='A',color='Trắng',esd='ESD',thickness='0.3',width=500))
    connection.execute(FilmPO.__table__.insert().values(id='_TEST_PO_IQC',supplier_id='_TEST_NCC_IQC'))
    connection.execute(FilmLine.__table__.insert().values(id='_TEST_DN_IQC',po_id='_TEST_PO_IQC',material_id='_TEST_VL_IQC',resin='PET'))
    # The existing fixture supplies products/customers, but not an order.
    from app.modules.orders.models import Order
    connection.execute(Order.__table__.insert().values(id='_TEST_ORDER_IQC',customer_id='_TEST_C1'))
    connection.execute(OrderLine.__table__.insert().values(id='_TEST_LINE_IQC',order_id='_TEST_ORDER_IQC',product_id='_TEST_P1',film_line_id='_TEST_DN_IQC',quantity=1,price=1,source={}))
    for suffix,values in [('TODAY',{}),('BOUNDARY',{'receipt_date':start}),('OLD',{'receipt_date':start-timedelta(days=1)}),
                          ('FUTURE',{'receipt_date':today+timedelta(days=1)}),('EMPTY',{}),('PENDING',{}),('RETURNED',{}),('CHECKED',{})]:
        receipt(connection,'_TEST_IQC_'+suffix,**values)
    for suffix,kind,quantity,receiver in [('EMPTY','CẤP NVL',100,''),('PENDING','CẤP NVL',100,''),
                                        ('PENDING','TRẢ NVL',10,''),('RETURNED','CẤP NVL',100,''),('RETURNED','TRẢ NVL',10,'_TEST_ADMIN')]:
        connection.execute(FilmMovement.__table__.insert().values(id='_TEST_MV_'+suffix+str(quantity)+kind,
                           receipt_id='_TEST_IQC_'+suffix,kind=kind,quantity=quantity,receiver_id=receiver))
    saved=create(admin,{**payload(),'object_id':'_TEST_IQC_CHECKED'}).json()
    params={'check_type':'QC NVL','object_type':'NVL','q':'_TEST_IQC_','size':50}
    response=admin.get('/api/qc/objects',params=params)
    assert response.status_code==200,response.text
    items=response.json()['items']
    assert {row['id'] for row in items}=={'_TEST_IQC_TODAY','_TEST_IQC_BOUNDARY','_TEST_IQC_RETURNED'}
    assert all(row['supplier']=='Nhà cung cấp IQC' and row['resin']=='PET' and row['products']==['Sản phẩm thử'] and '0.3 × 500' in row['specification'] for row in items)
    assert len(admin.get('/api/qc/objects',params={**params,'q':'Nhà cung cấp IQC'}).json()['items'])>=3
    product_results=admin.get('/api/qc/objects',params={**params,'q':'Sản phẩm thử'}).json()['items']
    assert {'_TEST_IQC_TODAY','_TEST_IQC_BOUNDARY','_TEST_IQC_RETURNED'}.issubset({row['id'] for row in product_results})
    assert admin.get('/api/qc/objects',params={**params,'size':1}).json()['has_more'] is True
    assert len(admin.get('/api/qc/objects',params={**params,'size':1,'page':2}).json()['items'])==1
    assert create(admin,{**payload(),'object_id':'_TEST_IQC_CHECKED'}).status_code==422
    assert create(admin,{**payload(),'object_id':'_TEST_IQC_OLD'}).status_code==422
    # Editing an existing IQC remains possible after its receipt ages out or is consumed.
    connection.execute(FilmReceipt.__table__.update().where(FilmReceipt.id=='_TEST_IQC_CHECKED').values(receipt_date=start-timedelta(days=10),quantity=0))
    assert admin.put('/api/qc/'+saved['id'],json={**payload(),'object_id':'_TEST_IQC_CHECKED','version':saved['version'],'note':'Chỉnh kết quả'}).status_code==200
    listing=admin.get('/api/qc',params={'q':saved['id']}).json()['items'][0]
    assert listing['staff_name']=='Kiểm thử' and 'evidence' in listing
    assert QualityCheck.__table__.c.image_url.name=='evidence'


def test_iqc_batch_atomic_limit_replay_and_permissions(clients):
    admin,reader,connection=clients
    for index in range(12):receipt(connection,'_TEST_BATCH_'+str(index))
    items=[{**payload(),'object_id':'_TEST_BATCH_'+str(index)} for index in range(10)]
    before=connection.scalar(select(func.count()).select_from(QualityCheck))
    audit_before=connection.scalar(select(func.count()).select_from(Audit))
    assert batch(reader,items).status_code==403
    assert batch(admin,items+[items[0]]).status_code==422
    assert batch(admin,[]).status_code==422
    assert batch(admin,[items[0],items[0]]).status_code==422
    assert batch(admin,[{**items[0],'check_type':'QC ĐẦU CA','object_type':'SETUP'}]).status_code==422
    # One invalid receipt rolls the entire batch back, including the request row.
    token=str(uuid4())
    assert batch(admin,[items[0],{**items[1],'object_id':'_MISSING'}],token).status_code==422
    assert connection.scalar(select(func.count()).select_from(QualityCheck))==before
    assert connection.scalar(select(func.count()).select_from(Audit))==audit_before
    assert connection.scalar(select(LegacyRequest.id).where(LegacyRequest.id=='qcb:'+token)) is None
    token=str(uuid4())
    response=batch(admin,items,token)
    assert response.status_code==201,response.text
    results=response.json()['items']
    assert len(results)==10 and len({item['id'] for item in results})==10
    assert batch(admin,items,token).json()==response.json()
    assert batch(admin,[items[0]],token).status_code==409
    assert connection.scalar(select(func.count()).select_from(QualityCheck))==before+10
    assert connection.scalar(select(func.count()).select_from(Audit))==audit_before+10
    assert create(admin,items[0]).status_code==422
    assert batch(admin,[items[0],{**payload(),'object_id':'_TEST_BATCH_10'}]).status_code==422
    assert connection.scalar(select(func.count()).select_from(QualityCheck).where(QualityCheck.object_id=='_TEST_BATCH_10'))==0


def test_iqc_batch_rolls_back_after_partial_flush(clients, monkeypatch):
    from fastapi import HTTPException
    from app.modules.qc import service
    admin,reader,connection=clients
    for index in range(2):receipt(connection,'_TEST_ATOMIC_'+str(index))
    before=connection.scalar(select(func.count()).select_from(QualityCheck))
    requests_before=connection.scalar(select(func.count()).select_from(LegacyRequest))
    apply=service.apply_values
    calls=[]
    def fail_second(*args):
        calls.append(1)
        if len(calls)==2:raise HTTPException(422,'Lỗi kiểm thử sau khi ghi phiếu đầu')
        return apply(*args)
    monkeypatch.setattr(service,'apply_values',fail_second)
    response=batch(admin,[{**payload(),'object_id':'_TEST_ATOMIC_'+str(index)} for index in range(2)])
    assert response.status_code==422 and len(calls)==2
    assert connection.scalar(select(func.count()).select_from(QualityCheck))==before
    assert connection.scalar(select(func.count()).select_from(LegacyRequest))==requests_before
import pytest

pytestmark = pytest.mark.usefixtures('qc_drive')
