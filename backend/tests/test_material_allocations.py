"""Stage-2 API and accounting tests in SQLite RAM. No ERP/MySQL writes."""
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from test_production_planning import planning, machine, standard
from app.core.database import Base
from app.compatibility.models import LegacyState
from app.modules.orders.models import Order,OrderLine
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.purchasing.models import FilmPO,FilmLine
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_models import MaterialAllocation,AllocationMovement
from app.modules.materials.inventory.allocation_api import router
from app.modules.materials.inventory import allocation_service as service
from app.modules.production.models import ProductionOrder,FormingLog

P='/api/production/materials/'


@pytest.fixture
def prepared(planning):
    names=['legacy_state','legacy_requests','orders','order_lines','film_purchase_orders','film_order_lines',
        'film_receipts','film_movements','production_orders','forming_logs','material_allocations','material_allocation_movements']
    Base.metadata.create_all(planning.engine,tables=[Base.metadata.tables[n] for n in names])
    planning.client.app.include_router(router)
    with Session(planning.engine) as db:
        db.add(LegacyState(id=1,revision=1,properties={},metadata_entries={},cell_notes={}))
        db.add(Order(id='O1',customer_id='C1',po_number='PO1'));db.flush()
        db.add_all([OrderLine(id='CT1',order_id='O1',product_id='P1',quantity=100,produced=40,delivered=95,unit='Cái',film_line_id='DN1'),
            OrderLine(id='CT2',order_id='O1',product_id='P2',quantity=100,produced=0,unit='Cái')])
        db.add(FilmPO(id='POFILM1',status='Đang đặt'))
        db.add(FilmLine(id='DN1',po_id='POFILM1',material_id='F1',resin='PET',quantity=150,status='Nhận một phần'))
        db.add_all([FilmReceipt(id='R1',line_id='DN1',quantity=100,status='OK'),FilmReceipt(id='R_NG',line_id='DN1',quantity=5,status='NG')])
        db.add_all([ProductionOrder(id='LSX1',order_line_id='CT1',product_id='P1',machine_id='DH1',source={}),
            ProductionOrder(id='LSX2',order_line_id='CT2',product_id='P2',machine_id='DH1',source={})])
        db.commit()
    c=planning.client
    assert c.post('/api/production/machines',json=machine()).status_code==201
    response=c.post('/api/production/standards',json=standard());assert response.status_code==201,response.text
    planning.standard_id=response.json()['id']
    yield planning


def write(c,path,data,method='post',key=None):
    return getattr(c,method)(P+path,json=data,headers={'Idempotency-Key':key or str(uuid4())})


def reserve(p,kg=80,line='CT1',receipt='R1',key=None):
    return write(p.client,'allocations',{'receipt_id':receipt,'order_line_id':line,'standard_id':p.standard_id,'kg':str(kg)},key=key)


def issue(p,allocation,kg=20,order='LSX1',key=None):
    return write(p.client,'allocations/'+allocation['id']+'/issue',{'version':allocation['version'],'production_order_id':order,'kg':str(kg)},key=key)


def balances(p):
    with Session(p.engine) as db:return service.receipt_balances(db,['R1'])['R1']


def test_hold_capacity_release_and_idempotency(prepared):
    p=prepared;c=p.client
    key=str(uuid4());response=reserve(p,80,key=key);assert response.status_code==201,response.text
    a=response.json()
    assert reserve(p,80,key=key).json()['id']==a['id']
    assert reserve(p,81,key=key).status_code==409
    assert reserve(p,30,line='CT2').status_code==409
    assert reserve(p,10,receipt='R_NG').status_code==422
    assert balances(p)['available_kg']==Decimal(20)
    response=write(c,'allocations/'+a['id'],{'version':1,'held_kg':'50','note':'Release unused'},method='put')
    assert response.status_code==200,response.text
    assert write(c,'allocations/'+a['id'],{'version':1,'held_kg':'0','note':'Stale'},method='put').status_code==409
    assert balances(p)['available_kg']==Decimal(50)
    assert reserve(p,50,line='CT2').status_code==201
    assert balances(p)['available_kg']==0


def test_issue_consumes_hold_once_and_return_requires_confirmation(prepared):
    p=prepared;c=p.client;a=reserve(p).json()
    assert issue(p,a,order='LSX2').status_code==422
    assert issue(p,a,kg=81).status_code==409
    key=str(uuid4());response=issue(p,a,key=key);assert response.status_code==201,response.text
    moved=response.json();assert moved['allocation']['held_kg']=='60.00000000'
    assert issue(p,a,key=key).json()['movement_id']==moved['movement_id']
    b=balances(p);assert b['stock_kg']==80 and b['held_kg']==60 and b['available_kg']==20
    row=c.get('/api/production/preparation?line_id=CT1').json()['items'][0]
    assert row['at_machine_kg'] is None and row['machine_balance_status']=='unknown'
    response=write(c,'issues/'+moved['movement_id']+'/return',{'kg':'5','note':'Physically counted 5kg'})
    assert response.status_code==201,response.text
    returned=response.json();assert balances(p)['stock_kg']==80
    response=write(c,'returns/'+returned['id']+'/confirm',{'kg':'5'});assert response.status_code==200,response.text
    assert balances(p)['stock_kg']==85
    assert write(c,'returns/'+returned['id']+'/confirm',{'kg':'5'}).json()['alreadyConfirmed']
    assert balances(p)['stock_kg']==85


def test_readiness_produced_is_not_delivered_and_expected_stock_is_not_held(prepared):
    p=prepared;c=p.client
    row=c.get('/api/production/preparation?line_id=CT1').json()['items'][0]
    assert Decimal(row['remaining_to_produce'])==60
    assert Decimal(row['demand']['sheets'])==15
    assert Decimal(row['demand']['base_kg'])==Decimal('2.625')
    assert Decimal(row['demand']['waste_kg'])==Decimal('0.07875')
    assert Decimal(row['held_kg'])==0 and row['material_status']=='none'
    assert Decimal(row['expected_source']['unreceived_kg'])==45
    assert c.get(P+'sources',params={'order_line_id':'CT1','standard_id':p.standard_id}).json()['total']==1
    assert c.get('/api/production/preparation?size=1').json()['total']==2
    assert reserve(p,3).status_code==201
    row=c.get('/api/production/preparation?line_id=CT1').json()['items'][0]
    assert row['material_status']=='enough'
    assert c.get('/api/production/preparation?has_hold=true').json()['total']==1


def test_journal_estimate_grams_and_automatic_return(prepared):
    p=prepared;c=p.client;a=reserve(p).json();m=issue(p,a).json()['movement_id']
    assert write(c,'issues/'+m+'/sync-return',{}).json()['unknown']
    with Session(p.engine) as db:
        db.add(FormingLog(id='LOG1',production_order_id='LSX1',movement_id=m,sheet_weight=100,good=50,ng=10,source={}))
        db.commit()
    row=c.get('/api/production/preparation?line_id=CT1').json()['items'][0]
    assert Decimal(row['at_machine_kg'])==14 and row['machine_balance_status']=='estimated'
    response=write(c,'issues/'+m+'/sync-return',{});assert response.status_code==200,response.text
    returned=response.json();assert Decimal(returned['kg'])==14
    assert balances(p)['stock_kg']==80
    assert write(c,'returns/'+returned['id']+'/confirm',{'kg':'14'}).status_code==200
    assert balances(p)['stock_kg']==94


def test_atomic_transfer_trace_and_rollback(prepared,monkeypatch):
    p=prepared;c=p.client;a=reserve(p).json();m=issue(p,a).json()['movement_id']
    data={'order_line_id':'CT2','standard_id':p.standard_id,'production_order_id':'LSX2',
        'kg':'10','measured_remaining_kg':'15','note':'Machine-to-machine count'}
    before=balances(p)
    response=write(c,'issues/'+m+'/transfer',data);assert response.status_code==201,response.text
    result=response.json();assert balances(p)==before
    with Session(p.engine) as db:
        links=db.scalars(select(AllocationMovement).where(AllocationMovement.transfer_id==result['transfer_id'])).all()
        assert len(links)==2
        assert db.get(FilmMovement,result['return_id']).receipt_id=='R1'
    original=service.new_movement
    def broken(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Forced failure after movement insert')
    monkeypatch.setattr(service,'new_movement',broken)
    with pytest.raises(RuntimeError,match='Forced failure'):
        write(c,'issues/'+m+'/transfer',{**data,'kg':'2','measured_remaining_kg':'5'})
    assert balances(p)==before
    with Session(p.engine) as db:assert db.scalar(select(func.count()).select_from(FilmMovement))==3


def test_permissions_and_legacy_guard(prepared):
    p=prepared;c=p.client;a=reserve(p).json()
    c.cookies.set('napaco_session','reader')
    assert reserve(p,1).status_code==403
    assert c.get('/api/production/preparation').status_code==403
    assert write(c,'returns/fake/confirm',{'kg':'1'}).status_code==403
    c.cookies.set('napaco_session','admin')
    with Session(p.engine) as db:
        receipt=db.get(FilmReceipt,'R1');receipt.quantity=Decimal(79)
        with pytest.raises(HTTPException) as error:service.reconcile_legacy(db,[{'table':'FILM_RECEIPTS','ids':['R1']}])
        assert error.value.status_code==409
        db.rollback()
    assert balances(p)['stock_kg']==100
