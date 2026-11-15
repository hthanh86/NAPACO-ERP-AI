"""Local MySQL race: issuing material while closing a shift must not lose/double stock."""
from scripts.production_demo import *
from app.modules.production.run_service import source_position
from app.modules.materials.inventory.allocation_models import MaterialAllocation


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',action='store_true',required=True);parser.parse_args()
    assert engine.url.host=='mysql' and M.get('acceptance_complete')
    if 'race:issue_shift:finish' in M['steps']:print('Race đã kiểm tra, giữ dữ liệu.');return
    standard=M['steps']['standard:v2:single']['id'];allocation=M['steps']['allocation:A'];rid='DEMO7-RACE-SHIFT'
    once('race:issue_shift:run',lambda:create_run(rid,standard,[{'order_line_id':CT1,'quantity':50,'cavity':5}],[{'allocation_id':allocation['id'],'kg':'2'}]))
    once('race:issue_shift:start',lambda:state(rid,'start'))
    at=datetime.now(ZONE)-timedelta(seconds=3)
    once('race:issue_shift:initial',lambda:issue(allocation,rid,1,at))
    def race():
        run=getrun(rid);end=datetime.now(ZONE)-timedelta(microseconds=1)
        with Session(engine) as db:version=db.get(MaterialAllocation,allocation['id']).version
        close={'id':rid+'-CA1','run_version':run['version'],'start':at.isoformat(),'end':end.isoformat(),
            'good_sheets':1,'ng_sheets':0,'seconds_per_cycle':.1,'pull_mm':500,'sheet_weight_kg':run['snapshot']['parameters']['sheet_weight_kg'],
            'items':[{'order_line_id':CT1,'good':5,'ng':0}],'sources':[{'receipt_id':RECEIPT,'consumed_kg':'1'}],'pure_seconds':.1,'setup_seconds':0,'note':NOTE}
        cap={'version':version,'production_order_id':rid,'kg':'1','note':NOTE+' concurrent issue'}
        def worker(task):
            path,body=task
            with TestClient(app) as c:return c.post('/api/production/'+path,json=body,headers={'Idempotency-Key':str(uuid4())})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(worker,[('materials/allocations/'+allocation['id']+'/issue',cap),('runs/'+rid+'/shifts',close)]))
        statuses=[r.status_code for r in responses]
        assert statuses[0]==201 and statuses[1] in [201,409],[(r.status_code,r.text) for r in responses]
        # An issue changes the run version: a stale close must be rejected, then safely retried.
        if statuses[1]==409:
            close['run_version']=getrun(rid)['version'];request('POST','runs/'+rid+'/shifts',close,201)
        with Session(engine) as db:
            position=source_position(db,rid,RECEIPT);assert position['kg']==1,position
        return {'statuses':statuses,'remaining_kg':'1','stale_close_retry':statuses[1]==409}
    result=once('race:issue_shift:result',lambda:check('mysql_concurrent_issue_and_shift_close',race))
    def balance():
        end=datetime.now(ZONE)-timedelta(microseconds=1)
        return shift(rid,rid+'-BALANCE',datetime.fromisoformat(request('GET','shifts/'+rid+'-CA1')['end']),end,0,{CT1:0},{RECEIPT:1},0)
    once('race:issue_shift:balance',balance);once('race:issue_shift:finish',lambda:state(rid,'finish'))
    with Session(engine) as db:
        M['counts']={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('forming',FormingLog),('cutting',CuttingLog),('edge',EBLog),('runs',ProductionOrder),('plans',SchedulePlan)]}
    save();print(json.dumps({'race':result,'counts':M['counts']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
