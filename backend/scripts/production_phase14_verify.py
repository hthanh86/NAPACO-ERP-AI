"""HTTP acceptance/races on retained P14 data only; never signs for a real user."""
import argparse,json,secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core import model_registry
from app.core.database import engine
from app.auth.models import User,LoginSession
from app.auth.security import token_hash
from app.modules.production.models import ProductionOrder,FormingLog
from app.modules.production.planning_service import ZONE
from app.modules.materials.inventory.allocation_models import MaterialAllocation
from app.modules.materials.inventory.handover_models import MaterialHandover
from app.modules.materials.inventory.allocation_service import receipt_balances
from app.modules.production.run_models import ShiftItem

REPORT=Path('/app/reports/production-phase14-verification.json')
MANIFEST=Path('/app/reports/production-phase14-demo.json')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',required=True,action='store_true');parser.parse_args()
    if engine.url.host!='mysql':raise RuntimeError('Chỉ kiểm tra compose local.')
    if REPORT.exists():print('Giữ nguyên kết quả kiểm tra và dữ liệu đã tạo:',REPORT);return
    data=json.loads(MANIFEST.read_text());checks={}
    with Session(engine) as db:
        admin=db.scalar(select(User).where(User.role=='LOCAL_ADMIN',User.active.is_(True)).limit(1));assert admin
        token=secrets.token_urlsafe(40)
        db.add(LoginSession(token_hash=token_hash(token),user_id=admin.id,expires_at=datetime.utcnow()+timedelta(minutes=30)));db.commit()
    def request(method,path,body=None,key=None):
        # Local boundary checks Host; requests still reach the running backend.
        with httpx.Client(base_url='http://backend:8000',cookies={'napaco_session':token},headers={'Host':'localhost:8000'},timeout=30) as client:
            return client.request(method,path,json=body,headers={'Idempotency-Key':key or str(uuid4())})
    def get(path):
        r=request('GET',path);assert r.is_success,(path,r.status_code,r.text);return r.json()
    for name,expected in [('PASS',True),('SORT',True),('STOP',False),('RESTART',False)]:
        c=data['cases'][name];value=get('/api/production/runs/'+c['run_id']+'/sample-eligibility?machine_id='+c['machine'])
        assert value['allowed']==expected,(name,value);checks['sample_'+name]=value
    assert get('/api/production/machines/P14_DRAFT_DH/work')['total']==0
    checks['draft_not_in_machine_queue']=True
    balance=get('/api/production/materials/runs/P14_NVL/balance')
    assert balance['lots'][0]['usable_kg']=='5.00000000' and balance['lots'][0]['pending_handover_kg']=='3.00000000'
    checks['received_vs_pending_kg']={'usable':5,'pending':3}
    a=get('/api/production/forming/runs/P14_A/summary')
    assert a['count']==2 and a['items'][0]['good_qty']==40 and a['lots'][0]['usable_kg']=='8.00000000'
    checks['multi_day_move_same_lsx']={'logs':a['count'],'good_qty':40,'remaining_kg':8}
    ab=get('/api/production/forming/runs/P14_AB/summary')
    assert ab['count']==1 and len(ab['items'])==2 and [i['good_qty'] for i in ab['items']]==[10,10]
    checks['group_one_interval']={'logs':1,'ctdh_good':[10,10],'seconds':ab['interval_seconds']}
    queue=get('/api/production/machines/P14_QUEUE_DH/work')
    assert {i['run_id'] for i in queue['items']}=={'P14_QUEUE_A','P14_QUEUE_B'}
    checks['B_before_A']=get('/api/production/forming/runs/P14_QUEUE_B/summary')['count']==1
    with Session(engine) as db:
        allocation=db.scalar(select(MaterialAllocation).where(MaterialAllocation.order_line_id=='P14_NVL_CT_A'))
        aid=allocation.id;av=allocation.version;stock_before=receipt_balances(db,['P14_NVL_LOT'])['P14_NVL_LOT']['stock_kg']
        before=db.scalar(select(func.count()).select_from(MaterialHandover).where(MaterialHandover.run_id=='P14_NVL'))
    body={'version':av,'production_order_id':'P14_NVL','kg':'6','note':'[P14 GIẢ LOCAL] Ghi đồng thời hai phiếu cùng phần giữ'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:request('POST','/api/production/materials/allocations/'+aid+'/issue',body),range(2)))
    assert sorted(r.status_code for r in responses)==[201,409],[(r.status_code,r.text) for r in responses]
    with Session(engine) as db:
        after=db.scalar(select(func.count()).select_from(MaterialHandover).where(MaterialHandover.run_id=='P14_NVL'))
        assert after==before+1 and receipt_balances(db,['P14_NVL_LOT'])['P14_NVL_LOT']['stock_kg']==stock_before
    created=next(r.json() for r in responses if r.status_code==201)
    data['cases']['NVL']['handovers'].append({'id':created['id'],'state':'draft','kg':6})
    checks['concurrent_draft_capacity']={'statuses':[r.status_code for r in responses],'one_new_draft':created['id'],'stock_unchanged':True}
    c=data['cases']['SORT'];end=datetime.now(ZONE).replace(microsecond=0)-timedelta(seconds=1);start=end-timedelta(seconds=5)
    context=get('/api/production/forming/context?run_id=P14_SORT&machine_id=P14_SORT_DH')
    body={'id':str(uuid4()),'run_version':context['run_version'],'machine_id':c['machine'],'assignment_id':context['assignment_id'],
        'setup_id':context['episode']['id'],'episode_version':context['episode']['version'],'sample_qc_id':context['sample_basis']['qc_id'],
        'sample_qc_version':context['sample_basis']['qc_version'],'source_hash':context['source_hash'],'start':start.isoformat(),'end':end.isoformat(),
        'good_sheets':2,'ng_sheets':0,'items':[{'order_line_id':'P14_SORT_CT_A','good':8,'ng':0}],
        'sources':[{'receipt_id':'P14_SORT_LOT','consumed_kg':'1'}],'episode_action':'continue','note':'[P14 GIẢ LOCAL] API đồng thời / NG cho chạy lọc'}
    key=str(uuid4());path='/api/production/forming/runs/P14_SORT/logs'
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:request('POST',path,body,key),range(2)))
    assert [r.status_code for r in responses]==[201,201],[(r.status_code,r.text) for r in responses]
    assert responses[0].json()['id']==responses[1].json()['id']==body['id']
    summary=get('/api/production/forming/runs/P14_SORT/summary')
    assert summary['count']==1 and summary['items'][0]['good_qty']==8 and summary['lots'][0]['consumed_kg']=='1.00000000'
    assert responses[0].json()['sample_basis']['result']=='NG' and responses[0].json()['sample_basis']['decision']=='sort'
    data['cases']['SORT']['logs'].append(body['id'])
    checks['concurrent_diary_idempotency_NG_sort']={'statuses':[201,201],'single_log':body['id'],'good_qty':8,'consumed_kg':1}
    # Include the row previously entered through the actual browser in the manifest.
    data['cases']['PASS']['logs']=[row['id'] for row in get('/api/production/runs/P14_PASS/shifts')['items']]
    for path in ['/production/schedule','/production/runs','/production/materials','/production/handovers','/production/samples','/production/forming']:
        response=request('GET',path);assert response.status_code==200 and 'Đăng nhập hệ thống' not in response.text,path
    checks['all_six_pages_served']=True
    result={'local_only':True,'checked_at':datetime.now(ZONE).isoformat(),'checks':checks,
        'not_verified':['Real Google OAuth signature','Real Google Sheets/Drive PDF export','Full legacy test-suite compatibility']}
    MANIFEST.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'checks':len(checks),'passed':True,'report':str(REPORT)},ensure_ascii=False))


if __name__=='__main__':main()
