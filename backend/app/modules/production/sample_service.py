"""Sample gates on existing production_setups and qc_checks, never a new LSX/template.

Writes run under allocation_api.write's ERP lock and transaction. JSON extensions
are versioned; historical setup/QC rows without them never authorize production.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4
from cryptography.fernet import InvalidToken
from sqlalchemy import select, func
from app.auth.security import require
from app.integrations.google.oauth import cipher
from app.modules.qc.signing import identity
from app.modules.qc import mapping, template_runtime as runtime
from app.modules.qc.models import QualityCheck as QC
from app.modules.production import run_service as runs, release_service as release
from app.modules.production.models import ProductionSetup as Setup, ProductionOrder as Run, FormingLog, CuttingLog, EBLog
from app.modules.production.run_models import ProductionOrderItem as Item, ProductionAssignment, ShiftItem, DownstreamItem
from app.modules.production.schedule_models import RunStop
from app.modules.production.planning_models import Machine
from app.modules.materials.inventory.handover_sources import source_contexts
from app.modules.materials.inventory.allocation_service import fail, audit

EPISODE='sample_episode_v1'
SAMPLE='production_sample_v1'
STAGES={'Định hình':'forming','Cắt':'cutting','Ép biên':'edge'}
DECISIONS={'normal':'Cho chạy hàng loạt','sort':'Cho chạy lọc','stop':'Dừng chạy'}


def info(setup):return (setup.source or {}).get(EPISODE) or {}
def sample(obj):return (obj.form_data or {}).get(SAMPLE) or {}
def stamp(value):return datetime.fromisoformat(value) if value else None


def machine_matches(machine,stage):
    return bool(machine and machine.kind in ({'automatic','semi_automatic'} if stage=='forming' else {stage})
        and machine.status in {'ready','running'})


def interrupted(db,run_id,opened,until,*,include_endpoint=False):
    from datetime import timedelta
    for stop in db.scalars(select(RunStop).where(RunStop.run_id==run_id,RunStop.enabled.is_(True),RunStop.started_at<=until)):
        if stop.started_at==until and not include_endpoint:continue
        if stop.started_at>=opened:return True
        finish=stop.started_at+timedelta(seconds=stop.duration_seconds) if stop.duration_seconds is not None else None
        if finish is None or finish>opened:return True
    return False


def setup_lock(db,identifier):
    row=db.scalar(select(Setup).where(Setup.id==identifier).with_for_update())
    if not row or not info(row):fail('Không tìm thấy đợt chạy mẫu mới; dữ liệu lịch sử không tự mở chạy.',404)
    return row


def qc_lock(db,identifier,version=None):
    row=db.scalar(select(QC).where(QC.id==identifier).with_for_update())
    if not row or not sample(row):fail('Không tìm thấy phiếu mẫu.',404)
    if version is not None and sample(row)['version']!=version:fail('Phiếu mẫu đã thay đổi; tải lại trước khi ghi.',409)
    return row


def fingerprint(db,run,setup):
    episode=info(setup);stage=STAGES[setup.stage]
    items=db.scalars(select(Item).where(Item.run_id==run.id,Item.enabled.is_(True)).order_by(Item.order_line_id)).all()
    selected=[i for i in items if i.order_line_id in episode['line_ids']]
    if len(selected)!=len(episode['line_ids']):fail('Thành phần ghép đã thay đổi; cần đợt chạy mẫu mới.',409)
    query=select(ProductionAssignment).where(ProductionAssignment.run_id==run.id,
        ProductionAssignment.stage==stage,ProductionAssignment.ended_at.is_(None))
    query=query.where(ProductionAssignment.order_line_id.in_(episode['line_ids'])) if stage!='forming' else query
    assigned=db.scalars(query.order_by(ProductionAssignment.id)).all()
    if len(assigned)!=(len(episode['line_ids']) if stage!='forming' else 1) or any(a.machine_id!=setup.machine_id for a in assigned):
        fail('Máy/LSX không còn đúng phân công; cần chạy mẫu lại.',409)
    assignments=[a.id for a in assigned]
    return mapping.digest(release.encoded({'machine':setup.machine_id,'stage':stage,'assignments':assignments,
        'run_snapshot':run.run_snapshot,'items':[{'line':i.order_line_id,'product':i.product_id,
        'quantity':i.planned_qty,'cavity':i.cavity,'snapshot':i.snapshot} for i in selected]}))


def sources(db,run,setup,at=None):
    episode=info(setup);stage=STAGES[setup.stage]
    if stage=='forming':
        context=source_contexts(db,[run.id],until=at)[run.id]
        available=[s for s in context['sources'] if runs.D(s['opening_kg'])+runs.D(s['input_kg'])-runs.D(s['output_kg'])>0]
        if not available:fail('Chưa có NVL đã ký nhận còn sử dụng được cho LSX.',409)
        return release.encoded(available)
    log=db.get(FormingLog,episode.get('source_forming_log_id'))
    if not log or log.production_order_id!=run.id or not (log.shift_snapshot or {}).get('handover_source_version'):
        fail('Công đoạn cần nguồn hút đã chốt theo NVL ký nhận; không tự dùng nguồn lịch sử chưa xác minh.',409)
    if at and log.shift_end>at:fail('Nguồn hút chưa hoàn tất tại thời điểm chạy mẫu.',409)
    upstream={i.order_line_id:i.good_qty for i in db.scalars(select(ShiftItem).where(ShiftItem.log_id==log.id))}
    processed={(line,st):(runs.D(qty),runs.D(good)) for line,st,qty,good in db.execute(select(DownstreamItem.order_line_id,
        DownstreamItem.stage,func.sum(DownstreamItem.input_qty),func.sum(DownstreamItem.good_qty)).where(DownstreamItem.forming_log_id==log.id)
        .group_by(DownstreamItem.order_line_id,DownstreamItem.stage))}
    products=(log.shift_snapshot or {}).get('items',{})
    for line in episode['line_ids']:
        capacity=processed.get((line,'cutting'),(0,0))[1] if stage=='edge' and 'cutting' in products.get(line,{}).get('route',[]) else runs.D(upstream.get(line,0))
        if capacity-processed.get((line,stage),(0,0))[0]<=0:fail('Không còn nguồn hàng hợp lệ cho các CTĐH của đợt chạy.',409)
    return [{'forming_log_id':log.id,'version':log.version,'line_ids':episode['line_ids']}]


def validate_episode(db,setup,*,at=None,need_sources=True):
    run=runs.run_lock(db,setup.production_order_id);release.require_released(run)
    if run.status==runs.ENDED and STAGES[setup.stage]=='forming' and not (setup.source or {}).get('forming_evidence_v1'):fail('LSX đã kết thúc định hình.',409)
    episode=info(setup);at=at or release.now()
    if (setup.source or {}).get('forming_evidence_v1'):
        # Evidence may be completed/signed after the recorded shift, including a closed episode.
        # It never grants strict sample clearance (see gate).
        return run,episode.get('received_sources_at_setup',[])
    if episode.get('closed_at') or at<stamp(episode['opened_at']) or at>=stamp(episode['valid_until']):
        fail('Đợt chạy đã đóng hoặc hết khoảng thực hiện; phải chạy mẫu lại.',409)
    machine=db.get(Machine,setup.machine_id)
    if not machine_matches(machine,STAGES[setup.stage]):fail('Máy chưa sẵn sàng hoặc sai công đoạn.',409)
    if fingerprint(db,run,setup)!=episode['fingerprint']:fail('Kế hoạch đã thay đổi; cần chạy mẫu lại.',409)
    if interrupted(db,run.id,stamp(episode['opened_at']),at,include_endpoint=True):
        fail('Đợt chạy có dừng máy hoặc bắt đầu trong khoảng dừng; khi chạy lại phải lập mẫu mới.',409)
    material=sources(db,run,setup,at) if need_sources else []
    return run,material


def create_episode(db,user,run_id,data):
    require(db,user,'PRODUCTION_EDIT')
    end=runs.local(data.valid_until)
    if end<=release.now():fail('Nhập thời điểm kết thúc dự kiến của đợt chạy trong tương lai.')
    chosen=data.order_line_ids or ([data.order_line_id] if data.order_line_id else [])
    result=release.create_setup(db,user,run_id,data.model_copy(update={'order_line_id':chosen[0] if chosen else None}))
    setup=db.get(Setup,result['id']);run=db.get(Run,run_id)
    active=runs.run_items(db,run_id)
    if data.stage!='forming' and not set(chosen)<={i.order_line_id for i in active}:fail('CTĐH không thuộc LSX.')
    line_ids=[i.order_line_id for i in active if data.stage=='forming' or i.order_line_id in chosen]
    if not line_ids:fail('Chọn CTĐH thuộc LSX cho công đoạn này.')
    if any(i.planned_qty<=i.completed_qty for i in runs.run_items(db,run_id) if i.order_line_id in line_ids) and data.stage=='forming':
        fail('CTĐH đã đủ số lượng kế hoạch; cập nhật kế hoạch trước khi chạy mẫu.',409)
    episode={'version':1,'opened_at':setup.checked_at.isoformat(),'valid_until':end.isoformat(),'closed_at':None,
        'line_ids':sorted(line_ids),'source_forming_log_id':data.source_forming_log_id,'fingerprint':''}
    setup.source={**setup.source,EPISODE:episode}
    episode['fingerprint']=fingerprint(db,run,setup)
    setup.source={**setup.source,EPISODE:deepcopy(episode)}
    _,material=validate_episode(db,setup)
    episode['received_sources_at_setup']=material
    setup.source={**setup.source,EPISODE:deepcopy(episode)}
    db.flush();return episode_record(db,setup)


def close_preceding(db,user,run_id,stage,line_ids,new_setup_id):
    """Shared by all setup creation routes, including the older setup API."""
    label=next(k for k,v in STAGES.items() if v==stage)
    for previous in db.scalars(select(Setup).where(Setup.production_order_id==run_id,Setup.stage==label,
            Setup.id!=new_setup_id).with_for_update()):
        old=info(previous)
        if old and not old.get('closed_at') and (stage=='forming' or not line_ids or set(old['line_ids'])&set(line_ids)):
            previous.source={**previous.source,EPISODE:{**old,'version':old['version']+1,
                'closed_at':release.now().isoformat(),'closed_by':user.id,'closed_reason':'new_setup'}}
            audit(db,user,'PRODUCTION_SAMPLE_EPISODE_SUPERSEDE',previous.id,{'new_setup_id':new_setup_id})


def episode_record(db,setup):
    run=db.get(Run,setup.production_order_id)
    return {'id':setup.id,'run_id':setup.production_order_id,'official_code':run.official_code,
        'machine_id':setup.machine_id,'stage':STAGES[setup.stage],'evidence_only':bool((setup.source or {}).get('forming_evidence_v1')),**release.encoded(info(setup))}


def template_entry(db,setup,check_type,template_id=None):
    values,products=runtime.context(db,'SETUP',setup.id,setup.production_order_id)
    kind='HUT' if (setup.source or {}).get('forming_evidence_v1') else 'SETUP'
    row=runtime.released(db,template_id,check_type,kind,products,lock=True) if template_id else runtime.resolve_template(db,check_type,kind,products)
    if not row.field_mapping or not row.field_mapping.get('signature_cell'):fail('Template cần mapping và vị trí chữ ký QC đã duyệt.',422)
    values.update(machine_id=setup.machine_id,setup_id=setup.id,order_line_ids=', '.join(info(setup)['line_ids']))
    definition={'id':row.id,'code':row.form_code,'version':row.version,'name':row.form_name,
        'spreadsheet_id':row.spreadsheet_id,'sheet_id':row.sheet_id,'source_hash':row.source_hash,
        'mapping_hash':mapping.digest(row.field_mapping),'approved_by':row.approved_by,
        'approved_at':row.approved_at.isoformat(),'mapping':deepcopy(row.field_mapping),'snapshot':deepcopy(row.source_snapshot)}
    return definition,values


def save(db,user,data,identifier=None):
    require(db,user,'QC_EDIT' if identifier else 'QC_CREATE')
    setup=setup_lock(db,data.setup_id);run,_=validate_episode(db,setup)
    if data.journal_id:
        journal=db.get(FormingLog,data.journal_id)
        if journal and (journal.production_order_id!=run.id or journal.setup_id!=setup.id):fail('Nhật ký không thuộc LSX/đợt kiểm tra này.',409)
        if not (setup.source or {}).get('forming_evidence_v1') and not journal:fail('Lưu nhật ký trước khi gắn phiếu cho đợt kiểm mẫu cũ.',409)
    obj=qc_lock(db,identifier,data.version) if identifier else None
    if obj:
        old=sample(obj)
        if old.get('journal_id')!=data.journal_id:fail('Không đổi liên kết nhật ký của phiếu đã lưu.',409)
        if obj.object_id!=setup.id:fail('Không chuyển đợt chạy của phiếu đã lưu.')
        if old['state']!='draft' or old.get('signatures'):fail('Phiếu đã ký không sửa nội dung; hủy có kiểm soát và lập phiếu mới.',409)
        if data.version is None:fail('Cần version để sửa phiếu mẫu.',409)
    definition,values=template_entry(db,setup,data.check_type,data.template_id)
    if data.source_hash!=definition['source_hash'] or data.mapping_hash!=definition['mapping_hash']:fail('Template/mapping đã thay đổi; chọn lại.',409)
    answers,conclusion=runtime.normalized_answers(definition['mapping']['fields'],data,complete=False)
    if not obj:
        from app.modules.qc.service import next_identifiers
        obj=QC(id=next_identifiers(db,1)[0],staff_id=user.id,ncr_id='',source={})
        db.add(obj)
    values.update(qc_id=obj.id,check_type=data.check_type,checked_at=release.now().isoformat(),quantity=str(data.quantity),
        staff_name=user.name,qc_note=data.note,conclusion='Đạt' if conclusion=='PASS' else 'Không đạt',
        decision=DECISIONS[data.decision],signer_name='',signed_at='')
    values.update(mapping.assessment_summary(answers))
    auto={f['id']:str(values.get(f['source'],'')) for f in definition['mapping']['fields'] if f['kind']=='ERP'}
    missing=[f['name'] for f in definition['mapping']['fields'] if f['kind']=='ERP' and f['required'] and not auto[f['id']] and f['source'] not in {'signer_name','signed_at'}]
    if missing:fail('Thiếu dữ liệu ERP bắt buộc: '+', '.join(missing))
    version=sample(obj).get('version',0)+1
    obj.production_order_id=run.id;obj.object_type='SETUP';obj.object_id=setup.id;obj.check_type=data.check_type
    obj.checked_at=release.now();obj.quantity=data.quantity;obj.result='OK' if conclusion=='PASS' else 'NG'
    obj.note=data.note;obj.standard_url='';obj.image_url='';obj.template_id=data.template_id
    obj.form_data={'kind':'google_template','template':definition,'context':values,'auto_values':auto,
        'input':{'answers':answers,'conclusion':conclusion,'signature':[]},
        SAMPLE:{'version':version,'state':'draft','decision':data.decision,'signatures':{},'journal_id':data.journal_id,
            'episode_fingerprint':info(setup)['fingerprint'],'episode':deepcopy(info(setup)),
            'parent_folder_id':data.parent_folder_id}}
    audit(db,user,'PRODUCTION_SAMPLE_SAVE',obj.id,{'setup_id':setup.id,'version':version,'decision':data.decision})
    db.flush();return record(db,obj)


def require_role(db,user,role):
    if role in {'technical','production_lead'}:require(db,user,'PRODUCTION_EDIT')
    else:
        from app.modules.qc.api import allowed
        allowed(db,user,'QC_CREATE','QC_EDIT')


def signing_content(obj,data):
    content=deepcopy(obj.form_data)
    return mapping.digest({'scope':SAMPLE,'id':obj.id,'version':data.version,'role':data.role,
        'content':content,'strokes':data.model_dump(mode='json')['signature']})


def signable(db,user,obj,data):
    require_role(db,user,data.role)
    metadata=sample(obj)
    if metadata['state'] not in {'draft','signing'} or data.role in metadata['signatures']:fail('Phiếu đã hủy/đủ ký hoặc vai trò đã ký.',409)
    roles=mapping.required_signers(obj.form_data['template']['mapping'])
    if data.role not in roles:fail('Vai trò không thuộc các vị trí ký đã duyệt của template.',409)
    if obj.form_data['template']['mapping'].get('signatures') and any(signature['proof']['user_id']==user.id for signature in metadata['signatures'].values()):fail('Mỗi vị trí xác nhận cần người ký khác nhau.',409)
    setup=setup_lock(db,obj.object_id);validate_episode(db,setup)
    if metadata['episode_fingerprint']!=info(setup)['fingerprint']:fail('Phiếu không khớp đợt chạy.',409)
    from types import SimpleNamespace
    from app.modules.qc.schemas import MappedAnswer
    runtime.normalized_answers(obj.form_data['template']['mapping']['fields'],SimpleNamespace(
        answers=[MappedAnswer(**a) for a in obj.form_data['input']['answers']],conclusion=obj.form_data['input']['conclusion']))
    return setup


def confirm(db,user,request,identifier,data):
    obj=qc_lock(db,identifier,data.version);signable(db,user,obj,data)
    actor=identity(request,db,user)
    proof={**actor,'scope':SAMPLE,'document_id':identifier,'version':data.version,'role':data.role,
        'content_hash':signing_content(obj,data),'signed_at':datetime.now(timezone.utc).isoformat(),'nonce':uuid4().hex,
        'method':'google_oauth_internal_drawn'}
    return {'confirmation':cipher().encrypt(json.dumps(proof).encode()).decode(),'name':user.name,'signed_at':proof['signed_at']}


def sign(db,user,request,identifier,data):
    obj=qc_lock(db,identifier,data.version);setup=signable(db,user,obj,data);actor=identity(request,db,user)
    try:
        proof=json.loads(cipher().decrypt((data.confirmation or '').encode(),ttl=8*3600))
        if any(proof[key]!=value for key,value in {'scope':SAMPLE,'document_id':identifier,'version':data.version,
                'role':data.role,'user_id':user.id,'session':actor['session'],'google_subject':actor['google_subject'],
                'content_hash':signing_content(obj,data)}.items()):raise ValueError()
    except (InvalidToken,ValueError,KeyError,TypeError):fail('Nội dung hoặc phiên ký thay đổi; xác nhận lại bằng đúng tài khoản Google.',422)
    saved=deepcopy(obj.form_data);metadata=saved[SAMPLE]
    metadata['signatures'][data.role]={'strokes':data.model_dump(mode='json')['signature'],
        'proof':proof,'accepted_at':release.now().isoformat()}
    metadata['version']+=1;metadata['state']='signed' if set(metadata['signatures'])==set(mapping.required_signers(saved['template']['mapping'])) else 'signing'
    if metadata['state']=='signed':
        metadata['authorized_at']=release.now().isoformat()
        qc=metadata['signatures']['qc']
        saved['signer']={k:v for k,v in qc['proof'].items() if k!='session'}
        saved['input']['signature']=qc['strokes']
        saved['context'].update(signer_name=qc['proof']['name'],signed_at=qc['proof']['signed_at'])
        for f in saved['template']['mapping']['fields']:
            if f['kind']=='ERP':saved['auto_values'][f['id']]=str(saved['context'].get(f['source'],''))
    obj.form_data=saved
    if metadata['state']=='signed':
        setup.result=obj.result;setup.qc_id=obj.id
        from app.modules.qc import drive_bundle
        from app.modules.qc.jobs import enqueue
        from app.auth.models import User
        export_owner=db.get(User,metadata['signatures']['qc']['proof']['user_id'])
        drive_bundle.schedule(obj,export_owner,metadata['parent_folder_id'])
        enqueue(db,export_owner,obj)
    audit(db,user,'PRODUCTION_SAMPLE_SIGN',identifier,{'role':data.role,'hash':proof['content_hash'],'nonce':proof['nonce']})
    db.flush();return record(db,obj)


def linked_logs(db,obj):
    journal_id=sample(obj).get('journal_id')
    if journal_id and db.scalar(select(FormingLog.id).where(FormingLog.id==journal_id,FormingLog.setup_id==obj.object_id).limit(1)):return journal_id
    return (db.scalar(select(FormingLog.id).where(FormingLog.setup_id==obj.object_id,
        FormingLog.shift_snapshot[SAMPLE]['qc_id'].as_string()==obj.id).limit(1)) or
        db.scalar(select(CuttingLog.id).where(CuttingLog.setup_id==obj.object_id,
            CuttingLog.source[SAMPLE]['qc_id'].as_string()==obj.id).limit(1)) or
        db.scalar(select(EBLog.id).where(EBLog.setup_id==obj.object_id,
            EBLog.source[SAMPLE]['qc_id'].as_string()==obj.id).limit(1)))


def cancel(db,user,identifier,data):
    require(db,user,'QC_EDIT');obj=qc_lock(db,identifier,data.version)
    if linked_logs(db,obj):fail('Phiếu đã dùng trong nhật ký; cần quy trình điều chỉnh liên kết, không hủy/sửa ngược.',409)
    if sample(obj)['state']=='cancelled':fail('Phiếu đã hủy.',409)
    saved=deepcopy(obj.form_data);saved[SAMPLE].update(state='cancelled',version=data.version+1,
        cancelled_by=user.id,cancelled_at=release.now().isoformat(),cancel_reason=data.note)
    obj.form_data=saved
    audit(db,user,'PRODUCTION_SAMPLE_CANCEL',identifier,{'note':data.note})
    db.flush();return record(db,obj)


def close_episode(db,user,identifier,data,*,closed_at=None):
    require(db,user,'PRODUCTION_EDIT');setup=setup_lock(db,identifier);metadata=info(setup)
    if metadata['version']!=data.version or metadata.get('closed_at'):fail('Đợt chạy đã thay đổi hoặc đã đóng.',409)
    close_time=closed_at or release.now()
    if close_time<stamp(metadata['opened_at']) or close_time>release.now():fail('Thời điểm đóng đợt không hợp lệ.',409)
    last_end=db.scalar(select(func.max(FormingLog.shift_end)).where(FormingLog.setup_id==identifier))
    if last_end and last_end>close_time:fail('Không đóng đợt trước nhật ký đã thực hiện.',409)
    setup.source={**setup.source,EPISODE:{**metadata,'version':metadata['version']+1,
        'closed_at':close_time.isoformat(),'closed_by':user.id,'closed_reason':data.note}}
    audit(db,user,'PRODUCTION_SAMPLE_EPISODE_CLOSE',identifier,{'note':data.note})
    db.flush();return episode_record(db,setup)


def gate(db,run_id,machine_id,stage='forming',setup_id=None,*,start=None,end=None,line_ids=None,edit_id=None,require_material=True):
    """Fail closed. No authorization inferred from a result flag or legacy QC."""
    query=select(Setup).where(Setup.production_order_id==run_id,Setup.machine_id==machine_id,
        Setup.stage==next(k for k,v in STAGES.items() if v==stage))
    setup=db.get(Setup,setup_id) if setup_id else db.scalar(query.order_by(Setup.checked_at.desc(),Setup.source['run_version'].as_integer().desc(),Setup.id.desc()).limit(1))
    if not setup or setup.production_order_id!=run_id or setup.machine_id!=machine_id or STAGES.get(setup.stage)!=stage or not info(setup):
        fail('Cần mở đợt chạy và kiểm mẫu mới đúng LSX/máy/công đoạn.',409)
    if (setup.source or {}).get('forming_evidence_v1'):
        fail('Phiếu QC này là bằng chứng nhật ký, không dùng để mở khóa công đoạn khác.',409)
    # Closed episodes may be referenced when recording their past interval; never reopen them.
    episode=info(setup);moment=start or release.now()
    if end and episode.get('closed_at') and end>stamp(episode['closed_at']):fail('Nhật ký vượt thời điểm đóng đợt chạy.',409)
    if end and end>stamp(episode['valid_until']):fail('Nhật ký vượt khoảng đợt chạy; cần mẫu mới cho đợt sau.',409)
    run=runs.run_lock(db,run_id);release.require_released(run)
    if run.status==runs.ENDED and stage=='forming':fail('LSX đã kết thúc định hình.',409)
    if moment<stamp(episode['opened_at']) or moment>=stamp(episode['valid_until']):fail('Thời điểm ngoài đợt chạy mẫu.',409)
    if not start and episode.get('closed_at'):fail('Đợt chạy đã đóng; cần mẫu mới.',409)
    if fingerprint(db,run,setup)!=episode['fingerprint']:fail('Kế hoạch thay đổi; cần mẫu mới.',409)
    machine=db.get(Machine,machine_id)
    if not machine_matches(machine,stage):fail('Máy chưa sẵn sàng hoặc sai công đoạn.',409)
    if line_ids and not set(line_ids)<=set(episode['line_ids']):fail('CTĐH không thuộc phiếu mẫu của đợt chạy.',409)
    until=end or moment
    if interrupted(db,run_id,stamp(episode['opened_at']),until,include_endpoint=end is None):
        fail('Đợt chạy có dừng; phải chạy mẫu lại cho lần chạy tiếp.',409)
    # Never fall back to an older clearance when the latest inspection is cancelled.
    candidates=db.scalars(select(QC).where(QC.object_type=='SETUP',QC.object_id==setup.id)
        .order_by(QC.checked_at.desc(),QC.id.desc())).all()
    obj=next((q for q in candidates if sample(q)),None)
    if not obj:fail('Đợt chạy chưa có phiếu kiểm mẫu.',409)
    metadata=sample(obj)
    if metadata['state']!='signed' or set(metadata['signatures'])!=set(mapping.required_signers(obj.form_data['template']['mapping'])) or metadata['decision']=='stop':
        fail('Phiếu mẫu chưa đủ xác nhận hoặc có quyết định Dừng chạy.',409)
    authorized=stamp(metadata['authorized_at'])
    if moment<authorized:fail('Không ghi chạy hàng loạt trước thời điểm đủ hai xác nhận.',409)
    if metadata['decision']=='normal' and obj.result!='OK' or metadata['decision']=='sort' and obj.result!='NG':
        fail('Kết quả và quyết định phiếu mẫu không hợp lệ.',409)
    if not edit_id and require_material:sources(db,run,setup,moment)
    return {'qc_id':obj.id,'qc_version':metadata['version'],'setup_id':setup.id,'stage':stage,
        'machine_id':machine_id,'result':obj.result,'decision':metadata['decision'],'authorized_at':metadata['authorized_at'],
        'valid_until':episode['valid_until'],'content_hash':mapping.digest(obj.form_data)}


def record(db,obj):
    saved=deepcopy(obj.form_data)
    if saved.get('signer'):saved['signer']={k:v for k,v in saved['signer'].items() if k not in {'session','google_subject'}}
    for entry in saved[SAMPLE].get('signatures',{}).values():
        entry['proof']={k:v for k,v in entry['proof'].items() if k not in {'session','google_subject'}}
    run=db.get(Run,obj.production_order_id)
    export=(obj.source or {}).get('qc_bundle',{})
    return {'id':obj.id,'setup_id':obj.object_id,'official_code':run.official_code,'result':obj.result,
        'quantity':str(obj.quantity),'check_type':obj.check_type,'note':obj.note,'form_data':saved,
        'version':sample(obj)['version'],'state':sample(obj)['state'],'linked_log_id':linked_logs(db,obj),
        'pdf_pending':bool(export.get('pending')),'pdf_error':export.get('error','')}
