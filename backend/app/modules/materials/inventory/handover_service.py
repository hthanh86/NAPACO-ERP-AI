"""Signed handovers reuse the allocation ledger and the QC identity proof.

Mutations are called inside allocation_api.write's shared ERP transaction.
"""
import json
from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from cryptography.fernet import InvalidToken
from sqlalchemy import select,func,or_
from fastapi.encoders import jsonable_encoder
from app.auth.security import require
from app.integrations.google.oauth import cipher
from app.modules.qc.signing import identity
from app.modules.qc.mapping import digest
from app.modules.materials.inventory.handover_models import MaterialHandover as H
from app.modules.materials.inventory import allocation_service as material
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.handover_sources import received
from app.modules.production.models import ProductionOrder as Run
from app.modules.production.run_models import ProductionOrderItem as Item,RunMaterial
from app.modules.production.release_service import require_released,now
from app.modules.production.planning_models import ProductionStandard
from app.modules.orders.models import OrderLine


def encoded(value):return jsonable_encoder(value,custom_encoder={Decimal:str})


def lock(db,identifier,version=None):
    row=db.scalar(select(H).where(H.id==identifier).with_for_update())
    if not row:material.fail('Không tìm thấy phiếu bàn giao.',404)
    if version is not None and row.version!=version:material.fail('Phiếu bàn giao đã thay đổi; tải lại trước khi ký.',409)
    return row


def reserved(db,allocation_id,run_id=None,exclude=None):
    query=select(func.coalesce(func.sum(H.quantity),0)).where(H.state=='draft',H.allocation_id==allocation_id,H.mode=='issue')
    if run_id is not None:query=query.where(H.run_id==run_id)
    if exclude is not None:query=query.where(H.id!=exclude)
    return db.scalar(query)


def transfer_reserved(db,source_id,exclude=None):
    query=select(func.coalesce(func.sum(H.quantity),0)).where(H.state=='draft',H.source_issue_id==source_id)
    if exclude is not None:query=query.where(H.id!=exclude)
    return db.scalar(query)


def active_run(db,identifier,line_id,*,require_remaining=True):
    run=db.scalar(select(Run).where(Run.id==identifier).with_for_update());require_released(run)
    if run.status=='Đã kết thúc':material.fail('LSX đã kết thúc không được cấp/nhận NVL.',409)
    item=db.get(Item,(identifier,line_id))
    if not item or not item.enabled or (require_remaining and item.completed_qty>=item.planned_qty):material.fail('CTĐH không còn được cấp để thực hiện trong LSX.',409)
    return run


def validate_issue(db,a,run,kg,exclude=None):
    material.target(db,a.order_line_id,a.standard_id,a.receipt_id,new=False)
    if kg+reserved(db,a.id,exclude=exclude)>a.held_kg:material.fail('Phần giữ đã được lập phiếu khác hoặc không đủ.',409)
    binding=db.get(RunMaterial,(run.id,a.id))
    if not binding or kg+reserved(db,a.id,run.id,exclude)>binding.planned_kg-binding.issued_kg:
        material.fail('Phiếu vượt phần NVL bố trí còn lại của LSX.',409)
    material.ensure_available(db,{a.receipt_id:kg},own_allocation_ids=[a.id],order_line_id=a.order_line_id)


def create_issue(db,user,allocation_id,data):
    a=material.allocation_lock(db,allocation_id,data.version)
    run=active_run(db,data.production_order_id,a.order_line_id)
    validate_issue(db,a,run,data.kg)
    row=H(id=str(uuid4()),run_id=run.id,allocation_id=a.id,mode='issue',quantity=data.kg,state='draft',version=1,
        created_by=user.id,created_at=now(),snapshot=encoded({'official_code':run.official_code,'receipt_id':a.receipt_id,
            'order_line_id':a.order_line_id,'standard_id':a.standard_id,'quantity_kg':data.kg,'note':data.note}))
    db.add(row);material.audit(db,user,'MATERIAL_HANDOVER_DRAFT',row.id,{'run_id':run.id,'quantity_kg':str(data.kg)})
    db.flush();return record(row)


def create_transfer(db,user,source_id,data):
    require(db,user,'NVL_RECEIVE');require(db,user,'NVL_STOCK_VIEW')
    source,link,a=material.linked_issue(db,source_id)
    material.return_limit(db,source,data.kg)
    if data.kg>data.measured_remaining_kg:material.fail('Số chuyển vượt lượng kiểm đếm tại nguồn.')
    material.target(db,data.order_line_id,data.standard_id,a.receipt_id)
    run=active_run(db,data.production_order_id,data.order_line_id)
    if run.id==source.production_order_id and data.order_line_id==a.order_line_id:material.fail('Chọn CTĐH hoặc LSX đích khác lần cấp gốc.')
    row=H(id=str(uuid4()),run_id=run.id,source_issue_id=source_id,mode='transfer',quantity=data.kg,state='draft',version=1,
        created_by=user.id,created_at=now(),snapshot=encoded({'official_code':run.official_code,'receipt_id':a.receipt_id,
            'order_line_id':data.order_line_id,'standard_id':data.standard_id,'quantity_kg':data.kg,
            'source_issue_id':source_id,'measured_remaining_kg':data.measured_remaining_kg,'note':data.note}))
    db.add(row);material.audit(db,user,'MATERIAL_TRANSFER_DRAFT',row.id,{'source_issue_id':source_id,'quantity_kg':str(data.kg)})
    db.flush();return record(row)


def content(row,role,signature):
    return digest(encoded({'scope':'material_handover_v1','document_id':row.id,'version':row.version,
        'role':role,'mode':row.mode,'run_id':row.run_id,'quantity_kg':row.quantity,'snapshot':row.snapshot,
        'issuer_proof':row.issue_signature if role=='receipt' else None,'signature':signature}))


def check_role(db,user,row,role):
    require(db,user,'PRODUCTION_EDIT')
    expected='draft' if role=='issue' else 'awaiting_receipt'
    if row.state!=expected:material.fail('Phiếu không ở trạng thái được ký cho bước này.',409)
    if role=='issue' and row.mode=='transfer':require(db,user,'NVL_RECEIVE');require(db,user,'NVL_STOCK_VIEW')
    run=active_run(db,row.run_id,row.snapshot['order_line_id'],require_remaining=role=='issue')
    if run.official_code!=row.snapshot['official_code']:material.fail('Mã LSX không khớp nội dung phiếu.',409)
    if role=='receipt' and not row.issue_signature:material.fail('Phiếu chưa có chữ ký cấp hợp lệ.',409)


def confirm_signature(db,user,request,row,data):
    check_role(db,user,row,data.role)
    actor=identity(request,db,user)
    signed={**actor,'scope':'material_handover_v1','role':data.role,'document_id':row.id,'version':row.version,
        'signed_at':datetime.now(timezone.utc).isoformat(),'nonce':uuid4().hex,
        'method':'google_oauth_internal_drawn','content_hash':content(row,data.role,data.signature)}
    token=cipher().encrypt(json.dumps(signed).encode()).decode()
    return {'confirmation':token,'name':actor['name'],'email':actor['email'],'signed_at':signed['signed_at']}


def verify_signature(db,user,request,row,data):
    actor=identity(request,db,user)
    try:
        signed=json.loads(cipher().decrypt((data.confirmation or '').encode(),ttl=8*3600))
        if any(signed.get(k)!=v for k,v in {'scope':'material_handover_v1','role':data.role,'document_id':row.id,
                'version':row.version,'user_id':user.id,'session':actor['session'],
                'google_subject':actor['google_subject'],'content_hash':content(row,data.role,data.signature)}.items()):raise ValueError()
    except (InvalidToken,ValueError,TypeError,KeyError):
        material.fail('Nội dung, nét ký hoặc phiên xác nhận đã thay đổi. Hãy ký xác nhận lại.',422)
    return {**signed,'signature':data.signature,'confirmed_at':signed['signed_at'],
        'signed_at':datetime.now(timezone.utc).isoformat()}


def sign(db,user,request,identifier,data):
    row=lock(db,identifier,data.version);check_role(db,user,row,data.role)
    proof=verify_signature(db,user,request,row,data)
    if data.role=='issue':
        row.issue_signature=encoded(proof)
        if row.mode=='issue':
            a=material.allocation_lock(db,row.allocation_id)
            run=active_run(db,row.run_id,a.order_line_id);validate_issue(db,a,run,row.quantity,row.id)
            result=material.issue(db,user,a.id,SimpleNamespace(version=a.version,production_order_id=row.run_id,
                kg=row.quantity,note=row.snapshot['note']),handover=row)
        else:
            values={k:row.snapshot[k] for k in ['order_line_id','standard_id','measured_remaining_kg','note']}
            values['measured_remaining_kg']=Decimal(values['measured_remaining_kg'])
            result=material.transfer(db,user,row.source_issue_id,SimpleNamespace(**values,production_order_id=row.run_id,kg=row.quantity),handover=row)
        row.movement_id=result['movement_id'];row.allocation_id=result['allocation']['id']
        row.issued_by=user.id;row.issued_at=now();row.state='awaiting_receipt'
    else:
        movement=db.scalar(select(FilmMovement).where(FilmMovement.id==row.movement_id).with_for_update())
        if not movement or movement.receiver_id.strip() or movement.issuer_id!=row.issued_by or movement.quantity!=row.quantity or movement.receipt_id!=row.snapshot['receipt_id'] or movement.production_order_id!=row.run_id:
            material.fail('Phiếu cấp không khớp hồ sơ đã ký hoặc đã có người nhận; cần tải lại.',409)
        movement.receiver_id=user.id
        row.receipt_signature=encoded(proof);row.received_by=user.id;row.received_at=now();row.state='received'
        run=db.get(Run,row.run_id);run.version+=1
    row.version+=1
    material.audit(db,user,'MATERIAL_HANDOVER_'+data.role.upper(),row.id,{'run_id':row.run_id,
        'movement_id':row.movement_id,'version':row.version,'content_hash':proof['content_hash'],'nonce':proof['nonce']})
    db.flush();return record(row)


def cancel(db,user,identifier,data):
    row=lock(db,identifier,data.version)
    if row.state!='draft':material.fail('Chỉ hủy phiếu nháp; phiếu đã ký cấp phải xử lý theo bàn giao/trả kho.',409)
    row.state='cancelled';row.version+=1
    material.audit(db,user,'MATERIAL_HANDOVER_CANCEL',row.id,{'version':row.version})
    db.flush();return record(row)


def record(row):
    value={k:getattr(row,k) for k in ['id','run_id','allocation_id','source_issue_id','mode','quantity','state','version',
        'movement_id','snapshot','created_by','created_at','issued_by','issued_at','received_by','received_at','issue_signature','receipt_signature']}
    for key in ['issue_signature','receipt_signature']:
        if value[key]:value[key]={k:v for k,v in value[key].items() if k not in {'session','google_subject'}}
    return encoded(value)


def listing(db,*,q='',state='',page=1,size=25):
    query=select(H)
    if state:query=query.where(H.state==state)
    if q:query=query.where(or_(H.snapshot['official_code'].as_string().contains(q,autoescape=True),H.snapshot['receipt_id'].as_string().contains(q,autoescape=True)))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(H.created_at.desc(),H.id).offset((page-1)*size).limit(size))
    return {'items':[{'id':r.id,'official_code':r.snapshot['official_code'],'receipt_id':r.snapshot['receipt_id'],
        'quantity':str(r.quantity),'state':r.state,'version':r.version,'created_at':r.created_at} for r in rows],
        'total':total,'page':page,'size':size}
