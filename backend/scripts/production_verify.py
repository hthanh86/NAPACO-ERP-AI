"""Verify explicit approved standards and grouped downstream history on local MySQL."""
from scripts.production_demo import *
from app.modules.production import run_service
from app.modules.production.run_schemas import RunInput
from app.modules.production.history_schemas import HistoryQuery,HistorySelection
from app.modules.production.history_service import suggestions


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',action='store_true',required=True);parser.parse_args()
    assert engine.url.host=='mysql' and M.get('acceptance_complete')
    if M.get('final_verification_complete'):print('Đã xác minh; giữ dữ liệu.');return
    for kind in ['single','other','group','auto']:
        old=M['steps']['standard:v2:'+kind]['id']
        def approve(old=old):
            item=request('GET','standards/'+old)
            fields=['code','name','machine_id','material_id','mold_id','active']
            payload={k:item[k] for k in fields};payload.update({k:item['parameters'][k] for k in ['pull_mm','seconds_per_cycle','density','setup_minutes','waste_percent']})
            payload['items']=[{k:i[k] for k in ['product_id','cavity','edge']} for i in item['items']];payload['approved']=True
            result=request('POST','standards/'+old+'/revisions',payload)
            assert not request('GET','standards/'+old)['snapshot'].get('approval')
            assert result['snapshot']['approval']['by']==admin.id
            return result
        once('approval:'+kind,approve)
    standard=M['steps']['approval:single']['id']
    data=request('POST','run-suggestions',{'standard_id':standard,'machine_id':'DEMO7-DH-A','items':[{'order_line_id':CT1,'cavity':5}]})
    assert data['approved_standard']['id']==standard
    with Session(engine) as db:
        record=run_service.save_run(db,admin,RunInput(id='DEMO7-APPROVED-PREVIEW',standard_id=standard,machine_id='DEMO7-DH-A',
            items=[{'order_line_id':CT1,'quantity':50,'cavity':5}],note=NOTE,
            history_selection=HistorySelection(kind='approved_standard',context_hash=data['context_hash'])),preview=True)
        assert record['snapshot']['history_applied']['source_standard']['id']==standard
        assert not db.get(ProductionOrder,'DEMO7-APPROVED-PREVIEW')
    check('approved_standard_explicit_immutable_and_source_snapshot',lambda:standard)
    source='DEMO7-G1-CA1';at=datetime.fromisoformat(M['seal_day']).replace(tzinfo=ZONE)-timedelta(days=1)+timedelta(hours=12)
    once('group:cut:1',lambda:downstream('DEMO7-G1-CUT1',source,'cutting',at,at+timedelta(minutes=5),{CT1:20,CT2:8},'BC-01'))
    once('group:cut:2',lambda:downstream('DEMO7-G1-CUT2',source,'cutting',at+timedelta(minutes=5),at+timedelta(minutes=10),{CT1:5,CT2:2},'BC-01'))
    once('group:edge',lambda:downstream('DEMO7-G1-EDGE',source,'edge',at+timedelta(minutes=10),at+timedelta(minutes=15),{CT1:25},'DEMO7-EDGE'))
    # Same-time machine occupancy is rejected, not just source overuse.
    response=client.post('/api/production/downstream',json={'id':'DEMO7-OVERLAP-REJECTED','forming_log_id':source,'stage':'cutting','machine_id':'BC-01',
        'start':at.isoformat(),'end':(at+timedelta(minutes=5)).isoformat(),'items':[{'order_line_id':CT1,'good':1,'ng':0}],'note':NOTE},headers={'Idempotency-Key':str(uuid4())})
    assert response.status_code==409 and 'chồng' in response.json()['detail'],response.text
    check('mysql_downstream_overlap_rejected',lambda:True)
    group=M['steps']['approval:group']['id']
    data=request('POST','run-suggestions',{'standard_id':group,'machine_id':'DEMO7-EDGE','stage':'edge','unit':'Cái',
        'items':[{'order_line_id':CT1,'cavity':5},{'order_line_id':CT2,'cavity':2}]})
    assert data['latest']['run_id']=='DEMO7-G1' and data['latest']['values']['seconds_per_unit']==.5,data
    assert data['samples']==1 and data['statistics']['seconds_per_unit']['eligible_default'] is False
    check('mysql_grouped_repeated_handoff_and_optional_edge',lambda:{'source_shift':source,'cuts':2,'edge_product':CT1,'samples':data['samples']})
    with Session(engine) as db:
        M['counts']={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('forming',FormingLog),('cutting',CuttingLog),('edge',EBLog),('runs',ProductionOrder),('plans',SchedulePlan)]}
        M['line_produced']={ct:str(db.get(OrderLine,ct).produced) for ct in [CT1,CT2]}
    M['final_verification_complete']=True;M.pop('error',None);save();print(json.dumps({'status':'complete','counts':M['counts'],'line_produced':M['line_produced']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
