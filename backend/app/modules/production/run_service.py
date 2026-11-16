"""LSX is the stable run ID. Shared ERP lock/transaction is owned by API writes."""
from collections import defaultdict
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_CEILING
from uuid import uuid4
from sqlalchemy import select,func,or_,delete,inspect
from app.modules.materials.inventory import allocation_service as material
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation,AllocationMovement as Link
from app.modules.materials.inventory.models import FilmMovement
from app.modules.orders.models import OrderLine,Order
from app.modules.production.models import ProductionOrder as Run,FormingLog,CuttingLog,EBLog,ProductionWIP
from app.modules.production.planning_models import ProductionStandard as Standard,ProductionStandardItem as StandardItem,Machine
from app.modules.production.run_models import ProductionOrderItem as Item,RunMaterial,ShiftItem,ShiftMaterial,DownstreamItem
from app.modules.production.planning_service import calculate_sheet_weight,ZONE

PLANNED='Chưa chạy';RUNNING='Đang chạy';ENDED='Đã kết thúc'
ZERO=material.ZERO
D=material.decimal
fail=material.fail


def local(value):
    # Existing MySQL DATETIME/TIME columns have second precision. Truncate before
    # validating/storing so server rounding cannot move a close into the future.
    return value.astimezone(ZONE).replace(tzinfo=None,microsecond=0)


def run_lock(db,identifier,version=None,*,readonly=False):
    query=select(Run).where(Run.id==identifier)
    run=db.scalar(query if readonly else query.with_for_update())
    if not run or not run.run_snapshot:fail('Không tìm thấy lần chạy giai đoạn 3.',404)
    if version is not None and version!=run.version:fail('Lần chạy đã thay đổi. Tải lại trước khi ghi.',409)
    return run


def run_items(db,identifier,*,all_items=False):
    query=select(Item).where(Item.run_id==identifier)
    if not all_items:query=query.where(Item.enabled.is_(True))
    return db.scalars(query.order_by(Item.order_line_id)).all()


def boundary(items):
    products=defaultdict(lambda:[ZERO,ZERO])
    for item in items:
        products[item.product_id][0]+=item.planned_qty
        products[item.product_id][1]+=item.completed_qty
    return any(done>=planned for planned,done in products.values())


def released_runs(db):
    """A released machine may accept another run; the old run still owns its ID."""
    if not inspect(db.connection()).has_table('production_run_stops'):return set()
    from app.modules.production.schedule_models import RunStop
    return set(db.scalars(select(RunStop.run_id).where(RunStop.enabled.is_(True),
        RunStop.hold_machine.is_(False),RunStop.started_at<=datetime.now(ZONE).replace(tzinfo=None))))


def save_run(db,user,data,identifier=None,*,preview=False,exclude_run_ids=(),ending_run_ids=(),scheduling=False):
    if identifier:
        if data.version is None:fail('Sửa lần chạy cần version hiện tại.',409)
        run=run_lock(db,identifier,data.version,readonly=preview)
        if not scheduling and run.release_state!='draft':
            fail('LSX đã phát hành/dữ liệu cũ phải sửa qua cập nhật kế hoạch.',409)
        if not scheduling and inspect(db.connection()).has_table('production_schedule_plans'):
            from app.modules.production.schedule_models import SchedulePlan
            plan=db.scalar(select(SchedulePlan).order_by(SchedulePlan.version.desc()).limit(1))
            if plan and identifier in plan.request.get('order',[]):
                fail('Lần chạy đã có trong kế hoạch; dùng API tính thử/lưu lịch để sửa hoặc chuyển máy có xác nhận.',409)
        if run.id!=data.id:fail('Không đổi ID lần chạy.')
        if run.status==ENDED:fail('LSX đã kết thúc chỉ được xem lịch sử.',409)
    else:
        if db.get(Run,data.id):fail('ID lệnh/lần chạy đã tồn tại.',409)
        if data.version is not None:fail('Lần chạy mới không có version cũ.')
        run=Run(id=data.id,status=PLANNED,version=1,source={},release_state='draft')
    old_items={i.order_line_id:i for i in run_items(db,run.id,all_items=True)} if identifier else {}
    old_bindings={b.allocation_id:b for b in db.scalars(select(RunMaterial).where(RunMaterial.run_id==run.id))} if identifier else {}
    if identifier:
        from app.modules.materials.inventory.handover_models import MaterialHandover
        drafts=list(db.scalars(select(MaterialHandover).where(MaterialHandover.run_id==identifier,MaterialHandover.state.in_(['draft','awaiting_receipt']))))
        requested_ids={i.order_line_id for i in data.items};requested_bindings={m.allocation_id:m.kg for m in data.materials}
        for doc in drafts:
            if doc.snapshot['order_line_id'] not in requested_ids:fail('CTĐH còn phiếu bàn giao chưa xong; xử lý phiếu trước khi bỏ khỏi LSX.',409)
        quantities=defaultdict(lambda:ZERO)
        for doc in drafts:
            if doc.state=='draft' and doc.mode=='issue':quantities[doc.allocation_id]+=doc.quantity
        for aid,quantity in quantities.items():
            if aid not in old_bindings or requested_bindings.get(aid,ZERO)<old_bindings[aid].issued_kg+quantity:
                fail('Không giảm bố trí dưới lượng đã cấp và phiếu bàn giao nháp.',409)
    standard=db.get(Standard,data.standard_id)
    if not standard or not standard.active:fail('Chọn định mức đang áp dụng.')
    latest=db.scalar(select(func.max(Standard.revision)).where(Standard.code==standard.code))
    # An explicitly selected saved version is valid; historical snapshots stay immutable.
    query=select(Machine).where(Machine.id==data.machine_id)
    machine=db.scalar(query if preview else query.with_for_update())
    if not machine or machine.status not in {'ready','running'} or machine.kind not in {'automatic','semi_automatic'} or (standard.snapshot.get('machine') and machine.kind!=standard.snapshot['machine']['kind']):
        fail('Máy cần sử dụng được và cùng loại tuyến với cấu hình.')
    if data.parent_run_id:
        parent=run_lock(db,data.parent_run_id,readonly=preview)
        if (parent.status!=ENDED and parent.id not in ending_run_ids) or parent.id==run.id:fail('Lần chạy trước phải đã kết thúc.')
    params=dict(standard.parameters)
    for name in ['seconds_per_cycle','pull_mm','setup_minutes','waste_percent']:
        value=getattr(data,name)
        if value is not None:params[name]=value
    spec=dict(standard.snapshot['material']);mold=standard.snapshot['mold']
    if data.planning_material:
        spec.update(data.planning_material.model_dump())
        params['density']=data.planning_material.density;params['resin']=data.planning_material.resin
    if data.mold_geometry_confirmed is not None:params['mold_geometry_confirmed']=data.mold_geometry_confirmed
    params['film_width_mm']=data.film_width_mm or params.get('film_width_mm') or float(spec['width'])
    if data.planning_material and abs(float(params['film_width_mm'])-float(spec['width']))>0.0001:fail('Khổ màng phải khớp thông số vật liệu dự kiến của lần chạy.')
    if machine.max_width_mm and D(params['film_width_mm'])>machine.max_width_mm:fail('Khổ màng vượt máy.')
    if machine.max_pull_mm and D(params['pull_mm'])>machine.max_pull_mm:fail('Bước kéo vượt máy.')
    for tool in standard.snapshot.get('molds') or [mold]:
        if D(tool.get('Dai_Khuon') or 0)>D(params['pull_mm']) or D(tool.get('Rong_Khuon') or 0)>D(params['film_width_mm']):
            if not params.get('mold_geometry_confirmed'):fail('Khổ/kéo màng nhỏ hơn khuôn. Cần xác nhận thông số riêng của lần chạy.')
    geometry_changed=(D(params['pull_mm'])!=D(standard.parameters['pull_mm']) or
        D(params['film_width_mm'])!=D(standard.parameters.get('film_width_mm') or spec['width']))
    params['sheet_weight_kg']=(data.sheet_weight_kg if data.sheet_weight_kg is not None and not geometry_changed and data.planning_material is None else
        calculate_sheet_weight(params['pull_mm'],params['film_width_mm'],spec['thickness'],params['density']))
    source_items={i.product_id:i for i in db.scalars(select(StandardItem).where(StandardItem.standard_id==standard.id))}
    ids=sorted(i.order_line_id for i in data.items)
    query=select(OrderLine).where(OrderLine.id.in_(ids)).order_by(OrderLine.id)
    lines={l.id:l for l in db.scalars(query if preview else query.with_for_update())}
    if len(lines)!=len(ids):fail('Có CTĐH không tồn tại.')
    other_quantities=dict(db.execute(select(Item.order_line_id,func.sum(Item.planned_qty-Item.completed_qty))
        .join(Run,Run.id==Item.run_id).where(Item.order_line_id.in_(ids),Run.status.in_([PLANNED,RUNNING]),Item.run_id!=data.id)
        .where(Item.enabled.is_(True),~Item.run_id.in_(list(exclude_run_ids))).group_by(Item.order_line_id)).all())
    legacy_lines=set(db.scalars(select(Run.order_line_id).where(Run.order_line_id.in_(ids),Run.run_snapshot.is_(None),
        or_(Run.status.is_(None),~Run.status.in_([ENDED,'Hoàn thành','Hủy'])))))
    totals=defaultdict(lambda:ZERO);cavities={};snapshots={}
    for entry in data.items:
        line=lines[entry.order_line_id];template=source_items.get(line.product_id)
        if not template:fail(line.id+': sản phẩm không có trong định mức.')
        from app.modules.production.forming_units import is_piece_unit
        if not is_piece_unit(line.unit):fail(f'{line.id}: định hình nhập theo Cái/Chiếc; CTĐH đang dùng {line.unit}. Không tự quy đổi từ đơn vị bế.')
        if line.product_id in cavities and cavities[line.product_id]!=entry.cavity:fail('Cùng sản phẩm phải dùng chung cavity, không tính cavity riêng theo CTĐH.')
        cavities[line.product_id]=entry.cavity;totals[line.product_id]+=entry.quantity
        other=other_quantities.get(line.id,ZERO)
        completed=old_items[line.id].completed_qty if line.id in old_items else ZERO
        if entry.quantity<completed:fail(line.id+': mục tiêu không được nhỏ hơn sản lượng đã làm.',409)
        if D(line.produced)+D(other)+entry.quantity-completed>D(line.quantity):fail(line.id+': sản lượng đã được bố trí ở lần chạy khác.',409)
        if line.id in legacy_lines:fail(line.id+': cần đối soát lệnh cũ trước khi bố trí thêm.',409)
        snapshots[line.id]={**template.snapshot,'product_id':line.product_id,'unit':line.unit,'cavity':entry.cavity}
    remaining={product:qty-sum((i.completed_qty for i in old_items.values() if i.product_id==product and i.order_line_id in ids),ZERO) for product,qty in totals.items()}
    suggested=min((qty/D(cavities[product])).to_integral_value(rounding=ROUND_CEILING) for product,qty in remaining.items())
    old_params=run.run_snapshot.get('parameters',{}) if identifier and run.run_snapshot else {}
    limit=old_params.get('planned_cycles_limit')
    if data.planned_cycles is not None or limit is not None:
        actual_cycles=db.scalar(select(func.coalesce(func.sum(FormingLog.good+FormingLog.ng),0)).where(
            FormingLog.production_order_id==run.id,FormingLog.shift_snapshot.is_not(None))) if identifier else ZERO
        actual_cycles=D(actual_cycles)
        if data.planned_cycles is not None:
            limit=int(actual_cycles)+data.planned_cycles
        params['planned_cycles_limit']=int(limit);params['completed_cycles']=int(actual_cycles)
    from app.modules.production.schedule_engine import requirements,ScheduleError
    try:
        req=requirements([{'product_id':lines[e.order_line_id].product_id,'planned_qty':e.quantity,
            'completed_qty':old_items[e.order_line_id].completed_qty if e.order_line_id in old_items else 0,
            'cavity':e.cavity} for e in data.items],params,run.id)
    except ScheduleError as error:fail(str(error))
    cycles=D(req['cycles'])
    needed=(D(params['sheet_weight_kg'])*cycles*(1+D(params['waste_percent'])/100)).quantize(material.SCALE,rounding=ROUND_CEILING)
    query=select(Allocation).where(Allocation.id.in_([m.allocation_id for m in data.materials]))
    allocations={a.id:a for a in db.scalars(query if preview else query.with_for_update())}
    claimed=dict(db.execute(select(RunMaterial.allocation_id,func.sum(RunMaterial.planned_kg-RunMaterial.issued_kg))
        .join(Run,Run.id==RunMaterial.run_id).where(RunMaterial.allocation_id.in_(allocations),RunMaterial.run_id!=data.id,
            Run.status.in_([PLANNED,RUNNING]),~RunMaterial.run_id.in_(list(exclude_run_ids))).group_by(RunMaterial.allocation_id)).all())
    requested=defaultdict(lambda:ZERO);pending_allocations=[]
    for binding in data.materials:
        a=allocations.get(binding.allocation_id)
        historical=old_bindings.get(binding.allocation_id)
        if not a or (a.order_line_id not in ids and not (historical and historical.issued_kg>0 and binding.kg==historical.issued_kg)):
            fail('Phân bổ phải thuộc CTĐH trong LSX; nguồn cũ đã cấp chỉ được giữ nguyên phần đã cấp.')
        old=claimed.get(a.id,ZERO)
        issued=old_bindings[a.id].issued_kg if a.id in old_bindings else ZERO
        if binding.kg<issued:fail('Tổng bố trí không được nhỏ hơn phần đã cấp.',409)
        if binding.kg-issued+D(old)>a.held_kg:fail('Phần giữ đã dùng cho lần chạy khác hoặc không đủ.',409)
        if binding.kg>issued:
            requested[a.receipt_id]+=binding.kg-issued;pending_allocations.append(a.id)
    if any(b.issued_kg>0 and b.allocation_id not in {e.allocation_id for e in data.materials} for b in old_bindings.values()):
        fail('Không bỏ nguồn đã cấp khỏi LSX; giữ tổng đã cấp khi giải phóng phần còn lại.',409)
    if requested:
        balances=material.ensure_available(db,requested,own_allocation_ids=pending_allocations,order_line_ids=ids,lock=not preview)
        if any(b['material_id']!=standard.material_id for b in balances.values()):fail('Nguồn nhựa không khớp định mức.')
    snapshot={'standard_id':standard.id,'standard_code':standard.code,'standard_revision':standard.revision,
        'standard_snapshot':standard.snapshot,'planning_material':data.planning_material.model_dump() if data.planning_material else None,'parameters':params,'machine_id':machine.id,
        'machine_kind':machine.kind,'note':data.note,'group_confirmed':data.group_confirmed,
        'required_kg':str(needed),'planned_cycles':str(cycles)}
    if data.history_selection:
        from app.modules.production.history_schemas import HistoryQuery
        from app.modules.production.history_service import resolve
        query=HistoryQuery(standard_id=standard.id,machine_id=machine.id,pull_mm=params['pull_mm'],
            allocation_ids=[e.allocation_id for e in data.materials],
            items=[{'order_line_id':e.order_line_id,'cavity':e.cavity} for e in data.items])
        snapshot['history_applied']={**resolve(db,query,data.history_selection),
            'applied_parameters':dict(params),'selected_by':user.id}
    if preview:
        return {'id':data.id,'version':run.version+1 if identifier else 1,'machine_id':machine.id,
            'status':run.status,'release_state':run.release_state,'official_code':run.official_code,'snapshot':snapshot,'group_id':data.group_id,'standard_id':standard.id,
            'parent_run_id':data.parent_run_id,
            'items':[{'order_line_id':e.order_line_id,'product_id':lines[e.order_line_id].product_id,
                'planned_qty':e.quantity,'completed_qty':old_items[e.order_line_id].completed_qty if e.order_line_id in old_items else 0,'cavity':e.cavity,'snapshot':snapshots[e.order_line_id]} for e in data.items],
            'materials':[{'allocation_id':b.allocation_id,'planned_kg':str(b.kg),'issued_kg':str(old_bindings[b.allocation_id].issued_kg if b.allocation_id in old_bindings else 0)} for b in data.materials]}
    if identifier:
        for old in old_items.values():old.enabled=old.order_line_id in ids
        for old in old_bindings.values():
            if old.allocation_id not in {b.allocation_id for b in data.materials}:db.delete(old)
        run.version+=1
    else:db.add(run)
    first=data.items[0];line=lines[first.order_line_id]
    run.standard_id=standard.id
    run.group_id=data.group_id;run.order_line_id=first.order_line_id;run.product_id=line.product_id
    run.machine_id=machine.id;run.stage='Định hình + Cắt liền' if machine.kind=='automatic' else 'Định hình'
    run.material_id=standard.material_id;run.mold_id=standard.mold_id;run.parent_run_id=data.parent_run_id
    run.quantity=first.quantity;run.cavity=first.cavity
    if identifier:
        run.good=old_items[first.order_line_id].completed_qty if first.order_line_id in old_items else ZERO
        run.ng=db.scalar(select(func.coalesce(func.sum(ShiftItem.ng_qty),0)).join(FormingLog,FormingLog.id==ShiftItem.log_id)
            .where(FormingLog.production_order_id==run.id,ShiftItem.order_line_id==first.order_line_id))
    run.speed=D(params['seconds_per_cycle']);run.planned_sheets=cycles
    run.planned_hours=cycles*D(params['seconds_per_cycle'])/3600;run.setup_minutes=D(params['setup_minutes'])
    if not identifier:run.good=0;run.ng=0
    run.run_snapshot=snapshot
    db.flush()
    for entry in data.items:
        item=old_items.get(entry.order_line_id)
        if not item:
            item=Item(run_id=run.id,order_line_id=entry.order_line_id,product_id=lines[entry.order_line_id].product_id,completed_qty=0)
            db.add(item)
        item.enabled=True;item.planned_qty=entry.quantity;item.cavity=entry.cavity;item.snapshot=snapshots[entry.order_line_id]
    for binding in data.materials:
        row=old_bindings.get(binding.allocation_id)
        if not row:row=RunMaterial(run_id=run.id,allocation_id=binding.allocation_id,issued_kg=0);db.add(row)
        row.planned_kg=binding.kg
    material.audit(db,user,'PRODUCTION_RUN_SAVE',run.id,{'version':run.version,'note':data.note})
    db.flush();return detail(db,run.id)


def change_state(db,user,identifier,data,start=False,*,preview=False):
    run=run_lock(db,identifier,data.version,readonly=preview)
    if start:
        from app.modules.production.release_service import require_released,assignment
        require_released(run)
        assigned=assignment(db,run.id,'forming')
        if not assigned or assigned.machine_id!=run.machine_id:fail('LSX chưa có phân công định hình hiệu lực.',409)
        if run.status!=PLANNED:fail('Chỉ bắt đầu lần chạy chưa chạy.',409)
        machine=db.get(Machine,run.machine_id)
        if not machine or machine.status not in {'ready','running'}:fail('Máy chưa sẵn sàng.')
        from app.modules.production.release_service import forming_machine_busy
        other=forming_machine_busy(db,run.machine_id,run.id)
        if other:
            code=db.scalar(select(Run.official_code).where(Run.id==other)) or 'khác'
            fail('Máy đang thuộc đợt chưa đóng của LSX '+code+'. Đóng đợt đó trước khi chuyển LSX.',409)
        from app.modules.production.sample_service import gate
        gate(db,run.id,run.machine_id)
        if not preview:run.status=RUNNING
    else:
        if run.status==ENDED:fail('Lần chạy đã kết thúc.',409)
        from app.modules.materials.inventory.handover_models import MaterialHandover
        if db.scalar(select(MaterialHandover.id).where(MaterialHandover.run_id==identifier,MaterialHandover.state.in_(['draft','awaiting_receipt'])).limit(1)):
            fail('LSX còn phiếu bàn giao chưa xong; hủy nháp hoặc ký nhận trước khi kết thúc.',409)
        if run.status==RUNNING and not db.scalar(select(FormingLog.id).where(FormingLog.production_order_id==run.id).limit(1)):
            fail('Cần chốt ít nhất một ca trước khi kết thúc.')
        context=shift_context(db,run.id,readonly=preview)
        # A return awaiting warehouse acknowledgement is not a completed handover.
        from app.modules.materials.inventory.models import FilmMovement
        if db.scalar(select(FilmMovement.id).where(FilmMovement.production_order_id==run.id,
                FilmMovement.kind=='TRẢ NVL',FilmMovement.receiver_id=='').limit(1)):
            fail('Còn phiếu trả NVL chờ kho xác nhận; hoàn tất bàn giao trước khi kết thúc LSX.',409)
        if any(s['movements'] for s in context['sources']):fail('Còn cấp/trả chưa chốt vào ca; chốt ca trước khi kết thúc.')
        if any(D(lot['usable_kg'])!=ZERO or D(lot['legacy_accounting_kg'])!=ZERO for lot in context['lots']):
            fail('NVL còn số dư hoặc chưa đối soát theo lô; trả/chuyển và chốt nhật ký trước khi kết thúc LSX.',409)
        if not preview:run.status=ENDED
    if preview:return {'id':run.id,'version':run.version}
    run.version+=1
    if not start:
        from app.modules.production.run_models import ProductionAssignment
        from app.modules.production.release_service import now
        for a in db.scalars(select(ProductionAssignment).where(ProductionAssignment.run_id==run.id,
                ProductionAssignment.stage=='forming',ProductionAssignment.ended_at.is_(None))):a.ended_at=now()
    material.audit(db,user,'PRODUCTION_RUN_START' if start else 'PRODUCTION_RUN_END',run.id,{'note':data.note,'version':run.version})
    db.flush();return detail(db,identifier)


def shift_context(db,identifier,exclude_log=None,until=None,*,readonly=False):
    run=run_lock(db,identifier,readonly=readonly)
    from app.modules.materials.inventory.handover_sources import source_contexts
    return {**source_contexts(db,[identifier],exclude_log=exclude_log,until=until)[identifier],'run_version':run.version}


def save_shift(db,user,identifier,data,edit_id=None):
    run=run_lock(db,identifier,data.run_version)
    from app.modules.production.release_service import check_interval,machine_expression
    if run.status!=RUNNING:fail('Chỉ chốt/sửa ca của lần chạy đang chạy.',409)
    start,end=local(data.start),local(data.end)
    if end<=start:fail('Khoảng ca cần ít nhất 1 giây theo độ chính xác nhật ký.')
    assigned=check_interval(db,run,'forming',run.machine_id,start,end)
    if data.assignment_id and data.assignment_id!=assigned.id:fail('Phân công máy đã thay đổi; nạp lại nhật ký.',409)
    if (data.pure_seconds or 0)+(data.setup_seconds or 0)>(end-start).total_seconds():fail('Setup và chạy thuần vượt khoảng ca sau chuẩn hóa giây.')
    if end>datetime.now(ZONE).replace(tzinfo=None):fail('Không chốt ca trong tương lai.')
    previous=None
    if edit_id:
        previous=db.get(FormingLog,edit_id)
        if not previous or previous.production_order_id!=identifier or previous.id!=data.id:fail('Không tìm thấy ca.',404)
        if previous.version!=data.version:fail('Ca đã thay đổi.',409)
        if previous.assignment_id!=assigned.id:fail('Ca thuộc phiên bản phân công cũ, không sửa ngược sau cập nhật kế hoạch.',409)
        latest=db.scalar(select(FormingLog.id).where(FormingLog.production_order_id==identifier).order_by(FormingLog.shift_end.desc(),FormingLog.id.desc()).limit(1))
        if latest!=edit_id:fail('Không sửa ca cũ khi đã có ca sau; cần đối soát chuỗi số dư.',409)
        if db.scalar(select(DownstreamItem.id).where(DownstreamItem.forming_log_id==edit_id).limit(1)):
            fail('Ca đã được công đoạn sau sử dụng; không sửa ngược nguồn.',409)
    elif db.get(FormingLog,data.id):fail('ID nhật ký đã tồn tại.',409)
    latest_end=db.scalar(select(func.max(FormingLog.shift_end)).where(FormingLog.production_order_id==identifier,
        FormingLog.id!=(edit_id or '')))
    if latest_end and start<latest_end:fail('Ca chồng lấn hoặc chen vào ca đã chốt; chưa hỗ trợ nhập bù giữa chuỗi nhật ký.',409)
    context=shift_context(db,identifier,exclude_log=edit_id,until=end)
    from app.modules.materials.inventory.handover_sources import source_hash
    if data.source_hash and data.source_hash!=source_hash(context):fail('Nguồn NVL đã thay đổi; nạp lại và kiểm tra số kiểm đếm trước khi lưu.',409)
    items=run_items(db,identifier);by_line={i.order_line_id:i for i in items}
    if {i.order_line_id for i in data.items}!=set(by_line):fail('Ca phải có đủ các CTĐH của lần chạy.')
    old={i.order_line_id:i for i in db.scalars(select(ShiftItem).where(ShiftItem.log_id==edit_id)).all()} if edit_id else {}
    if not edit_id and boundary(items) and data.good_sheets+data.ng_sheets>0:
        fail('Một sản phẩm đã đủ: cập nhật kế hoạch/thành phần ghép trước khi tiếp tục cùng LSX.',409)
    cycles=data.good_sheets+data.ng_sheets
    from app.modules.production.sample_service import gate
    sample_basis=gate(db,identifier,run.machine_id,setup_id=data.setup_id or (previous.setup_id if previous else None),
        start=start,end=end,line_ids=by_line,edit_id=edit_id,require_material=cycles>0)
    if data.sample_qc_id and (data.sample_qc_id!=sample_basis['qc_id'] or data.sample_qc_version!=sample_basis['qc_version']):
        fail('Phiếu mẫu căn cứ đã thay đổi; nạp lại trước khi lưu.',409)
    if previous and (previous.shift_snapshot or {}).get('production_sample_v1')!=sample_basis:
        fail('Không đổi phiếu mẫu căn cứ của nhật ký đã ghi; chưa hỗ trợ hồi tố nhật ký cũ thiếu căn cứ.',409)
    if cycles and inspect(db.connection()).has_table('production_run_stops'):
        from app.modules.production.schedule_models import RunStop
        for stop in db.scalars(select(RunStop).where(RunStop.run_id==identifier,RunStop.enabled.is_(True),RunStop.started_at<end)):
            finish=stop.started_at+timedelta(seconds=stop.duration_seconds) if stop.duration_seconds is not None else None
            if finish is None or finish>start:fail('Ca có sản lượng chồng khoảng dừng/giải phóng máy; cập nhật dừng trước khi chốt.',409)
    # A diary interval belongs to one machine and one LSX, including recorded rest.
    conflicting=db.scalar(select(FormingLog.id).where(
        FormingLog.id!=(edit_id or ''),FormingLog.shift_start<end,FormingLog.shift_end>start,
        or_(machine_expression()==run.machine_id,FormingLog.production_order_id==identifier)).limit(1))
    if conflicting:fail('Ca chồng máy với nhật ký '+conflicting,409)
    unknown=db.scalar(select(FormingLog.id).where(FormingLog.id!=(edit_id or ''),
        FormingLog.run_date>=start.date(),FormingLog.run_date<=end.date(),
        or_(FormingLog.shift_start.is_(None),FormingLog.shift_end.is_(None)),
        or_(machine_expression()==run.machine_id,FormingLog.production_order_id==identifier)).limit(1))
    if unknown:fail('Nhật ký cũ cùng máy/LSX thiếu khoảng giờ: '+unknown+'. Cần đối soát trước khi ghi chồng ngày.',409)
    if cycles<=0 and any(i.good or i.ng for i in data.items):fail('Sản lượng không thể có khi chưa có chu kỳ.')
    per_product=defaultdict(int)
    for entry in data.items:
        item=by_line[entry.order_line_id];old_good=old[entry.order_line_id].good_qty if old else ZERO
        if item.completed_qty-old_good+entry.good>item.planned_qty:fail(entry.order_line_id+': sản lượng tốt vượt phần đã bố trí.')
        per_product[item.product_id]+=entry.good+entry.ng
    for product,qty in per_product.items():
        cavity=next(i.cavity for i in items if i.product_id==product)
        if qty!=cycles*cavity:fail(product+': tổng tốt + NG phải bằng chu kỳ × cavity sản phẩm.')
    inputs={s.receipt_id:s for s in data.sources};expected={s['receipt_id']:s for s in context['sources']}
    if set(inputs)!=set(expected):fail('Cần chốt đủ và đúng các nguồn nhựa từ sổ cấp/trả và ca trước.')
    balances=[]
    for receipt,row in expected.items():
        entry=inputs[receipt];available=D(row['opening_kg'])+D(row['input_kg'])-D(row['output_kg'])
        if available<0:fail(receipt+': trả/chuyển ra vượt số mang sang và cấp thêm.')
        consumed=entry.consumed_kg if entry.consumed_kg is not None else available-entry.closing_kg
        closing=entry.closing_kg if entry.closing_kg is not None else available-consumed
        if consumed<0 or closing<0 or available-consumed!=closing:fail(receipt+': phương trình cân đối không khớp.')
        balances.append((receipt,row,consumed,closing))
    if cycles>0 and (not balances or sum(b[2] for b in balances)<=0):fail('Có sản lượng cần ghi nhận tiêu hao theo nguồn.')
    log=previous or FormingLog(id=data.id,production_order_id=identifier,source={},version=1)
    if previous:
        db.execute(delete(ShiftItem).where(ShiftItem.log_id==edit_id));db.execute(delete(ShiftMaterial).where(ShiftMaterial.log_id==edit_id));log.version+=1
    else:db.add(log)
    log.shift_start=start;log.shift_end=end;log.start_time=start.time();log.end_time=end.time();log.run_date=start.date()
    log.actual_machine_id=run.machine_id;log.assignment_id=assigned.id
    if sample_basis:log.setup_id=sample_basis['setup_id']
    log.good=data.good_sheets;log.ng=data.ng_sheets
    log.speed=D(data.seconds_per_cycle) if data.seconds_per_cycle is not None else None
    log.film_pull=D(data.pull_mm) if data.pull_mm is not None else None
    log.sheet_weight=D(data.sheet_weight_kg)*1000 if data.sheet_weight_kg is not None else None
    log.staff_id=user.id;log.note=data.note;log.mold_id=run.mold_id
    log.movement_id='';log.cavity=run.cavity
    log.shift_snapshot={'handover_source_version':1,'run_version':run.version,'run_snapshot':run.run_snapshot,'actual_machine_id':run.machine_id,
        'assignment_id':assigned.id,'items':{i.order_line_id:i.snapshot for i in items},'parameters':{
        'seconds_per_cycle':data.seconds_per_cycle,'pull_mm':data.pull_mm,'sheet_weight_kg':data.sheet_weight_kg},
        'cycles':cycles,'note':data.note,'pure_seconds':data.pure_seconds,'setup_seconds':data.setup_seconds}
    db.flush()
    touched_orders=set()
    if sample_basis:log.shift_snapshot={**log.shift_snapshot,'production_sample_v1':sample_basis}
    lines={line.id:line for line in db.scalars(select(OrderLine).where(OrderLine.id.in_(by_line)).order_by(OrderLine.id).with_for_update())}
    for entry in data.items:
        item=by_line[entry.order_line_id];delta=D(entry.good)-(old[entry.order_line_id].good_qty if old else ZERO)
        line=lines[entry.order_line_id]
        if D(line.produced)+delta<0 or D(line.produced)+delta>D(line.quantity):fail('Sản lượng CTĐH không hợp lệ sau điều chỉnh.',409)
        line.produced=D(line.produced)+delta;item.completed_qty+=delta;touched_orders.add(line.order_id)
        db.add(ShiftItem(log_id=log.id,order_line_id=entry.order_line_id,good_qty=entry.good,ng_qty=entry.ng))
    for order in db.scalars(select(Order).where(Order.id.in_(touched_orders)).order_by(Order.id).with_for_update()):order.version+=1
    for receipt,row,consumed,closing in balances:
        db.add(ShiftMaterial(log_id=log.id,receipt_id=receipt,opening_kg=D(row['opening_kg']),input_kg=D(row['input_kg']),
            output_kg=D(row['output_kg']),consumed_kg=consumed,closing_kg=closing,movements=row['movements']))
    db.flush()
    run.good=by_line[run.order_line_id].completed_qty
    run.ng=db.scalar(select(func.coalesce(func.sum(ShiftItem.ng_qty),0)).join(FormingLog,FormingLog.id==ShiftItem.log_id)
        .where(FormingLog.production_order_id==identifier,ShiftItem.order_line_id==run.order_line_id));run.version+=1
    material.audit(db,user,'PRODUCTION_SHIFT_EDIT' if previous else 'PRODUCTION_SHIFT_CLOSE',log.id,{'run_id':identifier,'note':data.note})
    db.flush();return shift_detail(db,log.id)


def shift_detail(db,identifier):
    log=db.get(FormingLog,identifier)
    if not log or not log.shift_snapshot:fail('Không tìm thấy nhật ký ca mới.',404)
    from app.modules.production.release_service import historical_machine
    owner=db.get(Run,log.production_order_id)
    return {'id':log.id,'run_id':log.production_order_id,'version':log.version,'start':log.shift_start.replace(tzinfo=ZONE),
        'official_code':owner.official_code if owner else None,
        'actual_machine_id':historical_machine(log),'assignment_id':log.assignment_id,
        'setup_id':log.setup_id,'sample_basis':(log.shift_snapshot or {}).get('production_sample_v1'),
        'end':log.shift_end.replace(tzinfo=ZONE),'good_sheets':log.good,'ng_sheets':log.ng,'snapshot':log.shift_snapshot,
        'items':[{'order_line_id':i.order_line_id,'good':i.good_qty,'ng':i.ng_qty} for i in db.scalars(select(ShiftItem).where(ShiftItem.log_id==identifier))],
        'sources':[{'receipt_id':s.receipt_id,**{k:str(getattr(s,k)) for k in ['opening_kg','input_kg','output_kg','consumed_kg','closing_kg']},
                    'movements':s.movements} for s in db.scalars(select(ShiftMaterial).where(ShiftMaterial.log_id==identifier))]}


def detail(db,identifier):
    run=run_lock(db,identifier);items=run_items(db,identifier,all_items=True)
    bindings=db.scalars(select(RunMaterial).where(RunMaterial.run_id==identifier)).all()
    return {'id':run.id,'official_code':run.official_code,'release_state':run.release_state,
        'released_at':run.released_at,'released_by':run.released_by,'release_snapshot':run.release_snapshot,
        'group_id':run.group_id,'machine_id':run.machine_id,'standard_id':run.standard_id,
        'status':run.status,'version':run.version,'parent_run_id':run.parent_run_id,'snapshot':run.run_snapshot,
        'can_continue':run.status!=ENDED and not boundary([i for i in items if i.enabled]),
        'planned_cycles':run.planned_sheets,'planned_hours':run.planned_hours,
        'items':[{'order_line_id':i.order_line_id,'product_id':i.product_id,'planned_qty':i.planned_qty,
            'completed_qty':i.completed_qty,'cavity':i.cavity,'snapshot':i.snapshot,'enabled':i.enabled} for i in items],
        'materials':[{'allocation_id':m.allocation_id,'planned_kg':str(m.planned_kg),'issued_kg':str(m.issued_kg)} for m in bindings],
        'material_shortage_kg':str(max(ZERO,D(run.run_snapshot['required_kg'])-sum((m.planned_kg for m in bindings),ZERO)))}


def save_downstream(db,user,data):
    log=db.get(FormingLog,data.forming_log_id)
    if not log or not log.shift_snapshot:fail('DH_ID phải là ID nhật ký hút có chi tiết sản phẩm/CTĐH.',422)
    run=run_lock(db,log.production_order_id)
    from app.modules.production.release_service import require_released,check_interval
    require_released(run)
    start,end=local(data.start),local(data.end)
    if end<=start:fail('Khoảng công đoạn cần ít nhất 1 giây theo độ chính xác nhật ký.')
    from app.modules.production.sample_service import gate
    sample_basis=gate(db,run.id,data.machine_id,data.stage,data.setup_id,start=start,end=end,
        line_ids=[i.order_line_id for i in data.items])
    from app.modules.production.sample_service import info as sample_episode
    from app.modules.production.models import ProductionSetup
    if sample_episode(db.get(ProductionSetup,sample_basis['setup_id'])).get('source_forming_log_id')!=log.id:
        fail('Nhật ký công đoạn không khớp nguồn hàng của đợt kiểm mẫu.',409)
    assigned={e.order_line_id:check_interval(db,run,data.stage,data.machine_id,start,end,e.order_line_id) for e in data.items}
    if (data.pure_seconds or 0)+(data.setup_seconds or 0)>(end-start).total_seconds():fail('Setup và chạy thuần vượt khoảng công đoạn sau chuẩn hóa giây.')
    if start<log.shift_end or end>datetime.now(ZONE).replace(tzinfo=None):fail('Công đoạn sau phải sau ca hút đã chốt, không ghi tương lai.')
    machine=db.get(Machine,data.machine_id)
    if not machine or machine.kind!=data.stage or machine.status not in {'ready','running'}:fail('Chọn máy đúng công đoạn và sử dụng được.')
    from app.modules.production.schedule_actual import read as read_actual,stamp
    existing=read_actual(db,start=start.replace(tzinfo=ZONE),end=end.replace(tzinfo=ZONE),machine_id=machine.id)
    for row in existing['records']:
        if not row['start'] or not row['end']:fail('Máy có nhật ký thiếu giờ trong phạm vi này; đối soát trước khi ghi.',409)
        if stamp(row['start'])<end.replace(tzinfo=ZONE) and stamp(row['end'])>start.replace(tzinfo=ZONE):
            fail('Công đoạn chồng thời gian máy với nhật ký '+row['id']+'. Ghi chung một nhật ký nếu cùng lô chạy ghép.',409)
    if data.wip_id:
        wip=db.get(ProductionWIP,data.wip_id)
        if not wip or wip.forming_log_id!=log.id:fail('WIP không thuộc nhật ký hút nguồn.')
    model=CuttingLog if data.stage=='cutting' else EBLog
    if db.get(model,data.id):fail('ID nhật ký công đoạn đã tồn tại.',409)
    source={i.order_line_id:i for i in db.scalars(select(ShiftItem).where(ShiftItem.log_id==log.id))}
    items={i.order_line_id:i for i in run_items(db,run.id)}
    processed={(ct,stage):(D(used),D(good)) for ct,stage,used,good in db.execute(select(DownstreamItem.order_line_id,
        DownstreamItem.stage,func.sum(DownstreamItem.input_qty),func.sum(DownstreamItem.good_qty))
        .where(DownstreamItem.forming_log_id==log.id).group_by(DownstreamItem.order_line_id,DownstreamItem.stage))}
    for entry in data.items:
        original=source.get(entry.order_line_id);item=items.get(entry.order_line_id)
        product=(log.shift_snapshot.get('items') or {}).get(entry.order_line_id,item.snapshot if item else {})
        if not original or not item or data.stage not in product.get('route',[]):fail('CTĐH/công đoạn không thuộc tuyến nguồn.')
        capacity=original.good_qty
        if data.stage=='edge' and 'cutting' in product['route']:
            capacity=processed.get((entry.order_line_id,'cutting'),(ZERO,ZERO))[1]
        used=processed.get((entry.order_line_id,data.stage),(ZERO,ZERO))[0]
        if entry.good+entry.ng<=0 or D(used)+entry.good+entry.ng>D(capacity):fail('Công đoạn sau vượt sản lượng nguồn còn lại.',409)
    result=model(id=data.id,order_ref=log.id,run_date=start.date(),machine_id=machine.id,wip_id=data.wip_id,
        good=data.items[0].good if len(data.items)==1 else None,
        ng=data.items[0].ng if len(data.items)==1 else None,start_time=start.time(),end_time=end.time(),
        staff_id=user.id,note=data.note,setup_id=sample_basis['setup_id'],source={'production_sample_v1':sample_basis})
    db.add(result);db.flush()
    for entry in data.items:
        db.add(DownstreamItem(id=str(uuid4()),cut_id=result.id if data.stage=='cutting' else None,
            edge_id=result.id if data.stage=='edge' else None,forming_log_id=log.id,order_line_id=entry.order_line_id,
            stage=data.stage,input_qty=entry.good+entry.ng,good_qty=entry.good,ng_qty=entry.ng,
            snapshot={'run_id':run.id,'group_id':run.group_id,'assignment_id':assigned[entry.order_line_id].id,
                      'product':(log.shift_snapshot.get('items') or {}).get(entry.order_line_id,items[entry.order_line_id].snapshot),
                      'source_shift_version':log.version,'start':start.replace(tzinfo=ZONE).isoformat(),'end':end.replace(tzinfo=ZONE).isoformat(),
                      'pure_seconds':data.pure_seconds,'setup_seconds':data.setup_seconds}))
    material.audit(db,user,'PRODUCTION_DOWNSTREAM',result.id,{'stage':data.stage,'DH_ID':log.id,'note':data.note})
    return {'id':result.id,'stage':data.stage,'DH_ID':log.id,'run_id':run.id}


def before_issue(db,a,run,kg):
    from app.modules.production.release_service import require_released
    require_released(run)
    if not run.run_snapshot:return
    if run.status==ENDED:fail('Không cấp thêm vào lần chạy đã kết thúc.')
    item=db.get(Item,(run.id,a.order_line_id))
    if not item or not item.enabled or item.completed_qty>=item.planned_qty:fail('CTĐH không còn được cấp để thực hiện trong LSX.')
    binding=db.get(RunMaterial,(run.id,a.id))
    if not binding or kg>binding.planned_kg-binding.issued_kg:fail('Phần nhựa chưa được bố trí hoặc vượt phần bố trí cho lần chạy.',409)
    binding.issued_kg+=kg


def bind_material(db,user,identifier,data):
    run=run_lock(db,identifier,data.version)
    if run.release_state!='draft':fail('Nguồn LSX đã phát hành/dữ liệu cũ phải đổi qua cập nhật kế hoạch.',409)
    if run.status==ENDED:fail('Lần chạy đã kết thúc.',409)
    a=material.allocation_lock(db,data.allocation_id)
    if not db.get(Item,(identifier,a.order_line_id)):fail('Nguồn giữ không thuộc CTĐH trong lần chạy.')
    binding=db.get(RunMaterial,(identifier,a.id))
    issued=binding.issued_kg if binding else ZERO
    if data.planned_kg<issued:fail('Tổng bố trí không được nhỏ hơn phần đã cấp.')
    outstanding=data.planned_kg-issued
    claimed=db.scalar(select(func.coalesce(func.sum(RunMaterial.planned_kg-RunMaterial.issued_kg),0)).join(Run,Run.id==RunMaterial.run_id)
        .where(RunMaterial.allocation_id==a.id,RunMaterial.run_id!=identifier,Run.status.in_([PLANNED,RUNNING])))
    if outstanding+D(claimed)>a.held_kg:fail('Phần giữ đã dùng cho lần chạy khác hoặc không đủ.',409)
    balances=material.ensure_available(db,{a.receipt_id:outstanding},own_allocation_ids=[a.id],order_line_id=a.order_line_id)
    if balances[a.receipt_id]['material_id']!=run.material_id:fail('Nguồn không đúng vật liệu lần chạy.')
    if not binding:binding=RunMaterial(run_id=identifier,allocation_id=a.id,issued_kg=0);db.add(binding)
    binding.planned_kg=data.planned_kg;run.version+=1
    material.audit(db,user,'PRODUCTION_RUN_MATERIAL',identifier,{'allocation_id':a.id,'planned_kg':str(data.planned_kg),'note':data.note})
    db.flush();return detail(db,identifier)


def protect_hold(db,a,new_held):
    committed=db.scalar(select(func.coalesce(func.sum(RunMaterial.planned_kg-RunMaterial.issued_kg),0))
        .join(Run,Run.id==RunMaterial.run_id).where(RunMaterial.allocation_id==a.id,Run.status.in_([PLANNED,RUNNING])))
    if new_held<D(committed):fail('Phần giữ đang được bố trí cho lần chạy; sửa/kết thúc lần chạy trước.',409)


def transfer_binding(db,run_id,allocation_id,kg):
    run=db.get(Run,run_id)
    if run and run.run_snapshot:
        if run.status==ENDED:fail('Không chuyển vào lần chạy đã kết thúc.')
        db.add(RunMaterial(run_id=run.id,allocation_id=allocation_id,planned_kg=kg,issued_kg=0));db.flush()


def source_position(db,run_id,receipt_id,*,legacy=False):
    """Last measured closing plus unrecorded movements; labelled as-of last closed shift."""
    run=db.get(Run,run_id)
    if not run or not run.run_snapshot:return None
    context=shift_context(db,run_id)
    rows=[s for s in context['legacy_sources' if legacy else 'sources'] if s['receipt_id']==receipt_id]
    stamp=context['legacy_previous_end'] if legacy else context['previous_end']
    return {'kg':sum((D(r['opening_kg'])+D(r['input_kg'])-D(r['output_kg']) for r in rows),ZERO),'as_of':stamp}
