"""Live production evidence. Missing journals are not idle time or zero output."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from sqlalchemy import select,func,or_,and_
from app.core.models import Audit
from app.modules.production.models import ProductionOrder as Run,FormingLog,CuttingLog,EBLog
from app.modules.production.run_models import ProductionOrderItem as Item,ShiftItem,DownstreamItem
from app.modules.production.planning_models import Machine
from app.modules.production.planning_service import ZONE
from app.modules.production.schedule_view import line_metadata
from app.modules.materials.inventory.allocation_service import fail
from app.modules.orders.models import OrderLine,Order
from app.modules.products.models import Product

LIMIT=2000


def stamp(value):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value)
        except ValueError:return None
    return value.replace(tzinfo=ZONE) if value and value.tzinfo is None else value


def qty(value):
    try:
        result=Decimal(str(value))
        return result if result.is_finite() and result>=0 else None
    except (InvalidOperation,ValueError):return None


def read(db,*,start,end,machine_id='',customer_id='',q='',related_run_ids=()):
    if start is None or end is None or end<=start or (end-start).total_seconds()>92*86400:fail('Chọn khoảng thực tế tăng dần, tối đa 92 ngày.')
    lo=start.astimezone(ZONE).date()-timedelta(days=1);hi=end.astimezone(ZONE).date()+timedelta(days=1)
    records=[];runs=set();primary={}
    def filtered(query,machine):
        if machine_id:query=query.where(or_(machine==machine_id,Run.id.in_(list(related_run_ids))))
        if customer_id or q:
            lines=select(OrderLine.id).join(Order,Order.id==OrderLine.order_id).outerjoin(Product,Product.id==OrderLine.product_id)
            if customer_id:lines=lines.where(Order.customer_id==customer_id)
            if q:lines=lines.where(or_(*[c.contains(q,autoescape=True) for c in [OrderLine.id,Order.po_number,Order.id,Product.name]]))
            query=query.where(or_(Run.id.in_(list(related_run_ids)),Run.id.in_(select(Item.run_id).where(Item.order_line_id.in_(lines))),Run.order_line_id.in_(lines)))
        return query
    def bounds(day,left,right,snapshot=None):
        snapshot=snapshot or {};a=stamp(snapshot.get('start'));b=stamp(snapshot.get('end'))
        if a and b and b>a:return a,b,'explicit'
        if day and left and right and right>left:
            return datetime.combine(day,left,tzinfo=ZONE),datetime.combine(day,right,tzinfo=ZONE),'legacy_same_day'
        return None,None,'missing_or_ambiguous'
    def add(row):
        a,b=row['start'],row['end']
        if a and b and b<=a:a=b=None;row['start']=row['end']=None
        if a and b and not (a<end and b>start):return
        row['missing_fields']=[]
        if not a or not b:row['missing_fields'].append('production_time')
        if not row['machine_id']:row['missing_fields'].append('machine_id')
        if not row['run_id']:row['missing_fields'].append('run_link')
        pure=qty(row.pop('reported_pure',None))
        if pure is not None and (not a or not b or pure>Decimal(str((b-a).total_seconds()))):pure=None
        row['pure_seconds']=pure
        if pure is None:row['missing_fields'].append('pure_seconds')
        row['within_view']=bool(a and b and a>=start and b<=end)
        records.append(row)
        if row['run_id']:runs.add(row['run_id'])
        if len(records)>LIMIT:fail('Hơn 2000 nhật ký trong phạm vi thực tế; thu hẹp ngày, máy hoặc CTĐH.')
    query=select(FormingLog.id,FormingLog.production_order_id.label('run_id'),FormingLog.shift_start,FormingLog.shift_end,
        FormingLog.run_date,FormingLog.start_time,FormingLog.end_time,FormingLog.shift_snapshot,FormingLog.good,FormingLog.ng,
        Run.machine_id,Run.run_snapshot,Run.status,Run.order_line_id,Run.group_id).join(Run,Run.id==FormingLog.production_order_id).where(or_(
        and_(FormingLog.shift_start<end.astimezone(ZONE).replace(tzinfo=None),FormingLog.shift_end>start.astimezone(ZONE).replace(tzinfo=None)),
        and_(or_(FormingLog.shift_start.is_(None),FormingLog.shift_end.is_(None)),FormingLog.run_date.between(lo,hi))))
    forming=db.execute(filtered(query,Run.machine_id).order_by(FormingLog.id).limit(LIMIT+1)).mappings().all()
    if len(forming)>LIMIT:fail('Quá nhiều nhật ký định hình; thu hẹp bộ lọc.')
    shift_rows=defaultdict(list)
    for i in db.execute(select(ShiftItem.log_id,ShiftItem.order_line_id,ShiftItem.good_qty,ShiftItem.ng_qty)
        .where(ShiftItem.log_id.in_([r['id'] for r in forming]))).mappings():shift_rows[i['log_id']].append(dict(i))
    for r in forming:
        snapshot=r['shift_snapshot'] or {};a,b,basis=bounds(r['run_date'],r['start_time'],r['end_time'])
        if r['shift_start'] and r['shift_end']:a,b,basis=stamp(r['shift_start']),stamp(r['shift_end']),'explicit'
        elif r['shift_snapshot']:a=b=None;basis='incomplete_native_time'
        members=[{'order_line_id':i['order_line_id'],'good_qty':qty(i['good_qty']),'ng_qty':qty(i['ng_qty'])} for i in shift_rows[r['id']]]
        if not members and r['order_line_id']:
            # Legacy header good is SHEETS; it cannot be relabelled as products.
            members=[{'order_line_id':r['order_line_id'],'good_qty':None,'ng_qty':None,'quantity_note':'Legacy: sản lượng bìa chưa có quy đổi đã xác minh.'}]
        primary[r['run_id']]=r['order_line_id']
        add({'id':r['id'],'run_id':r['run_id'],'stage':'forming','machine_id':r['machine_id'],
            'machine_kind':(r['run_snapshot'] or {}).get('machine_kind','unclassified'),'group_id':r['group_id'],
            'run_status':r['status'],'start':a,'end':b,'time_basis':basis,'items':members,'reported_pure':snapshot.get('pure_seconds')})
    for model,stage,column in [(CuttingLog,'cutting',DownstreamItem.cut_id),(EBLog,'edge',DownstreamItem.edge_id)]:
        query=select(model.id,model.machine_id,model.run_date,model.start_time,model.end_time,
            DownstreamItem.order_line_id,DownstreamItem.good_qty,DownstreamItem.ng_qty,DownstreamItem.input_qty,DownstreamItem.snapshot,
            FormingLog.production_order_id.label('run_id'),Run.status,Run.group_id).join(DownstreamItem,column==model.id)
        query=query.join(FormingLog,FormingLog.id==DownstreamItem.forming_log_id).join(Run,Run.id==FormingLog.production_order_id).where(or_(
            model.run_date.between(lo,hi),and_(func.substr(DownstreamItem.snapshot['start'].as_string(),1,10)<=hi.isoformat(),
                func.substr(DownstreamItem.snapshot['end'].as_string(),1,10)>=lo.isoformat())))
        native=db.execute(filtered(query,model.machine_id).order_by(model.id,DownstreamItem.order_line_id).limit(LIMIT+1)).mappings().all()
        if len(native)>LIMIT:fail('Quá nhiều dòng công đoạn thực tế; thu hẹp bộ lọc.')
        grouped={}
        for r in native:
            if r['id'] not in grouped:
                a,b,basis=bounds(r['run_date'],r['start_time'],r['end_time'],r['snapshot'])
                grouped[r['id']]={'id':r['id'],'run_id':r['run_id'],'stage':stage,'machine_id':r['machine_id'],
                    'machine_kind':stage,'group_id':r['group_id'],'run_status':r['status'],'start':a,'end':b,'time_basis':basis,
                    'items':[],'reported_pure':(r['snapshot'] or {}).get('pure_seconds')}
            grouped[r['id']]['items'].append({'order_line_id':r['order_line_id'],'good_qty':qty(r['good_qty']),
                'ng_qty':qty(r['ng_qty']),'input_qty':qty(r['input_qty'])})
        for row in grouped.values():add(row)
        legacy=select(model.id,model.machine_id,model.run_date,model.start_time,model.end_time,model.good,model.ng,
            FormingLog.production_order_id.label('run_id'),Run.order_line_id,Run.status,Run.group_id).outerjoin(DownstreamItem,column==model.id)
        legacy=legacy.outerjoin(FormingLog,FormingLog.id==model.order_ref).outerjoin(Run,Run.id==FormingLog.production_order_id)
        legacy=legacy.where(DownstreamItem.id.is_(None),model.run_date.between(lo,hi))
        for r in db.execute(filtered(legacy,model.machine_id).order_by(model.id).limit(LIMIT+1)).mappings():
            a,b,basis=bounds(r['run_date'],r['start_time'],r['end_time'])
            add({'id':r['id'],'run_id':r['run_id'],'stage':stage,'machine_id':r['machine_id'],'machine_kind':stage,
                'group_id':r['group_id'],'run_status':r['status'],'start':a,'end':b,'time_basis':basis,
                'items':[{'order_line_id':r['order_line_id'],'good_qty':None,'ng_qty':None,'quantity_note':'Nhật ký cũ chưa có chi tiết CTĐH/đơn vị.'}] if r['order_line_id'] else [],'reported_pure':None})
    item_info={}
    for i in db.execute(select(Item.run_id,Item.order_line_id,Item.snapshot).where(Item.run_id.in_(list(runs)))).mappings():
        item_info[(i['run_id'],i['order_line_id'])]=i['snapshot']
    line_ids={i['order_line_id'] for r in records for i in r['items']};metadata=line_metadata(db,line_ids)
    audits={}
    audit_stage=Audit.details['stage'].as_string()
    for entity,action,stage,at in db.execute(select(Audit.entity_id,Audit.action,audit_stage,func.max(Audit.created_at)).where(Audit.entity_id.in_([r['id'] for r in records]),
        Audit.action.in_(['PRODUCTION_SHIFT_CLOSE','PRODUCTION_SHIFT_EDIT','PRODUCTION_DOWNSTREAM'])).group_by(Audit.entity_id,Audit.action,audit_stage)):
        key=(entity,'forming' if action in {'PRODUCTION_SHIFT_CLOSE','PRODUCTION_SHIFT_EDIT'} else stage)
        audits[key]=max(audits.get(key,at),at)
    for r in records:
        for i in r['items']:
            info=item_info.get((r['run_id'],i['order_line_id']),{})
            i['unit']=info.get('unit') or metadata.get(i['order_line_id'],{}).get('unit')
            if i['good_qty'] is None or not i['unit']:r['missing_fields'].append('product_quantity_or_unit')
        updated=audits.get((r['id'],r['stage']))
        r['updated_at']=updated.replace(tzinfo=timezone.utc) if updated else None
        r['data_quality']='complete' if not r['missing_fields'] else 'partial'
    machine_ids={r['machine_id'] for r in records if r['machine_id']}
    machines={m.id:{'id':m.id,'name':m.name,'kind':m.kind,'status':m.status,'version':m.version} for m in db.scalars(select(Machine).where(Machine.id.in_(list(machine_ids))))}
    for r in records:
        if r['machine_id'] and r['machine_id'] not in machines:machines[r['machine_id']]={'id':r['machine_id'],'name':'Chưa có danh mục máy','kind':r['machine_kind'],'status':'unknown','version':0}
    return {'records':records,'machines':list(machines.values()),'line_metadata':metadata,
        'data_updated_at':max((r['updated_at'] for r in records if r['updated_at']),default=None),
        'retrieved_at':datetime.now(timezone.utc),'update_time_complete':all(r['updated_at'] is not None for r in records),
        'note':'Khoảng trống nhật ký là chưa có dữ liệu; không kết luận máy nghỉ. Thời điểm cập nhật lấy audit, không dùng để dựng khoảng sản xuất.'}
