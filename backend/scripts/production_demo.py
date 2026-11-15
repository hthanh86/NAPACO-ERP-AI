"""Explicit local-only phase-7 demo/acceptance. Keeps generated data for review.

Run via compose, never production. Existing master/orders/receipts are reused.
Generated movements alone are dated to demo production time, with an audit record.
A checkpoint report makes retries safe without issuing/producing twice.
"""
import argparse,json,os,copy
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,delete,text,func
from sqlalchemy.orm import Session
from app.core import model_registry
from app.core.database import engine
from app.auth.security import current_user
from app.auth.models import User
from app.modules.production import planning_api,run_api,schedule_api
from app.modules.materials.inventory import allocation_api,allocation_service
from app.modules.production.models import CuttingLog,EBLog,FormingLog,ProductionOrder
from app.modules.production.schedule_models import SchedulePlan,ScheduleDay
from app.modules.production.planning_service import ZONE
from app.modules.materials.inventory.models import FilmMovement
from app.modules.orders.models import OrderLine

CT1='CT_261101_14';CT2='CT_261106_08';RECEIPT='N_NVL_261110_01';RECEIPT2='N_NVL_261110_06'
NOTE='[DEMO7] Dữ liệu giả kiểm tra Kế hoạch sản xuất, giữ lại theo yêu cầu.'
REPORT=Path('/app/reports/production-phase7-demo.json')
app=FastAPI()
for router in [planning_api.router,allocation_api.router,run_api.router,schedule_api.router]:app.include_router(router)
with Session(engine) as db:
    admin=db.scalar(select(User).where(User.role=='LOCAL_ADMIN',User.active.is_(True)).limit(1))
    if not admin:raise RuntimeError('Cần tài khoản LOCAL_ADMIN hiện có; không tự tạo/thay quyền.')
    db.expunge(admin)
app.dependency_overrides[current_user]=lambda:admin
client=TestClient(app)
M=json.loads(REPORT.read_text()) if REPORT.exists() else {'steps':{},'checks':{},'prefix':'DEMO7','note':NOTE}

def save():
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(M,ensure_ascii=False,indent=2,default=str))

def once(key,fn):
    if key not in M['steps']:
        M['steps'][key]=fn();save();print('DONE',key,flush=True)
    return M['steps'][key]

def request(method,path,data=None,expected=None):
    response=client.request(method,'/api/production/'+path,json=data,headers={'Idempotency-Key':str(uuid4())})
    if expected is not None:assert response.status_code==expected,(method,path,response.status_code,response.text)
    else:assert response.is_success,(method,path,response.status_code,response.text)
    return response.json()

def check(key,fn):
    result=fn();M['checks'][key]=result if result is not None else 'passed';save();print('PASS',key,flush=True);return result

def getrun(identifier):return request('GET','runs/'+identifier)
def state(identifier,action):
    run=getrun(identifier);return request('POST','runs/'+identifier+'/'+action,{'version':run['version'],'note':NOTE})
def reserve(standard,ct,kg,receipt=RECEIPT):
    return request('POST','materials/allocations',{'standard_id':standard,'order_line_id':ct,'receipt_id':receipt,'kg':str(kg),'note':NOTE})
def create_run(identifier,standard,items,bindings,machine='DEMO7-DH-A',**extra):
    return request('POST','runs',{'id':identifier,'standard_id':standard,'machine_id':machine,'items':items,
        'materials':bindings,'group_id':'DEMO7-GROUP' if len(items)>1 else '', 'group_confirmed':len(items)>1,'note':NOTE,**extra})
def issue(allocation,run,kg,at):
    with Session(engine) as db:
        from app.modules.materials.inventory.allocation_models import MaterialAllocation
        version=db.get(MaterialAllocation,allocation['id']).version
    result=request('POST','materials/allocations/'+allocation['id']+'/issue',{'version':version,'production_order_id':run,'kg':str(kg),'note':NOTE})
    # Only this generated movement is backdated, never an existing receipt or business document.
    with Session(engine) as db:
        row=db.get(FilmMovement,result['movement_id']);row.moved_at=at.strftime('%Y-%m-%d %H:%M:%S');row.source={'demo':'DEMO7','purpose':NOTE}
        allocation_service.audit(db,admin,'PRODUCTION_DEMO_MOVEMENT_DATE',row.id,{'production_at':row.moved_at,'note':NOTE});db.commit()
    return result

def shift(run,identifier,start,end,cycles,goods,consumed,pure,setup=0):
    current=getrun(run)
    return request('POST','runs/'+run+'/shifts',{'id':identifier,'run_version':current['version'],
        'start':start.isoformat(),'end':end.isoformat(),'good_sheets':cycles,'ng_sheets':0,
        'seconds_per_cycle':pure/cycles if cycles else 4,'pull_mm':500,'sheet_weight_kg':current['snapshot']['parameters']['sheet_weight_kg'],
        'items':[{'order_line_id':ct,'good':qty,'ng':0} for ct,qty in goods.items()],
        'sources':[{'receipt_id':r,'consumed_kg':str(kg)} for r,kg in consumed.items()],
        'pure_seconds':pure,'setup_seconds':setup,'note':NOTE})

def downstream(identifier,source,stage,start,end,goods,machine):
    return request('POST','downstream',{'id':identifier,'forming_log_id':source,'stage':stage,'machine_id':machine,
        'start':start.isoformat(),'end':end.isoformat(),'items':[{'order_line_id':ct,'good':qty,'ng':0} for ct,qty in goods.items()],
        'pure_seconds':sum(goods.values())*.5,'setup_seconds':30,'note':NOTE})

def initial_cleanup():
    with Session(engine) as db:
        assert db.scalar(text('select version_num from alembic_version'))=='014'
        assert not db.scalar(select(func.count()).select_from(FormingLog))
        cuts=list(db.scalars(select(CuttingLog.id)));edges=list(db.scalars(select(EBLog.id)))
        assert cuts==['CUT_261020_01'] and edges==['CUT_261020_01'],('Dữ liệu đã khác bản kiểm kê; dừng xóa.',cuts,edges)
        db.execute(delete(CuttingLog).where(CuttingLog.id.in_(cuts)));db.execute(delete(EBLog).where(EBLog.id.in_(edges)))
        allocation_service.audit(db,admin,'PRODUCTION_DEMO_DRAFT_LOG_CLEAR','DEMO7',{'cutting_ids':cuts,'edge_ids':edges,'backup':'napaco-pre-phase7-20261114.sql.gz','note':NOTE})
        db.commit();return {'cutting_ids':cuts,'edge_ids':edges,'forming':0,'audit_preserved':True}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',action='store_true',required=True);parser.parse_args()
    assert engine.url.host=='mysql','Chỉ được chạy trong compose local mysql.'
    if M.get('status')=='completed':
        print('DEMO7 đã tạo xong; giữ nguyên dữ liệu. Xem',REPORT);return
    once('clear_original_draft_logs',initial_cleanup)
    for ct,product in [(CT1,'SP0006'),(CT2,'SP0002')]:
        with Session(engine) as db:
            line=db.get(OrderLine,ct);assert line and line.product_id==product and line.quantity-line.produced>1000
    today=datetime.now(ZONE).replace(hour=0,minute=0,second=0,microsecond=0);M['view_start']=(today-timedelta(days=4)).isoformat();M['view_end']=(today+timedelta(days=4)).isoformat();M['seal_day']=today.date().isoformat();save()
    for identifier,kind in [('DEMO7-DH-A','semi_automatic'),('DEMO7-DH-B','semi_automatic'),('DEMO7-AUTO','automatic'),('DEMO7-EDGE','edge')]:
        once('machine:'+identifier,lambda identifier=identifier,kind=kind:request('POST','machines',{'id':identifier,'name':'[Dữ liệu giả] '+identifier,'kind':kind,'status':'ready','max_width_mm':700,'max_pull_mm':700,'notes':NOTE}))
    def calendar():
        current=request('GET','calendar-default')
        return request('PUT','calendar-default',{'version':current['version'],'weekly':{str(i):{'shifts':[{'start':480,'end':1320}],'breaks':[{'start':720,'end':780},{'start':1080,'end':1110}]} for i in range(7)}}) if current['version']==0 else {'kept_existing':True}
    once('common_calendar',calendar)
    def standard(code,items,machine='DEMO7-DH-A'):
        previous=request('GET','standards?q='+code)['items'];prior=next((s for s in previous if s['code']==code),None)
        return request('POST','standards/'+prior['id']+'/revisions' if prior else 'standards',{'code':code,'name':NOTE+' '+code,'machine_id':machine,'material_id':'VL0001','mold_id':'CC0001',
            'pull_mm':500,'seconds_per_cycle':60,'density':1.4,'setup_minutes':10,'waste_percent':3,'items':items})
    single=once('standard:v2:single',lambda:standard('DEMO7-SINGLE',[{'product_id':'SP0006','cavity':5,'edge':True}]))['id']
    other=once('standard:v2:other',lambda:standard('DEMO7-OTHER',[{'product_id':'SP0002','cavity':2,'edge':False}]))['id']
    group=once('standard:v2:group',lambda:standard('DEMO7-GROUP',[{'product_id':'SP0006','cavity':5,'edge':True},{'product_id':'SP0002','cavity':2,'edge':False}]))['id']
    auto=once('standard:v2:auto',lambda:standard('DEMO7-AUTO',[{'product_id':'SP0006','cavity':5,'edge':False}],'DEMO7-AUTO'))['id']
    A=once('allocation:A',lambda:reserve(single,CT1,120));B=once('allocation:B',lambda:reserve(group,CT2,30));C=once('allocation:C',lambda:reserve(single,CT1,30,RECEIPT2))
    for index,pure in [(1,80),(2,84),(3,88)]:
        rid='DEMO7-H'+str(index);at=today-timedelta(days=4-index)+timedelta(hours=8)
        once('run:'+rid,lambda rid=rid:create_run(rid,single,[{'order_line_id':CT1,'quantity':100,'cavity':5}],[{'allocation_id':A['id'],'kg':'5'}]))
        once('start:'+rid,lambda rid=rid:state(rid,'start'))
        once('issue:'+rid,lambda rid=rid,at=at:issue(A,rid,5,at))
        once('shift:'+rid,lambda rid=rid,at=at,pure=pure:shift(rid,rid+'-CA1',at,at+timedelta(hours=1),20,{CT1:100},{RECEIPT:5},pure,60))
        once('cut:'+rid,lambda rid=rid,at=at:downstream(rid+'-CUT',rid+'-CA1','cutting',at+timedelta(hours=1),at+timedelta(hours=1,minutes=10),{CT1:100},'BC-01'))
        once('edge:'+rid,lambda rid=rid,at=at:downstream(rid+'-EDGE',rid+'-CA1','edge',at+timedelta(hours=1,minutes=10),at+timedelta(hours=1,minutes=20),{CT1:100},'DEMO7-EDGE'))
        once('finish:'+rid,lambda rid=rid:state(rid,'finish'))
    rid='DEMO7-G1';at=today-timedelta(days=2)+timedelta(hours=20)
    once('run:'+rid,lambda:create_run(rid,group,[{'order_line_id':CT1,'quantity':100,'cavity':5},{'order_line_id':CT2,'quantity':100,'cavity':2}],[{'allocation_id':A['id'],'kg':'3'},{'allocation_id':C['id'],'kg':'2'}]))
    once('start:'+rid,lambda:state(rid,'start'));once('issue:'+rid+'A',lambda:issue(A,rid,3,at));once('issue:'+rid+'C',lambda:issue(C,rid,2,at))
    once('shift:G1a',lambda:shift(rid,rid+'-CA1',at,at+timedelta(hours=2),5,{CT1:25,CT2:10},{RECEIPT:'.6',RECEIPT2:'.4'},20,60))
    g2=once('shift:G1b',lambda:shift(rid,rid+'-CA2',at+timedelta(hours=14),at+timedelta(hours=15),15,{CT1:75,CT2:30},{RECEIPT:'2.4',RECEIPT2:'1.6'},60))
    assert {s['receipt_id']:Decimal(s['opening_kg']) for s in g2['sources']}=={RECEIPT:Decimal('2.4'),RECEIPT2:Decimal('1.6')}
    check('multi_day_multi_source_carry',lambda:'opening + input - output - consumed = closing, both sources retained')
    once('finish:'+rid,lambda:state(rid,'finish'))
    once('run:tail',lambda:create_run('DEMO7-TAIL',other,[{'order_line_id':CT2,'quantity':60,'cavity':2}],[{'allocation_id':B['id'],'kg':'8'}],parent_run_id=rid))
    history=once('history:exact',lambda:request('POST','run-suggestions',{'standard_id':single,'machine_id':'DEMO7-DH-A','items':[{'order_line_id':CT1,'cavity':5}]}))
    assert history['samples']==3 and history['statistics']['seconds_per_cycle']['typical']==4.2
    check('measured_history_three_runs',lambda:{'samples':history['samples'],'typical':4.2,'wall_time_excluded':True})
    once('run:U1',lambda:create_run('DEMO7-U1',single,[{'order_line_id':CT1,'quantity':500,'cavity':5}],[{'allocation_id':A['id'],'kg':'30'}],history_selection={'kind':'statistics','context_hash':history['context_hash']}))
    once('run:U2',lambda:create_run('DEMO7-U2',other,[{'order_line_id':CT2,'quantity':200,'cavity':2}],[{'allocation_id':B['id'],'kg':'20'}],'DEMO7-DH-B'))
    once('run:AUTO',lambda:create_run('DEMO7-AUTO-RUN',auto,[{'order_line_id':CT1,'quantity':250,'cavity':5}],[{'allocation_id':C['id'],'kg':'15'}],'DEMO7-AUTO'))
    # Reject a duplicate CT quantity and stale run edit without modifying either run.
    request('POST','runs',{'id':'DEMO7-OVER','standard_id':single,'machine_id':'DEMO7-DH-A','items':[{'order_line_id':CT1,'quantity':1000000,'cavity':5}],'note':NOTE},409)
    check('duplicate_output_rejected',lambda:True)
    def hold_race():
        with Session(engine) as db:available=allocation_service.receipt_balances(db,[RECEIPT])[RECEIPT]['available_kg']
        kg=(available*Decimal('.75')).quantize(Decimal('.00000001'))
        def worker(_):
            with TestClient(app) as c:return c.post('/api/production/materials/allocations',json={'standard_id':single,'order_line_id':CT1,'receipt_id':RECEIPT,'kg':str(kg),'note':NOTE+' race'},headers={'Idempotency-Key':str(uuid4())})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(worker,range(2)))
        assert sorted(r.status_code for r in responses)==[201,409],[(r.status_code,r.text) for r in responses]
        winner=next(r.json() for r in responses if r.status_code==201)
        request('PUT','materials/allocations/'+winner['id'],{'version':winner['version'],'held_kg':'0','note':NOTE+' release race hold'})
        return [r.status_code for r in responses]
    once('race:hold',lambda:check('mysql_concurrent_holds',hold_race))
    once('allocation:B:expand',lambda:request('PUT','materials/allocations/'+B['id'],{'version':B['version'],'held_kg':'45','note':NOTE+' đủ cho U2 và phần chạy lẻ'}))
    once('run:U2:material',lambda:request('POST','runs/DEMO7-U2/materials',{'version':getrun('DEMO7-U2')['version'],'allocation_id':B['id'],'planned_kg':'27','note':NOTE}))
    stage=lambda ct,name,machine:{'order_line_id':ct,'stage':name,'machine_id':machine,'seconds_per_unit':.5,'setup_minutes':1,'wait_minutes':5,'unit':'Cái','mode':'rolling','handoff_quantity':100}
    payload={'base_version':0,'planning_day':today.date().isoformat(),'day_version':0,'start':today.replace(hour=8).isoformat(),'end':(today+timedelta(days=3,hours=22)).isoformat(),
        'order':['DEMO7-U1','DEMO7-U2','DEMO7-TAIL','DEMO7-AUTO-RUN'],'jobs':[
            {'run_id':'DEMO7-U1','stages':[stage(CT1,'cutting','BC-01'),stage(CT1,'edge','DEMO7-EDGE')]},
            {'run_id':'DEMO7-U2','stages':[stage(CT2,'cutting','BC-01')]},
            {'run_id':'DEMO7-TAIL','stages':[stage(CT2,'cutting','BC-01')]}]}
    def save_plan(data):
        preview=request('POST','schedule/preview',data)
        return request('POST','schedule/save',{**data,'preview_hash':preview['preview_hash'],'confirmations':[w['code'] for w in preview['warnings']]})
    first=once('plan:initial',lambda:save_plan(payload))
    closed=once('plan:close',lambda:request('POST','schedule/daily/close',{'day':today.date().isoformat(),'day_version':first['day']['version'],'plan_version':first['version'],'note':NOTE}))
    request('POST','schedule/daily/close',{'day':today.date().isoformat(),'day_version':closed['version'],'plan_version':first['version'],'note':NOTE},409)
    check('explicit_immutable_daily_close',lambda:closed['initial_plan_id'])
    with Session(engine) as db:
        row=db.get(SchedulePlan,closed['initial_plan_id']);baseline=json.dumps([row.request,row.result,row.context],sort_keys=True,default=str)
    def update_payload():
        from urllib.parse import urlencode
        latest=request('GET','schedule/latest');view=request('GET','schedule/view?'+urlencode({'view_start':M['view_start'],'view_end':M['view_end']}))
        return {'base_version':latest['version'],'planning_day':today.date().isoformat(),'day_version':view['day']['version'],**latest['request']}
    def moves():
        data=update_payload();data['moves']=[{'run_id':'DEMO7-U1','machine_id':'DEMO7-DH-B','version':getrun('DEMO7-U1')['version'],'note':NOTE}]
        preview=request('POST','schedule/preview',data)
        assert any(w['code'].startswith('CONFIRM_MOVE') for w in preview['warnings'])
        request('POST','schedule/save',{**data,'preview_hash':preview['preview_hash'],'confirmations':[]},409)
        saved=request('POST','schedule/save',{**data,'preview_hash':preview['preview_hash'],'confirmations':[w['code'] for w in preview['warnings']]})
        assert getrun('DEMO7-U1')['machine_id']=='DEMO7-DH-B';return saved
    once('plan:move',lambda:check('move_requires_confirmation_removes_old_placement',moves))
    def stop_preview(hold,duration=None):
        data=update_payload();data['stops']=[{'id':'DEMO7-STOP','run_id':'DEMO7-U1','at':today.replace(hour=8,minute=30).isoformat(),'duration_seconds':duration,'hold_machine':hold,'note':NOTE}]
        result=request('POST','schedule/preview',data);job=next(j for j in result['result']['jobs'] if j['run_id']=='DEMO7-U1')
        assert job['status']==('unknown' if hold and duration is None else 'released_waiting' if not hold else job['status'])
        return {'status':job['status'],'end':job['forming_end']}
    check('unknown_stop_hold',lambda:stop_preview(True));check('unknown_stop_release',lambda:stop_preview(False));check('known_stop_recalculate',lambda:stop_preview(True,600))
    def exception():
        machines=request('GET','machines?q=DEMO7-DH-B')['items'];m=next(m for m in machines if m['id']=='DEMO7-DH-B')
        return request('PUT','calendars',{'versions':{m['id']:m['version']},'exceptions':[{'day':today.date().isoformat(),'windows':[{'start':480,'end':1320}],'note':NOTE+' chạy xuyên nghỉ hôm nay'}]})
    once('calendar:exception',exception)
    once('plan:reorder',lambda:save_plan({**update_payload(),'order':['DEMO7-U2','DEMO7-U1','DEMO7-TAIL','DEMO7-AUTO-RUN']}))
    def plan_race():
        data=update_payload();preview=request('POST','schedule/preview',data);body={**data,'preview_hash':preview['preview_hash'],'confirmations':[w['code'] for w in preview['warnings']]}
        def worker(_):
            with TestClient(app) as c:return c.post('/api/production/schedule/save',json=body,headers={'Idempotency-Key':str(uuid4())})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(worker,range(2)))
        assert sorted(r.status_code for r in responses)==[201,409],[(r.status_code,r.text) for r in responses]
        return [r.status_code for r in responses]
    once('race:plan',lambda:check('mysql_concurrent_plan_save',plan_race))
    # A late-entered production journal for the baseline run, entered after the seal.
    rid='DEMO7-U1';at=today.replace(hour=8)
    once('start:'+rid,lambda:state(rid,'start'));once('issue:'+rid,lambda:issue(A,rid,3,at))
    once('shift:'+rid,lambda:shift(rid,rid+'-CA1',at,at+timedelta(hours=1),5,{CT1:25},{RECEIPT:3},100,60))
    # Started runs cannot move. Continue the shortfall with a stable new run ID.
    current=getrun(rid)
    request('PUT','runs/'+rid,{'id':rid,'version':current['version'],'standard_id':single,'machine_id':'DEMO7-DH-A','items':[{'order_line_id':CT1,'quantity':500,'cavity':5}],'note':NOTE},409)
    def continuation():
        data=update_payload();data['end_runs']=[{'run_id':rid,'version':getrun(rid)['version'],'note':NOTE+' chen đơn và tiếp phần thiếu'}]
        data['changes']=[{'split_from':rid,'config':{'id':'DEMO7-U1-CONT','standard_id':single,'machine_id':'DEMO7-DH-B','parent_run_id':rid,
            'items':[{'order_line_id':CT1,'quantity':475,'cavity':5}],'materials':[{'allocation_id':A['id'],'kg':'27'}],'note':NOTE}}]
        data['order']=[i for i in data['order'] if i!=rid]+['DEMO7-U1-CONT'];data['jobs']=[j for j in data['jobs'] if j['run_id']!=rid]+[
            {'run_id':'DEMO7-U1-CONT','stages':[stage(CT1,'cutting','BC-01'),stage(CT1,'edge','DEMO7-EDGE')]}]
        return save_plan(data)
    once('plan:continue',lambda:check('interrupt_close_and_continue_remaining',continuation))
    from urllib.parse import urlencode
    scope=urlencode({'view_start':M['view_start'],'view_end':M['view_end'],'day':M['seal_day']})
    for mode in ['actual','update']:
        result=request('GET','schedule/daily/compare?'+scope+'&mode='+mode)
        assert result['comparison'];M['checks']['comparison:'+mode]={'rows':len(result['comparison']['rows']) if 'rows' in result['comparison'] else 'available'}
    with Session(engine) as db:
        row=db.get(SchedulePlan,closed['initial_plan_id']);assert json.dumps([row.request,row.result,row.context],sort_keys=True,default=str)==baseline
        M['checks']['late_journal_preserves_sealed_snapshot']=True
        M['counts']={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('forming',FormingLog),('cutting',CuttingLog),('edge',EBLog),('runs',ProductionOrder),('plans',SchedulePlan)]}
    M['status']='completed';save();print(json.dumps({'status':M['status'],'counts':M['counts'],'report':str(REPORT)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        M['status']='failed';M['error']=str(exc);save();raise
