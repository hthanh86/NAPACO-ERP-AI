"""Phase 1 regression cases, local MySQL rollback only. Run with user approval."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core.database import engine
from app.auth.models import User
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.orders.models import Order,OrderLine
from app.modules.materials.models import FilmMaterial
from app.modules.production.models import ProductionOrder as Run,FormingLog
from app.modules.production.planning_models import Machine,ProductionStandard,ProductionStandardItem
from app.modules.production.run_models import ProductionOrderItem as Item,ProductionAssignment as Assignment,ShiftItem,DownstreamItem
from app.modules.production.schedule_models import SchedulePlan
from app.modules.production.run_schemas import RunInput,VersionInput,SetupInput
from app.modules.production import run_service as runs,release_service as release,schedule_service


@pytest.fixture
def context():
    connection=engine.connect();outer=connection.begin()
    db=Session(bind=connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
    key='_PH1_'+uuid4().hex[:12]
    user=User(id=key,name='Phase 1 rollback test',role='LOCAL_ADMIN',active=True,source={})
    customer=Customer(id=key,name='Phase 1 rollback customer')
    db.add_all([user,customer]);db.flush()
    product=Product(id=key,customer_id=key,name='Phase 1 product',unit='Cái')
    material=FilmMaterial(id=key,grade='PET',width=500,thickness=.5)
    machines=[Machine(id=key+suffix,name=suffix,kind=kind,status='ready',calendar={},notes='')
        for suffix,kind in [('DH1','semi_automatic'),('DH2','semi_automatic'),('CAT','cutting'),('EB','edge')]]
    db.add_all([product,material,*machines]);db.flush()
    order=Order(id=key,customer_id=key,po_number=key)
    db.add(order);db.flush()
    line=OrderLine(id=key,order_id=key,product_id=key,quantity=1000,produced=0,unit='Cái')
    other_line=OrderLine(id=key+'B',order_id=key,product_id=key,quantity=1000,produced=0,unit='Cái')
    params={'seconds_per_cycle':4,'pull_mm':500,'sheet_weight_kg':.175,'setup_minutes':0,'waste_percent':0,'density':1.4}
    snapshot={'machine':{'id':machines[0].id,'kind':'semi_automatic'},
        'material':{'id':key,'width':500,'thickness':.5},'mold':{'id':key,'Dai_Khuon':400}}
    standard=ProductionStandard(id=str(uuid4()),code=key,revision=1,machine_id=machines[0].id,material_id=key,
        mold_id=key,name='Phase 1 standard',active=True,parameters=params,snapshot=snapshot,created_by=key)
    db.add_all([line,other_line,standard]);db.flush()
    db.add(ProductionStandardItem(standard_id=standard.id,product_id=key,cavity=4,edge=True,
        snapshot={'name':'Phase 1 product','product_id':key,'unit':'Cái','route':['forming','cutting','edge']}));db.flush()
    payload=RunInput(id=key,standard_id=standard.id,machine_id=machines[0].id,
        items=[{'order_line_id':key,'quantity':100,'cavity':4}],materials=[],note='Phase 1 plan')
    ctx=SimpleNamespace(db=db,user=user,key=key,machines=machines,line=line,other_line=other_line,payload=payload)
    try:yield ctx
    finally:db.close();outer.rollback();connection.close()


def freeze(c,jobs=None):
    db=c.db;run=db.get(Run,c.key)
    version=(db.scalar(select(func.max(SchedulePlan.version))) or 0)+1
    row=SchedulePlan(id=str(uuid4()),version=version,request={'order':[run.id],'jobs':jobs or []},result={},
        source_hash='0'*64,created_by=c.user.id,context={'runs':[schedule_service.dto(run,
            runs.run_items(db,run.id),[])]})
    db.add(row);db.flush();return row


def created(c):
    runs.save_run(c.db,c.user,c.payload)
    return c.db.get(Run,c.key)


def released(c,jobs=None):
    run=created(c);plan=freeze(c,jobs)
    release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Explicit release'))
    return run,plan


def test_draft_cannot_start_issue_or_sample(context):
    c=context;run=created(c)
    assert run.release_state=='draft' and run.official_code is None and run.issued_at is None
    with pytest.raises(HTTPException):runs.change_state(c.db,c.user,run.id,VersionInput(version=run.version,note='No release'),start=True)
    with pytest.raises(HTTPException):runs.before_issue(c.db,SimpleNamespace(order_line_id=c.key),run,Decimal(1))
    with pytest.raises(HTTPException):release.create_setup(c.db,c.user,run.id,SetupInput(run_version=run.version,machine_id=run.machine_id,note='No release'))
    assert release.machine_queue(c.db,run.machine_id,'forming',1,25)['total']==0


def test_release_requires_saved_plan_and_freezes_content(context):
    c=context;run=created(c)
    with pytest.raises(HTTPException):release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Missing plan'))
    plan=freeze(c)
    result=release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Approved'))
    assert result['official_code'].startswith('LSX_'+release.now().strftime('%y%m%d')+'_')
    assert run.released_by==c.user.id and run.release_snapshot['plan_id']==plan.id
    code=run.official_code;frozen=deepcopy(run.release_snapshot)
    release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Retry'))
    assert run.official_code==code and run.release_snapshot==frozen
    assert c.db.scalar(select(func.count()).select_from(Assignment).where(Assignment.run_id==run.id))==1


def test_saved_plan_must_match_current_version(context):
    c=context;run=created(c);freeze(c);run.version+=1;c.db.flush()
    with pytest.raises(HTTPException) as error:release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Stale plan'))
    assert error.value.status_code==409 and run.official_code is None


def test_same_run_can_move_without_rewriting_journal(context):
    c=context;run,plan=released(c);frozen=deepcopy(run.release_snapshot)
    old=release.assignment(c.db,run.id,'forming');start=release.now()-timedelta(hours=2)
    log=FormingLog(id=str(uuid4()),production_order_id=run.id,source={},version=1,
        shift_start=start,shift_end=start+timedelta(minutes=1),actual_machine_id=run.machine_id,
        assignment_id=old.id,shift_snapshot={'run_snapshot':deepcopy(run.run_snapshot)})
    c.db.add(log);c.db.flush()
    run.status=runs.RUNNING
    item=c.db.get(Item,(run.id,c.key));item.completed_qty=20;c.line.produced=20;c.db.flush()
    payload=c.payload.model_copy(update={'version':run.version,'machine_id':c.machines[1].id})
    runs.save_run(c.db,c.user,payload,run.id,scheduling=True)
    new_plan=freeze(c);release.sync_assignments(c.db,c.user,run,new_plan,force=True)
    current=release.assignment(c.db,run.id,'forming')
    assert run.id==c.key and run.status==runs.RUNNING and current.machine_id==c.machines[1].id
    assert old.ended_at is not None and current.id!=old.id
    assert release.historical_machine(log)==c.machines[0].id and log.assignment_id==old.id
    assert run.release_snapshot==frozen and item.completed_qty==20 and c.line.produced==20
    assert release.machine_queue(c.db,c.machines[0].id,'forming',1,25)['total']==0
    assert release.machine_queue(c.db,c.machines[1].id,'forming',1,25)['items'][0]['remaining_qty']==80


def test_multi_lsx_per_line_and_group_removal_preserves_history(context):
    c=context;run=created(c)
    second=c.payload.model_copy(update={'id':c.key+'SECOND'})
    runs.save_run(c.db,c.user,second)
    assert c.db.scalar(select(func.count()).select_from(Item).where(Item.order_line_id==c.key))==2
    item=c.db.get(Item,(run.id,c.key));item.completed_qty=20;c.line.produced=20;c.db.flush()
    changed=c.payload.model_copy(update={'version':run.version,'items':[
        c.payload.items[0].model_copy(update={'order_line_id':c.other_line.id})]})
    runs.save_run(c.db,c.user,changed,run.id,scheduling=True)
    assert not item.enabled and item.completed_qty==20
    assert c.db.get(Item,(run.id,c.other_line.id)).enabled


def test_target_cannot_drop_below_completed(context):
    c=context;run=created(c);c.db.get(Item,(run.id,c.key)).completed_qty=20;c.line.produced=20;c.db.flush()
    payload=c.payload.model_copy(update={'version':run.version,'items':[c.payload.items[0].model_copy(update={'quantity':19})]})
    with pytest.raises(HTTPException) as error:runs.save_run(c.db,c.user,payload,run.id,scheduling=True)
    assert error.value.status_code==409


def test_legacy_remains_unreleased_until_explicit_action(context):
    c=context;run=created(c);run.release_state='legacy';old_date=release.now()-timedelta(days=10);run.issued_at=old_date;c.db.flush()
    freeze(c)
    with pytest.raises(HTTPException):release.require_released(run)
    release.release(c.db,c.user,run.id,VersionInput(version=run.version,note='Continue legacy explicitly'))
    assert run.release_snapshot['legacy_continuation'] and run.issued_at==old_date and run.released_at>old_date


def test_one_current_forming_assignment_and_no_cross_machine_interval(context):
    c=context;run,plan=released(c)
    for machine in [c.machines[1],c.machines[0]]:
        run.machine_id=machine.id;run.version+=1
        release.sync_assignments(c.db,c.user,run,plan,force=True)
    assert c.db.scalar(select(func.count()).select_from(Assignment).where(
        Assignment.run_id==run.id,Assignment.stage=='forming',Assignment.ended_at.is_(None)))==1
    with pytest.raises(HTTPException):release.check_interval(c.db,run,'forming',c.machines[1].id,release.now(),release.now())


def test_downstream_queue_needs_real_remaining_goods(context):
    c=context;jobs=[{'run_id':c.key,'stages':[{'order_line_id':c.key,'stage':'cutting','machine_id':c.machines[2].id}]}]
    run,plan=released(c,jobs)
    assert release.machine_queue(c.db,c.machines[2].id,'cutting',1,25)['total']==0
    start=release.now()-timedelta(hours=1)
    log=FormingLog(id=str(uuid4()),production_order_id=run.id,source={},version=1,shift_start=start,
        shift_end=start+timedelta(minutes=1),actual_machine_id=run.machine_id,shift_snapshot={'run_snapshot':run.run_snapshot})
    c.db.add(log);c.db.flush();c.db.add(ShiftItem(log_id=log.id,order_line_id=c.key,good_qty=12,ng_qty=0));c.db.flush()
    row=release.machine_queue(c.db,c.machines[2].id,'cutting',1,25)['items'][0]
    assert row['remaining_qty']==12 and row['run_id']==run.id
    assert release.machine_queue(c.db,c.machines[3].id,'cutting',1,25)['total']==0


def test_missing_historical_machine_is_never_guessed(context):
    c=context;run=created(c)
    log=FormingLog(id=str(uuid4()),production_order_id=run.id,source={},shift_snapshot={})
    assert release.historical_machine(log) is None
