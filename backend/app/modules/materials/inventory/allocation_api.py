"""Native stage-2 API. Existing role matrix and idempotency storage are reused."""
import hashlib
import json
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import select, func, or_, inspect
from pydantic import ValidationError
from app.auth.security import current_user, require
from app.compatibility.models import LegacyRequest
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.modules.materials.inventory import allocation_service as service
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation, AllocationMovement as Link
from app.modules.materials.inventory.allocation_schemas import ReserveInput, EditInput, IssueInput, ReturnInput, ConfirmInput, TransferInput
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.purchasing.models import FilmLine
from app.modules.production.planning_models import ProductionStandard as Standard
from app.modules.production.readiness_service import preparation

router=APIRouter()
PREFIX='/api/production/materials'


def access(user=Depends(current_user),db=Depends(get_db)):
    require(db,user,'PRODUCTION_EDIT')
    return user


def ready(db):
    inspector=inspect(db.connection())
    if not all(inspector.has_table(name) for name in ['production_standards','material_allocations','material_allocation_movements']):
        service.fail('Chưa áp dụng migration 010/011 cho dữ liệu nền và phân bổ nhựa.',503)


def write(db,user,operation,data,key,call):
    ready(db)
    state=service.lock_state(db)
    payload=data.model_dump(mode='json') if hasattr(data,'model_dump') else data
    checksum=hashlib.sha256(json.dumps([operation,payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    try:
        previous=db.get(LegacyRequest,key)
        if previous:
            if previous.user_id!=user.id or previous.payload_hash!=checksum:service.fail('Mã thao tác đã được dùng với nội dung khác.',409)
            return previous.result
        result=jsonable_encoder(call(),custom_encoder={Decimal:str})
        state.revision+=1
        db.add(LegacyRequest(id=key,user_id=user.id,payload_hash=checksum,result=result))
        db.commit()
        return result
    except Exception:
        db.rollback();raise


@router.get('/production/materials')
def page(user=Depends(access)):
    return FileResponse(FRONTEND_ROOT/'production/materials.html')


@router.get('/api/production/preparation')
def listing(q: str=Query('',max_length=200),customer_id: str=Query('',max_length=100),
            start: date|None=None,end: date|None=None,has_hold: bool|None=None,
            standard_id: str|None=Query(None,max_length=36),line_id: str|None=Query(None,max_length=100),
            page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    return preparation(db,q=q,customer_id=customer_id,start=start,end=end,has_hold=has_hold,
                       standard_id=standard_id,line_id=line_id,page=page,size=size)


@router.get(PREFIX+'/sources')
def sources(order_line_id: str,standard_id: str,q: str=Query('',max_length=200),
            page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    ready(db)
    standard=db.get(Standard,standard_id)
    if not standard:service.fail('Không tìm thấy định mức.',404)
    from app.modules.orders.models import OrderLine
    from app.modules.production.planning_models import ProductionStandardItem
    line=db.get(OrderLine,order_line_id)
    if not line or not db.get(ProductionStandardItem,(standard_id,line.product_id)):
        service.fail('Định mức không phù hợp CTĐH.')
    query=select(FilmReceipt.id,FilmReceipt.line_id,FilmReceipt.receipt_date,FilmReceipt.status,
        FilmReceipt.quantity.label('received_kg'),service.stock_expression().label('stock_kg'),
        service.held_expression().label('held_kg'),
        (service.stock_expression()-service.held_expression()).label('available_kg')).join(FilmLine,FilmLine.id==FilmReceipt.line_id)
    query=query.where(FilmLine.material_id==standard.material_id,FilmReceipt.status=='OK')
    if q:query=query.where(or_(FilmReceipt.id.contains(q,autoescape=True),FilmReceipt.line_id.contains(q,autoescape=True)))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[dict(r) for r in db.execute(query.order_by(FilmReceipt.receipt_date,FilmReceipt.id)
            .offset((page-1)*size).limit(size)).mappings()],'total':total,'page':page,'size':size}


@router.get(PREFIX+'/allocations')
def allocations(order_line_id: str,page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),
                user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(Allocation).where(Allocation.order_line_id==order_line_id)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[service.allocation_record(a) for a in db.scalars(query.order_by(Allocation.created_at,Allocation.id)
        .offset((page-1)*size).limit(size))],'total':total,'page':page,'size':size}


@router.get(PREFIX+'/allocations/{identifier}/movements')
def movements(identifier: str,page: int=Query(1,ge=1),size: int=Query(25,ge=1,le=100),
              user=Depends(access),db=Depends(get_db)):
    ready(db)
    query=select(Link,FilmMovement).join(FilmMovement,FilmMovement.id==Link.movement_id).where(Link.allocation_id==identifier)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(FilmMovement.moved_at,FilmMovement.id).offset((page-1)*size).limit(size)).all()
    from app.modules.production.models import ProductionOrder
    codes=dict(db.execute(select(ProductionOrder.id,ProductionOrder.official_code).where(
        ProductionOrder.id.in_([m.production_order_id for link,m in rows]))).all())
    return {'items':[{'id':m.id,'kind':m.kind,'kg':str(m.quantity),'receipt_id':m.receipt_id,'production_order_id':m.production_order_id,
                     'production_order_code':codes.get(m.production_order_id),
                     'source_issue_id':link.issue_id,'transfer_id':link.transfer_id,'confirmed':bool(m.receiver_id),
                     'mode':link.mode,'note':m.note,'moved_at':m.moved_at} for link,m in rows],
            'total':total,'page':page,'size':size}


KeyHeader=Header(alias='Idempotency-Key',min_length=16,max_length=64)


@router.post(PREFIX+'/allocations',status_code=201)
def reserve(data: ReserveInput,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    return write(db,user,'reserve',data,key,lambda:service.reserve(db,user,data))


@router.put(PREFIX+'/allocations/{identifier}')
def edit(identifier: str,data: EditInput,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    return write(db,user,'edit:'+identifier,data,key,lambda:service.edit(db,user,identifier,data))


@router.post(PREFIX+'/allocations/{identifier}/issue',status_code=201)
def issue(identifier: str,data: IssueInput,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    from app.modules.materials.inventory import handover_service
    from app.modules.materials.inventory.handover_api import ready as handover_ready
    handover_ready(db)
    return write(db,user,'handover:issue-draft:'+identifier,data,key,lambda:handover_service.create_issue(db,user,identifier,data))


@router.post(PREFIX+'/issues/{identifier}/return',status_code=201)
def return_request(identifier: str,data: ReturnInput,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    return write(db,user,'return:'+identifier,data,key,lambda:service.request_return(db,user,identifier,data))


@router.post(PREFIX+'/issues/{identifier}/sync-return')
def sync(identifier: str,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    return write(db,user,'sync:'+identifier,{},key,lambda:service.sync_return(db,user,identifier))


@router.post(PREFIX+'/returns/{identifier}/confirm')
def confirm(identifier: str,data: ConfirmInput,key: str=KeyHeader,user=Depends(current_user),db=Depends(get_db)):
    require(db,user,'NVL_RECEIVE');require(db,user,'NVL_STOCK_VIEW')
    return write(db,user,'confirm:'+identifier,data,key,lambda:service.confirm_return(db,user,identifier,data.kg))


@router.post(PREFIX+'/issues/{identifier}/transfer',status_code=201)
def transfer(identifier: str,data: TransferInput,key: str=KeyHeader,user=Depends(access),db=Depends(get_db)):
    # Draft only; signing later performs the atomic return/reissue with warehouse authority.
    require(db,user,'NVL_RECEIVE');require(db,user,'NVL_STOCK_VIEW')
    from app.modules.materials.inventory import handover_service
    from app.modules.materials.inventory.handover_api import ready as handover_ready
    handover_ready(db)
    return write(db,user,'handover:transfer-draft:'+identifier,data,key,lambda:handover_service.create_transfer(db,user,identifier,data))


@router.get(PREFIX+'/production-orders')
def production_orders(order_line_id: str,q: str=Query('',max_length=100),page: int=Query(1,ge=1),
                      size: int=Query(25,ge=1,le=100),user=Depends(access),db=Depends(get_db)):
    from app.modules.production.models import ProductionOrder
    from app.modules.production.run_models import ProductionOrderItem
    query=select(ProductionOrder.id,ProductionOrder.official_code,ProductionOrder.machine_id,ProductionOrder.product_id,ProductionOrder.status).where(
        ProductionOrder.release_state=='released',ProductionOrder.status.in_(['Chưa chạy','Đang chạy']),
        ProductionOrder.id.in_(select(ProductionOrderItem.run_id).where(
            ProductionOrderItem.order_line_id==order_line_id,ProductionOrderItem.enabled.is_(True),
            ProductionOrderItem.completed_qty<ProductionOrderItem.planned_qty)))
    if q:query=query.where(ProductionOrder.official_code.contains(q,autoescape=True))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items':[dict(r) for r in db.execute(query.order_by(ProductionOrder.id).offset((page-1)*size).limit(size)).mappings()],
            'total':total,'page':page,'size':size}


def dispatch_legacy(db,user,method,args,request_id):
    """Only native linked movements bypass JS; unlinked historical returns retain their flow."""
    if method not in {'confirmFilmReturn','syncFilmReturnFromJournal'}:return None
    if not inspect(db.connection()).has_table('material_allocations'):return None
    data=(args or [None])[0]
    identifier=data.get('id') if method=='confirmFilmReturn' and isinstance(data,dict) else data
    if not isinstance(identifier,str) or not db.get(Link,identifier):return None
    if method=='confirmFilmReturn':
        require(db,user,'NVL_RECEIVE');require(db,user,'NVL_STOCK_VIEW')
        try:
            payload=ConfirmInput(kg=data.get('kg'))
        except ValidationError:
            service.fail('Số kg xác nhận trả không hợp lệ.')
        result=write(db,user,'confirm:'+identifier,payload,request_id,lambda:service.confirm_return(db,user,identifier,payload.kg))
    else:
        require(db,user,'PRODUCTION_EDIT')
        result=write(db,user,'sync:'+identifier,{},request_id,lambda:service.sync_return(db,user,identifier))
    return {'result':result,'revision':service.lock_state(db).revision}
