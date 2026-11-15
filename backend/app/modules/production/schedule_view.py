"""Bounded projections of the canonical schedule; no scheduling arithmetic here."""
from copy import deepcopy
from datetime import datetime,timedelta
from sqlalchemy import select
from app.modules.production import schedule_service as service
from app.modules.production.planning_models import Machine
from app.modules.production.models import ProductionOrder as Run,FormingLog
from app.modules.production.run_models import ProductionOrderItem as Item,RunMaterial
from app.modules.production.planning_service import available_windows,ZONE
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_service import fail,allocation_record
from app.modules.orders.models import Order,OrderLine
from app.modules.customers.models import Customer
from app.modules.products.models import Product


def line_metadata(db,ids):
    rows=db.execute(select(OrderLine.id,OrderLine.product_id,OrderLine.order_id,OrderLine.unit,OrderLine.delivery_date,
        Order.po_number,Order.customer_id,Customer.name.label('customer_name'),Product.name.label('product_name'))
        .join(Order,Order.id==OrderLine.order_id).outerjoin(Customer,Customer.id==Order.customer_id)
        .outerjoin(Product,Product.id==OrderLine.product_id).where(OrderLine.id.in_(list(ids)))).mappings()
    return {r['id']:dict(r) for r in rows}


def editor(db,identifier):
    run=db.get(Run,identifier)
    if not run or not run.run_snapshot:fail('Không tìm thấy lần chạy.',404)
    items=db.scalars(select(Item).where(Item.run_id==identifier).order_by(Item.order_line_id)).all()
    bindings=db.scalars(select(RunMaterial).where(RunMaterial.run_id==identifier)).all()
    data=service.dto(run,items,bindings);meta=line_metadata(db,[i.order_line_id for i in items])
    for i in data['items']:
        i.update(meta.get(i['order_line_id'],{}));i['remaining_qty']=i['planned_qty']-i['completed_qty']
    allocations=db.scalars(select(Allocation).where(Allocation.order_line_id.in_(list(meta))).order_by(Allocation.id).limit(501)).all()
    if len(allocations)>500:fail('Nhóm có quá nhiều phân bổ; thu hẹp nhóm hoặc quản lý nguồn tại màn hình Chuẩn bị nhựa.')
    data['allocations']=[{**allocation_record(a),'issued_kg':str(next((b.issued_kg for b in bindings if b.allocation_id==a.id),0))} for a in allocations]
    movements=db.scalar(select(FilmMovement.id).where(FilmMovement.production_order_id==identifier).limit(1))
    actual=db.scalar(select(FormingLog.id).where(FormingLog.production_order_id==identifier).limit(1))
    data['can_edit']=run.status!=service.runs.ENDED
    return data


def project(db,result,canonical,version,start,end,machine_id='',customer_id='',q='',configs=(),frozen_context=None,read_only=False,related_run_ids=()):
    if end<=start or (end-start).total_seconds()>92*86400:fail('Khoảng xem phải tăng dần, tối đa 92 ngày.')
    result=deepcopy(service.encoded(result or {'jobs':[],'actual':[],'lines':[],'orders':[],'stops':[]}))
    candidate_ids=[j['run_id'] for j in result['jobs']]
    changed={c.id for c in configs}
    # Live labels/versions/capabilities only for jobs in the snapshot; no source catalog preload.
    rows=[] if read_only else db.scalars(select(Run).where(Run.id.in_(candidate_ids))).all();live={r.id:r for r in rows}
    items={};line_ids=set()
    for i in ([] if frozen_context else db.scalars(select(Item).where(Item.run_id.in_(candidate_ids)).order_by(Item.order_line_id))):
        items.setdefault(i.run_id,[]).append({'order_line_id':i.order_line_id,'planned_qty':str(i.planned_qty),
            'completed_qty':str(i.completed_qty),'cavity':i.cavity,'snapshot':i.snapshot});line_ids.add(i.order_line_id)
    for config in configs:
        items[config.id]=[{'order_line_id':i.order_line_id,'planned_qty':i.quantity,'completed_qty':0,'cavity':i.cavity,'snapshot':{}} for i in config.items]
        line_ids.update(i.order_line_id for i in config.items)
    for job in result['jobs']:
        if job.get('planned_items'):
            items[job['run_id']]=job['planned_items'];line_ids.update(i['order_line_id'] for i in job['planned_items'])
    metadata=frozen_context['lines'] if frozen_context else line_metadata(db,line_ids)
    moved=set() if read_only else set(db.scalars(select(FilmMovement.production_order_id).where(FilmMovement.production_order_id.in_(candidate_ids)).distinct()))
    actual_runs=set() if read_only else set(db.scalars(select(FormingLog.production_order_id).where(FormingLog.production_order_id.in_(candidate_ids)).distinct()))
    def overlaps(span):
        if not span.get('start') or not span.get('end'):return False
        return datetime.fromisoformat(span['start'])<end and datetime.fromisoformat(span['end'])>start
    def match(info):
        return (not customer_id or info.get('customer_id')==customer_id) and (not q or q.casefold() in ' '.join(str(info.get(k) or '') for k in ['id','product_name','po_number','order_id']).casefold())
    jobs=[];visible_lines=set()
    policy_map={p['run_id']:p for p in canonical.get('jobs',[])}
    for job in result['jobs']:
        members=[{**i,**metadata.get(i['order_line_id'],{})} for i in items.get(job['run_id'],[])]
        related=job['run_id'] in related_run_ids
        if (customer_id or q) and not related and not any(match(i) for i in members):continue
        stages=[s for s in job['stages'] if related or not machine_id or s['machine_id']==machine_id]
        own=related or not machine_id or job['machine_id']==machine_id
        spans=([*job['setup_segments'],*job['forming_segments']] if own else [])+[span for s in stages for span in s['segments']]
        uncertain=(own and job['status'] in {'unknown','released_waiting'}) or any(s['status']=='unknown' for s in stages)
        horizon_overlaps=datetime.fromisoformat(str(canonical.get('start',start)))<end and datetime.fromisoformat(str(canonical.get('end',end)))>start
        actual_visible=any(a.get('run_id')==job['run_id'] and overlaps(a) and
            (related or not machine_id or 'machine:'+machine_id in a['resources']) for a in result.get('actual',[]))
        relevant=actual_visible or (own or bool(stages)) and (any(overlaps(s) for s in spans) or uncertain and horizon_overlaps)
        if not relevant:continue
        row=live.get(job['run_id']);job['items']=members;job['policy']=policy_map.get(job['run_id'],{'run_id':job['run_id'],'stages':[],'line_order':[],'ready_at':None,'waiting':False})
        job['live_version']=row.version if row else job['run_version'];job['run_status']=row.status if row else service.runs.PLANNED
        job['can_move']=not read_only and job['run_status']!=service.runs.ENDED
        job['official_code']=row.official_code if row else job.get('official_code')
        job['release_state']=row.release_state if row else job.get('release_state','legacy')
        job['machine_kind']=job.get('machine_kind') or (row.run_snapshot.get('machine_kind') if row else None)
        job['stale']=bool(row and row.version!=job['run_version'] and row.id not in changed);jobs.append(job)
        visible_lines.update(i['order_line_id'] for i in members)
    machines=db.scalars(select(Machine).where(Machine.id==machine_id) if machine_id else select(Machine).where(Machine.kind.in_(['automatic','semi_automatic','cutting','edge'])).order_by(Machine.kind,Machine.id).limit(101)).all() if not read_only else []
    if len(machines)>100:fail('Có hơn 100 máy; chọn mã máy để thu hẹp khoảng xem.')
    if machine_id and not machines and not frozen_context:fail('Không tìm thấy mã máy cần xem.',404)
    if len(visible_lines)>500:fail('Hơn 500 CTĐH trong khoảng xem; thu hẹp thời gian, máy hoặc khách hàng.')
    machine_rows=[{'id':m.id,'name':m.name,'kind':m.kind,'status':m.status,'version':m.version} for m in machines]
    related_machines={m for j in jobs if j['run_id'] in related_run_ids for m in [j['machine_id'],*[s['machine_id'] for s in j['stages']]] if m}
    related_machines.update(resource.split(':',1)[1] for a in result.get('actual',[]) if a.get('run_id') in related_run_ids for resource in a['resources'] if resource.startswith('machine:'))
    if frozen_context:machine_rows=list({m['id']:m for m in [*machine_rows,*[m for m in frozen_context['machines'] if not machine_id or m['id']==machine_id or m['id'] in related_machines]]}.values())
    if len(machine_rows)>100:fail('Hơn 100 máy trong phạm vi; chọn mã máy để thu hẹp.')
    machine_ids={m['id'] for m in machine_rows}
    result['jobs']=jobs
    result['lines']=[l for l in result.get('lines',[]) if l['order_line_id'] in visible_lines]
    order_ids={l['order_id'] for l in result['lines']};result['orders']=[o for o in result.get('orders',[]) if o['order_id'] in order_ids]
    result['actual']=[a for a in result.get('actual',[]) if overlaps(a) and any('machine:'+m in a['resources'] for m in machine_ids)
        and (not customer_id and not q or any('line:'+ct in a['resources'] or ct in a.get('order_line_ids',[]) for ct in visible_lines))]
    result['stops']=[s for s in result.get('stops',[]) if s['machine_id'] in machine_ids and s['run_id'] in {j['run_id'] for j in jobs}]
    windows=frozen_context['availability'] if frozen_context else available_windows(db,sorted(machine_ids),start.astimezone(ZONE).date(),end.astimezone(ZONE).date()) if machine_ids else {'machines':[]}
    if frozen_context and not read_only:
        extra=machine_ids-{m['machine_id'] for m in windows['machines']}
        if extra:windows={'machines':[*windows['machines'],*available_windows(db,sorted(extra),start.astimezone(ZONE).date(),end.astimezone(ZONE).date())['machines']]}
    result['working_windows']={m['machine_id']:m['windows'] for m in windows['machines']}
    return {'version':version,'horizon':{'start':canonical.get('start',start),'end':canonical.get('end',end)},
        'queue':canonical.get('order',[]),'view':{'start':start,'end':end},'machines':machine_rows,
        'result':result,'hidden_jobs':len(candidate_ids)-len(jobs),'line_metadata':metadata_for_visible(metadata,visible_lines)}


def metadata_for_visible(metadata,visible):return {k:v for k,v in metadata.items() if k in visible}
