"""Suggestions use measured productive time, immutable configurations and independent runs.

No journal gap, wall time or nominal cycle speed is substituted for measured time.
Near matches are separated and never included in exact statistics.
"""
import hashlib
import json
import math
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from statistics import median
from sqlalchemy import select
from app.modules.orders.models import OrderLine
from app.modules.production.models import ProductionOrder as Run,FormingLog
from app.modules.production.planning_models import ProductionStandard,ProductionStandardItem,Machine
from app.modules.production.run_models import ProductionOrderItem,ShiftItem,ShiftMaterial,DownstreamItem
from app.modules.production.planning_service import ZONE
from app.modules.materials.inventory.allocation_models import MaterialAllocation
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.purchasing.models import FilmLine
from app.modules.materials.inventory.allocation_service import fail

MIN_SAMPLES=3
MAX_RUNS=200


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def signature(snapshot,items,machine_id,pull=None):
    std=snapshot.get('standard_snapshot',{});mat=std.get('material',{});params=snapshot.get('parameters',{})
    return {'machine':machine_id,'machine_kind':snapshot.get('machine_kind'),
        'mold':str(std.get('mold',{}).get('MaCC') or ''),
        'material_id':str(mat.get('id') or ''),'grade':str(mat.get('grade') or ''),'color':str(mat.get('color') or ''),'esd':str(mat.get('esd') or ''),
        'thickness':number(mat.get('thickness')),'width':number(mat.get('width')),
        'pull':number(pull if pull is not None else params.get('pull_mm')),
        'configuration':sorted({(i['product_id'],int(i['cavity']),str(i['unit']).strip().casefold()) for i in items})}


def criteria_match(target,candidate):
    matched=[];different=[]
    for key in target:
        a,b=target[key],candidate.get(key)
        equal=(math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-7) if isinstance(a,float) and isinstance(b,float) else a==b)
        (matched if equal else different).append(key)
    # Never mix product/cavity combinations or material dimensions in near suggestions.
    eligible=not(set(different)-{'machine','pull'})
    required=['mold','grade','thickness','width','pull','configuration','machine_kind']
    complete=all(candidate.get(k) not in (None,'',[]) for k in required)
    return matched,different,eligible and complete


def summarize(samples):
    """One aggregate per independent run, equal weight across runs, robust outlier rule."""
    excluded=[]
    if len(samples)>=5:
        speeds=[s['values']['seconds_per_cycle' if s['stage']=='forming' else 'seconds_per_unit'] for s in samples]
        center=median(speeds);mad=median(abs(v-center) for v in speeds)
        good=[]
        for sample,value in zip(samples,speeds):
            if abs(value-center)>max(3*1.4826*mad,center*.5):excluded.append(sample['run_id'])
            else:good.append(sample)
        samples=good
    stats={}
    for key in sorted({k for s in samples for k in s['values']}):
        values=[s['values'][key] for s in samples if key in s['values']]
        if values:
            stats[key]={'typical':median(values),'min':min(values),'max':max(values),'samples':len(values),
                'eligible_default':len(values)>=MIN_SAMPLES}
    return samples,stats,excluded


def suggestions(db,data):
    standard=db.get(ProductionStandard,data.standard_id)
    if not standard or not standard.active:fail('Chọn định mức đang áp dụng để đối chiếu lịch sử.')
    versions=list(db.scalars(select(ProductionStandard).where(ProductionStandard.code==standard.code,
        ProductionStandard.active.is_(True)).order_by(ProductionStandard.revision.desc()).limit(100)))
    approved=None;approved_match=[];approved_different=[]
    machine=db.get(Machine,data.machine_id)
    if not machine:fail('Không tìm thấy máy.',404)
    if data.stage=='forming' and machine.kind!=standard.snapshot['machine']['kind']:fail('Máy khác loại định mức.')
    if data.stage!='forming' and machine.kind!=data.stage:fail('Máy không thuộc công đoạn gợi ý.')
    ids=[i.order_line_id for i in data.items]
    if len(set(ids))!=len(ids):fail('CTĐH bị lặp.')
    lines={r.id:r for r in db.scalars(select(OrderLine).where(OrderLine.id.in_(ids)))}
    templates={i.product_id:i for i in db.scalars(select(ProductionStandardItem).where(ProductionStandardItem.standard_id==standard.id))}
    requested=[];cavities={};applicable=set()
    for item in data.items:
        line=lines.get(item.order_line_id)
        if not line or line.product_id not in templates:fail('Sản phẩm/CTĐH không có trong định mức.')
        if line.product_id in cavities and cavities[line.product_id]!=item.cavity:fail('Cùng sản phẩm cần cùng cavity.')
        cavities[line.product_id]=item.cavity
        if data.stage=='forming' or data.stage in templates[line.product_id].snapshot['route']:applicable.add(line.product_id)
        requested.append({'product_id':line.product_id,'cavity':item.cavity,'unit':line.unit})
    if not applicable:fail('Không có sản phẩm áp dụng công đoạn này.')
    units={r['unit'].strip().casefold() for r in requested if r['product_id'] in applicable}
    unit='seconds/cycle' if data.stage=='forming' else 'seconds/'+data.unit.strip().casefold()
    if data.stage!='forming' and (not data.unit or units!={data.unit.strip().casefold()}):fail('Cần đúng một đơn vị năng suất đã xác minh, không gộp đơn vị khác nhau.')
    base={'standard_snapshot':standard.snapshot,'parameters':standard.parameters,'machine_kind':standard.snapshot['machine']['kind']}
    target=signature(base,requested,data.machine_id,data.pull_mm)
    source_query=(select(MaterialAllocation.id,FilmLine.resin).join(FilmReceipt,FilmReceipt.id==MaterialAllocation.receipt_id)
        .join(FilmLine,FilmLine.id==FilmReceipt.line_id).where(MaterialAllocation.order_line_id.in_(ids),FilmLine.material_id==standard.material_id))
    source_query=source_query.where(MaterialAllocation.id.in_(data.allocation_ids)) if data.allocation_ids else source_query.where(MaterialAllocation.held_kg>0)
    selected_sources=list(db.execute(source_query))
    if data.allocation_ids and {r.id for r in selected_sources}!=set(data.allocation_ids):fail('Nguồn chọn đối chiếu nhựa không thuộc cấu hình/CTĐH.')
    target_resins={str(r.resin or '').strip().casefold() for r in selected_sources}
    target['resin']=next(iter(target_resins)) if len(target_resins)==1 and '' not in target_resins else None
    approved_versions=[s for s in versions if (s.snapshot.get('approval') or {}).get('approved') is True]
    approved_items=defaultdict(list)
    for item in db.scalars(select(ProductionStandardItem).where(ProductionStandardItem.standard_id.in_([s.id for s in approved_versions]))):
        approved_items[item.standard_id].append({'product_id':item.product_id,'cavity':item.cavity,'unit':item.snapshot.get('unit','')})
    for version in approved_versions:
        candidate=signature({'standard_snapshot':version.snapshot,'parameters':version.parameters,
            'machine_kind':version.snapshot['machine']['kind']},approved_items[version.id],version.machine_id)
        # Standards identify material by catalog ID; do not falsely claim their old
        # snapshot captured a polymer. Journal suggestions below verify actual receipts.
        matched,different,eligible=criteria_match({k:v for k,v in target.items() if k!='resin'},candidate)
        if eligible:
            approved=version;approved_match=matched;approved_different=different;break
    # ProductionOrderItem index narrows candidates before reading JSON; last 365 production days.
    related=select(ProductionOrderItem.run_id).where(ProductionOrderItem.product_id.in_(list(cavities)))
    runs=list(db.scalars(select(Run).where(Run.id.in_(related),Run.run_snapshot.is_not(None)).order_by(Run.issued_at.desc(),Run.id).limit(MAX_RUNS+1)))
    capped=len(runs)>MAX_RUNS;runs=runs[:MAX_RUNS];run_ids=[r.id for r in runs]
    members=defaultdict(list);membership={}
    for item in db.scalars(select(ProductionOrderItem).where(ProductionOrderItem.run_id.in_(run_ids))):
        members[item.run_id].append({'product_id':item.product_id,'cavity':item.cavity,'unit':item.snapshot.get('unit',''),'route':item.snapshot.get('route',[])})
        membership[(item.run_id,item.order_line_id)]=(item.product_id,item.cavity)
    cutoff=datetime.now(ZONE).replace(tzinfo=None)-timedelta(days=365)
    logs=list(db.scalars(select(FormingLog).where(FormingLog.production_order_id.in_(run_ids),FormingLog.shift_snapshot.is_not(None),
        FormingLog.shift_end>=cutoff).order_by(FormingLog.shift_end.desc()).limit(4001)))
    if len(logs)>4000:fail('Lịch sử vượt 4000 ca; thu hẹp cấu hình trước khi lấy gợi ý.')
    by_run={r.id:r for r in runs};log_ids=[l.id for l in logs]
    counts=defaultdict(list);material=defaultdict(list)
    for item in db.scalars(select(ShiftItem).where(ShiftItem.log_id.in_(log_ids))):counts[item.log_id].append(item)
    for item in db.scalars(select(ShiftMaterial).where(ShiftMaterial.log_id.in_(log_ids))):material[item.log_id].append(item)
    receipt_ids={s.receipt_id for rows in material.values() for s in rows}
    receipt_resins=dict(db.execute(select(FilmReceipt.id,FilmLine.resin).join(FilmLine,FilmLine.id==FilmReceipt.line_id).where(FilmReceipt.id.in_(receipt_ids))).all())
    def source_resin(log_id):
        types={str(receipt_resins.get(s.receipt_id) or '').strip().casefold() for s in material[log_id]}
        return next(iter(types)) if len(types)==1 and '' not in types else None
    observations=[];rejected=Counter()
    if data.stage=='forming':
        for log in logs:
            snapshot=log.shift_snapshot;pure=number(snapshot.get('pure_seconds'));cycles=number(snapshot.get('cycles'))
            if not log.shift_start or not log.shift_end or not pure or not cycles or pure<=0 or cycles<=0 or pure>(log.shift_end-log.shift_start).total_seconds():
                rejected['missing_measured_pure_or_cycles']+=1;continue
            run=by_run[log.production_order_id]
            frozen=snapshot.get('items')
            measured_members=list(frozen.values()) if frozen else members[run.id]
            totals=defaultdict(float);valid=True
            expected=set(frozen) if frozen else {ct for rid,ct in membership if rid==run.id}
            if {i.order_line_id for i in counts[log.id]}!=expected:valid=False
            for item in counts[log.id]:
                saved_member=frozen.get(item.order_line_id) if frozen else None
                member=(saved_member['product_id'],saved_member['cavity']) if saved_member else membership.get((run.id,item.order_line_id))
                if not member or item.good_qty<0 or item.ng_qty<0:valid=False;continue
                totals[member[0]]+=float(item.good_qty+item.ng_qty)
            if not valid or any(not math.isclose(totals[p['product_id']],cycles*p['cavity'],abs_tol=1e-6) for p in measured_members):
                rejected['quantity_cavity_balance']+=1;continue
            saved=snapshot.get('run_snapshot',{})
            sig=signature(saved,measured_members,saved.get('machine_id'),snapshot.get('parameters',{}).get('pull_mm'))
            sig['resin']=source_resin(log.id)
            if not sig['resin'] or not target['resin']:rejected['unverified_resin']+=1;continue
            seconds=pure/cycles
            if not .05<=seconds<=3600:rejected['abnormal_speed']+=1;continue
            values={'seconds_per_cycle':seconds}
            good=sum(float(i.good_qty) for i in counts[log.id]);ng=sum(float(i.ng_qty) for i in counts[log.id])
            if len({p['unit'].casefold() for p in measured_members})==1 and good+ng>0:values['yield_percent']=good/(good+ng)*100
            balanced=bool(material[log.id]) and all(i.opening_kg+i.input_kg-i.output_kg-i.consumed_kg==i.closing_kg and min(i.opening_kg,i.input_kg,i.output_kg,i.consumed_kg,i.closing_kg)>=0 for i in material[log.id])
            if balanced:
                consumed=sum(float(i.consumed_kg) for i in material[log.id])
                weight=number(snapshot.get('parameters',{}).get('sheet_weight_kg'))
                if consumed>0:
                    values['consumption_kg_per_cycle']=consumed/cycles
                    if weight and 0<=100*(consumed/(cycles*weight)-1)<=100:values['waste_percent']=100*(consumed/(cycles*weight)-1)
            else:rejected['missing_balanced_consumption']+=1
            setup=number(snapshot.get('setup_seconds'))
            if setup is not None and (setup<0 or setup+pure>(log.shift_end-log.shift_start).total_seconds()):setup=None;rejected['invalid_setup']+=1
            observations.append({'run_id':run.id,'journal_id':log.id,'at':log.shift_end,'signature':sig,'values':values,'weight':cycles,'pure':pure,'setup':setup})
    else:
        details=list(db.scalars(select(DownstreamItem).where(DownstreamItem.forming_log_id.in_(log_ids),DownstreamItem.stage==data.stage).limit(8001)))
        if len(details)>8000:fail('Quá nhiều chi tiết công đoạn để tổng hợp gợi ý.')
        grouped=defaultdict(list);forming={l.id:l for l in logs}
        for item in details:grouped[item.cut_id or item.edge_id].append(item)
        for identifier,items in grouped.items():
            snapshot=items[0].snapshot;log=forming[items[0].forming_log_id];run=by_run[log.production_order_id]
            try:start=datetime.fromisoformat(snapshot['start']);end=datetime.fromisoformat(snapshot['end'])
            except (KeyError,ValueError,TypeError):rejected['missing_dates']+=1;continue
            pure=number(snapshot.get('pure_seconds'));amount=sum(float(i.input_qty) for i in items)
            if not pure or pure<=0 or amount<=0 or pure>(end-start).total_seconds():rejected['missing_measured_pure_or_quantity']+=1;continue
            if {i.snapshot.get('product',{}).get('unit','').casefold() for i in items}!={data.unit.casefold()}:rejected['unit_mismatch']+=1;continue
            # Require the full product combination, not a partial downstream batch of a group.
            actual_products={i.snapshot.get('product',{}).get('product_id') for i in items}
            measured_members=list(log.shift_snapshot['items'].values()) if log.shift_snapshot.get('items') else members[run.id]
            expected_products={i['product_id'] for i in measured_members if data.stage in i['route']}
            if actual_products!=expected_products:rejected['partial_group']+=1;continue
            from app.modules.production.models import CuttingLog,EBLog
            observations.append({'run_id':run.id,'journal_id':identifier,'at':end.replace(tzinfo=None),
                'signature':signature(log.shift_snapshot.get('run_snapshot',{}),measured_members,None),
                'values':{'seconds_per_unit':pure/amount,'yield_percent':sum(float(i.good_qty) for i in items)/amount*100},
                'weight':amount,'pure':pure,'setup':number(snapshot.get('setup_seconds')),'stage_log':identifier})
        model=CuttingLog if data.stage=='cutting' else EBLog
        machines=dict(db.execute(select(model.id,model.machine_id).where(model.id.in_([o['journal_id'] for o in observations]))).all())
        for o in observations:o['signature']['machine']=machines.get(o['journal_id'])
        for o in observations:
            source=next((i.forming_log_id for i in grouped[o['journal_id']]),None)
            o['signature']['resin']=source_resin(source)
        observations=[o for o in observations if o['signature'].get('resin') and target['resin']]
    aggregates=defaultdict(list)
    for obs in observations:
        matched,different,eligible=criteria_match(target,obs['signature'])
        if not eligible:rejected['configuration_mismatch']+=1;continue
        aggregates[(obs['run_id'],tuple(different))].append(obs)
    exact=[];near=[]
    for (run_id,different),rows in aggregates.items():
        latest=max(rows,key=lambda r:r['at']);weight=sum(r['weight'] for r in rows)
        values={}
        for key in {k for r in rows for k in r['values']}:
            valid=[r for r in rows if key in r['values']]
            values[key]=sum(r['values'][key]*r['weight'] for r in valid)/sum(r['weight'] for r in valid)
        setups=[r['setup'] for r in rows if r['setup'] is not None and r['setup']>=0]
        if setups:values['setup_minutes']=sum(setups)/60
        matched=[k for k in target if k not in different]
        sample={'run_id':run_id,'stage':data.stage,'at':latest['at'].isoformat()+'+07:00','journal_ids':[r['journal_id'] for r in rows],
            'values':values,'journals':len(rows),'criteria_matched':matched,'criteria_different':list(different),
            'unit':unit,'source':'measured_journals','complete_run':by_run[run_id].status=='Đã kết thúc'}
        (near if different else exact).append(sample)
    exact.sort(key=lambda s:s['at'],reverse=True);near.sort(key=lambda s:s['at'],reverse=True)
    exact,_,outliers=summarize(exact[:30]);rejected['robust_speed_outliers']=len(outliers)
    completed=[s for s in exact if s['complete_run']]
    _,stats,_=summarize(completed)
    warnings=[]
    if not target['resin']:warnings.append('Chưa xác minh một loại nhựa từ nguồn đã giữ: không lấy mẫu mặc định. Chọn đúng nguồn trước khi tìm.')
    if not approved:warnings.append('Cấu hình chưa có phiên bản được duyệt chủ động; định mức đang áp dụng không được coi là đã duyệt.')
    elif approved_different:warnings.append('Định mức đã duyệt khác máy/bước kéo đang chọn; cần đối chiếu trước khi áp dụng.')
    if approved:warnings.append('Định mức lưu mã vật liệu, chưa chụp riêng polymer; loại nhựa của lần chạy được xác minh từ nguồn nhập chọn, không suy từ grade.')
    if len(completed)<MIN_SAMPLES:warnings.append('Ít hơn 3 lần chạy phù hợp đã kết thúc: chưa đủ mẫu làm gợi ý thống kê mặc định.')
    if not exact:warnings.append('Chưa có mẫu khớp đầy đủ và đo chạy thuần; giữ định mức hoặc nhập thủ công.')
    if near:warnings.append('Mẫu gần giống khác máy/bước kéo: chỉ tham khảo và áp dụng chủ động; không gộp thống kê.')
    if capped:warnings.append('Giới hạn 200 lần chạy gần nhất có sản phẩm; không phải toàn bộ lịch sử.')
    evidence={'criteria':target,'stage':data.stage,'unit':unit,'exact':exact,'near':near[:5],
        'approved_standard':{'id':approved.id,'parameters':approved.parameters,'approval':approved.snapshot['approval']} if approved else None}
    digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,default=str).encode()).hexdigest()
    return {'context_hash':digest,'criteria':target,'stage':data.stage,'unit':unit,
        'approved_standard':{'id':approved.id,'code':approved.code,'revision':approved.revision,
            'parameters':approved.parameters,'approval':approved.snapshot['approval'],
            'criteria_matched':approved_match,'criteria_different':approved_different,
            'resin_verification':'selected_receipts_only_not_standard_snapshot'} if approved else None,
        'standard':{'id':standard.id,'code':standard.code,'revision':standard.revision,'parameters':standard.parameters,
            'status':'active','note':'Định mức đang áp dụng theo quyền hiện hành; không tự cập nhật từ nhật ký.'},
        'latest':exact[0] if exact else None,'statistics':stats,'samples':len(completed),'sample_runs':completed,
        'near_latest':near[0] if near else None,'excluded':dict(rejected),'outlier_run_ids':outliers,'warnings':warnings,
        'policy':{'min_samples':MIN_SAMPLES,'lookback_days':365,'max_runs':MAX_RUNS,'aggregation':'median of independent run aggregates'}}


def resolve(db,query,selection):
    result=suggestions(db,query)
    if result['context_hash']!=selection.context_hash:fail('Lịch sử gợi ý/cấu hình đã đổi; tải lại gợi ý hoặc bỏ lựa chọn để nhập thủ công.',409)
    if selection.kind=='approved_standard':
        if query.stage!='forming':fail('Định mức giây/chu kỳ chỉ áp dụng cho Định hình, không dùng thay giây/đơn vị công đoạn sau.')
        standard=result['approved_standard']
        if not standard:fail('Chưa có định mức đã duyệt để áp dụng.')
        values=standard['parameters'];sources=[]
    elif selection.kind=='statistics':
        values={k:v['typical'] for k,v in result['statistics'].items() if v['eligible_default']}
        if not values:fail('Chưa đủ mẫu cho thống kê mặc định.')
        sources=[s['run_id'] for s in result['sample_runs']]
    else:
        sample=result['latest' if selection.kind=='latest' else 'near_latest']
        if not sample or sample['run_id']!=selection.run_id:fail('Nguồn gợi ý không còn phù hợp.',409)
        values=sample['values'];sources=[sample['run_id']]
    return {'selection':selection.model_dump(),'criteria':result['criteria'],'stage':query.stage,'unit':result['unit'],
        'values':values,'source_run_ids':sources,'samples':result['samples'],'warnings':result['warnings'],
        'source_standard':result['approved_standard'] if selection.kind=='approved_standard' else None}
