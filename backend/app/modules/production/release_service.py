"""Release the existing LSX, retain immutable assignments and real machine evidence.

All mutations run under allocation_api.write's ERP lock/transaction.
"""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select,func,or_,and_
from sqlalchemy.dialects.mysql import insert
from app.core.models import Sequence
from app.modules.production.models import ProductionOrder as Run,FormingLog
from app.modules.production.run_models import ProductionOrderItem as Item,ProductionAssignment as Assignment,ShiftItem,DownstreamItem
from app.modules.production.planning_models import Machine
from app.modules.production.schedule_models import SchedulePlan
from app.modules.production.planning_service import ZONE
from app.modules.materials.inventory.allocation_service import fail,audit


def now():return datetime.now(ZONE).replace(tzinfo=None,microsecond=0)
def encoded(value):return jsonable_encoder(value,custom_encoder={Decimal:str})


def require_released(run):
    if not run or run.release_state!='released' or not run.released_at or not run.official_code:
        fail('LSX chưa phát hành hoặc là dữ liệu cũ chưa xác nhận phát hành.',409)


def historical_machine(log):
    """Never reconstruct old machine evidence from today's order header."""
    snap=log.shift_snapshot or {}
    return log.actual_machine_id or snap.get('actual_machine_id') or (snap.get('run_snapshot') or {}).get('machine_id')


def machine_expression():
    return func.coalesce(FormingLog.actual_machine_id,
        FormingLog.shift_snapshot['actual_machine_id'].as_string(),
        FormingLog.shift_snapshot['run_snapshot']['machine_id'].as_string())


def assignment(db,run_id,stage,line_id=None):
    return db.scalar(select(Assignment).where(Assignment.run_id==run_id,Assignment.stage==stage,
        Assignment.order_line_id==line_id,Assignment.ended_at.is_(None)).with_for_update())


def check_interval(db,run,stage,machine_id,start,end,line_id=None):
    require_released(run)
    row=assignment(db,run.id,stage,line_id)
    if not row or row.machine_id!=machine_id or start<row.started_at:
        fail('Khoảng nhật ký không thuộc phân công hiện hành; chốt đúng máy và sau thời điểm phân công.',409)
    if end>now():fail('Không ghi nhật ký tương lai.')
    return row


def forming_machine_busy(db,machine_id,excluding_run_id):
    """Closed episodes free the machine without ending their stable LSX.

    Legacy RUNNING headers without episode evidence remain conservative blockers.
    No planned start time or position participates in this check.
    """
    from app.modules.production.models import ProductionSetup
    from app.modules.production.sample_service import info,stamp
    from app.modules.production.run_service import released_runs
    others=list(db.scalars(select(Run).where(Run.machine_id==machine_id,Run.status=='Đang chạy',Run.id!=excluding_run_id)))
    if not others:return None
    legacy_released=released_runs(db)
    setups=list(db.scalars(select(ProductionSetup).where(ProductionSetup.production_order_id.in_([r.id for r in others]),
        ProductionSetup.stage=='Định hình').order_by(ProductionSetup.checked_at.desc(),ProductionSetup.source['run_version'].as_integer().desc(),ProductionSetup.id.desc())))
    latest={}
    for row in setups:latest.setdefault(row.production_order_id,row)
    for run in others:
        setup=latest.get(run.id);episode=info(setup) if setup else {}
        if episode and (episode.get('closed_at') or stamp(episode['valid_until'])<=now()):continue
        if not episode and run.id in legacy_released:continue
        return run.id
    return None


def sync_assignments(db,user,run,plan,*,force=False):
    if run.release_state!='released':return
    items=list(db.scalars(select(Item).where(Item.run_id==run.id,Item.enabled.is_(True))))
    scheduled=run.id in plan.request.get('order',[])
    desired={('forming',None):run.machine_id} if scheduled and run.status!='Đã kết thúc' else {}
    policy=next((p for p in plan.request.get('jobs',[]) if p['run_id']==run.id),{})
    for stage in policy.get('stages',[]):
        if scheduled and stage.get('machine_id') and stage['order_line_id'] in {i.order_line_id for i in items}:
            desired[(stage['stage'],stage['order_line_id'])]=stage['machine_id']
    current=list(db.scalars(select(Assignment).where(Assignment.run_id==run.id,Assignment.ended_at.is_(None)).with_for_update()))
    stamp=now()
    # A new version is also a boundary for quantities/configuration, even on the same machine.
    if any(r.stage=='forming' for r in current) and (force or any(desired.get((r.stage,r.order_line_id))!=r.machine_id for r in current)):
        last=db.scalar(select(func.max(FormingLog.shift_end)).where(FormingLog.production_order_id==run.id))
        if last and last>stamp:fail('Chốt ca máy cũ trước khi đổi phân công.',409)
    for row in current:
        key=(row.stage,row.order_line_id)
        if not force and desired.get(key)==row.machine_id:
            desired.pop(key);continue
        row.ended_at=stamp
    snapshot=encoded({'run_version':run.version,'run_snapshot':run.run_snapshot,
        'items':[{'order_line_id':i.order_line_id,'planned_qty':i.planned_qty,'completed_qty':i.completed_qty,
                  'cavity':i.cavity,'snapshot':i.snapshot} for i in items]})
    for (stage,line),machine in desired.items():
        m=db.get(Machine,machine)
        if not m or m.status not in {'ready','running'}:fail('Máy phân công chưa sẵn sàng.')
        if stage=='forming' and run.status=='Đang chạy':
            other=forming_machine_busy(db,machine,run.id)
            if other:fail('Máy đích đang chạy LSX khác.',409)
        db.add(Assignment(id=str(uuid4()),run_id=run.id,stage=stage,machine_id=machine,order_line_id=line,
            started_at=stamp,plan_id=plan.id,created_by=user.id,snapshot=snapshot))
    audit(db,user,'PRODUCTION_ASSIGNMENT_UPDATE',run.id,{'plan_id':plan.id,'run_version':run.version,
        'closed_assignment_ids':[r.id for r in current if r.ended_at is not None],
        'assigned':[{'stage':s,'order_line_id':ct,'machine_id':m} for (s,ct),m in desired.items()]})
    db.flush()


def release(db,user,identifier,data):
    from app.modules.production import run_service as runs
    run=runs.run_lock(db,identifier,data.version)
    if run.release_state=='released':return runs.detail(db,identifier)
    if run.status==runs.ENDED:fail('LSX đã kết thúc chỉ được xem lịch sử.',409)
    plan=db.scalar(select(SchedulePlan).order_by(SchedulePlan.version.desc()).limit(1))
    saved=next((r for r in (plan.context or {}).get('runs',[]) if r['id']==run.id),None) if plan else None
    if not saved or saved['version']!=run.version:
        fail('Cần tính thử và lưu kế hoạch hiện tại chứa LSX này trước khi Phát lệnh.',409)
    items=runs.run_items(db,run.id)
    if not items or all(i.completed_qty>=i.planned_qty for i in items):fail('LSX không còn thành phần được thực hiện.')
    stamp=now();day=stamp.strftime('%y%m%d');key='LSX_'+day
    db.execute(insert(Sequence).values(name=key,value=0).on_duplicate_key_update(name=key))
    sequence=db.scalar(select(Sequence).where(Sequence.name==key).with_for_update())
    sequence.value+=1
    run.official_code=f'{key}_{sequence.value:03d}'
    was_legacy=run.release_state=='legacy'
    run.released_at=stamp;run.released_by=user.id
    if not was_legacy:run.issued_at=stamp
    run.release_state='released'
    run.release_snapshot=encoded({'plan_id':plan.id,'plan_version':plan.version,'run':saved,
        'policy':next((p for p in plan.request.get('jobs',[]) if p['run_id']==run.id),{}),
        'released_at':stamp,'released_by':user.id,'note':data.note,'legacy_continuation':was_legacy})
    run.version+=1
    sync_assignments(db,user,run,plan,force=True)
    audit(db,user,'PRODUCTION_ORDER_RELEASE',run.id,{'official_code':run.official_code,'plan_id':plan.id,
        'version':run.version,'released_at':stamp.isoformat(),'note':data.note})
    db.flush();return runs.detail(db,identifier)


def history(db,identifier,page,size):
    query=select(Assignment).where(Assignment.run_id==identifier)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(Assignment.started_at.desc(),Assignment.id).offset((page-1)*size).limit(size))
    return {'items':[{'id':a.id,'stage':a.stage,'machine_id':a.machine_id,'order_line_id':a.order_line_id,
        'started_at':a.started_at,'ended_at':a.ended_at,'plan_id':a.plan_id,'created_by':a.created_by,
        'snapshot':a.snapshot} for a in rows],'total':total,'page':page,'size':size}


def create_setup(db,user,identifier,data):
    from app.modules.production import run_service as runs
    from app.modules.production.models import ProductionSetup
    run=runs.run_lock(db,identifier,data.run_version);require_released(run)
    if run.status==runs.ENDED and data.stage=='forming':fail('LSX đã kết thúc không được chạy mẫu định hình mới.',409)
    assigned=assignment(db,identifier,data.stage,data.order_line_id if data.stage!='forming' else None)
    if not assigned or assigned.machine_id!=data.machine_id:fail('Máy chạy mẫu không thuộc phân công hiện hành.',409)
    if data.stage=='forming' and forming_machine_busy(db,data.machine_id,run.id):
        fail('Máy định hình đang chạy LSX khác, chưa được chạy mẫu.',409)
    if db.get(ProductionSetup,data.id):fail('ID chạy mẫu đã tồn tại.',409)
    from app.modules.production.sample_service import close_preceding
    close_preceding(db,user,identifier,data.stage,getattr(data,'order_line_ids',[]) or ([data.order_line_id] if data.order_line_id else []),data.id)
    row=ProductionSetup(id=data.id,production_order_id=identifier,checked_at=now(),machine_id=data.machine_id,
        stage={'forming':'Định hình','cutting':'Cắt','edge':'Ép biên'}[data.stage],tool_id=data.tool_id or run.mold_id,
        cavity=run.cavity,result='',qc_id='',staff_id=user.id,note=data.note,
        source=encoded({'assignment_id':assigned.id,'run_version':run.version,'official_code':run.official_code,
            'run_snapshot':run.run_snapshot,'order_line_id':data.order_line_id}))
    db.add(row);run.version+=1
    audit(db,user,'PRODUCTION_SETUP_CREATE',row.id,{'run_id':run.id,'assignment_id':assigned.id,'note':data.note})
    db.flush();return {'id':row.id,'production_order_id':run.id,'official_code':run.official_code,
        'machine_id':row.machine_id,'assignment_id':assigned.id,'run_version':run.version}


def machine_queue(db,machine_id,stage,page,size):
    """Current assignment eligibility, independent of scheduled times and queue order."""
    query=select(Run,Item,Assignment).join(Item,Item.run_id==Run.id).join(Assignment,and_(Assignment.run_id==Run.id,
        or_(Assignment.order_line_id==Item.order_line_id,Assignment.order_line_id.is_(None))))
    query=query.where(Run.release_state=='released',Run.released_at.is_not(None),Run.official_code.is_not(None),
        Item.enabled.is_(True),Assignment.machine_id==machine_id,Assignment.stage==stage,Assignment.ended_at.is_(None))
    remaining=Item.planned_qty-Item.completed_qty
    if stage=='forming':query=query.where(Run.status.in_(['Chưa chạy','Đang chạy']),Item.completed_qty<Item.planned_qty)
    # Downstream eligibility comes from remaining measured upstream goods, not planned order quantities.
    if stage!='forming':
        query=query.where(Item.snapshot['route'].contains(stage))
        source=select(func.coalesce(func.sum(ShiftItem.good_qty),0)).join(FormingLog,FormingLog.id==ShiftItem.log_id).where(
            FormingLog.production_order_id==Run.id,ShiftItem.order_line_id==Item.order_line_id).correlate(Run,Item).scalar_subquery()
        if stage=='edge':
            cut=select(func.coalesce(func.sum(DownstreamItem.good_qty),0)).join(FormingLog,FormingLog.id==DownstreamItem.forming_log_id).where(
                FormingLog.production_order_id==Run.id,DownstreamItem.order_line_id==Item.order_line_id,
                DownstreamItem.stage=='cutting').correlate(Run,Item).scalar_subquery()
            from sqlalchemy import case
            source=case((Item.snapshot['route'].contains('cutting'),cut),else_=source)
        used=select(func.coalesce(func.sum(DownstreamItem.input_qty),0)).join(FormingLog,FormingLog.id==DownstreamItem.forming_log_id).where(
            FormingLog.production_order_id==Run.id,DownstreamItem.order_line_id==Item.order_line_id,
            DownstreamItem.stage==stage).correlate(Run,Item).scalar_subquery()
        query=query.where(source>used)
        remaining=source-used
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.add_columns(remaining.label('remaining')).order_by(Run.official_code,Item.order_line_id).offset((page-1)*size).limit(size)).all()
    return {'items':[{'run_id':r.id,'official_code':r.official_code,'run_version':r.version,'status':r.status,
        'order_line_id':i.order_line_id,'product_id':i.product_id,'planned_qty':i.planned_qty,'completed_qty':i.completed_qty,
        'remaining_qty':remaining,'assignment_id':a.id,
        'machine_id':a.machine_id,'stage':a.stage} for r,i,a,remaining in rows],'total':total,'page':page,'size':size}
