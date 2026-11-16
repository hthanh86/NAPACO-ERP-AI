"""Compile existing LSX/stock/calendars into one deterministic planning context."""
import hashlib,json
from collections import defaultdict
from datetime import datetime,timedelta
from decimal import Decimal
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select,func,inspect
from app.modules.production import run_service as runs
from app.modules.production.schedule_engine import calculate,requirements,ScheduleError
from app.modules.production.schedule_schemas import JobPolicy,RunInput,ScheduleInput
from app.modules.production.schedule_models import SchedulePlan,RunStop
from app.modules.production.run_models import ProductionOrderItem as Item,RunMaterial,ShiftItem,ShiftMaterial,DownstreamItem
from app.modules.production.models import ProductionOrder as Run,FormingLog,CuttingLog,EBLog
from app.modules.production.planning_models import Machine,MachineCalendarException
from app.modules.production.planning_service import available_windows,ZONE
from app.modules.production.calendar_settings import read_default
from app.modules.orders.models import OrderLine,Order
from app.modules.products.models import Product
from app.modules.customers.models import Customer
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory import allocation_service as material

D=material.decimal


def encoded(value):return jsonable_encoder(value,custom_encoder={Decimal:str})
def digest(value):return hashlib.sha256(json.dumps(encoded(value),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def aware(value):return value.replace(tzinfo=ZONE) if value else None


def integer(value,label):
    n=D(value)
    if n<0 or n!=n.to_integral_value():material.fail(label+': sản lượng phải nguyên và không âm.')
    return int(n)


def latest(db):return db.scalar(select(SchedulePlan).order_by(SchedulePlan.version.desc()).limit(1))


def dto(run,items,bindings):
    return {'id':run.id,'version':run.version,'status':run.status,'machine_id':run.machine_id,
        'official_code':run.official_code,'release_state':run.release_state,
        'standard_id':run.standard_id,'parent_run_id':run.parent_run_id,'group_id':run.group_id,'snapshot':run.run_snapshot,
        'items':[{'order_line_id':i.order_line_id,'product_id':i.product_id,'planned_qty':integer(i.planned_qty,i.order_line_id),
                  'completed_qty':integer(i.completed_qty,i.order_line_id),'cavity':i.cavity,'snapshot':i.snapshot} for i in items if i.enabled],
        'materials':[{'allocation_id':m.allocation_id,'planned_kg':str(m.planned_kg),'issued_kg':str(m.issued_kg)} for m in bindings]}


def moved_config(run,move):
    p=run['snapshot']['parameters']
    return RunInput.model_validate({'id':run['id'],'version':move.version,'standard_id':run['standard_id'],
        'machine_id':move.machine_id,'group_id':run['group_id'],'group_confirmed':run['snapshot']['group_confirmed'],
        'parent_run_id':run['parent_run_id'],'film_width_mm':p.get('film_width_mm'),'items':[{'order_line_id':i['order_line_id'],'quantity':i['planned_qty'],'cavity':i['cavity']} for i in run['items']],
        'materials':[{'allocation_id':m['allocation_id'],'kg':m['planned_kg']} for m in run['materials']],
        **{k:p[k] for k in ['seconds_per_cycle','pull_mm','setup_minutes','sheet_weight_kg','waste_percent']},'note':move.note})


def prepare(db,user,data,*,for_update=False,reason_view=None):
    """Preview uses SELECT only. Save invokes this under the shared ERP write lock."""
    base=latest(db);version=base.version if base else 0
    planning_now=datetime.now(ZONE).replace(second=0,microsecond=0)
    old_jobs={j['run_id']:j for j in (base.result.get('jobs',[]) if base else [])}
    past=set()
    for identifier,job in old_jobs.items():
        start=job.get('allocation_start') or next((span['start'] for span in [*job.get('setup_segments',[]),*job.get('forming_segments',[])]),None)
        if start and datetime.fromisoformat(str(start))<planning_now:past.add(identifier)
    previous_policies={p['run_id']:JobPolicy.model_validate(p).model_dump(mode='json') for p in (base.request.get('jobs',[]) if base else [])}
    changed_policies={p.run_id for p in data.jobs if p.model_dump(mode='json')!=previous_policies.get(p.run_id)}
    edits={c.config.id for c in data.changes}|{m.run_id for m in data.moves}|set(data.unschedule)|changed_policies
    if edits&past:material.fail('Không được thay đổi kế hoạch đã bắt đầu trong quá khứ. Chỉ xem lại lịch đã lưu.',409)
    for policy in data.jobs:
        if policy.run_id in edits and policy.ready_at and policy.ready_at<planning_now:
            material.fail('Không được chọn thời gian bắt đầu trong quá khứ.',422)

    if data.base_version!=version:material.fail('Kế hoạch đã thay đổi; tính thử lại với phiên bản mới.',409)
    from app.modules.production import schedule_daily
    day_state=schedule_daily.check_request(db,data,for_update) if inspect(db.connection()).has_table('production_schedule_days') else None
    def read(query):return db.scalars(query.with_for_update() if for_update else query)
    rows=read(select(Run).where(Run.run_snapshot.is_not(None)).order_by(Run.id).limit(1001)).all()
    if len(rows)>1000:material.fail('Phạm vi vượt 1000 lần chạy; cần thu hẹp dữ liệu lưu trữ trước khi tính.',422)
    ids=[r.id for r in rows];by_run={r.id:r for r in rows}
    items=defaultdict(list);bindings=defaultdict(list)
    for i in db.scalars(select(Item).where(Item.run_id.in_(ids)).order_by(Item.order_line_id)):items[i.run_id].append(i)
    for m in db.scalars(select(RunMaterial).where(RunMaterial.run_id.in_(ids)).order_by(RunMaterial.allocation_id)):bindings[m.run_id].append(m)
    original={r.id:dto(r,items[r.id],bindings[r.id]) for r in rows};virtual=dict(original)
    ending={e.run_id for e in data.end_runs};configs=[];warnings=[]
    replaced={c.config.id for c in data.changes}|{m.run_id for m in data.moves}
    exclusions=ending|replaced
    for end in data.end_runs:
        runs.change_state(db,user,end.run_id,end,preview=True)
        virtual[end.run_id]={**virtual[end.run_id],'status':runs.ENDED}
    for change in data.changes:
        if change.split_from:
            source=original.get(change.split_from)
            if not source:material.fail('Không tìm thấy nhóm cần tách.')
            if change.config.id in original:material.fail('Phần tách phải dùng ID lần chạy mới.')
            if not {i.order_line_id for i in change.config.items}<={i['order_line_id'] for i in source['items']}:
                material.fail('Phần tách có CTĐH ngoài nhóm gốc.')
            if source['status']==runs.RUNNING and source['id'] not in ending:
                material.fail('Phải chốt/kết thúc nhóm đang chạy trước khi tách.')
            if source['status']==runs.PLANNED and source['id'] not in exclusions:
                material.fail('Phải sửa hoặc kết thúc bố trí gốc cùng transaction khi tách.')
        configs.append(change.config)
    for move in data.moves:
        if move.run_id not in original:material.fail('Không tìm thấy lần chạy cần chuyển.')
        configs.append(moved_config(original[move.run_id],move))
    for config in configs:
        identifier=config.id if config.id in original else None
        prospective=runs.save_run(db,user,config,identifier,preview=True,exclude_run_ids=exclusions,ending_run_ids=ending,scheduling=True)
        old=original.get(config.id)
        if old and old['machine_id']!=config.machine_id:
            warnings.append({'code':'CONFIRM_MOVE:'+config.id+':'+str(old['version'])+':'+config.machine_id,
                'message':'Chuyển máy sẽ gỡ toàn bộ bố trí cũ của lần chạy này và tính lại các công việc bị ảnh hưởng.',
                'run_id':config.id,'from_machine':old['machine_id'],'to_machine':config.machine_id})
        if not old:
            target_lines={i.order_line_id for i in config.items}
            for source_id in sorted(exclusions & set(original)):
                source=original[source_id]
                shared=target_lines & {i['order_line_id'] for i in source['items']}
                if source['status']==runs.PLANNED and source['machine_id']!=config.machine_id and shared:
                    warnings.append({'code':'CONFIRM_TRANSFER_PART:'+source_id+':'+str(source['version'])+':'+config.id+':'+config.machine_id,
                        'message':'Tách/chuyển phần chưa chạy sang máy khác sẽ thay bố trí nguồn; cần xác nhận cấu hình và lịch mới.',
                        'from_run_id':source_id,'run_id':config.id,'order_line_ids':sorted(shared),
                        'from_machine':source['machine_id'],'to_machine':config.machine_id})
        virtual[config.id]=prospective
    # Validate aggregate final state, including two newly created runs claiming the same stock/output.
    quantities=defaultdict(Decimal);claims=defaultdict(Decimal)
    for r in virtual.values():
        if r['status']==runs.ENDED:continue
        for i in r['items']:quantities[i['order_line_id']]+=D(i['planned_qty'])-D(i['completed_qty'])
        for m in r['materials']:claims[m['allocation_id']]+=max(Decimal(0),D(m['planned_kg'])-D(m['issued_kg']))
    lines={l.id:l for l in read(select(OrderLine).where(OrderLine.id.in_(list(quantities))).order_by(OrderLine.id))}
    for ct,qty in quantities.items():
        if ct not in lines or D(lines[ct].produced)+qty>D(lines[ct].quantity):material.fail(ct+': tổng phần bố trí vượt còn phải sản xuất.',409)
    allocations={a.id:a for a in read(select(Allocation).where(Allocation.id.in_(list(claims))).order_by(Allocation.id))}
    for aid,kg in claims.items():
        if aid not in allocations or kg>allocations[aid].held_kg:material.fail('Phân bổ bị dùng vượt lượng giữ: '+aid,409)
    policies={p['run_id']:JobPolicy.model_validate(p).model_dump() for p in (base.request.get('jobs',[]) if base else [])}
    policies.update({p.run_id:p.model_dump() for p in data.jobs})
    old_policies={p['run_id']:p for p in (base.request.get('jobs',[]) if base else [])}
    history_cache={}
    for policy in data.jobs:
        old_stages={(s['order_line_id'],s['stage']):s for s in old_policies.get(policy.run_id,{}).get('stages',[])}
        for stage in policy.stages:
            old=old_stages.get((stage.order_line_id,stage.stage))
            policies[policy.run_id]['stages'][policy.stages.index(stage)]['history_evidence']=old.get('history_evidence') if old and stage.history_selection else None
            if stage.history_selection and (not old or old.get('history_selection')!=stage.history_selection.model_dump() or
                    any(old.get(k)!=getattr(stage,k) for k in ['machine_id','seconds_per_unit','setup_minutes','unit'])):
                from app.modules.production.history_service import resolve
                from app.modules.production.history_schemas import HistoryQuery
                r=virtual.get(policy.run_id)
                if not r or not stage.machine_id:material.fail('Gợi ý công đoạn cần lần chạy và máy cụ thể.')
                query=HistoryQuery(standard_id=r['standard_id'],machine_id=stage.machine_id,stage=stage.stage,
                    unit=stage.unit,pull_mm=r['snapshot']['parameters']['pull_mm'],
                    allocation_ids=[m['allocation_id'] for m in r['materials']],
                    items=[{'order_line_id':i['order_line_id'],'cavity':i['cavity']} for i in r['items']])
                key=(query.model_dump_json(),stage.history_selection.model_dump_json())
                if key not in history_cache:history_cache[key]=resolve(db,query,stage.history_selection)
                matched=history_cache[key]
                # Evidence is frozen in the request/context; no standard is updated.
                policies[policy.run_id]['stages'][policy.stages.index(stage)]['history_evidence']=matched
            if old and old.get('machine_id') and old['machine_id']!=stage.machine_id:
                warnings.append({'code':'CONFIRM_STAGE_MOVE:'+policy.run_id+':'+stage.order_line_id+':'+stage.stage+':'+str(stage.machine_id),
                    'message':'Chuyển phần công đoạn chưa thực hiện sang máy khác; giữ nguyên nhật ký đã chốt.',
                    'run_id':policy.run_id,'order_line_id':stage.order_line_id,'stage':stage.stage,
                    'from_machine':old['machine_id'],'to_machine':stage.machine_id})
    for identifier in data.order:
        if identifier not in virtual:material.fail('Thứ tự chứa lần chạy không tồn tại: '+identifier)
        policies.setdefault(identifier,JobPolicy(run_id=identifier).model_dump())
    for config in configs:policies.setdefault(config.id,JobPolicy(run_id=config.id).model_dump())
    for identifier in policies:
        if identifier not in virtual:material.fail('Cấu hình lịch chứa lần chạy không tồn tại: '+identifier)
    for identifier in data.unschedule:
        if identifier not in virtual:material.fail('Không tìm thấy lần chạy cần gỡ lịch.')
        if virtual[identifier]['status']==runs.RUNNING:material.fail('Lần chạy đang chạy phải chốt/kết thúc hoặc giải phóng máy; không gỡ thực tế.')
        policies.pop(identifier,None)
    queue=[i for i in dict.fromkeys([*data.order,*((base.request.get('order',[])) if base else []),*policies]) if i not in data.unschedule]
    if base and past:
        old_order=base.request.get('order',[])
        for identifier in past & set(queue):
            machine=virtual[identifier]['machine_id']
            before_old=[i for i in old_order[:old_order.index(identifier)] if i in original and original[i]['machine_id']==machine] if identifier in old_order else []
            before_new=[i for i in queue[:queue.index(identifier)] if i in virtual and virtual[i]['machine_id']==machine]
            if before_old!=before_new:material.fail('Không được đảo vị trí hoặc chèn lần chạy làm thay đổi kế hoạch trong quá khứ.',409)
    if len(queue)>200:material.fail('Một bản lịch tối đa 200 lần chạy.')
    # Active runs cannot disappear from the authoritative schedule when recalculating.
    for r in virtual.values():
        if r['status']==runs.RUNNING and r['id'] not in queue:
            queue.append(r['id']);policies[r['id']]=JobPolicy(run_id=r['id']).model_dump()
    if len(queue)>200:material.fail('Một bản lịch tối đa 200 lần chạy.')
    stops={s.id:{'id':s.id,'run_id':s.run_id,'version':s.version,'at':aware(s.started_at),
        'duration_seconds':s.duration_seconds,'hold_machine':s.hold_machine,'enabled':s.enabled,'note':s.note}
        for s in read(select(RunStop).order_by(RunStop.id))}
    logs=db.scalars(select(FormingLog).where(FormingLog.production_order_id.in_(ids)).order_by(FormingLog.shift_end,FormingLog.id)).all()
    log_by_id={l.id:l for l in logs};last_end={};actual_cycles=defaultdict(int)
    for log in logs:
        if log.shift_snapshot:actual_cycles[log.production_order_id]+=integer(log.good+log.ng,log.id)
    for log in logs:
        if log.shift_end:last_end[log.production_order_id]=max(last_end.get(log.production_order_id,log.shift_end),log.shift_end)
    for patch in data.stops:
        old=stops.get(patch.id);r=virtual.get(patch.run_id)
        if not r or r['status']==runs.ENDED:material.fail('Dừng/nghỉ cần lần chạy chưa kết thúc.')
        if old and (patch.version!=old['version'] or old['run_id']!=patch.run_id):material.fail('Dừng máy đã thay đổi hoặc thuộc lần chạy khác.',409)
        if not old and patch.version is not None:material.fail('Dừng máy mới không có version cũ.')
        boundary=last_end.get(patch.run_id)
        if boundary and (runs.local(patch.at)<boundary or (old and runs.local(old['at'])<boundary)):
            material.fail('Không sửa khoảng dừng đã nằm trong phần thực tế; tạo điều chỉnh tương lai.',409)
        stops[patch.id]={**patch.model_dump(exclude={'version'}),'version':old['version']+1 if old else 1}
    machine_ids={virtual[i]['machine_id'] for i in queue}
    for p in policies.values():machine_ids.update(s['machine_id'] for s in p['stages'] if s['machine_id'])
    machines={m.id:m for m in read(select(Machine).where(Machine.id.in_(list(machine_ids))).order_by(Machine.id))}
    for identifier in queue:
        r=virtual[identifier]
        if r['machine_id'] not in machines or machines[r['machine_id']].status not in {'ready','running'}:
            material.fail('Máy không sẵn sàng: '+r['machine_id'])
        for s in policies.get(identifier,{}).get('stages',[]):
            if s['order_line_id'] not in {i['order_line_id'] for i in r['items']}:material.fail('Công đoạn thuộc CTĐH ngoài lần chạy.')
            if s['machine_id']:
                m=machines.get(s['machine_id'])
                if not m or m.kind!=s['stage'] or m.status not in {'ready','running'}:material.fail('Máy công đoạn sau không phù hợp.')
    windows=available_windows(db,sorted(machine_ids),data.start.astimezone(ZONE).date(),data.end.astimezone(ZONE).date()) if machine_ids else {'machines':[]}
    spans={m['machine_id']:[(datetime.fromisoformat(w['start']),datetime.fromisoformat(w['end'])) for w in m['windows']] for m in windows['machines']}
    actual=[];actual_keys={};streams=defaultdict(lambda:defaultdict(list));processed=defaultdict(lambda:defaultdict(int));fingerprints=[]
    def fixed(machine,start,end,line_ids,reference,stage='forming',run_id=None,evidence=(),pure_seconds=None):
        if not start or not end or end<=start:material.fail('Nhật ký thiếu/sai khoảng thực tế: '+reference)
        key=(machine,start,end,reference)
        if key in actual_keys:
            actual_keys[key]['order_line_ids']=sorted(set(actual_keys[key]['order_line_ids'])|set(line_ids))
            actual_keys[key]['items'].extend(evidence);return
        entry={'resources':['machine:'+machine,*(['line:'+ct for ct in line_ids] if stage=='forming' else [])],
            'start':start,'end':end,'reference':reference,'stage':stage,'order_line_ids':line_ids,'run_id':run_id,
            'items':list(evidence),'pure_seconds':pure_seconds}
        actual_keys[key]=entry;actual.append(entry)
    from app.modules.production.release_service import machine_expression,historical_machine
    legacy=db.execute(select(FormingLog,machine_expression(),Run.order_line_id).join(Run,Run.id==FormingLog.production_order_id)
        .where(Run.run_snapshot.is_(None),machine_expression().in_(list(machine_ids)),
               FormingLog.run_date.between(data.start.astimezone(ZONE).date()-timedelta(days=1),data.end.astimezone(ZONE).date()))).all()
    for log,machine,ct in legacy:
        if not log.start_time or not log.end_time:material.fail('Nhật ký cũ thiếu giờ; cần đối soát trước khi xếp máy: '+log.id)
        start=datetime.combine(log.run_date,log.start_time,tzinfo=ZONE);end=datetime.combine(log.run_date,log.end_time,tzinfo=ZONE)
        if end<=start:end+=timedelta(days=1)
        fixed(machine,start,end,[ct] if ct else [],log.id)
    shift_items=defaultdict(list)
    for i in db.scalars(select(ShiftItem).where(ShiftItem.log_id.in_(list(log_by_id)))):shift_items[i.log_id].append(i)
    for log in logs:
        r=original[log.production_order_id]
        if not log.shift_snapshot:
            if log.run_date and data.start.date()<=log.run_date<=data.end.date() and r['machine_id'] in machine_ids:
                material.fail('Cần đối soát giờ nhật ký cũ trước khi xếp máy: '+log.id)
            continue
        units={i.order_line_id:i.snapshot['unit'] for i in items[r['id']]}
        actual_machine=historical_machine(log)
        if not actual_machine:material.fail('Nhật ký chưa xác định máy thực tế, cần đối soát: '+log.id,409)
        fixed(actual_machine,aware(log.shift_start),aware(log.shift_end),[i.order_line_id for i in shift_items[log.id]],log.id,run_id=r['id'],
            evidence=[{'order_line_id':i.order_line_id,'good_qty':i.good_qty,'ng_qty':i.ng_qty,'unit':units.get(i.order_line_id)} for i in shift_items[log.id]],
            pure_seconds=log.shift_snapshot.get('pure_seconds'))
        fingerprints.append([log.id,log.version,log.shift_snapshot])
        for i in shift_items[log.id]:streams[r['id']][(i.order_line_id,'forming')].append({'quantity':integer(i.good_qty,log.id),'at':aware(log.shift_end),'actual':True,'estimated':False})
    downstream=db.scalars(select(DownstreamItem).where(DownstreamItem.forming_log_id.in_(list(log_by_id))).order_by(DownstreamItem.id)).all()
    cut_ids={i.cut_id for i in downstream if i.cut_id};edge_ids={i.edge_id for i in downstream if i.edge_id}
    headers={('cutting',h.id):h for h in db.scalars(select(CuttingLog).where(CuttingLog.id.in_(list(cut_ids))))}
    headers.update({('edge',h.id):h for h in db.scalars(select(EBLog).where(EBLog.id.in_(list(edge_ids))))})
    for i in downstream:
        log=log_by_id[i.forming_log_id];h=headers[(i.stage,i.cut_id or i.edge_id)]
        if not h.run_date or not h.start_time or not h.end_time:material.fail('Cần đối soát giờ công đoạn: '+h.id)
        start=datetime.fromisoformat(i.snapshot['start']);end=datetime.fromisoformat(i.snapshot['end'])
        fixed(h.machine_id,start,end,[i.order_line_id],h.id,stage=i.stage,run_id=log.production_order_id,
            evidence=[{'order_line_id':i.order_line_id,'good_qty':i.good_qty,'ng_qty':i.ng_qty,'unit':i.snapshot.get('product',{}).get('unit')}],
            pure_seconds=i.snapshot.get('pure_seconds'))
        streams[log.production_order_id][(i.order_line_id,i.stage)].append({'quantity':integer(i.good_qty,i.id),'at':end,'actual':True,'estimated':False})
        processed[log.production_order_id][(i.order_line_id,i.stage)]+=integer(i.input_qty,i.id)
        fingerprints.append([i.id,i.snapshot,i.input_qty,i.good_qty,start,end])
    source_used=defaultdict(int);source_cut_good=defaultdict(int)
    source_good={(i.log_id,i.order_line_id):integer(i.good_qty,i.log_id) for values in shift_items.values() for i in values}
    for i in downstream:
        source_used[(i.forming_log_id,i.order_line_id,i.stage)]+=integer(i.input_qty,i.id)
        if i.stage=='cutting':source_cut_good[(i.forming_log_id,i.order_line_id)]+=integer(i.good_qty,i.id)
    for (log_id,ct,stage),used in source_used.items():
        r=original[log_by_id[log_id].production_order_id]
        item=next((i for i in items[r['id']] if i.order_line_id==ct),None)
        if not item:material.fail('Công đoạn có CTĐH ngoài lần chạy: '+log_id)
        product=(log_by_id[log_id].shift_snapshot or {}).get('items',{}).get(ct,item.snapshot)
        capacity=source_cut_good[(log_id,ct)] if stage=='edge' and 'cutting' in product['route'] else source_good.get((log_id,ct),0)
        if used>capacity:material.fail('Công đoạn sau đã dùng vượt nguồn nhật ký '+log_id,409)
    for values in streams.values():
        for events in values.values():events.sort(key=lambda event:event['at'])
    for model,stage,linked in [(CuttingLog,'cutting',cut_ids),(EBLog,'edge',edge_ids)]:
        for h in db.scalars(select(model).where(model.machine_id.in_(list(machine_ids)),~model.id.in_(list(linked)),
            model.run_date.between(data.start.astimezone(ZONE).date()-timedelta(days=1),data.end.astimezone(ZONE).date()))):
            if not h.start_time or not h.end_time:material.fail('Nhật ký công đoạn cũ thiếu giờ: '+h.id)
            start=datetime.combine(h.run_date,h.start_time,tzinfo=ZONE);end=datetime.combine(h.run_date,h.end_time,tzinfo=ZONE)
            if end<=start:end+=timedelta(days=1)
            fixed(h.machine_id,start,end,[],h.id,stage=stage)
    # Include every line of an affected PO, so a partially scheduled PO cannot appear complete.
    selected_ct={i['order_line_id'] for rid in queue for i in virtual[rid]['items']}
    order_ids=set(db.scalars(select(OrderLine.order_id).where(OrderLine.id.in_(list(selected_ct)))))
    line_rows=read(select(OrderLine).where(OrderLine.order_id.in_(list(order_ids))).order_by(OrderLine.id)).all()
    final_actual=defaultdict(list)
    for r in original.values():
        for i in r['items']:
            stages=[s for s in i['snapshot']['route'] if s in {'cutting','edge'}]
            final_actual[i['order_line_id']].extend(streams[r['id']].get((i['order_line_id'],stages[-1] if stages else 'forming'),[]))
    # Load machine balances and receipt availability in batches, not once per job.
    source_rows=db.scalars(select(ShiftMaterial).where(ShiftMaterial.log_id.in_(list(log_by_id)))).all()
    from app.modules.materials.inventory.handover_sources import source_contexts
    material_contexts=source_contexts(db,queue,logs=logs,materials=source_rows)
    positions={rid:{s['receipt_id']:s for s in c['sources']} for rid,c in material_contexts.items()}
    selected_bindings=[b for rid in queue if virtual[rid]['status']!=runs.ENDED for b in virtual[rid]['materials'] if D(b['planned_kg'])>D(b['issued_kg'])]
    selected_allocation_ids={b['allocation_id'] for b in selected_bindings}
    all_allocations={a.id:a for a in read(select(Allocation).where(Allocation.id.in_(list(selected_allocation_ids))).order_by(Allocation.id))}
    total_required=defaultdict(Decimal)
    for b in selected_bindings:
        a=all_allocations.get(b['allocation_id'])
        if not a:material.fail('Phân bổ đã mất: '+b['allocation_id'],409)
        total_required[a.receipt_id]+=max(Decimal(0),D(b['planned_kg'])-D(b['issued_kg']))
    balances=material.ensure_available(db,total_required,own_allocation_ids=list(selected_allocation_ids),
        order_line_ids=list(selected_ct),lock=for_update) if total_required else {}
    context_runs=[];stock_fingerprints=[balances,[material.allocation_record(a) for a in all_allocations.values()]]
    for identifier in queue:
        r=virtual[identifier];r={**r,'policy':policies.get(identifier,JobPolicy(run_id=identifier).model_dump()),
            'future_only':identifier not in original or identifier in edits,
            'has_actual':identifier in last_end,'actual_end':aware(last_end.get(identifier)),
            'streams':streams[identifier],'processed':processed[identifier]}
        if r['snapshot'].get('parameters',{}).get('planned_cycles_limit') is not None:
            r={**r,'snapshot':{**r['snapshot'],'parameters':{**r['snapshot']['parameters'],'completed_cycles':actual_cycles[identifier]}}}
        # Do not invalidate old saved starts solely because this reason field is new.
        previous_policy=old_policies.get(identifier,{})
        previous_start=previous_policy.get('ready_at')
        if isinstance(previous_start,str):previous_start=datetime.fromisoformat(previous_start)
        r['validate_start_reason']=(r['policy'].get('start_basis','setup')!=previous_policy.get('start_basis','setup') or r['policy'].get('ready_at')!=previous_start or
            r['policy'].get('start_reason','')!=previous_policy.get('start_reason',''))
        if r['status']==runs.ENDED:
            # Ended runs retain actual downstream WIP but cannot claim future forming output.
            r={**r,'items':[{**i,'planned_qty':i['completed_qty']} for i in r['items']]}
        if not r['items']:material.fail('Lần chạy thiếu chi tiết sản phẩm: '+identifier)
        try:
            requirement=requirements(r['items'],r['snapshot'].get('parameters'),identifier);needed=requirement['required_kg']
        except ScheduleError as error:
            from fastapi import HTTPException
            raise HTTPException(422,detail=error.detail) from error
        required=defaultdict(Decimal);own=[];held=Decimal(0)
        for b in r['materials'] if r['status']!=runs.ENDED else []:
            if D(b['planned_kg'])<=D(b['issued_kg']):continue
            a=all_allocations.get(b['allocation_id'])
            if not a:material.fail('Phân bổ đã mất: '+b['allocation_id'],409)
            unissued=max(Decimal(0),D(b['planned_kg'])-D(b['issued_kg']));required[a.receipt_id]+=unissued;held+=unissued;own.append(a.id)
        for receipt in required:
            if balances[receipt]['material_id']!=r['snapshot']['standard_snapshot']['material']['id']:material.fail('Nguồn nhựa khác vật liệu định mức.')
        position={'sources':list(positions[identifier].values()),'previous_end':last_end.get(identifier)}
        source_kg=[D(s['opening_kg'])+D(s['input_kg'])-D(s['output_kg']) for s in position['sources']]
        if any(kg<0 for kg in source_kg):material.fail(identifier+': số dư một nguồn tại máy âm, cần đối soát.')
        measured=sum(source_kg,Decimal(0))
        if r['status']==runs.RUNNING and needed>0 and (identifier in last_end or measured>0):
            warnings.append({'code':'MACHINE_STOCK_AS_OF:'+identifier,'message':'Số dư tại máy là số chốt ca gần nhất cộng cấp/trả chưa chốt; phải đối chiếu trước khi chạy tiếp.','run_id':identifier})
        pending=sum((D(l['pending_handover_kg']) for l in material_contexts[identifier]['lots']),Decimal(0))
        if pending>0:warnings.append({'code':'PENDING_HANDOVER:'+identifier,'message':'Có NVL chờ ký nhận; chỉ là nguồn kế hoạch, chưa được dùng để ghi sản xuất.','run_id':identifier})
        shortage=max(Decimal(0),needed-held-measured-pending)
        if shortage:
            warnings.append({'code':'MATERIAL_SHORTAGE:'+identifier,'run_id':identifier,'requires_confirmation':False,
                'message':f'Thiếu {shortage} kg NVL cho kế hoạch. Vẫn được xếp lịch; phải bổ sung nguồn, cấp và ký nhận trước khi chạy thực tế.'})
        r['material']={'required_kg':str(needed),'held_unissued_kg':str(held),'machine_accounted_kg':str(measured),
            'pending_handover_kg':str(pending),'shortage_kg':str(shortage),'machine_balance_as_of':aware(position['previous_end']),
            'machine_balance_certainty':'last_closed_shift_plus_signed_receipts'}
        per_sheet=requirement['weight']*(1+requirement['waste']/100)
        capacity_known=bool(r['materials'] or material_contexts[identifier]['lots'] or position['sources'])
        r['material']['max_plannable_sheets']=int((held+measured+pending)//per_sheet) if capacity_known else None
        r['material']['capacity_basis']='bound_unissued_plus_signed_balance_plus_pending_handover'
        r['material']['sources']=[{**s,'accounted_kg':str(kg)} for s,kg in zip(position['sources'],source_kg)]
        stock_fingerprints.append([identifier,position,material_contexts[identifier]['lots']]);context_runs.append(r)
    stop_context=[]
    for s in stops.values():
        r=virtual.get(s['run_id'])
        if r:stop_context.append({**s,'run_ended':r['status']==runs.ENDED,'machine_id':r['machine_id'],'line_ids':[i['order_line_id'] for i in r['items']]})
    labels=db.execute(select(OrderLine.id,OrderLine.product_id,OrderLine.order_id,OrderLine.unit,OrderLine.delivery_date,
        Order.po_number,Order.customer_id,Customer.name.label('customer_name'),Product.name.label('product_name'))
        .join(Order,Order.id==OrderLine.order_id).outerjoin(Customer,Customer.id==Order.customer_id)
        .outerjoin(Product,Product.id==OrderLine.product_id).where(OrderLine.id.in_([l.id for l in line_rows]))).mappings().all()
    context={'planning_now':planning_now,'reason_view':reason_view,'changed_runs':{c.id for c in configs},'line_labels':{r['id']:dict(r) for r in labels},'start':data.start,'end':data.end,'windows':spans,'actual':actual,'stops':stop_context,'warnings':warnings,
        'runs':context_runs,'lines':[{'id':l.id,'order_id':l.order_id,'unit':l.unit,'quantity':integer(l.quantity,l.id),
        'actual_finished_qty':sum(e['quantity'] for e in final_actual[l.id]),
        'actual_finished_at':max((e['at'] for e in final_actual[l.id]),default=None)} for l in line_rows]}
    # tuple keys in runtime streams are not JSON keys; fingerprint their ordered pairs explicitly.
    fingerprint={'request':data.model_dump(mode='json',exclude={'preview_hash','confirmations'}),'base':version,'reason_view':reason_view,
        'planning_floor':planning_now if any(r.get('future_only') and not r['policy'].get('ready_at') for r in context_runs) else None,
        'runs':list(virtual.values()),'windows':windows,'default':read_default(db),'stops':list(stops.values()),
        'actual':actual,'logs':fingerprints,'stock':stock_fingerprints,
        'lines':[[l.id,l.quantity,l.produced,l.unit] for l in line_rows],
        'machines':[[m.id,m.version,m.status,m.kind] for m in machines.values()]}
    source_hash=digest(fingerprint)
    try:result=calculate(context)
    except ScheduleError as error:
        from fastapi import HTTPException
        raise HTTPException(422,detail=error.detail) from error
    canonical={'start':data.start,'end':data.end,'order':queue,'jobs':[policies.get(i,JobPolicy(run_id=i).model_dump()) for i in queue]}

    snapshot_context={'schema_version':1,'runs':[virtual[i] for i in queue],
        'lines':{r['id']:dict(r) for r in labels},'default_calendar':read_default(db),
        'machines':[{'id':m.id,'name':m.name,'kind':m.kind,'status':m.status,'version':m.version,
            'calendar':m.calendar,'max_width_mm':m.max_width_mm,'max_pull_mm':m.max_pull_mm} for m in machines.values()],
        'availability':windows,'exceptions':[{'machine_id':e.machine_id,'day':e.day,'windows':e.windows,'note':e.note}
            for e in db.scalars(select(MachineCalendarException).where(MachineCalendarException.machine_id.in_(list(machine_ids)),
                MachineCalendarException.day.between(data.start.astimezone(ZONE).date(),data.end.astimezone(ZONE).date())))],
        'day':day_state}
    source_hash=digest([source_hash,snapshot_context])
    return {'preview_hash':source_hash,'base_version':version,'result':result,'warnings':warnings,
        '_configs':configs,'_stops':stops,'_canonical':canonical,'_original':original,'_snapshot_context':snapshot_context}


def preview(db,user,data):
    with db.no_autoflush:
        outcome=prepare(db,user,data)
    return {k:v for k,v in outcome.items() if not k.startswith('_')}


def save(db,user,data,*,reason_view=None):
    outcome=prepare(db,user,data,for_update=True,reason_view=reason_view)
    if outcome['preview_hash']!=data.preview_hash:
        from fastapi import HTTPException
        raise HTTPException(409,detail={'code':'PREVIEW_STALE','message':'Thời gian hiện tại hoặc dữ liệu/lịch máy đã đổi; tính lại và xác nhận mốc mới trước khi lưu.'})
    missing={w['code'] for w in outcome['warnings'] if w.get('requires_confirmation',True)}-set(data.confirmations)
    if missing:
        from fastapi import HTTPException
        raise HTTPException(409,detail={'code':'CONFIRMATION_REQUIRED','warnings':[w for w in outcome['warnings'] if w['code'] in missing]})
    for end in data.end_runs:runs.change_state(db,user,end.run_id,end)
    exclusions={c.id for c in outcome['_configs']}|{e.run_id for e in data.end_runs}
    for config in outcome['_configs']:
        runs.save_run(db,user,config,config.id if config.id in outcome['_original'] else None,exclude_run_ids=exclusions,scheduling=True)
    changed={c.id for c in outcome['_configs']}
    old=latest(db)
    old_policies={p['run_id']:p for p in old.request.get('jobs',[])} if old else {}
    affected=changed|set(data.unschedule)|{p.run_id for p in data.jobs if encoded(p.model_dump())!=old_policies.get(p.run_id)}
    for identifier in affected-changed:
        run=db.get(Run,identifier)
        if run:run.version+=1
    for patch in data.stops:
        value=outcome['_stops'][patch.id];row=db.get(RunStop,patch.id)
        if not row:row=RunStop(id=patch.id);db.add(row)
        for key in ['run_id','version','duration_seconds','hold_machine','enabled','note']:setattr(row,key,value[key])
        row.started_at=runs.local(value['at'])
        if row.enabled:
            from app.modules.production.sample_service import EPISODE,info,stamp
            from app.modules.production.models import ProductionSetup
            # A recorded stop bounds this actual episode permanently. Disabling
            # the stop later must not silently resurrect its sample clearance.
            for setup in db.scalars(select(ProductionSetup).where(ProductionSetup.production_order_id==row.run_id).with_for_update()):
                episode=info(setup)
                if not episode:continue
                opened=stamp(episode['opened_at']);until=stamp(episode['valid_until'])
                finish=row.started_at+timedelta(seconds=row.duration_seconds) if row.duration_seconds is not None else None
                if row.started_at<until and (row.started_at>=opened or finish is None or finish>opened):
                    setup.source={**setup.source,EPISODE:{**episode,'version':episode['version']+1,
                        'valid_until':max(opened,row.started_at).isoformat(),'bounded_by_stop':row.id}}
                    material.audit(db,user,'PRODUCTION_SAMPLE_BOUND_BY_STOP',setup.id,
                        {'stop_id':row.id,'previous_valid_until':episode['valid_until'],'stop_at':row.started_at.isoformat()})
    db.flush()
    # Same engine, now from committed-intent state; no duplicate action application.
    canonical=outcome['_canonical']
    clean=ScheduleInput.model_validate({'base_version':data.base_version,**encoded(canonical)})
    fresh=prepare(db,user,clean,for_update=True,reason_view=reason_view)
    identifier=str(uuid4());version=data.base_version+1
    result=encoded(fresh['result'])
    plan=SchedulePlan(id=identifier,version=version,request=encoded(canonical),result=result,
        source_hash=fresh['preview_hash'],created_by=user.id,context=encoded(fresh['_snapshot_context']))
    db.add(plan);db.flush()
    from app.modules.production.release_service import sync_assignments
    for affected_id in affected:
        run=db.get(Run,affected_id)
        if run:sync_assignments(db,user,run,plan,force=True)
    from app.modules.production import schedule_daily
    day=schedule_daily.update(db,user,plan,data)
    material.audit(db,user,'PRODUCTION_SCHEDULE_SAVE',identifier,{'version':version,'preview_hash':data.preview_hash,
        'stops':encoded(data.stops),'changed_runs':[c.id for c in outcome['_configs']],
        'ended_runs':[e.run_id for e in data.end_runs],'unscheduled':data.unschedule})
    db.flush()
    return {'id':identifier,'version':version,'result':result,'source_hash':fresh['preview_hash'],'day':day}
