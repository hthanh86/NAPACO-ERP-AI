"""Batch source accounting: warehouse issue is not production receipt.

Historical balances remain visible separately; receiver_id alone is never proof.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_models import AllocationMovement as Link
from app.modules.materials.inventory.handover_models import MaterialHandover as Handover
from app.modules.production.models import FormingLog
from app.modules.production.run_models import ShiftMaterial

ZERO=Decimal(0)


def received(doc):
    return bool(doc and doc.state=='received' and doc.received_at and doc.issued_at and doc.issued_by and
        doc.received_by and doc.issue_signature and doc.receipt_signature)


def source_hash(context):
    from app.modules.qc.mapping import digest
    def number(value):return format(Decimal(str(value)).normalize(),'f')
    return digest({'run_id':context['run_id'],'previous_end':context['previous_end'].isoformat() if context['previous_end'] else None,
        'sources':[{'receipt_id':row['receipt_id'],**{key:number(row[key]) for key in ['opening_kg','input_kg','output_kg']},
            'movements':sorted(row['movements'])} for row in sorted(context['sources'],key=lambda row:row['receipt_id'])]})


def source_contexts(db,run_ids,*,logs=None,materials=None,exclude_log=None,until=None):
    ids=list(set(run_ids))
    if not ids:return {}
    if logs is None:
        logs=list(db.scalars(select(FormingLog).where(FormingLog.production_order_id.in_(ids),
            FormingLog.shift_snapshot.is_not(None),FormingLog.id!=(exclude_log or '')).order_by(FormingLog.shift_end,FormingLog.id)))
    logs=[l for l in logs if l.id!=exclude_log and l.shift_snapshot]
    if any(not l.shift_start or not l.shift_end for l in logs):
        from app.modules.materials.inventory.allocation_service import fail
        fail('Nhật ký nguồn thiếu thời gian chốt; cần đối soát trước khi dùng số dư.',409)
    if until is not None:logs=[l for l in logs if l.shift_end<=until]
    if materials is None:
        materials=list(db.scalars(select(ShiftMaterial).where(ShiftMaterial.log_id.in_([l.id for l in logs]))))
    by_log=defaultdict(list)
    for s in materials:by_log[s.log_id].append(s)
    by_run=defaultdict(list)
    for log in logs:by_run[log.production_order_id].append(log)
    moves=list(db.scalars(select(FilmMovement).where(FilmMovement.production_order_id.in_(ids)).order_by(FilmMovement.moved_at,FilmMovement.id)))
    docs={h.movement_id:h for h in db.scalars(select(Handover).where(Handover.movement_id.in_([m.id for m in moves])))}
    roots=dict(db.execute(select(Link.movement_id,Link.issue_id).where(Link.movement_id.in_([m.id for m in moves]),Link.issue_id.is_not(None))).all())
    moves_by_run=defaultdict(list)
    for m in moves:moves_by_run[m.production_order_id].append(m)
    for m in moves:
        h=docs.get(m.id)
        if h and (h.quantity!=m.quantity or h.run_id!=m.production_order_id or h.snapshot['receipt_id']!=m.receipt_id or
                m.kind!='CẤP NVL' or m.issuer_id!=h.issued_by or m.receiver_id!=(h.received_by or '')):
            from app.modules.materials.inventory.allocation_service import fail
            fail('Phiếu cấp không khớp nội dung bàn giao đã ký; cần đối soát.',409)
    result={}
    def source(receipt,opening=ZERO):
        return {'receipt_id':receipt,'opening_kg':str(opening),'input_kg':'0','output_kg':'0','movements':[]}
    for identifier in ids:
        history=sorted(by_run[identifier],key=lambda l:(l.shift_end,l.id))
        latest=history[-1] if history else None
        legacy_logs=[l for l in history if (l.shift_snapshot or {}).get('handover_source_version')!=1]
        legacy_latest=legacy_logs[-1] if legacy_logs else None
        assigned={mid for log in history for s in by_log[log.id] for mid in s.movements}
        legacy_assigned={mid for log in legacy_logs for s in by_log[log.id] for mid in s.movements}
        sources={s.receipt_id:source(s.receipt_id,s.closing_kg) for s in by_log[latest.id]} if latest and latest.shift_snapshot.get('handover_source_version')==1 else {}
        legacy={s.receipt_id:source(s.receipt_id,s.closing_kg) for s in by_log[legacy_latest.id]} if legacy_latest else {}
        totals=defaultdict(lambda:{'issued_signed_kg':ZERO,'pending_handover_kg':ZERO,'received_signed_kg':ZERO,
            'confirmed_return_kg':ZERO,'pending_return_kg':ZERO,'consumed_kg':ZERO,'legacy_issued_kg':ZERO})
        for log in history:
            if log.shift_snapshot.get('handover_source_version')==1:
                for s in by_log[log.id]:totals[s.receipt_id]['consumed_kg']+=s.consumed_kg
        for m in moves_by_run[identifier]:
            if m.kind not in {'CẤP NVL','TRẢ NVL'}:continue
            h=docs.get(m.id) if m.kind=='CẤP NVL' else docs.get(roots.get(m.id))
            signed=received(h)
            try:stamp=datetime.strptime(m.moved_at,'%Y-%m-%d %H:%M:%S')
            except (ValueError,TypeError):
                from app.modules.materials.inventory.allocation_service import fail
                fail('Giao dịch có thời gian không hợp lệ; cần đối soát.')
            effective=h.received_at if signed and m.kind=='CẤP NVL' else stamp
            if m.kind=='CẤP NVL':
                if h:
                    totals[m.receipt_id]['issued_signed_kg']+=m.quantity
                    if h.state=='awaiting_receipt':totals[m.receipt_id]['pending_handover_kg']+=m.quantity
                    if signed and (until is None or effective<=until):totals[m.receipt_id]['received_signed_kg']+=m.quantity
                else:totals[m.receipt_id]['legacy_issued_kg']+=m.quantity
            elif signed and (until is None or effective<=until):
                totals[m.receipt_id]['confirmed_return_kg' if m.receiver_id.strip() else 'pending_return_kg']+=m.quantity
            if until and effective>until:continue
            if signed:
                if m.id in assigned:continue
                row=sources.setdefault(m.receipt_id,source(m.receipt_id))
            elif h:
                # Pending receipt has left the warehouse but is never a usable input.
                continue
            else:
                if m.id in legacy_assigned:continue
                row=legacy.setdefault(m.receipt_id,source(m.receipt_id))
            key='input_kg' if m.kind=='CẤP NVL' else 'output_kg'
            row[key]=str(Decimal(row[key])+m.quantity);row['movements'].append(m.id)
        lots=[]
        for receipt in sorted(set(totals)|set(sources)|set(legacy)):
            s=sources.get(receipt,source(receipt));old=legacy.get(receipt,source(receipt))
            available=Decimal(s['opening_kg'])+Decimal(s['input_kg'])-Decimal(s['output_kg'])
            legacy_kg=Decimal(old['opening_kg'])+Decimal(old['input_kg'])-Decimal(old['output_kg'])
            lots.append({'receipt_id':receipt,**{k:str(v) for k,v in totals[receipt].items()},
                'usable_kg':str(available),'legacy_accounting_kg':str(legacy_kg),
                'legacy_measured_carry_kg':str(legacy_kg) if legacy_latest else None,
                'balance_as_of':latest.shift_end if latest else None,'basis':'last_closed_shift_plus_signed_receipts'})
        result[identifier]={'run_id':identifier,'previous_end':latest.shift_end if latest else None,
            'legacy_previous_end':legacy_latest.shift_end if legacy_latest else None,
            'sources':[s for s in sources.values() if Decimal(s['opening_kg'])>0 or s['movements']],
            'legacy_sources':list(legacy.values()),'lots':lots}
    return result
