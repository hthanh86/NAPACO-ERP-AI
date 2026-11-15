"""Machine-first entry built on run_service.save_shift and its existing details.

All mutations belong to allocation_api.write's shared lock/transaction. Planning
parameters are reference-only; unknown actual measures remain NULL.
"""
from datetime import datetime,time
from fastapi import HTTPException
from sqlalchemy import select,func,literal_column
from app.auth.models import User
from app.modules.production import run_service as runs,release_service as release,sample_service as samples
from app.modules.production.run_schemas import ShiftInput,VersionInput
from app.modules.production.sample_schemas import SampleVersion
from app.modules.production.models import ProductionOrder as Run,ProductionSetup as Setup,FormingLog
from app.modules.production.run_models import ShiftItem,DownstreamItem
from app.modules.production.planning_models import Machine
from app.modules.production.calendar_settings import effective_week,read_default
from app.modules.materials.inventory.handover_sources import source_contexts,source_hash
from app.modules.materials.inventory.allocation_service import fail,audit


def calendar(db,machine):
    common=read_default(db)
    return {'default_version':common['version'],'weekly':effective_week(db,machine,common),
        'basis':'configured_reference_only','splits_diary':False}


def machine(db,identifier):
    row=db.get(Machine,identifier)
    if not samples.machine_matches(row,'forming'):fail('Chọn máy định hình đang sử dụng được.',409)
    return row


def episode_choices(db,run_id,machine_id):
    # Only a paginated history screen loads old episodes; the entry form needs
    # this assignment's episodes and all checks are repeated on save.
    rows=db.scalars(select(Setup).where(Setup.production_order_id==run_id,Setup.machine_id==machine_id,
        Setup.stage=='Định hình').order_by(Setup.checked_at.desc(),Setup.source['run_version'].as_integer().desc(),Setup.id.desc()).limit(101)).all()
    items=[{'id':s.id,**release.encoded(samples.info(s))} for s in rows[:100] if samples.info(s)]
    return {'items':items,'has_more':len(rows)>100}


def context(db,run_id,machine_id,setup_id=None,until=None,edit_id=None,since=None):
    current=machine(db,machine_id);run=runs.run_lock(db,run_id,readonly=True);release.require_released(run)
    if run.status==runs.ENDED:fail('LSX đã kết thúc chỉ xem lịch sử.',409)
    assigned=release.assignment(db,run_id,'forming')
    if not assigned or assigned.machine_id!=machine_id or run.machine_id!=machine_id:fail('LSX không còn gán cho máy đã chọn.',409)
    latest=db.execute(select(FormingLog.id,FormingLog.shift_end).where(FormingLog.production_order_id==run_id)
        .order_by(FormingLog.shift_end.desc(),FormingLog.id.desc()).limit(1)).first()
    previous=None
    if edit_id:
        previous=db.get(FormingLog,edit_id)
        if not previous or previous.production_order_id!=run_id or not previous.shift_snapshot:fail('Không tìm thấy nhật ký mới cần sửa.',404)
        if not previous.shift_snapshot.get(samples.SAMPLE):fail('Chưa hỗ trợ sửa nhật ký lịch sử thiếu phiếu mẫu căn cứ.',409)
        if not latest or latest.id!=edit_id:fail('Chỉ sửa nhật ký cuối; chưa hỗ trợ sửa giữa chuỗi cân đối.',409)
        if previous.assignment_id!=assigned.id or previous.actual_machine_id!=machine_id:fail('Nhật ký thuộc phân công/máy cũ, chưa hỗ trợ sửa sau chuyển máy.',409)
        if db.scalar(select(DownstreamItem.id).where(DownstreamItem.forming_log_id==edit_id).limit(1)):
            fail('Nhật ký đã được cắt/ép biên sử dụng; chưa hỗ trợ sửa ngược nguồn.',409)
        setup_id=previous.setup_id
    choices=episode_choices(db,run_id,machine_id)
    if not setup_id and choices['items']:setup_id=choices['items'][0]['id']
    setup=samples.setup_lock(db,setup_id) if setup_id else None
    if setup and (setup.production_order_id!=run_id or setup.machine_id!=machine_id):fail('Đợt chạy không thuộc LSX/máy đã chọn.',409)
    cutoff=runs.local(until) if until else release.now()
    if cutoff>release.now():fail('Giờ kết thúc đang ở tương lai.')
    if since and runs.local(since)>=cutoff:fail('Giờ kết thúc cần sau giờ bắt đầu.')
    material=source_contexts(db,[run_id],exclude_log=edit_id,until=cutoff)[run_id]
    reconciliation_only=bool(latest and material['sources'] and all(runs.D(lot['usable_kg'])==0 for lot in material['lots']))
    today=release.now().date()
    start_default=release.now()
    if previous:start_default=previous.shift_start
    elif latest and latest.shift_end and latest.shift_end.date()==today:start_default=latest.shift_end
    elif setup and setup.checked_at and setup.checked_at.date()==today:start_default=setup.checked_at
    start_default=max(start_default,assigned.started_at,datetime.combine(today,time.min)) if not previous else start_default
    basis=None;blocked='Chưa có đợt chạy mẫu đúng máy. Mở đợt và ký mẫu trước khi ghi.'
    items=runs.run_items(db,run_id)
    if setup:
        try:
            # Use a past interval only for a diary being edited; current eligibility
            # is a preview, never a substitute for save_shift's interval guard.
            basis=samples.gate(db,run_id,machine_id,setup_id=setup.id,
                start=previous.shift_start if previous else runs.local(since) if since else None,
                end=previous.shift_end if previous else cutoff if since else None,
                edit_id=edit_id,line_ids=[i.order_line_id for i in items],require_material=not reconciliation_only)
            blocked=''
            start_default=max(start_default,samples.stamp(basis['authorized_at']))
        except HTTPException as error:
            if error.status_code not in {404,409,422}:raise
            blocked=error.detail
    if previous and blocked:fail(blocked,409)
    return {'run_id':run.id,'official_code':run.official_code,'run_version':run.version,'status':run.status,
        'machine':{'id':current.id,'name':current.name},'assignment_id':assigned.id,
        'episode':samples.episode_record(db,setup) if setup else None,'episodes':choices,
        'sample_basis':basis,'blocked_reason':blocked,'reconciliation_only':reconciliation_only,'today':today.isoformat(),
        'defaults':{'start':start_default.replace(tzinfo=runs.ZONE),'end':(previous.shift_end if previous else cutoff).replace(tzinfo=runs.ZONE),
            'parameters':(previous.shift_snapshot or {}).get('parameters',{}) if previous else {},'ng_sheets':previous.ng if previous else 0},
        'reference_parameters':run.run_snapshot.get('parameters',{}),'calendar':calendar(db,current),
        'items':[{'order_line_id':i.order_line_id,'product_id':i.product_id,'name':i.snapshot.get('name',i.product_id),
            'cavity':i.cavity,'planned_qty':i.planned_qty,'completed_qty':i.completed_qty,
            'remaining_qty':i.planned_qty-i.completed_qty} for i in items],
        'sources':material['sources'],'lots':material['lots'],'source_hash':source_hash(material),
        'source_cutoff':cutoff.replace(tzinfo=runs.ZONE),'previous_end':material['previous_end'],
        'latest_log_id':latest.id if latest else None,'journal':runs.shift_detail(db,edit_id) if previous else None}


def save(db,user,run_id,data,edit_id=None):
    current=machine(db,data.machine_id);run=runs.run_lock(db,run_id,data.run_version)
    assigned=release.assignment(db,run_id,'forming')
    if not assigned or assigned.id!=data.assignment_id or assigned.machine_id!=data.machine_id or run.machine_id!=data.machine_id:
        fail('Phân công đã thay đổi; nạp lại đúng LSX/máy.',409)
    setup=samples.setup_lock(db,data.setup_id);episode=samples.info(setup)
    if episode['version']!=data.episode_version:fail('Đợt chạy đã thay đổi; nạp lại phiếu mẫu và khoảng thực hiện.',409)
    previous=db.get(FormingLog,edit_id) if edit_id else None
    old_calendar=((previous.shift_snapshot or {}).get('forming_entry_v1') or {}).get('calendar') if previous else None
    if edit_id:
        if not data.edit_reason.strip():fail('Sửa nhật ký cần lý do rõ ràng.')
        if not previous or previous.production_order_id!=run_id or not (previous.shift_snapshot or {}).get(samples.SAMPLE):
            fail('Chưa hỗ trợ hồi tố/sửa nhật ký lịch sử thiếu phiếu mẫu căn cứ.',409)
        old_action=(previous.shift_snapshot.get('forming_entry_v1') or {}).get('episode_action','continue')
        if old_action!=data.episode_action:fail('Không đổi hành động đóng/tiếp tục đợt khi sửa nhật ký.',409)
    # Starting a PLANNED LSX is part of the same transaction as the first diary;
    # failure in sample/material/output validation rolls both back.
    if run.status==runs.PLANNED:
        runs.change_state(db,user,run_id,VersionInput(version=run.version,note='Bắt đầu từ nhật ký định hình'),start=True)
    fields=set(ShiftInput.model_fields)
    payload=data.model_dump(include=fields)
    payload['run_version']=run.version;payload['note']=data.note.strip() or 'Nhật ký định hình'
    result=runs.save_shift(db,user,run_id,ShiftInput(**payload),edit_id)
    log=db.get(FormingLog,result['id'])
    log.shift_snapshot={**log.shift_snapshot,'forming_entry_v1':{'episode_action':data.episode_action,
        'calendar':old_calendar or calendar(db,current),'source_hash':data.source_hash,
        'entry_method':'machine_first','edit_reason':data.edit_reason,
        'actual_parameters_basis':'operator_reported_or_unknown'}}
    if data.episode_action=='close' and not episode.get('closed_at'):
        samples.close_episode(db,user,setup.id,SampleVersion(version=episode['version'],note=data.note.strip() or 'Đóng đợt khi chốt nhật ký'),
            closed_at=runs.local(data.end))
    audit(db,user,'FORMING_ENTRY_EDIT' if edit_id else 'FORMING_ENTRY_CREATE',log.id,
        {'run_id':run_id,'machine_id':current.id,'qc_id':data.sample_qc_id,'episode_action':data.episode_action,'edit_reason':data.edit_reason})
    db.flush();return {**runs.shift_detail(db,log.id),'official_code':run.official_code,'run_version':run.version}


def summary(db,run_id):
    run=runs.run_lock(db,run_id,readonly=True)
    # One header interval per grouped run, never multiplied by CTĐH detail joins.
    header=db.execute(select(func.count(FormingLog.id).label('count'),
        func.coalesce(func.sum(FormingLog.good),0).label('good_sheets'),func.coalesce(func.sum(FormingLog.ng),0).label('ng_sheets'),
        func.coalesce(func.sum(func.timestampdiff(literal_column('SECOND'),FormingLog.shift_start,FormingLog.shift_end)),0).label('interval_seconds'))
        .where(FormingLog.production_order_id==run_id,FormingLog.shift_snapshot.is_not(None))).mappings().one()
    quantities={line:(good,ng) for line,good,ng in db.execute(select(ShiftItem.order_line_id,func.sum(ShiftItem.good_qty),func.sum(ShiftItem.ng_qty))
        .join(FormingLog,FormingLog.id==ShiftItem.log_id).where(FormingLog.production_order_id==run_id).group_by(ShiftItem.order_line_id))}
    items=runs.run_items(db,run_id,all_items=True)
    material=source_contexts(db,[run_id])[run_id]
    return {'run_id':run.id,'official_code':run.official_code,**dict(header),
        'items':[{'order_line_id':i.order_line_id,'product_id':i.product_id,'enabled':i.enabled,'planned_qty':i.planned_qty,
            'good_qty':quantities.get(i.order_line_id,(0,0))[0],'ng_qty':quantities.get(i.order_line_id,(0,0))[1],
            'completed_qty':i.completed_qty,'remaining_qty':i.planned_qty-i.completed_qty} for i in items],
        'lots':material['lots'],'previous_end':material['previous_end'],'time_basis':'recorded_intervals_including_rest'}


def history(db,machine_id,run_id,start_day,end_day,page,size):
    from app.modules.production.release_service import machine_expression
    query=select(FormingLog.id,FormingLog.production_order_id.label('run_id'),Run.official_code,
        FormingLog.shift_start,FormingLog.shift_end,FormingLog.good,FormingLog.ng,FormingLog.version,
        machine_expression().label('machine_id'),User.name.label('staff_name'),
        FormingLog.shift_snapshot[samples.SAMPLE]['qc_id'].as_string().label('sample_qc_id'))
    query=query.join(Run,Run.id==FormingLog.production_order_id).outerjoin(User,User.id==FormingLog.staff_id)
    query=query.where(FormingLog.shift_snapshot.is_not(None))
    if machine_id:query=query.where(machine_expression()==machine_id)
    if run_id:query=query.where(FormingLog.production_order_id==run_id)
    if start_day:query=query.where(FormingLog.run_date>=start_day)
    if end_day:query=query.where(FormingLog.run_date<=end_day)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(FormingLog.shift_start.desc(),FormingLog.id.desc()).offset((page-1)*size).limit(size)).mappings()
    return {'items':[dict(r) for r in rows],'total':total,'page':page,'size':size}
