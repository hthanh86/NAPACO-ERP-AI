"""Paginated order-line preparation, using authoritative produced quantity."""
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from sqlalchemy import select, func, or_, inspect
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.orders.models import Order, OrderLine
from app.modules.production.models import ProductionOrder
from app.modules.production.planning_models import ProductionStandard as Standard, ProductionStandardItem as Item
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_models import MaterialAllocation as Allocation, AllocationMovement as Link
from app.modules.materials.inventory import allocation_service as materials
from app.modules.materials.purchasing.models import FilmLine, FilmPO
from app.modules.materials.receiving.models import FilmReceipt


def preparation(db,*,q='',customer_id='',start=None,end=None,has_hold=None,standard_id=None,line_id=None,page=1,size=25):
    delivery=func.coalesce(OrderLine.delivery_date,Order.delivery_date)
    query=(select(OrderLine.id,OrderLine.product_id,OrderLine.quantity,OrderLine.produced,OrderLine.delivered,
        OrderLine.unit,OrderLine.film_line_id,Order.id.label('order_id'),Order.po_number,
        Customer.id.label('customer_id'),Customer.name.label('customer_name'),Product.name.label('product_name'),
        delivery.label('delivery_date')).join(Order,Order.id==OrderLine.order_id)
        .join(Customer,Customer.id==Order.customer_id).outerjoin(Product,Product.id==OrderLine.product_id)
        .where(OrderLine.quantity>OrderLine.produced))
    if q:
        query=query.where(or_(*[col.contains(q,autoescape=True) for col in [OrderLine.id,Order.po_number,Product.name,Customer.name,Order.id]]))
    if customer_id:query=query.where(Order.customer_id==customer_id)
    if start:query=query.where(delivery>=start)
    if end:query=query.where(delivery<=end)
    if start and end and start>end:materials.fail('Từ ngày phải trước đến ngày.')
    holds=select(Allocation.id).where(Allocation.order_line_id==OrderLine.id,Allocation.held_kg>0).exists()
    if has_hold is not None:query=query.where(holds if has_hold else ~holds)
    if line_id:query=query.where(OrderLine.id==line_id)
    if standard_id:query=query.where(OrderLine.product_id.in_(select(Item.product_id).where(Item.standard_id==standard_id)))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=[dict(r) for r in db.execute(query.order_by(delivery,OrderLine.id).offset((page-1)*size).limit(size)).mappings()]
    if not rows:return {'items':[],'total':total,'page':page,'size':size}
    line_ids=[r['id'] for r in rows];product_ids={r['product_id'] for r in rows if r['product_id']}
    scheduled={}
    if inspect(db.connection()).has_table('production_order_items'):
        from app.modules.production.run_models import ProductionOrderItem
        scheduled=dict(db.execute(select(ProductionOrderItem.order_line_id,
            func.sum(ProductionOrderItem.planned_qty-ProductionOrderItem.completed_qty)).join(ProductionOrder,
            ProductionOrder.id==ProductionOrderItem.run_id).where(ProductionOrderItem.order_line_id.in_(line_ids),
            ProductionOrder.status.in_(['Chưa chạy','Đang chạy']),ProductionOrderItem.enabled.is_(True)).group_by(ProductionOrderItem.order_line_id)).all())
    allocations=db.scalars(select(Allocation).where(Allocation.order_line_id.in_(line_ids))).all()
    by_line=defaultdict(list)
    for a in allocations:by_line[a.order_line_id].append(a)
    receipt_balances=materials.receipt_balances(db,{a.receipt_id for a in allocations})
    latest=select(Standard.code,func.max(Standard.revision).label('revision')).group_by(Standard.code).subquery()
    options=db.execute(select(Standard,Item).join(Item,Item.standard_id==Standard.id).join(latest,
        (latest.c.code==Standard.code)&(latest.c.revision==Standard.revision))
        .where(Item.product_id.in_(product_ids),Standard.active.is_(True)).order_by(Standard.code)).all()
    by_product=defaultdict(list)
    for standard,item in options:by_product[item.product_id].append((standard,item))
    # Include explicitly selected historical version for existing reservation inspection.
    if standard_id and not any(s.id==standard_id for s,i in options):
        for standard,item in db.execute(select(Standard,Item).join(Item,Item.standard_id==Standard.id)
                .where(Standard.id==standard_id,Item.product_id.in_(product_ids))):by_product[item.product_id].append((standard,item))
    issue_ct=func.coalesce(Allocation.order_line_id,ProductionOrder.order_line_id)
    issued=db.execute(select(FilmMovement,Link,issue_ct).join(ProductionOrder,
        ProductionOrder.id==FilmMovement.production_order_id).outerjoin(Link,Link.movement_id==FilmMovement.id)
        .outerjoin(Allocation,Allocation.id==Link.allocation_id)
        .where(issue_ct.in_(line_ids),func.upper(func.trim(FilmMovement.kind))=='CẤP NVL')).all()
    tracked=[m for m,link,ct in issued if link]
    balances=materials.issue_balances(db,tracked)
    codes=dict(db.execute(select(ProductionOrder.id,ProductionOrder.official_code).where(
        ProductionOrder.id.in_([m.production_order_id for m in tracked]))).all())
    issues_by_line=defaultdict(list)
    for movement,link,ct in issued:issues_by_line[ct].append((movement,link))
    expected_ids={r['film_line_id'] for r in rows if r['film_line_id']}
    received=select(FilmReceipt.line_id,func.sum(FilmReceipt.quantity).label('kg')).group_by(FilmReceipt.line_id).subquery()
    expected={r['id']:dict(r) for r in db.execute(select(FilmLine.id,FilmLine.po_id,FilmLine.material_id,
        FilmLine.quantity.label('ordered_kg'),func.coalesce(received.c.kg,0).label('received_kg'),
        FilmLine.delivery_date,FilmLine.status).outerjoin(received,received.c.line_id==FilmLine.id)
        .outerjoin(FilmPO,FilmPO.id==FilmLine.po_id).where(FilmLine.id.in_(expected_ids),
            or_(FilmPO.status.is_(None),FilmPO.status!='Hủy'),FilmLine.status!='Hủy')).mappings()}
    for row in rows:
        remaining=max(materials.ZERO,materials.decimal(row['quantity'])-materials.decimal(row['produced']))
        row['remaining_to_produce']=str(remaining)
        row['scheduled_remaining_qty']=str(scheduled.get(row['id'],0))
        row['available_to_schedule']=str(max(materials.ZERO,remaining-Decimal(str(scheduled.get(row['id'],0)))))
        candidates=by_product[row['product_id']]
        row['standard_options']=[{'id':s.id,'code':s.code,'revision':s.revision,'material_id':s.material_id,
            'cavity':i.cavity,'active':s.active} for s,i in candidates]
        selected=next(((s,i) for s,i in candidates if s.id==standard_id),None) if standard_id else (candidates[0] if len(candidates)==1 else None)
        row['selected_standard_id']=selected[0].id if selected else None
        row['demand_status']='defined' if selected else 'choose_standard' if candidates else 'missing_standard'
        demand=None
        if selected:
            standard,item=selected
            if row['unit'].strip().casefold()!=str(item.snapshot.get('unit','')).strip().casefold():
                row['demand_status']='unit_mismatch'
            else:
                sheets=(remaining/materials.decimal(item.cavity)).to_integral_value(rounding=ROUND_CEILING)
                base=materials.decimal(standard.parameters['sheet_weight_kg'])*sheets
                waste=base*materials.decimal(standard.parameters['waste_percent'])/100
                demand={'sheets':str(sheets),'sheet_weight_kg':str(standard.parameters['sheet_weight_kg']),
                    'base_kg':str(base.quantize(materials.SCALE,rounding=ROUND_CEILING)),
                    'waste_kg':str(waste.quantize(materials.SCALE,rounding=ROUND_CEILING)),
                    'total_kg':str((base+waste).quantize(materials.SCALE,rounding=ROUND_CEILING)),
                    'waste_percent':standard.parameters['waste_percent'],'material_id':standard.material_id}
        row['demand']=demand
        all_holds=sum((a.held_kg for a in by_line[row['id']]),materials.ZERO)
        usable=sum((a.held_kg for a in by_line[row['id']] if receipt_balances.get(a.receipt_id,{}).get('eligible') and
            (not demand or receipt_balances[a.receipt_id]['material_id']==demand['material_id'])),materials.ZERO)
        row['held_kg']=str(all_holds);row['usable_held_kg']=str(usable)
        row['allocations']=[materials.allocation_record(a) for a in by_line[row['id']]]
        issued_kg=materials.ZERO;at_machine=materials.ZERO;unknown=False;has_issue=False
        untracked=materials.ZERO
        row['issues']=[]
        for movement,link in issues_by_line[row['id']]:
            has_issue=True;issued_kg+=materials.decimal(movement.quantity)
            b=balances.get(movement.id)
            if not link or not b:
                unknown=True;untracked+=materials.decimal(movement.quantity)
            elif b['at_machine_kg'] is None:unknown=True
            elif demand:
                a=next((a for a in by_line[row['id']] if a.id==link.allocation_id),None)
                if a and receipt_balances.get(a.receipt_id,{}).get('material_id')==demand['material_id']:
                    at_machine+=b['at_machine_kg']
            else:at_machine+=b['at_machine_kg']
            row['issues'].append({'id':movement.id,'receipt_id':movement.receipt_id,'production_order_id':movement.production_order_id,
                'official_code':codes.get(movement.production_order_id),
                'handover_id':b['handover_id'] if b else None,'handover_state':b['handover_state'] if b else 'legacy_unverified',
                'received_signed_kg':str(b['received_signed_kg']) if b else '0',
                'pending_handover_kg':str(b['pending_handover_kg']) if b else '0',
                'allocation_id':link.allocation_id if link else None,'issued_kg':str(movement.quantity),
                'at_machine_kg':str(b['at_machine_kg']) if b and b['at_machine_kg'] is not None else None,
                'balance_status':b['balance_status'] if b else 'unknown','pending_return_kg':str(b['pending_return_kg']) if b else None})
        row['issued_kg']=str(issued_kg);row['untracked_issued_kg']=str(untracked)
        row['at_machine_kg']=None if unknown else str(at_machine)
        row['machine_balance_status']='unknown' if unknown else 'estimated' if has_issue else 'none'
        exp=expected.get(row['film_line_id'])
        if exp:
            exp={**exp,'unreceived_kg':str(max(materials.ZERO,materials.decimal(exp['ordered_kg'])-materials.decimal(exp['received_kg'])))}
        row['expected_source']=exp if exp and Decimal(exp['unreceived_kg'])>0 else None
        row['material_status']='unknown';row['shortage_kg']=None;row['surplus_kg']=None;row['estimated_shortage_kg']=None
        if demand:
            need=Decimal(demand['total_kg'])
            row['shortage_kg']=str(max(materials.ZERO,need-usable))
            row['surplus_kg']=str(max(materials.ZERO,usable-need))
            row['estimated_shortage_kg']=None if unknown else str(max(materials.ZERO,need-usable-at_machine))
            row['material_status']='enough' if usable>=need else 'partial' if usable>0 or unknown or at_machine>0 else 'none'
    return {'items':rows,'total':total,'page':page,'size':size,
        'note':'Đủ nhựa dựa trên phần giữ đủ điều kiện. Số tại máy từ nhật ký chỉ là ước tính; không dùng tổng đã cấp thay số dư.'}
