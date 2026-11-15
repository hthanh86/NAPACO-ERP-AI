from copy import deepcopy
from datetime import datetime,timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from test_production_runs import running_setup,prepared,planning,create
from app.modules.production.models import ProductionOrder,FormingLog
from app.modules.production.run_models import ProductionOrderItem,ShiftItem,ShiftMaterial
from app.modules.production.history_service import criteria_match,summarize
from app.modules.production.run_service import ZONE


def query(p,**changes):
    return {'standard_id':p.standard_id,'machine_id':'DH1','items':[{'order_line_id':'CT1','cavity':4},{'order_line_id':'CT2','cavity':2}],**changes}


def samples(p):
    original=create(p)
    with Session(p.engine) as db:
        first=db.get(ProductionOrder,'RUN1');first.status='Đã kết thúc'
        for index,pure in enumerate([40,42,44,40000],1):
            run=ProductionOrder(id='H'+str(index),issued_at=datetime.now(),machine_id='DH1',status='Đã kết thúc',
                run_snapshot=deepcopy(original['snapshot']),version=1,source={})
            db.add(run);db.flush()
            for ct,product,cavity in [('CT1','P1',4),('CT2','P2',2)]:
                db.add(ProductionOrderItem(run_id=run.id,order_line_id=ct,product_id=product,planned_qty=100,completed_qty=0,cavity=cavity,
                    snapshot=deepcopy(next(i['snapshot'] for i in original['items'] if i['order_line_id']==ct))))
            start=(datetime.now()-timedelta(days=index,hours=1)).replace(microsecond=0)
            log=FormingLog(id='HLOG'+str(index),production_order_id=run.id,shift_start=start,shift_end=start+timedelta(minutes=10),
                shift_snapshot={'run_snapshot':deepcopy(original['snapshot']),'cycles':10,'pure_seconds':pure,'setup_seconds':60,
                    'parameters':{'pull_mm':500,'sheet_weight_kg':.175}},good=10,ng=0,source={},version=1)
            db.add(log);db.flush()
            db.add_all([ShiftItem(log_id=log.id,order_line_id='CT1',good_qty=40,ng_qty=0),ShiftItem(log_id=log.id,order_line_id='CT2',good_qty=20,ng_qty=0),
                ShiftMaterial(log_id=log.id,receipt_id='R1',opening_kg=5,input_kg=0,output_kg=0,consumed_kg=Decimal('1.8'),closing_kg=Decimal('3.2'),movements=[])])
        db.commit()


def test_exact_history_uses_measured_time_and_reports_sources(running_setup):
    p=running_setup;samples(p)
    r=p.client.post('/api/production/run-suggestions',json=query(p));assert r.status_code==200,r.text
    data=r.json();assert data['samples']==3
    assert data['latest']['values']['seconds_per_cycle']==4
    assert data['statistics']['seconds_per_cycle']['typical']==4.2
    assert data['statistics']['setup_minutes']['typical']==1
    assert data['excluded']['missing_measured_pure_or_cycles']==1
    assert data['latest']['journal_ids']==['HLOG1']
    before=p.client.get('/api/production/standards/'+p.standard_id).json()
    # The same products with another cavity must never be treated as a near group.
    bad=query(p);bad['items'][0]['cavity']=3
    assert p.client.post('/api/production/run-suggestions',json=bad).json()['latest'] is None
    assert p.client.get('/api/production/standards/'+p.standard_id).json()==before


def test_history_permission_and_no_fake_default(running_setup):
    p=running_setup
    data=p.client.post('/api/production/run-suggestions',json=query(p)).json()
    assert data['latest'] is None and data['samples']==0 and data['statistics']=={}
    assert data['approved_standard'] is None
    p.client.cookies.set('napaco_session','reader')
    assert p.client.post('/api/production/run-suggestions',json=query(p)).status_code==403


def test_standard_approval_is_explicit_versioned_and_never_inferred(running_setup):
    from test_production_planning import standard
    p=running_setup
    old=p.client.get('/api/production/standards/'+p.standard_id).json()
    assert not old['snapshot']['approval']
    r=p.client.post('/api/production/standards/'+p.standard_id+'/revisions',json={**standard(),'approved':True})
    assert r.status_code==201,r.text
    approved=r.json();assert approved['snapshot']['approval']['by']=='admin'
    data=p.client.post('/api/production/run-suggestions',json=query(p)).json()
    assert data['approved_standard']['id']==approved['id']
    assert p.client.get('/api/production/standards/'+p.standard_id).json()==old


def test_applied_source_is_frozen_and_stale_history_is_rejected(running_setup):
    p=running_setup;samples(p)
    data=p.client.post('/api/production/run-suggestions',json=query(p)).json()
    selection={'kind':'statistics','context_hash':data['context_hash']}
    payload={**p.run_payload,'id':'APPLIED','items':[{'order_line_id':'CT1','quantity':8,'cavity':4},{'order_line_id':'CT2','quantity':4,'cavity':2}],
        'materials':[],'seconds_per_cycle':4.2,'waste_percent':5,'history_selection':selection}
    from test_production_runs import write
    r=write(p,'runs',payload);assert r.status_code==201,r.text
    evidence=r.json()['snapshot']['history_applied']
    assert evidence['source_run_ids']==['H1','H2','H3']
    assert evidence['applied_parameters']['seconds_per_cycle']==4.2
    with Session(p.engine) as db:
        log=db.get(FormingLog,'HLOG1');log.shift_snapshot={**log.shift_snapshot,'pure_seconds':41};db.commit()
    assert write(p,'runs',{**payload,'id':'STALE'}).status_code==409
    assert p.client.get('/api/production/runs/APPLIED').json()['snapshot']['history_applied']==evidence


def test_near_matching_never_mixes_group_or_material():
    a={'machine':'A','pull':500,'mold':'M','grade':'PET','thickness':.5,'width':500,'configuration':[('P',4,'cái')],'machine_kind':'automatic'}
    assert criteria_match(a,{**a,'machine':'B'})[2] is True
    assert criteria_match(a,{**a,'configuration':[('P',2,'cái')]})[2] is False
    assert criteria_match(a,{**a,'grade':'PP'})[2] is False


def test_edge_history_keeps_group_signature_when_only_one_product_needs_edge(running_setup):
    from test_production_runs import write
    p=running_setup;samples(p)
    for identifier,kind in [('CUT1','cutting'),('EDGE1','edge')]:
        assert p.client.post('/api/production/machines',json={'id':identifier,'name':identifier,'kind':kind,'status':'ready'}).status_code==201
    with Session(p.engine) as db:start=db.get(FormingLog,'HLOG1').shift_end.replace(tzinfo=ZONE)
    payload={'id':'HCUT','forming_log_id':'HLOG1','stage':'cutting','machine_id':'CUT1','start':start.isoformat(),'end':(start+timedelta(minutes=5)).isoformat(),
        'pure_seconds':30,'items':[{'order_line_id':'CT1','good':40,'ng':0},{'order_line_id':'CT2','good':20,'ng':0}],'note':'Grouped cut'}
    result=write(p,'downstream',payload);assert result.status_code==201,result.text
    result=write(p,'downstream',{**payload,'id':'HEDGE','stage':'edge','machine_id':'EDGE1','start':payload['end'],
        'end':(start+timedelta(minutes=10)).isoformat(),'pure_seconds':20,'items':[{'order_line_id':'CT1','good':40,'ng':0}]})
    assert result.status_code==201,result.text
    r=p.client.post('/api/production/run-suggestions',json=query(p,stage='edge',unit='Cái',machine_id='EDGE1'))
    assert r.status_code==200,r.text
    assert r.json()['latest']['run_id']=='H1'
    assert r.json()['latest']['values']['seconds_per_unit']==.5


def test_independent_run_outlier_and_insufficient_samples():
    rows=[{'run_id':str(i),'stage':'forming','values':{'seconds_per_cycle':n}} for i,n in enumerate([4,4,4.1,4.2,80])]
    clean,stats,excluded=summarize(rows)
    assert excluded==['4'] and len(clean)==4
    assert stats['seconds_per_cycle']['eligible_default'] is True
    assert summarize(rows[:2])[1]['seconds_per_cycle']['eligible_default'] is False


def test_polymer_type_is_verified_from_receipts_not_material_grade(running_setup):
    from app.modules.materials.purchasing.models import FilmLine
    from app.modules.materials.receiving.models import FilmReceipt
    from test_material_allocations import reserve
    p=running_setup;samples(p)
    with Session(p.engine) as db:
        db.add(FilmLine(id='DN_PP',po_id='POFILM1',material_id='F1',resin='PP',quantity=100,status='Nhận đủ'))
        db.add(FilmReceipt(id='R_PP',line_id='DN_PP',quantity=100,status='OK'));db.commit()
    allocation=reserve(p,5,receipt='R_PP').json()
    r=p.client.post('/api/production/run-suggestions',json=query(p,allocation_ids=[allocation['id']]))
    assert r.status_code==200,r.text
    assert r.json()['criteria']['resin']=='pp'
    assert r.json()['latest'] is None and r.json()['samples']==0
