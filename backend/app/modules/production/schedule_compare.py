"""Compare stable run IDs without recalculating or changing historical plans."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select
from app.modules.production.schedule_models import SchedulePlan
from app.modules.production import schedule_daily as daily,schedule_view,schedule_actual as actual
from app.modules.production.schedule_actual import stamp,qty
from app.modules.production.schedule_service import encoded
from app.modules.materials.inventory.allocation_service import fail


def metrics(parts,start,end):
    """Never prorate output or pure time for a partly visible journal/batch."""
    result={}
    for p in parts:
        spans=[s for s in p['spans'] if s.get('start') and s.get('end')]
        relevant=not spans or any(stamp(s['start'])<end and stamp(s['end'])>start for s in spans)
        if not relevant:continue
        complete=bool(spans) and all(start<=stamp(s['start'])<stamp(s['end'])<=end for s in spans)
        key=(p['run_id'],p['stage']);row=result.setdefault(key,{'run_id':p['run_id'],'stage':p['stage'],'machine_ids':set(),
            'start':None,'end':None,'quantities':{},'units':{},'pure_seconds':Decimal(0),'records':0,'scope_complete':True,
            'timing_complete':True,'quantity_complete':True,'pure_complete':True,'machine_complete':True,'run_status':p.get('run_status'),'estimated':False})
        row['records']+=1;row['scope_complete']&=complete;row['timing_complete']&=bool(spans);row['estimated']|=p.get('estimated',False)
        if p.get('machine_id'):row['machine_ids'].add(p['machine_id'])
        else:row['machine_complete']=False
        for span in spans:
            a,b=stamp(span['start']),stamp(span['end']);row['start']=min(row['start'],a) if row['start'] else a;row['end']=max(row['end'],b) if row['end'] else b
        value=qty(p.get('pure_seconds'))
        if value is None or not complete:row['pure_complete']=False
        else:row['pure_seconds']+=value
        if not p['items']:row['quantity_complete']=False
        for item in p['items']:
            ct=item['order_line_id'];n=qty(item.get('good_qty'));unit=item.get('unit')
            compatible=unit and (ct not in row['units'] or row['units'][ct].strip().casefold()==unit.strip().casefold())
            if n is None or not complete or not compatible:row['quantities'][ct]=None;row['quantity_complete']=False
            elif row['quantities'].get(ct,0) is not None:row['quantities'][ct]=row['quantities'].get(ct,Decimal(0))+n
            if unit:row['units'][ct]=unit
    for row in result.values():
        row['machine_ids']=sorted(row['machine_ids'])
        if not row['pure_complete']:row['pure_seconds']=None
    return result


def planned_parts(plan,start,end):
    parts=[]
    if stamp(plan.request['start'])>=end or stamp(plan.request['end'])<=start:return parts
    for job in plan.result['jobs']:
        spans=[*job['setup_segments'],*job['forming_segments']]
        if spans or job['cycles']:
            parts.append({'run_id':job['run_id'],'stage':'forming','machine_id':job['machine_id'],'spans':spans,
                'pure_seconds':job['pure_seconds'],'estimated':False,
                'items':[{'order_line_id':i['order_line_id'],'good_qty':i['quantity'],'unit':i['unit']} for i in job.get('line_quantities',[])]})
        for batch in job['stages']:
            parts.append({'run_id':job['run_id'],'stage':batch['stage'],'machine_id':batch['machine_id'],'spans':batch['segments'],
                'pure_seconds':batch.get('pure_seconds'),'estimated':batch['status']=='estimated',
                'items':[{'order_line_id':batch['order_line_id'],'good_qty':batch['input_qty'],'unit':batch['unit']}]})
    for record in plan.result.get('actual',[]):
        if record.get('run_id'):
            parts.append({'run_id':record['run_id'],'stage':record.get('stage','forming'),
                'machine_id':next((r.split(':',1)[1] for r in record['resources'] if r.startswith('machine:')),None),
                'spans':[{'start':record['start'],'end':record['end']}],'pure_seconds':record.get('pure_seconds'),'items':record.get('items',[])})
    return parts


def actual_parts(records):
    return [{'run_id':r['run_id'] or 'UNLINKED:'+r['id'],'stage':r['stage'],'machine_id':r['machine_id'],
        'spans':[{'start':r['start'],'end':r['end']}] if r['start'] and r['end'] else [],
        'items':r['items'],'pure_seconds':r['pure_seconds'],'run_status':r['run_status']} for r in records]


def compare_metrics(left,right,mode):
    rows=[]
    for key in sorted(set(left)|set(right)):
        a=left.get(key);b=right.get(key);quantity_equal=None
        if a and b and a['quantity_complete'] and b['quantity_complete']:
            compatible=all(a['units'].get(ct,'').strip().casefold()==b['units'].get(ct,'').strip().casefold() for ct in set(a['quantities'])|set(b['quantities']))
            quantity_equal=all(b['quantities'].get(ct,0)>=n for ct,n in a['quantities'].items()) if compatible else None
        completion='no_data' if not b else 'unplanned' if not a else 'unknown'
        if a and b:
            if mode=='update':completion='planned'
            elif quantity_equal:
                completion='quantity_reached_run_open' if key[1]=='forming' and b['run_status']!='Đã kết thúc' else 'complete_for_plan'
            elif quantity_equal is False:completion='not_finished'
        final=mode=='update' or completion=='complete_for_plan'
        pure_comparable=bool(a and b and final and a['pure_seconds'] is not None and b['pure_seconds'] is not None)
        rows.append({'run_id':key[0],'stage':key[1],'baseline':a,'current':b,'completion':completion,
            'missing_order_lines':sorted(set(a['quantities'])-set(b['quantities'])) if a and b else [],
            'machine_changed':a['machine_ids']!=b['machine_ids'] if a and b else None,
            'start_delta_seconds':(b['start']-a['start']).total_seconds() if a and b and a['start'] and b['start'] else None,
            'end_delta_seconds':(b['end']-a['end']).total_seconds() if a and b and a['end'] and b['end'] and final else None,
            'pure_delta_seconds':b['pure_seconds']-a['pure_seconds'] if pure_comparable else None,
            'pure_comparable':pure_comparable,'data_quality':'no_data' if not b else 'complete' if b['timing_complete'] and b['quantity_complete'] and b['pure_complete'] and b['scope_complete'] and b['machine_complete'] and (not a or set(a['quantities'])<=set(b['quantities'])) else 'partial'})
    return rows


def view(db,day,mode,**scope):
    row=daily.get_day(db,day)
    if not row or not row.initial_plan_id:fail('Ngày này chưa chốt bản đầu ngày; không có bản nền để so sánh.',404)
    baseline=db.get(SchedulePlan,row.initial_plan_id)
    if not baseline.context:fail('Bản lịch sử thiếu ngữ cảnh snapshot, không ghép dữ liệu hiện hành vào lịch sử.',409)
    workspace=schedule_view.project(db,baseline.result,baseline.request,baseline.version,**scope,frozen_context=baseline.context,read_only=True)
    workspace['baseline_recorded']=workspace['result']['actual']
    a=metrics(planned_parts(baseline,scope['start'],scope['end']),scope['start'],scope['end'])
    live=None;right=None
    if mode=='update':
        right=db.get(SchedulePlan,row.update_plan_id)
        if not right or not right.context:fail('Chưa có bản cập nhật đầy đủ để so sánh.',404)
        secondary=schedule_view.project(db,right.result,right.request,right.version,**scope,frozen_context=right.context,read_only=True,related_run_ids=[j['run_id'] for j in workspace['result']['jobs']])
        b=metrics(planned_parts(right,scope['start'],scope['end']),scope['start'],scope['end'])
        workspace['secondary']=secondary
        workspace['line_metadata']={**secondary['line_metadata'],**workspace['line_metadata']}
        workspace['machines']=list({m['id']:m for m in [*secondary['machines'],*workspace['machines']]}.values())
        workspace['result']['actual']=[]
    else:
        live=actual.read(db,**scope,related_run_ids=[j['run_id'] for j in workspace['result']['jobs']]);b=metrics(actual_parts(live['records']),scope['start'],scope['end'])
        workspace['result']['actual']=[{'reference':r['id'],'run_id':r['run_id'],'stage':r['stage'],
            'start':r['start'],'end':r['end'],'resources':['machine:'+r['machine_id']] if r['machine_id'] else [],
            'order_line_ids':[i['order_line_id'] for i in r['items']],'items':r['items'],'updated_at':r['updated_at']}
            for r in live['records'] if r['start'] and r['end']]
        workspace['line_metadata']={**live['line_metadata'],**{ct:baseline.context['lines'][ct] for ct in live['line_metadata'] if ct in baseline.context['lines']},**workspace['line_metadata']}
        workspace['machines']=list({m['id']:m for m in [*live['machines'],*workspace['machines']]}.values())
        workspace['live_actual']=live
    # Comparison rows follow the production view and filter, not all jobs in either archive.
    visible={j['run_id'] for j in workspace['result']['jobs']}
    if workspace.get('secondary'):visible.update(j['run_id'] for j in workspace['secondary']['result']['jobs'])
    if live:visible.update(r['run_id'] or 'UNLINKED:'+r['id'] for r in live['records'])
    # A delayed or moved job may be visible only on the right. Keep its original
    # planned dates as context instead of mislabelling it as never planned.
    full_baseline=metrics(planned_parts(baseline,stamp(baseline.request['start']),stamp(baseline.request['end'])),stamp(baseline.request['start']),stamp(baseline.request['end']))
    for key,value in full_baseline.items():
        if key[0] in visible and key not in a:a[key]={**value,'outside_view':True}
    if right:
        full_update=metrics(planned_parts(right,stamp(right.request['start']),stamp(right.request['end'])),stamp(right.request['start']),stamp(right.request['end']))
        for key,value in full_update.items():
            if key[0] in visible and key not in b:b[key]={**value,'outside_view':True}
    workspace['comparison']={'mode':mode,'day':day,'baseline_id':baseline.id,'baseline_version':baseline.version,
        'baseline_closed_at':daily.utc(row.initial_closed_at),'update_id':right.id if right else None,
        'update_version':right.version if right else None,'rows':[r for r in compare_metrics(a,b,mode) if r['run_id'] in visible and
            (not scope['machine_id'] or any(scope['machine_id'] in (side or {}).get('machine_ids',[]) for side in [r['baseline'],r['current']]))],
        'actual_data_updated_at':live['data_updated_at'] if live else None,'actual_retrieved_at':live['retrieved_at'] if live else None,
        'actual_update_time_complete':live['update_time_complete'] if live else None}
    workspace['day']=daily.metadata(row)
    if len(workspace['machines'])>100 or len(workspace['line_metadata'])>500:fail('Phạm vi so sánh vượt 100 máy hoặc 500 CTĐH; thu hẹp bộ lọc.')
    return encoded(workspace)
