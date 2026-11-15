"""Prepared stage-3 tests; isolated SQLite only. Run only with user approval."""
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.core.database import Base
from app.modules.production.run_api import router
from app.modules.production.models import ProductionOrder
from test_material_allocations import prepared,reserve,write as material_write
from test_production_planning import planning


@pytest.fixture
def running_setup(prepared):
    p=prepared
    names=['production_order_items','production_run_materials','production_shift_items','production_shift_materials',
           'cutting_logs','eb_logs','production_wip','production_downstream_items','system_settings']
    Base.metadata.create_all(p.engine,tables=[Base.metadata.tables[n] for n in names])
    with Session(p.engine) as db:
        for identifier in ['LSX1','LSX2']:db.get(ProductionOrder,identifier).status='Đã kết thúc'
        db.commit()
    p.client.app.include_router(router)
    p.allocation=reserve(p,80).json()
    p.run_payload={'id':'RUN1','standard_id':p.standard_id,'machine_id':'DH1','group_id':'GROUP1','group_confirmed':True,
        'items':[{'order_line_id':'CT1','quantity':60,'cavity':4},{'order_line_id':'CT2','quantity':100,'cavity':2}],
        'materials':[{'allocation_id':p.allocation['id'],'kg':'80'}],'note':'Planner confirmed grouping'}
    yield p


def write(p,path,data,method='post'):
    return getattr(p.client,method)('/api/production/'+path,json=data,headers={'Idempotency-Key':str(uuid4())})


def create(p):
    r=write(p,'runs',p.run_payload);assert r.status_code==201,r.text
    return r.json()


def start_and_issue(p):
    run=create(p)
    r=write(p,'runs/RUN1/start',{'version':run['version'],'note':'Start'});assert r.status_code==200,r.text
    r=material_write(p.client,'allocations/'+p.allocation['id']+'/issue',{'version':1,'production_order_id':'RUN1','kg':'20'})
    assert r.status_code==201,r.text
    from app.modules.materials.inventory.models import FilmMovement
    from app.modules.production.run_service import ZONE
    with Session(p.engine) as db:
        db.get(FilmMovement,r.json()['movement_id']).moved_at=(datetime.now(ZONE)-timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
        db.commit()
    return p.client.get('/api/production/runs/RUN1').json()


def shift(p,identifier,sheets,goods,consumed,*,edit=None,start=None):
    current=p.client.get('/api/production/runs/RUN1').json()
    end=datetime.now(timezone.utc)-timedelta(hours={'SHIFT1':2,'SHIFT2':1,'SHIFT3':.5}.get(identifier,2))
    begin=start or end-timedelta(minutes=1)
    payload={'id':identifier,'run_version':current['version'],'start':begin.isoformat(),'end':end.isoformat(),
        'good_sheets':sheets,'ng_sheets':0,'seconds_per_cycle':4,'pull_mm':500,'sheet_weight_kg':0.175,
        'items':[{'order_line_id':'CT1','good':goods[0],'ng':0},{'order_line_id':'CT2','good':goods[1],'ng':0}],
        'sources':[{'receipt_id':'R1','consumed_kg':str(consumed)}],'note':'Counted shift'}
    if edit:payload['version']=edit
    return write(p,'runs/RUN1/shifts'+('/'+identifier if edit else ''),payload,'put' if edit else 'post')


def test_group_common_cycles_and_double_booking(running_setup):
    p=running_setup;run=create(p)
    assert Decimal(str(run['planned_cycles']))==15
    assert Decimal(str(run['planned_hours']))==pytest.approx(Decimal(60)/3600)
    assert write(p,'runs',{**p.run_payload,'id':'RUN2'}).status_code==409
    r=material_write(p.client,'allocations/'+p.allocation['id'],{'version':1,'held_kg':'79','note':'Would break run commitment'},method='put')
    assert r.status_code==409
    with Session(p.engine) as db:
        assert db.get(ProductionOrder,'RUN1').group_id=='GROUP1'


def test_shift_second_precision_and_safe_next_shift(running_setup):
    p=running_setup;run=create(p)
    started=write(p,'runs/RUN1/start',{'version':run['version'],'note':'Start'}).json()
    base=(datetime.now(timezone.utc)-timedelta(seconds=10)).replace(microsecond=0)
    payload={'id':'PRECISE1','run_version':started['version'],'start':(base+timedelta(microseconds=100000)).isoformat(),
        'end':(base+timedelta(microseconds=900000)).isoformat(),'good_sheets':0,'ng_sheets':0,'seconds_per_cycle':4,
        'pull_mm':500,'sheet_weight_kg':.175,'items':[{'order_line_id':ct,'good':0,'ng':0} for ct in ['CT1','CT2']],
        'sources':[],'pure_seconds':0,'note':'Second precision'}
    assert write(p,'runs/RUN1/shifts',payload).status_code==422
    payload['start']=(base-timedelta(minutes=1)+timedelta(microseconds=100000)).isoformat()
    result=write(p,'runs/RUN1/shifts',payload);assert result.status_code==201,result.text
    first=result.json();assert datetime.fromisoformat(first['end']).microsecond==0
    assert datetime.fromisoformat(first['end'])==base
    payload.update(id='PRECISE2',run_version=p.client.get('/api/production/runs/RUN1').json()['version'],
        start=first['end'],end=(base+timedelta(seconds=1)).isoformat())
    result=write(p,'runs/RUN1/shifts',payload);assert result.status_code==201,result.text


def test_shift_balance_carry_stop_at_product_boundary(running_setup):
    p=running_setup;start_and_issue(p)
    r=shift(p,'SHIFT1',5,(20,10),2);assert r.status_code==201,r.text
    first=r.json();assert Decimal(first['sources'][0]['closing_kg'])==18
    current=p.client.get('/api/production/runs/RUN1').json();assert current['status']=='Đang chạy'
    assert write(p,'runs/RUN1',{**p.run_payload,'version':current['version'],'machine_id':'Other'} ,'put').status_code==409
    r=shift(p,'SHIFT2',10,(40,20),3,start=datetime.fromisoformat(first['end']));assert r.status_code==201,r.text
    second=r.json();assert Decimal(second['sources'][0]['opening_kg'])==18 and Decimal(second['sources'][0]['closing_kg'])==15
    current=p.client.get('/api/production/runs/RUN1').json();assert not current['can_continue']
    assert shift(p,'SHIFT3',1,(0,2),1,start=datetime.fromisoformat(second['end'])).status_code==409
    assert shift(p,'SHIFT1',5,(20,10),2,edit=first['version']).status_code==409
    r=write(p,'runs/RUN1/finish',{'version':current['version'],'note':'First product complete'});assert r.status_code==200,r.text
    row=p.client.get('/api/production/preparation?line_id=CT2').json()['items'][0]
    assert Decimal(row['available_to_schedule'])==70


def test_separate_calendar_default_version_and_inheritance(running_setup):
    p=running_setup
    weekly={'0':{'shifts':[{'start':480,'end':1320}],'breaks':[{'start':720,'end':780},{'start':1050,'end':1080}]}}
    r=p.client.put('/api/production/calendar-default',json={'version':0,'weekly':weekly});assert r.status_code==200,r.text
    assert p.client.put('/api/production/calendar-default',json={'version':0,'weekly':weekly}).status_code==409
    data=p.client.get('/api/production/calendars/DH1?start=2026-11-16&end=2026-11-16').json()
    assert data['inherited'] and data['weekly']==weekly
    result=p.client.get('/api/production/availability?machine_id=DH1&start=2026-11-16&end=2026-11-16').json()
    assert len(result['machines'][0]['windows'])==3


def test_downstream_repeated_source_and_tail_edit_guard(running_setup):
    p=running_setup;start_and_issue(p);r=shift(p,'SHIFT1',5,(20,10),2);assert r.status_code==201,r.text
    log=r.json()
    assert p.client.post('/api/production/machines',json={'id':'CUT1','name':'Cutting','kind':'cutting','status':'ready'}).status_code==201
    payload={'id':'CUTLOG1','stage':'cutting','forming_log_id':'SHIFT1','machine_id':'CUT1',
        'start':log['end'],'end':(datetime.fromisoformat(log['end'])+timedelta(minutes=5)).isoformat(),
        'items':[{'order_line_id':'CT1','good':10,'ng':0}],'note':'First partial cut'}
    r=write(p,'downstream',payload);assert r.status_code==201,r.text
    assert r.json()['DH_ID']=='SHIFT1'
    assert write(p,'downstream',{**payload,'id':'OVERLAP'}).status_code==409
    second={**payload,'id':'CUTLOG2','start':payload['end'],'end':(datetime.fromisoformat(payload['end'])+timedelta(minutes=5)).isoformat()}
    r=write(p,'downstream',second);assert r.status_code==201,r.text
    assert write(p,'downstream',{**second,'id':'CUTLOG3','start':second['end'],'end':(datetime.fromisoformat(second['end'])+timedelta(minutes=5)).isoformat()}).status_code==409
    assert shift(p,'SHIFT1',5,(20,10),2,edit=log['version']).status_code==409
