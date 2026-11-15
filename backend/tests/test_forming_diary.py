"""Phase-4 cases prepared for the deferred test session; NOT executed here.

Local MySQL rollback fixtures and fake Google identities. No production data,
Drive writes or implicit test execution. API transaction owner is exercised.
"""
from datetime import datetime,timedelta
from uuid import uuid4
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from test_production_release import context,freeze
from test_material_handovers import handover_context,draft,issue,receive
from test_production_samples import sample_context,received_episode,new_episode,sample_draft,signed
from app.modules.production import forming_service as forming,run_service as runs,release_service as release
from app.modules.production.models import FormingLog
from app.modules.production.run_models import ShiftMaterial,ShiftItem
from app.modules.production.forming_schemas import FormingInput
from app.modules.production.run_schemas import RunItemInput,VersionInput,DownstreamInput
from app.modules.materials.inventory.allocation_api import write
from app.modules.materials.inventory.handover_sources import source_contexts
from app.modules.materials.inventory import allocation_service as material
from app.modules.production.sample_schemas import EpisodeInput
from app.modules.production import sample_service as samples


@pytest.fixture
def forming_context(sample_context,monkeypatch):
    c=sample_context
    class ClockDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            value=c.clock.now.replace(tzinfo=runs.ZONE)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(runs,'datetime',ClockDateTime)
    c.episode=received_episode(c)
    c.sample=signed(c,signed(c,sample_draft(c,c.episode),'technical'),'qc')
    # Release the session savepoint into the outer rollback-only fixture. Each
    # API write/rollback now has its own savepoint without deleting fixture data.
    c.db.commit()
    return c


def payload(c,*,goods=2,consumed='1',action='continue'):
    start=c.clock.now+timedelta(seconds=1);c.clock.now+=timedelta(minutes=15)
    aware=lambda value:value.replace(tzinfo=runs.ZONE)
    ctx=forming.context(c.db,c.key,c.run.machine_id,c.episode['id'],until=aware(c.clock.now),since=aware(start))
    return FormingInput(machine_id=c.run.machine_id,assignment_id=ctx['assignment_id'],run_version=c.run.version,
        setup_id=c.episode['id'],episode_version=ctx['episode']['version'],sample_qc_id=c.sample['id'],
        sample_qc_version=c.sample['version'],source_hash=ctx['source_hash'],start=aware(start),end=aware(c.clock.now),
        good_sheets=goods,ng_sheets=0,items=[{'order_line_id':c.key,'good':goods*4,'ng':0}],
        sources=[{'receipt_id':c.key,'consumed_kg':consumed}],episode_action=action)


def save(c,data,edit_id=None):
    return write(c.db,c.user,'fixture:forming:'+str(uuid4()),data,str(uuid4()),lambda:forming.save(c.db,c.user,c.key,data,edit_id))


def test_minimal_entry_does_not_turn_plan_parameters_into_actuals(forming_context):
    c=forming_context;result=save(c,payload(c));log=c.db.get(FormingLog,result['id'])
    assert result['actual_machine_id']==c.run.machine_id and result['sample_basis']['qc_id']==c.sample['id']
    assert log.speed is None and log.film_pull is None and log.sheet_weight is None
    assert log.shift_snapshot['pure_seconds'] is None
    assert log.shift_snapshot['parameters']['seconds_per_cycle'] is None
    assert c.line.produced==8 and c.run.status==runs.RUNNING
    material=c.db.get(ShiftMaterial,(log.id,c.key))
    assert material.opening_kg+material.input_kg-material.output_kg-material.consumed_kg==material.closing_kg==9


def test_next_day_restarts_with_new_sample_same_lsx_and_carries_material(forming_context):
    c=forming_context;first=save(c,payload(c,action='close'))
    c.clock.now+=timedelta(days=1)
    c.episode=new_episode(c);c.sample=signed(c,signed(c,sample_draft(c,c.episode),'technical'),'qc')
    second=save(c,payload(c));summary=forming.summary(c.db,c.key)
    assert first['run_id']==second['run_id']==c.key and first['id']!=second['id']
    assert summary['count']==2 and summary['good_sheets']==4
    assert summary['items'][0]['good_qty']==16
    materials=list(c.db.scalars(select(ShiftMaterial).where(ShiftMaterial.log_id==second['id'])))
    assert materials[0].opening_kg==9 and materials[0].input_kg==0 and materials[0].closing_kg==8
    assert Decimal(summary['lots'][0]['consumed_kg'])==2


def test_continuing_in_same_episode_does_not_require_a_new_sample(forming_context):
    c=forming_context;first=save(c,payload(c));second=save(c,payload(c))
    assert first['setup_id']==second['setup_id']==c.episode['id']
    assert first['sample_basis']['qc_id']==second['sample_basis']['qc_id']
    assert c.db.scalar(select(func.count()).select_from(FormingLog).where(FormingLog.production_order_id==c.key))==2


def test_source_at_past_cutoff_does_not_use_a_later_diary_balance(forming_context):
    c=forming_context;first=save(c,payload(c));save(c,payload(c))
    past=source_contexts(c.db,[c.key],until=datetime.fromisoformat(first['end']).replace(tzinfo=None))[c.key]
    current=source_contexts(c.db,[c.key])[c.key]
    assert Decimal(past['sources'][0]['opening_kg'])==9
    assert Decimal(current['sources'][0]['opening_kg'])==8
    assert Decimal(past['lots'][0]['consumed_kg'])==1


def test_stale_material_source_rolls_back_the_automatic_start(forming_context):
    c=forming_context;data=payload(c)
    receive(c,issue(c,draft(c,2)))
    c.db.commit()
    data=data.model_copy(update={'run_version':c.run.version})
    with pytest.raises(HTTPException):save(c,data)
    assert c.db.get(type(c.run),c.key).status==runs.PLANNED
    assert c.db.scalar(select(func.count()).select_from(FormingLog).where(FormingLog.production_order_id==c.key))==0


@pytest.mark.parametrize('change',[{'sample_qc_id':'another-qc'},{'assignment_id':'another-assignment'},
    {'sources':[{'receipt_id':'wrong-lot','consumed_kg':'1'}]}])
def test_cannot_substitute_sample_assignment_or_lot(forming_context,change):
    c=forming_context;data=payload(c).model_dump();data.update(change)
    with pytest.raises(HTTPException):save(c,FormingInput(**data))
    assert c.db.scalar(select(func.count()).select_from(FormingLog).where(FormingLog.production_order_id==c.key))==0


def test_overrun_and_invalid_material_consumption_do_not_change_totals(forming_context):
    c=forming_context;data=payload(c,goods=26)
    with pytest.raises(HTTPException):save(c,data)
    assert c.db.get(type(c.line),c.key).produced==0
    invalid=payload(c,consumed='11')
    with pytest.raises(HTTPException):save(c,invalid)
    assert c.db.get(type(c.line),c.key).produced==0


def test_cannot_insert_a_diary_before_the_latest_one(forming_context):
    c=forming_context;first_data=payload(c);first=save(c,first_data)
    inserted=payload(c).model_copy(update={'start':first_data.start,'end':first_data.end})
    with pytest.raises(HTTPException):save(c,inserted)
    assert c.db.scalar(select(func.count()).select_from(FormingLog).where(FormingLog.production_order_id==c.key))==1


def test_machine_change_preserves_old_log_and_carries_same_lsx_balance(forming_context):
    c=forming_context;first=save(c,payload(c,action='close'));old_machine=first['actual_machine_id']
    c.clock.now+=timedelta(seconds=1)
    config=c.payload.model_copy(update={'machine_id':c.machines[1].id,'version':c.run.version,'note':'Move same LSX to DH2'})
    runs.save_run(c.db,c.user,config,c.key,scheduling=True)
    plan=freeze(c);release.sync_assignments(c.db,c.user,c.run,plan)
    c.episode=new_episode(c);c.sample=signed(c,signed(c,sample_draft(c,c.episode),'technical'),'qc')
    second=save(c,payload(c));original=c.db.get(FormingLog,first['id'])
    assert first['run_id']==second['run_id']==c.key
    assert original.actual_machine_id==old_machine and second['actual_machine_id']==c.machines[1].id
    assert c.db.get(ShiftMaterial,(second['id'],c.key)).opening_kg==9


def test_grouped_ctdh_share_one_machine_interval(forming_context):
    c=forming_context
    config=c.payload.model_copy(update={'version':c.run.version,'group_id':c.key,'group_confirmed':True,
        'items':[RunItemInput(order_line_id=c.key,quantity=50,cavity=4),
            RunItemInput(order_line_id=c.other_line.id,quantity=50,cavity=4)],'note':'Group two CTDH'})
    runs.save_run(c.db,c.user,config,c.key,scheduling=True)
    plan=freeze(c);release.sync_assignments(c.db,c.user,c.run,plan)
    c.episode=new_episode(c);c.sample=signed(c,signed(c,sample_draft(c,c.episode),'technical'),'qc')
    data=payload(c).model_dump();data['items']=[{'order_line_id':c.key,'good':4,'ng':0},{'order_line_id':c.other_line.id,'good':4,'ng':0}]
    data=FormingInput(**data);result=save(c,data);summary=forming.summary(c.db,c.key)
    assert c.db.scalar(select(func.count()).select_from(ShiftItem).where(ShiftItem.log_id==result['id']))==2
    assert summary['count']==1 and summary['interval_seconds']==int((data.end-data.start).total_seconds())
    assert sum(i['good_qty'] for i in summary['items'])==8


def test_finish_requires_received_handover_warehouse_return_and_zero_lot_balance(forming_context):
    c=forming_context;save(c,payload(c))
    finish=lambda:runs.change_state(c.db,c.user,c.key,VersionInput(version=c.run.version,note='Close after reconciliation'))
    with pytest.raises(HTTPException,match='số dư'):finish()
    from app.modules.materials.inventory.handover_models import MaterialHandover
    h=c.db.scalar(select(MaterialHandover).where(MaterialHandover.run_id==c.key))
    returned=material.request_return(c.db,c.user,h.movement_id,SimpleNamespace(kg=Decimal(9),note='Return actual balance'))
    with pytest.raises(HTTPException,match='chờ kho'):finish()
    material.confirm_return(c.db,c.user,returned['id'],Decimal(9))
    with pytest.raises(HTTPException,match='chưa chốt'):finish()
    save(c,payload(c,goods=0,consumed='0'))
    result=finish()
    assert result['status']==runs.ENDED
    assert release.machine_queue(c.db,c.run.machine_id,'forming',1,25)['total']==0


def test_cutting_valid_goods_can_overlap_next_forming_interval(forming_context):
    c=forming_context;first=save(c,payload(c))
    plan=freeze(c,jobs=[{'run_id':c.key,'stages':[{'order_line_id':c.key,'stage':'cutting','machine_id':c.machines[2].id}]}])
    release.sync_assignments(c.db,c.user,c.run,plan)
    c.clock.now+=timedelta(seconds=1)
    episode=samples.create_episode(c.db,c.user,c.key,EpisodeInput(run_version=c.run.version,stage='cutting',
        machine_id=c.machines[2].id,order_line_ids=[c.key],source_forming_log_id=first['id'],
        valid_until=(c.clock.now+timedelta(hours=8)).replace(tzinfo=runs.ZONE),note='Cut goods already measured'))
    cut_sample=signed(c,signed(c,sample_draft(c,episode),'technical'),'qc')
    start=c.clock.now+timedelta(seconds=2)
    second=save(c,payload(c))
    result=runs.save_downstream(c.db,c.user,DownstreamInput(id=str(uuid4()),setup_id=episode['id'],forming_log_id=first['id'],
        stage='cutting',machine_id=c.machines[2].id,start=start.replace(tzinfo=runs.ZONE),
        end=(start+timedelta(minutes=2)).replace(tzinfo=runs.ZONE),items=[{'order_line_id':c.key,'good':4,'ng':0}],note='Parallel cutting'))
    assert result['run_id']==second['run_id']==c.key
    assert datetime.fromisoformat(second['start']).replace(tzinfo=None)<start<datetime.fromisoformat(second['end']).replace(tzinfo=None)


def test_other_lsx_on_machine_blocks_overlapping_forming(forming_context):
    c=forming_context;data=payload(c)
    # Immutable evidence from a different LSX blocks actual time overlap even if
    # its header has since moved or ended; current planner order is irrelevant.
    other=type(c.run)(id=c.key+'OTHER',machine_id=c.machines[1].id,status=runs.ENDED,source={})
    c.db.add(other);c.db.flush()
    c.db.add(FormingLog(id=c.key+'OVERLAP',production_order_id=other.id,actual_machine_id=c.run.machine_id,
        shift_start=runs.local(data.start),shift_end=runs.local(data.end),shift_snapshot={'actual_machine_id':c.run.machine_id},source={}))
    c.db.commit()
    with pytest.raises(HTTPException,match='chồng máy'):save(c,data)
    assert c.db.get(type(c.run),c.key).status==runs.PLANNED


def test_finishing_forming_keeps_valid_downstream_source_and_rejects_new_forming(forming_context):
    c=forming_context;first=save(c,payload(c,consumed='10'))
    plan=freeze(c,jobs=[{'run_id':c.key,'stages':[{'order_line_id':c.key,'stage':'cutting','machine_id':c.machines[2].id}]}])
    release.sync_assignments(c.db,c.user,c.run,plan)
    runs.change_state(c.db,c.user,c.key,VersionInput(version=c.run.version,note='Material reconciled, forming ended'))
    assert release.machine_queue(c.db,c.run.machine_id,'forming',1,25)['total']==0
    assert release.machine_queue(c.db,c.machines[2].id,'cutting',1,25)['items'][0]['remaining_qty']==8
    with pytest.raises(HTTPException):new_episode(c)
    c.clock.now+=timedelta(seconds=1)
    episode=samples.create_episode(c.db,c.user,c.key,EpisodeInput(run_version=c.run.version,stage='cutting',
        machine_id=c.machines[2].id,order_line_ids=[c.key],source_forming_log_id=first['id'],
        valid_until=(c.clock.now+timedelta(hours=8)).replace(tzinfo=runs.ZONE),note='Cut remaining actual goods after forming ended'))
    signed(c,signed(c,sample_draft(c,episode),'technical'),'qc')
    start=c.clock.now+timedelta(seconds=1);c.clock.now+=timedelta(minutes=5)
    result=runs.save_downstream(c.db,c.user,DownstreamInput(id=str(uuid4()),setup_id=episode['id'],forming_log_id=first['id'],
        stage='cutting',machine_id=c.machines[2].id,start=start.replace(tzinfo=runs.ZONE),end=c.clock.now.replace(tzinfo=runs.ZONE),
        items=[{'order_line_id':c.key,'good':4,'ng':0}],note='Keep source link after forming end'))
    assert result['DH_ID']==first['id'] and c.run.status==runs.ENDED
