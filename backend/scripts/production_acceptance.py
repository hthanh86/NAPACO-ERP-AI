"""Additional local MySQL acceptance; reuses phase-7 checkpoint and retains demo rows."""
from scripts.production_demo import *
from app.modules.production import schedule_daily
from app.modules.production.run_schemas import ShiftInput
from app.modules.materials.inventory.allocation_models import MaterialAllocation
from urllib.parse import urlencode


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',action='store_true',required=True);parser.parse_args()
    assert engine.url.host=='mysql' and M['status']=='completed'
    if M.get('acceptance_complete'):print('Acceptance đã hoàn tất; giữ dữ liệu.');return
    single=M['steps']['standard:v2:single']['id'];other=M['steps']['standard:v2:other']['id']
    A=M['steps']['allocation:A'];B=M['steps']['allocation:B'];today=datetime.fromisoformat(M['seal_day']).replace(tzinfo=ZONE)
    rid='DEMO7-STOCK-SRC';target='DEMO7-STOCK-DST';at=today.replace(hour=14)
    once('stock:run:source',lambda:create_run(rid,single,[{'order_line_id':CT1,'quantity':50,'cavity':5}],[{'allocation_id':A['id'],'kg':'3'}]))
    once('stock:start',lambda:state(rid,'start'));issued=once('stock:issue',lambda:issue(A,rid,3,at))
    once('stock:shift',lambda:shift(rid,rid+'-CA1',at,at+timedelta(hours=1),1,{CT1:5},{RECEIPT:1},4,0))
    returned=once('stock:return',lambda:request('POST','materials/issues/'+issued['movement_id']+'/return',{'kg':'1','note':NOTE}))
    once('stock:return:confirm',lambda:request('POST','materials/returns/'+returned['id']+'/confirm',{'kg':'1'}))
    once('stock:target',lambda:create_run(target,other,[{'order_line_id':CT2,'quantity':10,'cavity':2}],[],'DEMO7-DH-B'))
    transfer=once('stock:transfer',lambda:request('POST','materials/issues/'+issued['movement_id']+'/transfer',{'order_line_id':CT2,'standard_id':other,'production_order_id':target,'kg':'1','measured_remaining_kg':'1','note':NOTE}))
    def close_source():
        context=request('GET','runs/'+rid+'/shift-context');assert len(context['sources'])==1
        row=context['sources'][0];assert Decimal(row['opening_kg'])+Decimal(row['input_kg'])-Decimal(row['output_kg'])==0
        end=datetime.now(ZONE)-timedelta(microseconds=1)
        return shift(rid,rid+'-BALANCE',at+timedelta(hours=1),end,0,{CT1:0},{RECEIPT:0},0,0)
    once('stock:source:balance',close_source);once('stock:source:finish',lambda:state(rid,'finish'))
    once('stock:target:start',lambda:state(target,'start'))
    def target_shift():
        end=datetime.now(ZONE)-timedelta(microseconds=1)
        return shift(target,target+'-CA1',end-timedelta(seconds=2),end,2,{CT2:4},{RECEIPT:1},.2,0)
    once('stock:target:shift',target_shift);once('stock:target:finish',lambda:state(target,'finish'))
    check('mysql_issue_return_transfer_and_shift_balance',lambda:{'return':returned['id'],'transfer':transfer['transfer_id'],'source_final_kg':0,'target_final_kg':0})
    def next_day():
        with Session(engine) as db:
            count=db.scalar(select(func.count()).select_from(ScheduleDay));day=today.date()+timedelta(days=1)
            plan,meta=schedule_daily.source(db,day)
            assert meta['initial_plan_id'] is None and meta['version']==0 and meta['draft_from_day']==today.date()
            assert db.scalar(select(func.count()).select_from(ScheduleDay))==count
            return {'draft_plan_id':plan.id,'auto_closed':False,'writes':0}
    check('next_day_uses_update_draft_without_write_or_auto_close',next_day)
    def payload():
        latest=request('GET','schedule/latest');view=request('GET','schedule/view?'+urlencode({'view_start':M['view_start'],'view_end':M['view_end']}))
        return {'base_version':latest['version'],'planning_day':M['seal_day'],'day_version':view['day']['version'],**latest['request']}
    def apply_downstream_history():
        data=payload();recipe=request('POST','run-suggestions',{'standard_id':single,'machine_id':'BC-01','stage':'cutting','unit':'Cái','items':[{'order_line_id':CT1,'cavity':5}]})
        assert recipe['samples']==3,recipe
        policy=next(j for j in data['jobs'] if j['run_id']=='DEMO7-U1-CONT');stage=next(s for s in policy['stages'] if s['stage']=='cutting')
        stage['history_selection']={'kind':'statistics','context_hash':recipe['context_hash']};stage['seconds_per_unit']=recipe['statistics']['seconds_per_unit']['typical']
        stage['setup_minutes']=recipe['statistics']['setup_minutes']['typical']
        preview=request('POST','schedule/preview',data)
        result=request('POST','schedule/save',{**data,'preview_hash':preview['preview_hash'],'confirmations':[w['code'] for w in preview['warnings']]})
        latest=request('GET','schedule/latest');policy=next(j for j in latest['request']['jobs'] if j['run_id']=='DEMO7-U1-CONT')
        frozen=next(s for s in policy['stages'] if s['stage']=='cutting')['history_evidence'];assert frozen['unit']=='seconds/cái'
        return {'plan_id':result['id'],'source_run_ids':frozen['source_run_ids']}
    once('history:downstream:applied',lambda:check('downstream_history_frozen_in_plan',apply_downstream_history))
    def retain_stops():
        data=payload();data['stops']=[{'id':'DEMO7-AUTO-HOLD','run_id':'DEMO7-AUTO-RUN','at':today.replace(hour=8,minute=30).isoformat(),'duration_seconds':None,'hold_machine':True,'note':NOTE+' dừng chưa rõ, giữ máy'},
            {'id':'DEMO7-TAIL-RELEASE','run_id':'DEMO7-TAIL','at':today.replace(hour=8).isoformat(),'duration_seconds':None,'hold_machine':False,'note':NOTE+' giải phóng máy, phần thiếu về chờ'}]
        preview=request('POST','schedule/preview',data);result=request('POST','schedule/save',{**data,'preview_hash':preview['preview_hash'],'confirmations':[w['code'] for w in preview['warnings']]})
        jobs={j['run_id']:j for j in result['result']['jobs']};assert jobs['DEMO7-AUTO-RUN']['status']=='unknown' and jobs['DEMO7-TAIL']['status']=='released_waiting'
        return {'plan_id':result['id'],'hold_run':'DEMO7-AUTO-RUN','released_run':'DEMO7-TAIL'}
    once('plan:retained_stops',lambda:check('visible_unknown_hold_and_release',retain_stops))
    with Session(engine) as db:
        row=db.get(SchedulePlan,M['steps']['plan:close']['initial_plan_id'])
        assert row.version==1
        assert db.get(ProductionOrder,'DEMO7-U1').status=='Đã kết thúc'
        assert db.get(ProductionOrder,'DEMO7-U1-CONT').parent_run_id=='DEMO7-U1'
        M['counts']={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('forming',FormingLog),('cutting',CuttingLog),('edge',EBLog),('runs',ProductionOrder),('plans',SchedulePlan)]}
    M['acceptance_complete']=True;save();print(json.dumps({'status':'complete','counts':M['counts']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
