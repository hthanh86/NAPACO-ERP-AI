"""Material reservations. Caller owns permission checks and commit/rollback.

Every write takes legacy_state first, then receipt locks. The same serialization
boundary is used by existing receipt/return writes. Physical stock uses one ledger.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from uuid import uuid4
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, func, or_, inspect
from app.compatibility.models import LegacyState
from app.core.models import Audit
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.stock import stock_expression
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation, AllocationMovement as Link
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.models import FilmMaterial
from app.modules.materials.purchasing.models import FilmLine
from app.modules.orders.models import OrderLine
from app.modules.production.models import ProductionOrder, FormingLog
from app.modules.production.planning_models import ProductionStandard as Standard, ProductionStandardItem as StandardItem

ZERO = Decimal('0')
SCALE = Decimal('0.00000001')


def fail(message,status=422):
    raise HTTPException(status,message)


def decimal(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result<0: raise ValueError()
        return result
    except (InvalidOperation,ValueError,TypeError):
        fail('Số lượng không hợp lệ; cần đối soát dữ liệu nguồn.')


def lock_state(db):
    state = db.scalar(select(LegacyState).where(LegacyState.id==1).with_for_update())
    if not state: fail('Chưa khởi tạo ERP.',503)
    return state


def held_expression(exclude_ids=()):
    query = select(func.coalesce(func.sum(Allocation.held_kg),0)).where(Allocation.receipt_id==FilmReceipt.id)
    if exclude_ids: query=query.where(~Allocation.id.in_(exclude_ids))
    return query.correlate(FilmReceipt).scalar_subquery()


def receipt_balances(db,receipt_ids,exclude_ids=()):
    if not receipt_ids:return {}
    statement = (select(FilmReceipt.id,FilmReceipt.status,FilmReceipt.quantity,
        FilmLine.material_id,stock_expression().label('stock_kg'),held_expression(exclude_ids).label('held_kg'))
        .outerjoin(FilmLine,FilmLine.id==FilmReceipt.line_id).where(FilmReceipt.id.in_(receipt_ids)))
    result={}
    for row in db.execute(statement).mappings():
        stock=Decimal(str(row['stock_kg']));held=decimal(row['held_kg'])
        result[row['id']]={**dict(row),'stock_kg':stock,'held_kg':held,'available_kg':stock-held,
                           'eligible':row['status']=='OK' and row['material_id'] is not None}
    return result


def ensure_available(db,required,*,own_allocation_ids=(),order_line_id=None,order_line_ids=(),lock=True):
    """Reusable by plan-save: lock and assert free kg, optionally credit own holds.

    Caller must authorize CTDH, validate recipe/material and keep this transaction
    open through saving the plan/reservation. Never credit another order's holds.
    """
    identifiers=sorted(required)
    if lock:
        lock_state(db)
        db.scalars(select(FilmReceipt).where(FilmReceipt.id.in_(identifiers)).order_by(FilmReceipt.id).with_for_update()).all()
    if own_allocation_ids:
        owns=db.scalars(select(Allocation).where(Allocation.id.in_(own_allocation_ids))).all()
        allowed=set(order_line_ids)|({order_line_id} if order_line_id else set())
        if not allowed or len(owns)!=len(set(own_allocation_ids)) or any(
            a.order_line_id not in allowed or a.receipt_id not in required for a in owns):
            fail('Phần giữ được bù phải thuộc đúng CTĐH và nguồn nhập.')
    balances=receipt_balances(db,identifiers,own_allocation_ids)
    for identifier,kg in required.items():
        balance=balances.get(identifier)
        if not balance or not balance['eligible']:fail(identifier+': nguồn nhập không đủ điều kiện sử dụng.')
        if decimal(kg)>balance['available_kg']:fail(identifier+': khả dụng không đủ sau khi trừ lượng đang giữ.',409)
    return balances


def audit(db,user,action,identifier,details):
    db.add(Audit(user_id=user.id,action=action,entity_id=identifier,details=details))


def allocation_record(a):
    return {'id':a.id,'receipt_id':a.receipt_id,'order_line_id':a.order_line_id,'standard_id':a.standard_id,
            'held_kg':str(a.held_kg),'version':a.version,'note':a.note}


def target(db,order_line_id,standard_id,receipt_id,*,new=True):
    line=db.scalar(select(OrderLine).where(OrderLine.id==order_line_id).with_for_update())
    standard=db.get(Standard,standard_id)
    if not line or not standard:fail('CTĐH hoặc định mức không tồn tại.')
    item=db.get(StandardItem,(standard_id,line.product_id)) if line.product_id else None
    if not item:fail('Định mức không có sản phẩm của CTĐH.')
    from app.modules.production.forming_units import is_piece_unit
    if not is_piece_unit(line.unit):
        fail(f'{line.id}: định hình dùng Cái/Chiếc; CTĐH đang dùng "{line.unit}". Không tự quy đổi từ đơn vị bế.')
    if new:
        latest=db.scalar(select(func.max(Standard.revision)).where(Standard.code==standard.code))
        if not standard.active:fail('Phiên bản định mức này đã ngừng sử dụng.')
        if decimal(line.quantity)<=decimal(line.produced):fail('CTĐH không còn số lượng phải sản xuất.')
    source=db.execute(select(FilmReceipt,FilmLine.material_id).outerjoin(FilmLine,FilmLine.id==FilmReceipt.line_id)
        .where(FilmReceipt.id==receipt_id)).first()
    if not source or not source.material_id or not db.get(FilmMaterial,source.material_id):fail('Nguồn nhập không có thông tin NVL hợp lệ.')
    return line,standard,item


def reservation_standard(db,order_line_id,standard_id=None):
    """Resolve the existing schema reference; it never chooses an LSX to issue to."""
    if standard_id:return standard_id
    line=db.get(OrderLine,order_line_id)
    if not line:fail('Không tìm thấy CTĐH.',404)
    from app.modules.production.run_models import ProductionOrderItem
    linked=db.scalar(select(Standard.id).join(ProductionOrder,ProductionOrder.standard_id==Standard.id).join(
        ProductionOrderItem,ProductionOrderItem.run_id==ProductionOrder.id).where(
        ProductionOrderItem.order_line_id==order_line_id,ProductionOrderItem.enabled.is_(True),
        ProductionOrder.status.in_(['Chưa chạy','Đang chạy']),Standard.active.is_(True)).order_by(Standard.id).limit(1))
    if linked:return linked
    candidate=db.scalar(select(Standard.id).join(StandardItem,StandardItem.standard_id==Standard.id).where(
        StandardItem.product_id==line.product_id,Standard.active.is_(True)).order_by(Standard.code,Standard.revision.desc()).limit(1))
    if not candidate:fail('CTĐH chưa có cấu hình sản xuất để liên kết phần giữ; lập kế hoạch cho sản phẩm trước.')
    return candidate


def reserve(db,user,data):
    standard_id=reservation_standard(db,data.order_line_id,data.standard_id)
    target(db,data.order_line_id,standard_id,data.receipt_id)
    ensure_available(db,{data.receipt_id:data.kg})
    a=Allocation(id=str(uuid4()),receipt_id=data.receipt_id,order_line_id=data.order_line_id,
                 standard_id=standard_id,held_kg=data.kg,version=1,note=data.note,created_by=user.id)
    db.add(a);db.flush()
    source_material_id=db.scalar(select(FilmLine.material_id).join(FilmReceipt,FilmReceipt.line_id==FilmLine.id).where(FilmReceipt.id==a.receipt_id))
    audit(db,user,'MATERIAL_RESERVE',a.id,{**allocation_record(a),'source_material_id':source_material_id})
    return allocation_record(a)


def allocation_lock(db,identifier,version=None):
    a=db.scalar(select(Allocation).where(Allocation.id==identifier).with_for_update())
    if not a:fail('Không tìm thấy phân bổ.',404)
    if version is not None and version!=a.version:fail('Phân bổ đã thay đổi; tải lại trước khi thao tác.',409)
    return a


def edit(db,user,identifier,data):
    a=allocation_lock(db,identifier,data.version)
    from app.modules.materials.inventory.handover_service import reserved
    if data.held_kg<reserved(db,a.id):fail('Lượng giữ đã có phiếu bàn giao nháp; hủy phiếu trước khi giảm.',409)
    previous=a.held_kg
    if inspect(db.connection()).has_table('production_run_materials'):
        from app.modules.production.run_service import protect_hold
        protect_hold(db,a,data.held_kg)
    if data.held_kg>a.held_kg:
        target(db,a.order_line_id,a.standard_id,a.receipt_id)
        ensure_available(db,{a.receipt_id:data.held_kg-a.held_kg})
    a.held_kg=data.held_kg;a.version+=1;a.note=data.note
    audit(db,user,'MATERIAL_RESERVE_EDIT',a.id,{'before_kg':str(previous),'after_kg':str(a.held_kg),'reason':data.note})
    db.flush();return allocation_record(a)


def production_order(db,a,identifier):
    order=db.scalar(select(ProductionOrder).where(ProductionOrder.id==identifier).with_for_update())
    from app.modules.production.release_service import require_released
    require_released(order)
    line=db.get(OrderLine,a.order_line_id)
    if order and order.run_snapshot:
        from app.modules.production.run_models import ProductionOrderItem
        item=db.get(ProductionOrderItem,(identifier,a.order_line_id))
        if not item or not item.enabled or item.product_id!=line.product_id:fail('CTĐH/sản phẩm không thuộc phần được thực hiện của LSX.')
        return order
    if not order or order.order_line_id!=a.order_line_id or order.product_id!=line.product_id:
        fail('LSX phải thuộc đúng CTĐH và sản phẩm được phân bổ.')
    return order


def new_movement(db,user,a,kg,kind,order_id,*,issue_id=None,mode='issue',transfer_id=None,note='',confirmed=False,extra=None):
    order=db.get(ProductionOrder,order_id)
    if order and order.run_snapshot:order.version+=1
    movement=FilmMovement(id=('MV_CAP_' if kind=='CẤP NVL' else 'MV_TRA_')+str(uuid4()),
        moved_at=datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M:%S'),
        kind=kind,production_order_id=order_id,receipt_id=a.receipt_id,quantity=kg,
        issuer_id=user.id,receiver_id=user.id if kind=='TRẢ NVL' and confirmed else '',
        qc_id='',note=note,source={})
    db.add(movement);db.flush()
    db.add(Link(movement_id=movement.id,allocation_id=a.id,issue_id=issue_id,mode=mode,transfer_id=transfer_id,
        snapshot={'receipt_id':a.receipt_id,'production_order_id':order_id,'quantity_kg':str(kg),**(extra or {})}))
    db.flush();return movement


def issue(db,user,identifier,data,*,handover=None):
    if not handover or handover.state!='draft' or not handover.issue_signature or handover.run_id!=data.production_order_id or handover.quantity!=data.kg:
        fail('Cấp NVL phải được Ký cấp trên phiếu bàn giao.',409)
    a=allocation_lock(db,identifier,data.version)
    from app.modules.materials.inventory.handover_service import reserved
    if data.kg+reserved(db,a.id,exclude=handover.id)>a.held_kg:fail('Phần giữ đã cam kết cho phiếu bàn giao khác.',409)
    if data.kg>a.held_kg:fail('Số kg cấp vượt phần chưa cấp đang giữ.',409)
    target(db,a.order_line_id,a.standard_id,a.receipt_id,new=False)
    order=production_order(db,a,data.production_order_id)
    if order.run_snapshot:
        from app.modules.production.run_service import before_issue
        before_issue(db,a,order,data.kg)
    ensure_available(db,{a.receipt_id:data.kg},own_allocation_ids=[a.id],order_line_id=a.order_line_id)
    a.held_kg-=data.kg;a.version+=1
    movement=new_movement(db,user,a,data.kg,'CẤP NVL',data.production_order_id,note=data.note)
    audit(db,user,'MATERIAL_ISSUE',movement.id,{'allocation_id':a.id,'kg':str(data.kg),'receipt_id':a.receipt_id})
    return {'allocation':allocation_record(a),'movement_id':movement.id,'kg':str(data.kg)}


def issue_balances(db,issues):
    """Batch journal estimates; no logs never means the entire issue is still at machine."""
    by_id={m.id:m for m in issues}
    if not by_id:return {}
    returned=db.execute(select(Link,FilmMovement).join(FilmMovement,FilmMovement.id==Link.movement_id)
        .where(Link.issue_id.in_(by_id))).all()
    root={identifier:identifier for identifier in by_id}
    returns=defaultdict(list)
    for link,m in returned:root[m.id]=link.issue_id;returns[link.issue_id].append(m)
    logs=db.scalars(select(FormingLog).where(FormingLog.movement_id.in_(root),FormingLog.shift_snapshot.is_(None))).all()
    used=defaultdict(lambda:ZERO);entries=defaultdict(int);invalid=set()
    for log in logs:
        identifier=root[log.movement_id];entries[identifier]+=1
        try:
            if any(v is None for v in [log.sheet_weight,log.good,log.ng]):raise ValueError()
            weight=decimal(log.sheet_weight);good=decimal(log.good);ng=decimal(log.ng)
            if weight<=0 or good!=good.to_integral_value() or ng!=ng.to_integral_value():raise ValueError()
            # Existing forming journal weight unit is grams/sheet (returns.js divides by 1000).
            used[identifier]+=weight*(good+ng)/1000
        except (HTTPException,ValueError):invalid.add(identifier)
    result={}
    from app.modules.materials.inventory.handover_models import MaterialHandover
    from app.modules.materials.inventory.handover_sources import received
    handovers={h.movement_id:h for h in db.scalars(select(MaterialHandover).where(MaterialHandover.movement_id.in_(by_id)))}
    for identifier,m in by_id.items():
        confirmed=sum((decimal(r.quantity) for r in returns[identifier] if r.receiver_id.strip()),ZERO)
        pending=sum((decimal(r.quantity) for r in returns[identifier] if not r.receiver_id.strip()),ZERO)
        upper=decimal(m.quantity)-confirmed
        complete=entries[identifier]>0 and identifier not in invalid
        estimated=(upper-used[identifier]).quantize(SCALE) if complete else ZERO if upper==0 and not entries[identifier] else None
        if estimated is not None and estimated<0:invalid.add(identifier);estimated=None
        result[identifier]={'issued_kg':decimal(m.quantity),'confirmed_return_kg':confirmed,'pending_return_kg':pending,
            'used_estimate_kg':used[identifier] if complete else None,'at_machine_kg':estimated,
            'balance_status':'estimated' if estimated is not None else 'unknown',
            'upper_kg':upper,'invalid_journal':identifier in invalid,'entries':entries[identifier]}
        doc=handovers.get(identifier)
        result[identifier].update(handover_id=doc.id if doc else None,
            handover_state=doc.state if doc else 'legacy_unverified',
            received_signed_kg=doc.quantity if received(doc) else ZERO,
            pending_handover_kg=doc.quantity if doc and doc.state=='awaiting_receipt' else ZERO)
        if doc and not received(doc):result[identifier].update(at_machine_kg=ZERO,balance_status='awaiting_receipt')
    return result


def linked_issue(db,identifier):
    link=db.get(Link,identifier)
    if not link:fail('Giao dịch không thuộc phân bổ có truy vết.',404)
    source_id=link.issue_id or link.movement_id
    source=db.get(FilmMovement,source_id)
    source_link=db.get(Link,source_id)
    if not source or not source_link or source.kind!='CẤP NVL':fail('Không xác định được lần cấp gốc.')
    from app.modules.materials.inventory.handover_models import MaterialHandover
    from app.modules.materials.inventory.handover_sources import received
    handover=db.scalar(select(MaterialHandover).where(MaterialHandover.movement_id==source.id))
    if handover and not received(handover):fail('NVL chưa ký nhận, không được trả/chuyển từ máy.',409)
    return source,source_link,allocation_lock(db,source_link.allocation_id)


def return_limit(db,source,kg,*,handover=None):
    balance=issue_balances(db,[source])[source.id]
    limit=balance['at_machine_kg'] if balance['at_machine_kg'] is not None else balance['upper_kg']
    if balance['invalid_journal']:fail('Nhật ký không đầy đủ/hợp lệ; đối soát trước khi trả/chuyển.')
    limit-=balance['pending_return_kg']
    from app.modules.production.run_service import source_position
    position=source_position(db,source.production_order_id,source.receipt_id,legacy=balance['handover_state']=='legacy_unverified')
    if position is not None:limit=min(limit,position['kg'])
    from app.modules.materials.inventory.handover_service import transfer_reserved
    committed=transfer_reserved(db,source.id,handover.id if handover else None)
    if kg+committed>limit:fail('Lượng trả/chuyển vượt số dư hoặc đã có phần trả/phiếu chuyển chờ.',409)
    return balance


def request_return(db,user,identifier,data,*,mode='manual_return'):
    source,link,a=linked_issue(db,identifier)
    return_limit(db,source,data.kg)
    movement=new_movement(db,user,a,data.kg,'TRẢ NVL',source.production_order_id,issue_id=source.id,
        mode=mode,note=data.note)
    a.version+=1
    audit(db,user,'MATERIAL_RETURN_PENDING',movement.id,{'source_issue_id':source.id,'kg':str(data.kg),'note':data.note})
    return {'id':movement.id,'kg':str(data.kg),'pending':True,'source_issue_id':source.id}


def sync_return(db,user,identifier):
    source,link,a=linked_issue(db,identifier)
    returns=db.execute(select(Link,FilmMovement).join(FilmMovement,FilmMovement.id==Link.movement_id)
        .where(Link.issue_id==source.id,FilmMovement.receiver_id=='')).all()
    order=db.get(ProductionOrder,source.production_order_id)
    if order and order.run_snapshot:
        if returns:return {'id':returns[0][1].id,'kg':str(returns[0][1].quantity),'changed':False}
        from app.modules.production.run_service import source_position
        balance=issue_balances(db,[source])[source.id]
        position=source_position(db,order.id,source.receipt_id,legacy=balance['handover_state']=='legacy_unverified')
        if not position or not position['as_of']:return {'id':'','kg':0,'changed':False,'unknown':True}
        kg=min(position['kg'],balance['upper_kg']-balance['pending_return_kg'])
        if kg<=0:return {'id':'','kg':0,'changed':False}
        return request_return(db,user,source.id,SimpleNamespace(kg=kg,note='Trả từ số dư ca đã chốt; chờ kho nhận.'),mode='auto_return')
    if any(link.mode!='auto_return' for link,m in returns):
        return {'id':returns[0][1].id,'kg':str(returns[0][1].quantity),'changed':False,'manual':True}
    if len(returns)>1:fail('Có nhiều phiếu trả tự động chờ, cần đối soát.')
    balance=issue_balances(db,[source])[source.id]
    if balance['invalid_journal']:fail('Nhật ký không đủ dữ liệu hợp lệ để tính trả tự động.')
    if balance['at_machine_kg'] is None:return {'id':'','kg':0,'changed':False,'unknown':True}
    kg=balance['at_machine_kg']
    if returns:
        movement=returns[0][1]
        if movement.quantity!=kg:
            movement.quantity=kg;a.version+=1
            audit(db,user,'MATERIAL_RETURN_SYNC',movement.id,{'kg':str(kg),'source_issue_id':source.id})
        db.flush();return {'id':movement.id,'kg':str(kg),'changed':True}
    if kg<=0:return {'id':'','kg':0,'changed':False}
    result=request_return(db,user,source.id,SimpleNamespace(kg=kg,note='Trả tự động từ nhật ký; chờ kho kiểm nhận.'),mode='auto_return')
    return {**result,'changed':True,'used':str(balance['used_estimate_kg'])}


def confirm_return(db,user,identifier,kg):
    movement=db.scalar(select(FilmMovement).where(FilmMovement.id==identifier).with_for_update())
    link=db.get(Link,identifier)
    if not movement or movement.kind!='TRẢ NVL' or not link or not link.issue_id:fail('Không tìm thấy trả nhựa có truy vết.',404)
    if movement.receiver_id.strip():return {'id':identifier,'alreadyConfirmed':True}
    if link.mode=='auto_return':sync_return(db,user,identifier);db.refresh(movement)
    if movement.quantity!=kg or kg<=0:fail('Số kg trả đã thay đổi; tải lại trước khi xác nhận.',409)
    source,source_link,a=linked_issue(db,identifier)
    balance=issue_balances(db,[source])[source.id]
    limit=balance['at_machine_kg'] if balance['at_machine_kg'] is not None else balance['upper_kg']
    if balance['invalid_journal'] or balance['pending_return_kg']>limit:fail('Số trả vượt số dư sau nhật ký; cần đối soát.',409)
    movement.receiver_id=user.id;a.version+=1
    audit(db,user,'MATERIAL_RETURN_CONFIRMED',identifier,{'source_issue_id':source.id,'kg':str(kg)})
    db.flush();return {'id':identifier,'kg':str(kg)}


def transfer(db,user,identifier,data,*,handover=None):
    if not handover or handover.state!='draft' or not handover.issue_signature or handover.mode!='transfer':
        fail('Chuyển NVL phải Ký cấp trên phiếu bàn giao.',409)
    source,link,old=linked_issue(db,identifier)
    if data.kg>data.measured_remaining_kg:fail('Số chuyển vượt số dư kiểm đếm tại máy.')
    balance=return_limit(db,source,data.kg,handover=handover)
    upper=balance['at_machine_kg'] if balance['at_machine_kg'] is not None else balance['upper_kg']
    if data.measured_remaining_kg>upper:fail('Kiểm đếm vượt giới hạn sổ cấp/nhật ký; cần đối soát.')
    target(db,data.order_line_id,data.standard_id,old.receipt_id)
    if data.order_line_id==old.order_line_id and data.production_order_id==source.production_order_id:
        fail('Chọn CTĐH hoặc LSX đích khác lần cấp gốc.')
    group=str(uuid4())
    returned=new_movement(db,user,old,data.kg,'TRẢ NVL',source.production_order_id,issue_id=source.id,
        mode='transfer_return',transfer_id=group,note=data.note,confirmed=True,
        extra={'measured_remaining_kg':str(data.measured_remaining_kg)})
    # A transfer is an atomic confirmed return + reservation + issue of the same receipt.
    allocation=reserve(db,user,SimpleNamespace(receipt_id=old.receipt_id,order_line_id=data.order_line_id,
        standard_id=data.standard_id,kg=data.kg,note=data.note))
    from app.modules.production.run_service import transfer_binding
    transfer_binding(db,data.production_order_id,allocation['id'],data.kg)
    result=issue(db,user,allocation['id'],SimpleNamespace(version=1,kg=data.kg,
        production_order_id=data.production_order_id,note=data.note),handover=handover)
    db.get(Link,result['movement_id']).transfer_id=group
    old.version+=1
    audit(db,user,'MATERIAL_TRANSFER',group,{'from_issue':source.id,'return_id':returned.id,
        'to_issue':result['movement_id'],'kg':str(data.kg),'measured_remaining_kg':str(data.measured_remaining_kg),'note':data.note})
    return {'transfer_id':group,'return_id':returned.id,**result}


def reconcile_legacy(db,touched):
    """Guard existing receipt/return writes against spending held stock.

    Before 011 is installed, preserve all existing workflows. Native linked
    confirmations/sync are dispatched to this service before legacy execution.
    """
    if not any(t['table'] in {'FILM_RECEIPTS','FILM_MOVEMENTS','FILM_LINES'} for t in touched):return
    if not inspect(db.connection()).has_table('material_allocations'):return
    db.flush()
    receipts=set()
    for t in touched:
        if t['table']=='FILM_RECEIPTS':receipts.update(t['ids'])
        elif t['table']=='FILM_MOVEMENTS':
            receipts.update(db.scalars(select(FilmMovement.receipt_id).where(FilmMovement.id.in_(t['ids']))))
        elif t['table']=='FILM_LINES':
            receipts.update(db.scalars(select(FilmReceipt.id).where(FilmReceipt.line_id.in_(t['ids']))))
    balances=receipt_balances(db,receipts)
    for identifier,b in balances.items():
        if b['stock_kg']<b['held_kg']:fail(identifier+': thay đổi làm tồn nhỏ hơn lượng đang giữ.',409)
    traced=select(Link.movement_id).where(Link.allocation_id==Allocation.id).exists()
    affected=db.execute(select(Allocation,Standard.material_id,Audit.details).join(Standard,Standard.id==Allocation.standard_id)
        .outerjoin(Audit,(Audit.entity_id==Allocation.id)&(Audit.action=='MATERIAL_RESERVE'))
        .where(Allocation.receipt_id.in_(receipts),or_(Allocation.held_kg>0,traced))).all()
    # New reservations pin the actual source material. Old reservations were
    # required to match the standard, so retain that original fallback.
    if any(balances[a.receipt_id]['material_id']!=((details or {}).get('source_material_id') or material_id) for a,material_id,details in affected):
        fail('Không đổi vật liệu của nguồn nhập đang được giữ hoặc đã cấp.',409)
    changed=[identifier for t in touched if t['table']=='FILM_MOVEMENTS' for identifier in t['ids']]
    from app.modules.materials.inventory.handover_models import MaterialHandover
    handovers={h.movement_id:h for h in db.scalars(select(MaterialHandover).where(MaterialHandover.movement_id.in_(changed)))}
    for link,movement in db.execute(select(Link,FilmMovement).join(FilmMovement,FilmMovement.id==Link.movement_id)
            .where(Link.movement_id.in_(changed))).all():
        snapshot=link.snapshot
        if movement.receipt_id!=snapshot['receipt_id'] or movement.production_order_id!=snapshot['production_order_id']:
            fail('Không đổi nguồn/LSX của giao dịch đã có truy vết.',409)
        if link.mode=='issue' and (movement.kind!='CẤP NVL' or movement.quantity!=decimal(snapshot['quantity_kg'])):
            fail('Không sửa số kg của lần cấp đã có truy vết; dùng trả/chuyển.',409)
        doc=handovers.get(movement.id)
        if doc and (movement.issuer_id!=doc.issued_by or movement.receiver_id!=(doc.received_by or '')):
            fail('Không sửa người cấp/nhận qua đường tương thích; phải ký trên hồ sơ bàn giao.',409)
