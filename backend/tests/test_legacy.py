import secrets
from decimal import Decimal
from sqlalchemy import select, func
from app.models import Customer, Product, Order, OrderLine
from app.film_models import FilmPO, FilmLine, FilmReceipt, FilmMovement, LegacyState


class RPC:
    def __init__(self,client):
        self.client=client
        self.revision=None

    def call(self,method,*args,request_id=None):
        response=self.client.post('/api/legacy/'+method,json={'args':list(args),'revision':self.revision,
                'request_id':request_id or secrets.token_hex(16)})
        assert response.status_code==200,response.text
        envelope=response.json();self.revision=envelope['revision']
        result=envelope.get('result')
        assert not (isinstance(result,dict) and result.get('success') is False),str(result)
        return result


def web_order(po='LOCAL-TEST-COMPAT',new_customer=False):
    return {'webOrder':True,'requestId':secrets.token_hex(16),'poGroups':[
        {'customerId':'' if new_customer else '_TEST_C1','customerName':'Khách mới kiểm thử local' if new_customer else 'Khách kiểm thử',
         'soPO':po,'salesPerson':'_TEST_ADMIN','ngayDat':'2026-11-11','ngayGiaoDK':'2026-11-21',
         'orderNote':'','existingFileUrl':'','items':[
             {'spId':'','prodName':'Sản phẩm mới kiểm thử local','codeSP':'TEST-CODE','unit':'Cái','qty':10,
              'price':1200,'giaKhuon':200000,'mang':'PET 0.3','type':'1','donggoi':'Thùng',
              'ngayDat':'2026-11-11','ngayGiao':'2026-11-21','note':'Ghi chú thử','isNew':True}]}]}


def test_all_original_screens_and_menu_render(clients):
    client,_,_=clients
    for view in ['index','create','list','be','film','film-create','film-receive','film-stock']:
        response=client.get('/?view='+view)
        assert response.status_code==200,response.text[:500]
        assert 'Lỗi khởi chạy ứng dụng' not in response.text,response.text[:1000]
        assert '/static/legacy-bridge.js' in response.text
        assert 'erp-module-link' in response.text
        assert '<?' not in response.text


def test_all_original_read_contracts(clients):
    client,_,_=clients;rpc=RPC(client)
    query=rpc.call('queryOrdersAndLineItems',{'viewMode':'ALL_VIEWS','productType':'1','status':'ALL'})
    assert query['success'] is True
    rpc.call('getOrderFormData');rpc.call('getOrderModalInitData','')
    saved_page=rpc.call('getSavedOrderListPage',{'view':'be','orders':'DH_261024_01'})
    assert '/static/legacy-bridge.js' in saved_page
    rpc.call('apiGetLineKanbanData')
    film=rpc.call('getFilmOrders',{})
    assert film['setup']==[],film['setup']
    rpc.call('getFilmOrderFormData',None,True)
    products=rpc.call('getFilmProducts');assert products
    rpc.call('getFilmProductReference',products[0]['id'])
    rpc.call('getFilmReceiptLines');rpc.call('getFilmStock',{})
    rpc.call('getFilmPendingReturns')
    if film['orders']:
        po=film['orders'][0];line=po['lines'][0]['DN_ID']
        rpc.call('getFilmOrders',{'orderId':po['PO_NVL_ID'],'formData':True})
        rpc.call('getFilmOrderAssignments',[line])
        rpc.call('getFilmAssignedDetails',line)
        rpc.call('getFilmAssignmentOptions',line)
        rpc.call('getFilmReceiptHistory',line)


def test_original_multi_po_creation_new_catalog_and_retry(clients):
    client,_,conn=clients;rpc=RPC(client);rpc.call('getOrderFormData')
    before=conn.scalar(select(func.count()).select_from(Order))
    payload=web_order(new_customer=True)
    second=web_order('LOCAL-TEST-SECOND')['poGroups'][0]
    payload['poGroups'].append(second)
    saved=rpc.call('saveOrderTransaction',payload)
    assert len(saved['createdOrders'])==2
    assert saved['newCustomerCount']==1
    assert saved['newProductCount']==2
    assert conn.scalar(select(func.count()).select_from(Order))==before+2
    retry=rpc.call('saveOrderTransaction',payload)
    assert retry['createdOrders']==saved['createdOrders']
    assert conn.scalar(select(func.count()).select_from(Order))==before+2
    line=conn.execute(select(OrderLine).where(OrderLine.order_id==saved['createdOrders'][0]['maDH'])).first()
    assert line is not None


def create_film(rpc):
    catalog=rpc.call('getFilmOrders',{'create':True,'formData':True})
    supplier=catalog['suppliers'][0]['Ma_NCC']
    payload={'supplier':supplier,'date':'2026-11-11','note':'LOCAL-TEST','token':secrets.token_hex(16),
             'lines':[{'resin':'PET','grade':'NS','color':'Trong','esd':'','thickness':'0.31','width':'555',
                       'qty':100,'price':20000,'delivery':'2026-11-21','note':'test',
                       'detailIds':[],'originalIds':[]}]}
    saved=rpc.call('saveFilmOrder',payload)
    order=rpc.call('getFilmOrders',{'orderId':saved['id'],'formData':True})['orders'][0]
    return order,payload


def test_film_create_receive_idempotency_and_stock(clients):
    client,_,conn=clients;rpc=RPC(client)
    before=conn.scalar(select(func.count()).select_from(FilmPO))
    po,payload=create_film(rpc)
    assert conn.scalar(select(func.count()).select_from(FilmPO))==before+1
    assert rpc.call('saveFilmOrder',payload)['id']==po['PO_NVL_ID']
    line=po['lines'][0]['DN_ID']
    receive={'token':'12345678-1234-1234-1234-123456789012','receipts':[
        {'dn':line,'received':0,'ordered':100,'date':'2026-11-11','productionDate':'2026-11-10',
         'rolls':2,'kg':60,'quality':'OK','location':'TEST-A','note':''}]}
    saved=rpc.call('saveFilmReceipts',receive)
    assert len(saved['ids'])==1
    again=rpc.call('saveFilmReceipts',receive)
    assert again==saved
    receipt=conn.execute(select(FilmReceipt.quantity).where(FilmReceipt.id==saved['ids'][0])).scalar_one()
    assert receipt==Decimal('60')
    stock=rpc.call('getFilmStock',{})
    assert any(x['id']==saved['ids'][0] and x['stock']==60 for x in stock['rows'])
    history=rpc.call('getFilmReceiptHistory',line)
    assert history[0]['id']==saved['ids'][0]


def test_original_bulk_edit_and_kanban(clients):
    client,_,conn=clients;rpc=RPC(client);rpc.call('getOrderFormData')
    saved=rpc.call('saveOrderTransaction',web_order())
    oid=saved['createdOrders'][0]['maDH']
    lid=conn.execute(select(OrderLine.id).where(OrderLine.order_id==oid)).scalar_one()
    edit=rpc.call('updateOrderLineItemsBulk',{'targetIds':[lid],'fieldsToUpdate':{'soLuongDat':25,'donGia':1500,'dvt':'Cái','codeSP':'UPDATED'}})
    assert edit['success'] is True
    quantity=conn.execute(select(OrderLine.quantity).where(OrderLine.id==lid)).scalar_one()
    assert quantity==Decimal('25')
    result=rpc.call('apiUpdateLineKanbanPositions',{'updates':[{'idChiTiet':lid,'vungHienThi':'UU_TIEN','thuTu':1}]})
    assert result['success'] is True
    assert conn.execute(select(OrderLine.zone).where(OrderLine.id==lid)).scalar_one()=='UU_TIEN'


def test_original_concurrency_contract_and_non_whitelisted_functions_blocked(clients):
    client,_,conn=clients;rpc=RPC(client);rpc.call('getOrderFormData');old=rpc.revision
    payload=web_order();key=secrets.token_hex(16)
    saved=rpc.call('saveOrderTransaction',payload,request_id=key)
    retry=client.post('/api/legacy/saveOrderTransaction',json={'args':[payload],
                      'revision':old,'request_id':key})
    assert retry.status_code==200
    assert retry.json()['result']==saved
    result=client.post('/api/legacy/saveOrderTransaction',json={'args':[web_order('OTHER')],
                      'revision':old,'request_id':secrets.token_hex(16)})
    assert result.status_code==200  # unrelated changes do not force every old screen to reload
    assert client.post('/api/legacy/setupSystemProperties',json={'args':[],'request_id':secrets.token_hex(16)}).status_code==404
    film,payload=create_film(rpc)
    edit={**payload,'id':film['PO_NVL_ID'],'revision':film['revision'],
          'lines':[{**payload['lines'][0],'id':film['lines'][0]['DN_ID']}],'note':'Changed'}
    rpc.call('saveFilmOrder',edit)
    stale=client.post('/api/legacy/saveFilmOrder',json={'args':[{**edit,'note':'Other'}],
                      'revision':rpc.revision,'request_id':secrets.token_hex(16)})
    assert stale.status_code==422  # original per-PO revision is still enforced


def test_film_assignment_round_trip(clients):
    client,_,conn=clients;rpc=RPC(client);rpc.call('getOrderFormData')
    order=rpc.call('saveOrderTransaction',web_order())['createdOrders'][0]['maDH']
    detail=conn.execute(select(OrderLine.id).where(OrderLine.order_id==order)).scalar_one()
    film,_=create_film(rpc);line=film['lines'][0]['DN_ID']
    rpc.call('saveFilmAssignments',line,[],[detail])
    assert conn.execute(select(OrderLine.film_line_id).where(OrderLine.id==detail)).scalar_one()==line
    rpc.call('getFilmAssignedDetails',line)
    rpc.call('saveFilmAssignments',line,[detail],[])
    assert conn.execute(select(OrderLine.film_line_id).where(OrderLine.id==detail)).scalar_one()==''


def test_confirm_return_updates_stock_once(clients):
    client,_,conn=clients;rpc=RPC(client)
    receipt=conn.execute(select(FilmReceipt.id).limit(1)).scalar_one()
    conn.execute(FilmMovement.__table__.insert(),[
       {'id':'_TEST_ISSUE','moved_at':'2026-11-11 10:00:00','kind':'CẤP NVL','receipt_id':receipt,'quantity':10,
        'production_order_id':'_TEST_SX','issuer_id':'_TEST_ADMIN','receiver_id':'_TEST_ADMIN','source':{}},
       {'id':'_TEST_RETURN','moved_at':'2026-11-11 11:00:00','kind':'TRẢ NVL','receipt_id':receipt,'quantity':2,
        'production_order_id':'_TEST_SX','issuer_id':'_TEST_ADMIN','receiver_id':'','source':{}}])
    before=rpc.call('getFilmStock',{})
    stock_before=next(x['stock'] for x in before['rows'] if x['id']==receipt)
    assert rpc.call('getFilmPendingReturns')['count']>=1
    saved=rpc.call('confirmFilmReturn',{'id':'_TEST_RETURN','kg':2})
    assert saved['kg']==2
    after=rpc.call('getFilmStock',{})
    assert next(x['stock'] for x in after['rows'] if x['id']==receipt)==stock_before+2
    assert rpc.call('confirmFilmReturn',{'id':'_TEST_RETURN','kg':2})['alreadyConfirmed'] is True


def test_drive_without_credentials_fails_explicitly_without_saving(clients):
    client,_,conn=clients;rpc=RPC(client);rpc.call('getOrderFormData')
    before=conn.scalar(select(func.count()).select_from(Order))
    search=client.post('/api/legacy/searchUserDriveFiles',json={'args':['test'],'request_id':secrets.token_hex(16)})
    assert search.status_code==200
    assert search.json()['result']['success'] is False
    payload=web_order();payload['poGroups'][0]['fileData']={'fileName':'test.pdf','mimeType':'application/pdf','base64':'dGVzdA=='}
    result=client.post('/api/legacy/saveOrderTransaction',json={'args':[payload],'revision':rpc.revision,'request_id':secrets.token_hex(16)})
    assert result.status_code==200
    assert result.json()['result']['success'] is False
    assert conn.scalar(select(func.count()).select_from(Order))==before


def test_receipt_retry_notes_follow_ids_when_new_receipts_sort_differently(clients):
    client,_,conn=clients;rpc=RPC(client);film,_=create_film(rpc)
    line=film['lines'][0]['DN_ID']
    first={'token':'aaaaaaaa-1234-1234-1234-123456789012','receipts':[
        {'dn':line,'received':0,'ordered':100,'date':'2026-11-11','productionDate':'2026-11-10','rolls':1,'kg':10,'quality':'OK','note':''}]}
    saved=rpc.call('saveFilmReceipts',first)
    second={'token':'bbbbbbbb-1234-1234-1234-123456789012','receipts':[
        {'dn':line,'received':10,'ordered':100,'date':'2026-11-10','productionDate':'2026-11-09','rolls':1,'kg':10,'quality':'OK','note':''}]}
    rpc.call('saveFilmReceipts',second)
    assert rpc.call('saveFilmReceipts',first)==saved


def test_unresolved_customer_reference_is_not_silently_assigned_to_new_customer(clients):
    client,_,conn=clients
    product=conn.execute(select(Product.id,Product.source_customer_id).where(Product.customer_id.is_(None),Product.source_customer_id!='').limit(1)).one()
    conn.execute(Customer.__table__.insert().values(id=product.source_customer_id,name='Khách mới trùng mã tham chiếu cũ',source={}))
    data=RPC(client).call('getOrderFormData')
    visible=next(p for p in data['products'] if p['spId']==product.id)
    assert visible['customerId']==''
    assert conn.execute(select(Product.source_customer_id).where(Product.id==product.id)).scalar_one()==product.source_customer_id
    assert conn.execute(select(Product.customer_id).where(Product.id==product.id)).scalar_one() is None
