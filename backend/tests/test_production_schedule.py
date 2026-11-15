"""Prepared scheduler cases; execute only after the user's test approval."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest
from app.modules.production.schedule_engine import calculate,ScheduleError

ZONE=timezone(timedelta(hours=7))
DAY=datetime(2026,11,16,8,tzinfo=ZONE)


def job(identifier='R1',machine='DH1',ct='CT1',quantity=10,cavity=1,route=None):
    return {'id':identifier,'version':1,'machine_id':machine,
        'snapshot':{'parameters':{'seconds_per_cycle':60,'setup_minutes':0,'sheet_weight_kg':0.2,'waste_percent':10}},
        'items':[{'order_line_id':ct,'product_id':'P1','planned_qty':quantity,'completed_qty':0,'cavity':cavity,
            'snapshot':{'unit':'Cái','route':route or ['forming_cutting']}}],
        'policy':{'line_order':[],'stages':[],'ready_at':None,'waiting':False},
        'has_actual':False,'actual_end':None,'streams':{},'processed':{},'material':{}}


def context(*jobs):
    return {'start':DAY,'end':DAY+timedelta(days=1),'windows':{
        machine:[(DAY,DAY+timedelta(hours=4)),(DAY+timedelta(hours=5),DAY+timedelta(hours=9))]
        for machine in ['DH1','DH2','CUT1','EDGE1']},'actual':[],'stops':[],'warnings':[],
        'runs':list(jobs),'lines':[{'id':ct,'order_id':'PO1','unit':'Cái','quantity':sum(i['planned_qty'] for r in jobs for i in r['items'] if i['order_line_id']==ct),
            'actual_finished_qty':0,'actual_finished_at':None} for ct in sorted({i['order_line_id'] for r in jobs for i in r['items']})]}


def stage(name,machine=None,mode='all',size=None):
    return {'order_line_id':'CT1','stage':name,'machine_id':machine,'seconds_per_unit':60,
        'setup_minutes':0,'wait_minutes':0,'unit':'Cái','mode':mode,'handoff_quantity':size,
        'handoff_quantities':[],'hold_machine_while_waiting':False}


def stop(hold=True,duration=None):
    return {'id':'STOP1','run_id':'R1','enabled':True,'run_ended':False,'machine_id':'DH1',
        'line_ids':['CT1'],'at':DAY+timedelta(minutes=5),'duration_seconds':duration,'hold_machine':hold}


def test_group_common_cycles_surplus_and_separate_waste():
    r=job(quantity=39,cavity=4)
    r['items'].append({'order_line_id':'CT2','product_id':'P2','planned_qty':25,'completed_qty':0,'cavity':2,
        'snapshot':{'unit':'Cái','route':['forming_cutting']}})
    result=calculate(context(r))['jobs'][0]
    assert result['cycles']==10
    assert result['products'][0]['rounding_surplus_qty']==1
    assert result['products'][1]['requires_next_run_qty']==5
    assert Decimal(result['base_kg'])==2
    assert Decimal(result['waste_kg'])==Decimal('0.2')
    assert Decimal(result['pure_seconds'])==600


def test_setup_and_production_split_around_break():
    r=job();r['snapshot']['parameters'].update(seconds_per_cycle=1800,setup_minutes=30)
    result=calculate(context(r))['jobs'][0]
    assert result['forming_end']==DAY+timedelta(hours=6.5)
    assert len(result['forming_segments'])==2


def test_same_ct_cannot_form_simultaneously_on_two_machines():
    result=calculate(context(job(),job('R2','DH2')))
    assert result['jobs'][1]['forming_segments'][0]['start']>=result['jobs'][0]['forming_end']


def test_unknown_hold_marks_later_machine_time_unknown():
    c=context(job(),job('R2',ct='CT2'));c['stops']=[stop()]
    result=calculate(c)
    assert result['jobs'][0]['status']=='unknown'
    assert result['jobs'][1]['forming_end'] is None
    assert result['orders'][0]['all_finished_at'] is None


def test_release_keeps_remainder_waiting_and_frees_machine():
    c=context(job(),job('R2',ct='CT2'));c['stops']=[stop(False)]
    result=calculate(c)
    assert result['jobs'][0]['status']=='released_waiting'
    assert result['jobs'][1]['forming_segments'][0]['start']==DAY


def test_known_stop_delays_completion_without_changing_work_seconds():
    c=context(job());c['stops']=[stop(True,600)]
    result=calculate(c)['jobs'][0]
    assert result['forming_end']==DAY+timedelta(minutes=20)
    assert result['pure_seconds']=='600'


def test_rolling_handoff_and_estimated_stage_are_explicit():
    r=job(route=['forming','cutting','edge'])
    r['policy']['stages']=[stage('cutting','CUT1','rolling',5),stage('edge',None,'rolling',5)]
    result=calculate(context(r))
    cut=[s for s in result['jobs'][0]['stages'] if s['stage']=='cutting']
    assert cut[0]['handoff_ready_at']==DAY+timedelta(minutes=5)
    assert cut[1]['input_qty']==5
    assert result['lines'][0]['certainty']=='estimated'
    assert result['lines'][0]['first_planned_finished_at']<result['lines'][0]['all_finished_at']


def test_actual_downstream_cannot_consume_future_supply():
    r=job(route=['forming','cutting']);r['policy']['stages']=[stage('cutting','CUT1')]
    r['processed'][('CT1','cutting')]=1
    with pytest.raises(ScheduleError) as error:calculate(context(r))
    assert error.value.detail['code']=='ACTUAL_UPSTREAM_OVERUSED'


def test_missing_parameters_fail_instead_of_zero_and_input_is_immutable():
    r=job();del r['snapshot']['parameters']['seconds_per_cycle'];c=context(r);before=deepcopy(c)
    with pytest.raises(ScheduleError) as error:calculate(c)
    assert error.value.detail['code']=='MISSING_OR_INVALID_PARAMETER'
    assert c==before


def test_reorder_changes_machine_sequence_without_mutating_actual():
    first=job();second=job('R2',ct='CT2');c=context(first,second)
    c['actual']=[{'resources':['machine:DH1'],'start':DAY,'end':DAY+timedelta(minutes=2),'reference':'CLOSED'}]
    before=deepcopy(c['actual']);one=calculate(c)
    c['runs']=[second,first];two=calculate(c)
    assert one['jobs'][0]['run_id']=='R1' and two['jobs'][0]['run_id']=='R2'
    assert two['jobs'][0]['forming_segments'][0]['start']==DAY+timedelta(minutes=2)
    assert c['actual']==before
