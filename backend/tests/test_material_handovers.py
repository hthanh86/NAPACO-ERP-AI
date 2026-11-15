"""Focused phase-2 tests; MySQL writes are enclosed in the existing rollback fixture.

Google identity and encryption key are test doubles; no Google/Drive calls occur.
Run only after user approval.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from cryptography.fernet import Fernet
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from test_production_release import context,freeze
from app.modules.materials.purchasing.models import FilmPO,FilmLine
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_models import MaterialAllocation,AllocationMovement
from app.modules.materials.inventory.handover_models import MaterialHandover
from app.modules.materials.inventory import allocation_service as material,handover_service as service
from app.modules.materials.inventory.handover_sources import source_contexts
from app.modules.materials.inventory.handover_schemas import HandoverSign,HandoverVersion
from app.modules.production import run_service as runs,release_service
from app.modules.production.run_schemas import RunMaterialInput,VersionInput
from app.modules.production.models import ProductionOrder,FormingLog
from app.modules.production.run_models import ShiftMaterial
from app.auth.models import User


@pytest.fixture
def handover_context(context,monkeypatch):
    c=context;db=c.db
    db.add(FilmPO(id=c.key,status='Đang đặt'));db.flush()
    db.add(FilmLine(id=c.key,po_id=c.key,material_id=c.key,resin='PET',quantity=100,status='Nhận một phần'));db.flush()
    db.add(FilmReceipt(id=c.key,line_id=c.key,quantity=100,status='OK'));db.flush()
    a=material.reserve(db,c.user,SimpleNamespace(receipt_id=c.key,order_line_id=c.key,standard_id=c.payload.standard_id,kg=Decimal(20),note='Hold'))
    c.allocation=db.get(MaterialAllocation,a['id'])
    c.payload=c.payload.model_copy(update={'materials':[RunMaterialInput(allocation_id=a['id'],kg=Decimal(20))]})
    runs.save_run(db,c.user,c.payload);freeze(c)
    c.run=db.get(ProductionOrder,c.key)
    release_service.release(db,c.user,c.key,VersionInput(version=c.run.version,note='Release'))
    c.receiver=User(id=c.key+'RECV',name='Receiver',role='LOCAL_ADMIN',active=True,source={});db.add(c.receiver);db.flush()
    test_cipher=Fernet(Fernet.generate_key());monkeypatch.setattr(service,'cipher',lambda:test_cipher)
    monkeypatch.setattr(service,'identity',lambda request,db,user:{'user_id':user.id,'name':user.name,'email':user.email,
        'google_subject':'google:'+user.id,'session':request.session})
    c.request=SimpleNamespace(session='issuer-session');c.receive_request=SimpleNamespace(session='receiver-session')
    return c


def draft(c,kg=10):
    return service.create_issue(c.db,c.user,c.allocation.id,SimpleNamespace(version=c.allocation.version,
        production_order_id=c.key,kg=Decimal(kg),note='Measured handover'))


def signature(c,doc,role,*,user=None,request=None):
    user=user or c.user;request=request or c.request
    data=HandoverSign(version=doc['version'],role=role,signature=[[(.1,.2),(.3,.5),(.8,.4)]])
    proof=service.confirm_signature(c.db,user,request,service.lock(c.db,doc['id'],doc['version']),data)
    return data.model_copy(update={'confirmation':proof['confirmation']})


def issue(c,doc):return service.sign(c.db,c.user,c.request,doc['id'],signature(c,doc,'issue'))
def receive(c,doc):return service.sign(c.db,c.receiver,c.receive_request,doc['id'],signature(c,doc,'receipt',user=c.receiver,request=c.receive_request))
def lot(c,run_id=None):return source_contexts(c.db,[run_id or c.key])[run_id or c.key]['lots'][0]
def stock(c):return material.receipt_balances(c.db,[c.key])[c.key]['stock_kg']


def test_draft_is_not_a_stock_movement_and_reserves_capacity(handover_context):
    c=handover_context;doc=draft(c,12)
    assert doc['state']=='draft' and doc['movement_id'] is None and stock(c)==100 and c.allocation.held_kg==20
    assert c.db.scalar(select(func.count()).select_from(FilmMovement).where(FilmMovement.production_order_id==c.key))==0
    with pytest.raises(HTTPException):draft(c,9)
    service.cancel(c.db,c.user,doc['id'],HandoverVersion(version=doc['version']))
    assert draft(c,20)['state']=='draft' and stock(c)==100


def test_two_actual_signers_and_only_one_stock_debit(handover_context):
    c=handover_context;pending=issue(c,draft(c));m=c.db.get(FilmMovement,pending['movement_id'])
    assert stock(c)==90 and c.allocation.held_kg==10 and m.issuer_id==c.user.id and m.receiver_id==''
    assert Decimal(lot(c)['pending_handover_kg'])==10 and Decimal(lot(c)['usable_kg'])==0
    done=receive(c,pending);assert stock(c)==90 and c.allocation.held_kg==10
    assert done['issued_by']==c.user.id and done['received_by']==c.receiver.id and m.receiver_id==c.receiver.id
    assert done['issue_signature']['nonce']!=done['receipt_signature']['nonce']
    assert Decimal(lot(c)['received_signed_kg'])==10 and Decimal(lot(c)['usable_kg'])==10


def test_pending_cannot_be_returned_or_consumed(handover_context):
    c=handover_context;pending=issue(c,draft(c))
    assert runs.shift_context(c.db,c.key)['sources']==[]
    with pytest.raises(HTTPException):material.request_return(c.db,c.user,pending['movement_id'],SimpleNamespace(kg=Decimal(1),note='Not yet received'))
    with pytest.raises(HTTPException):runs.change_state(c.db,c.user,c.key,VersionInput(version=c.run.version,note='Pending handover'))


def test_signature_is_bound_to_user_session_document_role_and_strokes(handover_context):
    c=handover_context;doc=draft(c);data=signature(c,doc,'issue')
    with pytest.raises(HTTPException):service.sign(c.db,c.user,SimpleNamespace(session='other'),doc['id'],data)
    with pytest.raises(HTTPException):service.sign(c.db,c.receiver,c.request,doc['id'],data)
    changed=data.model_copy(update={'signature':[[(.2,.2),(.9,.9)]]})
    with pytest.raises(HTTPException):service.sign(c.db,c.user,c.request,doc['id'],changed)
    other=draft(c)
    with pytest.raises(HTTPException):service.sign(c.db,c.user,c.request,other['id'],data)
    wrong_role=data.model_copy(update={'role':'receipt'})
    with pytest.raises(HTTPException):service.sign(c.db,c.user,c.request,doc['id'],wrong_role)
    assert stock(c)==100


def test_received_after_shift_end_is_not_backdated_input(handover_context):
    c=handover_context;done=receive(c,issue(c,draft(c)))
    row=c.db.get(MaterialHandover,done['id'])
    assert runs.shift_context(c.db,c.key,until=row.received_at-timedelta(seconds=1))['sources']==[]
    assert Decimal(runs.shift_context(c.db,c.key,until=row.received_at)['sources'][0]['input_kg'])==10


def test_multiple_issues_on_same_run_and_lot_do_not_duplicate_receipts(handover_context):
    c=handover_context
    first=receive(c,issue(c,draft(c,7)));second=receive(c,issue(c,draft(c,5)))
    assert first['movement_id']!=second['movement_id'] and stock(c)==88
    assert Decimal(lot(c)['received_signed_kg'])==12 and Decimal(lot(c)['usable_kg'])==12
    with pytest.raises(HTTPException):service.sign(c.db,c.receiver,c.receive_request,second['id'],signature(c,first,'receipt',user=c.receiver,request=c.receive_request))


def test_returns_only_restore_warehouse_after_confirmation(handover_context):
    c=handover_context;doc=receive(c,issue(c,draft(c)))
    pending=material.request_return(c.db,c.user,doc['movement_id'],SimpleNamespace(kg=Decimal(3),note='Measured return'))
    assert stock(c)==90 and Decimal(lot(c)['usable_kg'])==7 and Decimal(lot(c)['pending_return_kg'])==3
    material.confirm_return(c.db,c.user,pending['id'],Decimal(3))
    assert stock(c)==93 and Decimal(lot(c)['usable_kg'])==7 and Decimal(lot(c)['confirmed_return_kg'])==3


def test_legacy_receiver_is_not_new_receipt_evidence(handover_context):
    c=handover_context
    m=FilmMovement(id=str(uuid4()),moved_at=release_service.now().strftime('%Y-%m-%d %H:%M:%S'),kind='CẤP NVL',
        production_order_id=c.key,receipt_id=c.key,quantity=Decimal(4),issuer_id=c.user.id,receiver_id=c.user.id,source={})
    c.db.add(m);c.db.flush()
    assert Decimal(lot(c)['legacy_issued_kg'])==4 and Decimal(lot(c)['received_signed_kg'])==0 and Decimal(lot(c)['usable_kg'])==0
    assert m.receiver_id==c.user.id and stock(c)==96


def test_closed_shift_balance_carries_without_crediting_same_issue_twice(handover_context):
    c=handover_context;doc=receive(c,issue(c,draft(c)));stamp=release_service.now()
    log=FormingLog(id=str(uuid4()),production_order_id=c.key,shift_start=stamp-timedelta(minutes=1),shift_end=stamp,
        shift_snapshot={'handover_source_version':1},source={},version=1)
    c.db.add(log);c.db.flush();c.db.add(ShiftMaterial(log_id=log.id,receipt_id=c.key,opening_kg=0,input_kg=10,
        output_kg=0,consumed_kg=2,closing_kg=8,movements=[doc['movement_id']]));c.db.flush()
    context=runs.shift_context(c.db,c.key);assert Decimal(context['sources'][0]['opening_kg'])==8
    assert Decimal(context['sources'][0]['input_kg'])==0 and Decimal(lot(c)['usable_kg'])==8


def test_unreleased_run_and_lowering_hold_under_draft_are_blocked(handover_context):
    c=handover_context;draft(c,12)
    with pytest.raises(HTTPException):material.edit(c.db,c.user,c.allocation.id,SimpleNamespace(version=c.allocation.version,held_kg=Decimal(11),note='Too low'))
    c.run.release_state='draft';c.db.flush()
    with pytest.raises(HTTPException):draft(c,1)


def test_transfer_reuses_atomic_return_issue_and_waits_for_target_receipt(handover_context):
    c=handover_context;src=receive(c,issue(c,draft(c)))
    target_id=c.key+'DST';payload=c.payload.model_copy(update={'id':target_id,'materials':[]})
    runs.save_run(c.db,c.user,payload)
    original=c.key;c.key=target_id;freeze(c);target=c.db.get(ProductionOrder,target_id)
    release_service.release(c.db,c.user,target_id,VersionInput(version=target.version,note='Destination'))
    c.key=original
    data=SimpleNamespace(order_line_id=original,standard_id=c.payload.standard_id,production_order_id=target_id,
        kg=Decimal(4),measured_remaining_kg=Decimal(10),note='Physical transfer')
    doc=service.create_transfer(c.db,c.user,src['movement_id'],data)
    pending=issue(c,doc);assert stock(c)==90 and Decimal(lot(c,target_id)['usable_kg'])==0
    receive(c,pending)
    assert stock(c)==90 and Decimal(lot(c,target_id)['usable_kg'])==4 and Decimal(lot(c)['usable_kg'])==6
