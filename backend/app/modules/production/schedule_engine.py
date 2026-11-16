"""Deterministic, storage-free schedule arithmetic shared by preview and save."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timedelta
from decimal import Decimal,InvalidOperation,ROUND_CEILING


class ScheduleError(ValueError):
    def __init__(self,code,message,**context):
        super().__init__(message);self.detail={'code':code,'message':message,**context}


def number(value,field,run_id,*,zero=False):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<0 or (not zero and result==0):raise ValueError()
        return result
    except (InvalidOperation,ValueError,TypeError):
        raise ScheduleError('MISSING_OR_INVALID_PARAMETER','Thiếu hoặc sai thông số '+field,run_id=run_id,field=field)


def ceil(value):return int(value.to_integral_value(rounding=ROUND_CEILING))
def iso(value):return value.isoformat() if value else None


def requirements(items,parameters,identifier):
    """The single formula for material validation and calendar calculation."""
    p=parameters or {};seconds=number(p.get('seconds_per_cycle'),'seconds_per_cycle',identifier)
    setup=number(p.get('setup_minutes'),'setup_minutes',identifier,zero=True)*60
    weight=number(p.get('sheet_weight_kg'),'sheet_weight_kg',identifier)
    waste=number(p.get('waste_percent'),'waste_percent',identifier,zero=True)
    if waste>100:raise ScheduleError('INVALID_WASTE','Hao hụt cần trong 0–100%.',run_id=identifier)
    totals=defaultdict(int);cavities={}
    if not items:raise ScheduleError('MISSING_ITEMS','Lần chạy thiếu sản phẩm.',run_id=identifier)
    for item in items:
        cavity=number(item.get('cavity'),'cavity',identifier)
        planned=number(item.get('planned_qty'),'planned_qty',identifier,zero=True)
        done=number(item.get('completed_qty'),'completed_qty',identifier,zero=True)
        if any(n!=n.to_integral_value() for n in [cavity,planned,done]) or done>planned:
            raise ScheduleError('INVALID_QUANTITY','Cavity/sản lượng phải nguyên và hoàn thành không vượt bố trí.',run_id=identifier)
        product=item['product_id']
        if product in cavities and cavities[product]!=int(cavity):
            raise ScheduleError('INCONSISTENT_CAVITY','Cùng sản phẩm có cavity không nhất quán.',run_id=identifier)
        cavities[product]=int(cavity);totals[product]+=int(planned-done)
    cycles=min(ceil(Decimal(qty)/cavities[product]) for product,qty in totals.items())
    suggested=cycles
    if p.get('planned_cycles_limit') is not None:
        limit=number(p['planned_cycles_limit'],'planned_cycles_limit',identifier,zero=True)
        completed=number(p.get('completed_cycles',0),'completed_cycles',identifier,zero=True)
        if limit!=limit.to_integral_value() or completed!=completed.to_integral_value():
            raise ScheduleError('INVALID_CYCLES','Số bìa phải là số nguyên.',run_id=identifier)
        cycles=max(0,int(limit-completed)) if suggested else 0
    return {'cycles':cycles,'suggested_cycles':suggested,'cavities':cavities,'totals':totals,'seconds':seconds,'setup':setup,
        'weight':weight,'waste':waste,'base_kg':weight*cycles,'waste_kg':weight*cycles*waste/100,
        'required_kg':weight*cycles*(1+waste/100)}


def subtract(start,end,occupied):
    for left,right in sorted(occupied):
        if right<=start or left>=end:continue
        if left>start:yield start,min(left,end)
        start=max(start,right)
        if start>=end:return
    if start<end:yield start,end


class ResourceCalendar:
    def __init__(self,windows,start,end,fixed,stops):
        self.windows=windows;self.start=start;self.end=end
        self.busy=defaultdict(list);self.unknown={};self.stops=stops;self.cursor={}
        for item in fixed:
            for resource in item['resources']:self.busy[resource].append((item['start'],item['end']))
        for stop in stops:
            if not stop['enabled'] or stop['run_ended']:continue
            resources=['machine:'+stop['machine_id']]
            if stop['hold_machine'] and stop['duration_seconds'] is None:
                resources+=['line:'+line for line in stop['line_ids']]
                for key in resources:self.unknown[key]=min(self.unknown.get(key,stop['at']),stop['at'])
            elif stop['hold_machine'] and stop['duration_seconds'] is not None:
                self.busy[resources[0]].append((stop['at'],stop['at']+timedelta(seconds=stop['duration_seconds'])))

    def place(self,machine,seconds,earliest,resources=()):
        if seconds==0:return [],Decimal(0)
        if machine not in self.windows or not self.windows[machine]:
            raise ScheduleError('NO_WORKING_HOURS','Máy chưa có khoảng được phép chạy trong kỳ.',machine_id=machine)
        keys=['machine:'+machine,*resources];earliest=max(self.start,earliest,self.cursor.get(machine,self.start))
        cutoff=min([self.end]+[self.unknown[k] for k in keys if k in self.unknown])
        remaining=Decimal(seconds);segments=[]
        occupied=[span for key in keys for span in self.busy[key]]
        for left,right in self.windows[machine]:
            left=max(left,earliest);right=min(right,cutoff)
            if right<=left:continue
            for a,b in subtract(left,right,occupied):
                capacity=Decimal(str((b-a).total_seconds()))
                used=min(remaining,capacity)
                if used<=0:continue
                finish=a+timedelta(seconds=float(used));segments.append((a,finish))
                self.cursor[machine]=finish
                remaining-=used
                for key in keys:self.busy[key].append((a,finish))
                if remaining<=0:return segments,Decimal(0)
        if remaining and cutoff==self.end:
            raise ScheduleError('INSUFFICIENT_WORKING_WINDOW','Không đủ giờ làm trong khoảng tính; mở rộng kỳ hoặc chỉnh lịch máy.',machine_id=machine,remaining_seconds=str(remaining))
        return segments,remaining

    def setup_start_before(self,machine,seconds,target,earliest,resources=()):
        if not seconds:return target
        floor=max(self.start,earliest,self.cursor.get(machine,self.start));remaining=Decimal(seconds)
        occupied=[span for key in ['machine:'+machine,*resources] for span in self.busy[key]]
        free=[span for left,right in self.windows.get(machine,[]) for span in subtract(max(left,floor),min(right,target),occupied) if span[1]>span[0]]
        for left,right in reversed(free):
            capacity=Decimal(str((right-left).total_seconds()))
            if capacity>=remaining:return right-timedelta(seconds=float(remaining))
            remaining-=capacity
        raise ScheduleError('START_TOO_EARLY_FOR_SETUP','Giờ bắt đầu chạy chưa đủ thời gian setup sau đơn trước / thời điểm hiện tại. Chọn giờ muộn hơn hoặc để nối tiếp tự động.',machine_id=machine)

    def hold_wait(self,machine,start,end):
        start=max(start,self.cursor.get(machine,self.start))
        if end<=start:return
        key='machine:'+machine
        if any(a<end and start<b for a,b in self.busy[key]):
            raise ScheduleError('WAIT_MACHINE_CONFLICT','Khoảng giữ máy chờ hàng chồng công việc đã xếp.',machine_id=machine)
        self.busy[key].append((start,end))


def time_at(segments,seconds):
    offset=Decimal(seconds)
    if offset==0:return segments[0][0] if segments else None
    for start,end in segments:
        duration=Decimal(str((end-start).total_seconds()))
        if offset<=duration:return start+timedelta(seconds=float(offset))
        offset-=duration
    return None


def release_for(stream,quantity):
    used=0;latest=None;estimated=False
    for event in stream:
        used+=event['quantity'];estimated|=event.get('estimated',False)
        if event['at'] is None:return None,estimated
        latest=max(latest,event['at']) if latest else event['at']
        if used>=quantity:return latest,estimated
    raise ScheduleError('UPSTREAM_QUANTITY_SHORT','Lượng bàn giao vượt nguồn công đoạn trước.',requested=quantity,available=used)


def drop_consumed(stream,quantity):
    result=[];remaining=quantity
    for event in stream:
        take=min(remaining,event['quantity']);remaining-=take
        if event['quantity']>take:result.append({**event,'quantity':event['quantity']-take})
    if remaining:raise ScheduleError('UPSTREAM_ALREADY_OVERUSED','Dữ liệu công đoạn sau đã dùng vượt nguồn.',excess=remaining)
    return result


def batches(policy,quantity):
    if not quantity:return []
    if policy['mode']=='all':return [quantity]
    if policy['handoff_quantities']:
        if sum(policy['handoff_quantities'])!=quantity:
            raise ScheduleError('HANDOFF_TOTAL_MISMATCH','Tổng lượng bàn giao riêng phải bằng lượng chưa xử lý của công đoạn.',expected=quantity)
        return policy['handoff_quantities']
    size=policy['handoff_quantity']
    if not size:raise ScheduleError('MISSING_HANDOFF_QUANTITY','Cuốn chiếu cần lượng bàn giao có đơn vị.')
    if ceil(Decimal(quantity)/size)>1000:raise ScheduleError('TOO_MANY_HANDOFFS','Tối đa 1000 lần bàn giao cho một công đoạn.')
    return [min(size,quantity-offset) for offset in range(0,quantity,size)]


def calculate(context):
    calendar=ResourceCalendar(context['windows'],context['start'],context['end'],context['actual'],context['stops'])
    result={'timezone':'Asia/Ho_Chi_Minh','jobs':[],'actual':[a for a in context['actual'] if a['start']<context['end'] and a['end']>context['start']],'lines':[],
            'orders':[],'warnings':list(context['warnings']),'engine_version':'production-scheduler-v1',
            'stops':context['stops'],'working_windows':{machine:[{'start':a,'end':b} for a,b in spans]
                for machine,spans in context['windows'].items()}}
    finished=defaultdict(list);visible_machines=set();view=context.get('reason_view')
    def matches_view(run):
        if not view:return True
        if view.get('machine_id') and run['machine_id']!=view['machine_id']:return False
        for item in run['items']:
            label=context.get('line_labels',{}).get(item['order_line_id'],{})
            if view.get('customer_id') and label.get('customer_id')!=view['customer_id']:continue
            query=(view.get('q') or '').casefold()
            if query and query not in ' '.join(str(label.get(k) or '') for k in ['id','product_name','po_number','order_id']).casefold():continue
            return True
        return False
    def occupies_view(run,report):
        if not matches_view(run):return False
        if not view or run['id'] in context.get('changed_runs',set()):return True
        spans=[*report['setup_segments'],*report['forming_segments'],*report.get('rest_segments',[])]
        if any(span['start']<view['end'] and span['end']>view['start'] for span in spans):return True
        if any(a.get('run_id')==run['id'] and a['start']<view['end'] and a['end']>view['start'] for a in context['actual']):return True
        return report['status'] in {'unknown','released_waiting'} and context['start']<view['end'] and context['end']>view['start']
    for run in context['runs']:
        identifier=run['id'];params=run['snapshot'].get('parameters');policy=run['policy'];items=run['items']
        req=requirements(items,params,identifier)
        seconds,setup,weight,waste=(req[key] for key in ['seconds','setup','weight','waste'])
        totals,cavities=req['totals'],req['cavities'];by_product=defaultdict(list)
        line_order=policy['line_order'] or [i['order_line_id'] for i in items]
        if set(line_order)!={i['order_line_id'] for i in items}:raise ScheduleError('INVALID_LINE_ORDER','Thứ tự CTĐH phải đủ các thành viên.',run_id=identifier)
        rank={line:i for i,line in enumerate(line_order)}
        for item in sorted(items,key=lambda i:rank[i['order_line_id']]):
            remaining=max(0,int(item['planned_qty'])-int(item['completed_qty']))
            by_product[item['product_id']].append((item,remaining))
        # A product already complete ends this grouped configuration: only downstream may remain.
        cycles=req['cycles']
        run_seconds=seconds*cycles;setup_seconds=Decimal(0) if run['has_actual'] or cycles==0 else setup
        waiting=policy['waiting'] or any(s['enabled'] and not s['hold_machine'] and not s['run_ended'] and s['run_id']==identifier for s in context['stops'])
        ready=max(context['start'],run['actual_end'] or context['start'],policy['ready_at'] or context['start'])
        if run.get('future_only'):ready=max(ready,context['planning_now'])
        resources=['line:'+i['order_line_id'] for i in items]
        setup_segments=[];forming=[];rest_segments=[];missing=run_seconds;left=Decimal(0)
        if not waiting and cycles:
            if run.get('validate_start_reason',True) and policy.get('ready_at'):
                automatic=max(context['start'],run['actual_end'] or context['start'])
                if policy['ready_at']<calendar.cursor.get(run['machine_id'],context['start']):
                    raise ScheduleError('START_BEFORE_PREVIOUS','Giờ bắt đầu trước khi đơn trước kết thúc (kể cả đơn ngoài khung nhìn). Đổi giờ hoặc đổi thứ tự kế hoạch.',run_id=identifier)
                if any(a<=policy['ready_at']<b for a,b in calendar.busy['machine:'+run['machine_id']]):
                    raise ScheduleError('START_TIME_CONFLICT','Giờ bắt đầu trùng lịch máy đã có (có thể nằm ngoài khung nhìn). Chọn giờ khác hoặc đổi thứ tự kế hoạch.',run_id=identifier,machine_id=run['machine_id'])
                first_visible=matches_view(run) and run['machine_id'] not in visible_machines
                if not first_visible and not policy.get('start_reason','').strip():
                    probe_calendar=deepcopy(calendar)
                    if policy.get('start_basis')=='forming':
                        setup_probe,_=probe_calendar.place(run['machine_id'],setup_seconds,max(automatic,context.get('planning_now',automatic)) if run.get('future_only') else automatic,resources)
                        automatic=setup_probe[-1][1] if setup_probe else automatic
                    probe,_=probe_calendar.place(run['machine_id'],Decimal(1),automatic,resources)
                    chosen,_=deepcopy(calendar).place(run['machine_id'],Decimal(1),ready,resources)
                    if probe and chosen and chosen[0][0]>probe[0][0]:
                        raise ScheduleError('START_REASON_REQUIRED','Bắt đầu khác thời điểm nối tiếp tự động: cần ghi lý do.',run_id=identifier)
            if policy.get('ready_at') and policy.get('start_basis')=='forming':
                chosen,_=deepcopy(calendar).place(run['machine_id'],Decimal(1),ready,resources)
                if chosen:
                    floor=max(context['start'],run['actual_end'] or context['start'])
                    if run.get('future_only'):floor=max(floor,context['planning_now'])
                    ready=calendar.setup_start_before(run['machine_id'],setup_seconds,chosen[0][0],floor,resources)
            setup_segments,left=calendar.place(run['machine_id'],setup_seconds,ready,resources)
            if not left:
                forming,missing=calendar.place(run['machine_id'],run_seconds,setup_segments[-1][1] if setup_segments else ready,resources)
                if not missing and policy.get('rest_minutes',0):
                    rest_segments,rest_missing=calendar.place(run['machine_id'],Decimal(str(policy['rest_minutes']))*60,forming[-1][1],resources)
                    missing+=rest_missing
        missing+=left
        status='released_waiting' if waiting else 'unknown' if missing else 'scheduled'
        report={'run_id':identifier,'run_version':run['version'],'machine_id':run['machine_id'],
            'official_code':run.get('official_code'),'release_state':run.get('release_state','legacy'),
            'machine_kind':run['snapshot'].get('machine_kind'),'planned_items':items,
            'status':status,'cycles':cycles,'suggested_cycles':req['suggested_cycles'],'sheets':cycles,
            'planned_cycles_limit':params.get('planned_cycles_limit'),'completed_cycles':params.get('completed_cycles',0),'setup_seconds':str(setup_seconds),'pure_seconds':str(run_seconds),
            'seconds_per_cycle':str(seconds),
            'base_kg':str(req['base_kg']),'waste_kg':str(req['waste_kg']),'required_kg':str(req['required_kg']),
            'waste_policy':'extra_material_allowance','yield_assumption':'no_future_ng',
            'setup_segments':[{'start':a,'end':b} for a,b in setup_segments],
            'rest_segments':[{'start':a,'end':b} for a,b in rest_segments],
            'rest_minutes':policy.get('rest_minutes',0),
            'allocation_start':(setup_segments or forming or [(None,None)])[0][0],
            'planned_start':forming[0][0] if forming else None,
            'planned_end':(rest_segments or forming)[-1][1] if forming and not missing else None,
            'forming_segments':[{'start':a,'end':b} for a,b in forming],'unknown_seconds':str(missing),
            'first_forming_at':forming[0][0] if forming else None,'forming_end':forming[-1][1] if forming and not missing else None,
            'products':[],'stages':[],'material':run['material'],'line_quantities':[]}
        stage_map={(s['order_line_id'],s['stage']):s for s in policy['stages']}
        for product,group in by_product.items():
            produced=cycles*cavities[product];target=totals[product]
            report['products'].append({'product_id':product,'cavity':cavities[product],
                'target_qty':target,'planned_good_qty':min(target,produced),'rounding_surplus_qty':max(0,produced-target),
                'requires_next_run_qty':max(0,target-produced)})
            offset=0
            for item,remaining in group:
                line=item['order_line_id'];count=min(remaining,max(0,produced-offset));stream=list(run['streams'].get((line,'forming'),[]))
                report['line_quantities'].append({'order_line_id':line,'quantity':count,'unit':item['snapshot']['unit']})
                # Release events only at required handoff thresholds, never expand every cycle.
                downstream_policies=[s for (ct,stage),s in stage_map.items() if ct==line]
                thresholds={1,count} if count else set()
                for s in downstream_policies:
                    size=s.get('handoff_quantity')
                    if s['mode']=='rolling' and size:
                        if ceil(Decimal(max(count,1))/size)>1000:raise ScheduleError('TOO_MANY_HANDOFFS','Giảm số lô bàn giao.',run_id=identifier)
                        thresholds.update(range(size,count+1,size))
                    cumulative=0
                    for n in s.get('handoff_quantities',[]):cumulative+=n;thresholds.add(min(cumulative,count))
                previous=0
                for threshold in sorted(t for t in thresholds if t>0):
                    cycle=ceil(Decimal(offset+threshold)/cavities[product])
                    at=None if waiting else time_at(forming,seconds*cycle)
                    stream.append({'quantity':threshold-previous,'at':at,'estimated':False,'actual':False,'run_id':identifier})
                    previous=threshold
                offset+=count
                for stage in item['snapshot']['route']:
                    if stage not in {'cutting','edge'}:continue
                    actual_stream=list(run['streams'].get((line,stage),[]))
                    actual_input=run['processed'].get((line,stage),0)
                    actual_supplied=sum(e['quantity'] for e in stream if e.get('actual'))
                    if actual_input>actual_supplied:raise ScheduleError('ACTUAL_UPSTREAM_OVERUSED','Thực tế công đoạn sau vượt lượng đã cung cấp.',run_id=identifier,order_line_id=line,stage=stage)
                    pending=drop_consumed(stream,actual_input);quantity=sum(e['quantity'] for e in pending)
                    if not quantity:stream=actual_stream;continue
                    s=stage_map.get((line,stage))
                    if not s and policy.get('defer_downstream',False):
                        # Forming-only planning leaves downstream timing unknown.
                        # Never fabricate a rate or treat formed goods as finished.
                        stream=actual_stream+[{'quantity':quantity,'at':None,'estimated':True,
                            'actual':False,'run_id':identifier}]
                        continue
                    if not s:raise ScheduleError('MISSING_STAGE_PARAMETERS','Chưa có tốc độ/setup/bàn giao công đoạn sau.',run_id=identifier,order_line_id=line,stage=stage)
                    if s['unit'].strip().casefold()!=item['snapshot']['unit'].strip().casefold():
                        raise ScheduleError('HANDOFF_UNIT_MISMATCH','Đơn vị bàn giao khác đơn vị sản phẩm; chưa có quy đổi.',run_id=identifier,order_line_id=line)
                    rate=number(s['seconds_per_unit'],'seconds_per_unit',identifier)
                    machine=s['machine_id'];scheduled_output=[];cumulative=0;last_end=None
                    for index,batch in enumerate(batches(s,quantity)):
                        cumulative+=batch;release,upstream_estimate=release_for(pending,cumulative)
                        release=release+timedelta(minutes=s['wait_minutes']) if release else None
                        duration=rate*batch+(Decimal(str(s['setup_minutes']))*60 if index==0 else 0)
                        segments=[];unknown=Decimal(0)
                        if release is None:
                            unknown=duration
                            if machine and s['hold_machine_while_waiting']:
                                key='machine:'+machine;calendar.unknown[key]=min(calendar.unknown.get(key,ready),ready)
                        elif machine:
                            if s['hold_machine_while_waiting']:
                                calendar.hold_wait(machine,last_end or ready,max(release,last_end or ready))
                            segments,unknown=calendar.place(machine,duration,max(release,last_end or ready))
                        else:
                            start=max(context['start'],release,last_end or release)
                            segments=[(start,start+timedelta(seconds=float(duration)))]
                            if segments[-1][1]>context['end']:
                                raise ScheduleError('INSUFFICIENT_ESTIMATE_WINDOW','Thời gian ước tính vượt kỳ tính lịch.',run_id=identifier,order_line_id=line,stage=stage)
                        end=segments[-1][1] if segments and not unknown else None
                        first=time_at(segments,rate+(Decimal(str(s['setup_minutes']))*60 if index==0 else 0))
                        if end:last_end=end
                        estimated=machine is None or upstream_estimate
                        scheduled_output.append({'quantity':1,'at':first,'estimated':estimated,'actual':False,'run_id':identifier})
                        if batch>1:scheduled_output.append({'quantity':batch-1,'at':end,'estimated':estimated,'actual':False,'run_id':identifier})
                        report['stages'].append({'order_line_id':line,'stage':stage,'batch':index+1,'input_qty':batch,
                            'pure_seconds':str(rate*batch),'setup_seconds':str(Decimal(str(s['setup_minutes']))*60 if index==0 else 0),
                            'unit':s['unit'],'machine_id':machine,'handoff_ready_at':release,'wait_minutes':s['wait_minutes'],
                            'status':'unknown' if not end else 'estimated' if estimated else 'scheduled',
                            'segments':[{'start':a,'end':b} for a,b in segments],'first_output_at':first,'end':end,
                            'yield_assumption':'no_future_ng','unknown_seconds':str(unknown)})
                    stream=actual_stream+scheduled_output
                finished[line].extend(e for e in stream if not e.get('actual'))
        if occupies_view(run,report):visible_machines.add(run['machine_id'])
        result['jobs'].append(report)
    orders=defaultdict(list)
    for line in context['lines']:
        future=finished[line['id']];known=line['actual_finished_qty'];planned=sum(e['quantity'] for e in future)
        unknown=any(e['at'] is None for e in future);times=[e['at'] for e in future if e['at'] is not None]
        complete=known+planned>=line['quantity'] and not unknown
        end=max([*times,*([line['actual_finished_at']] if line['actual_finished_at'] else [])]) if complete and (times or line['actual_finished_at']) else None
        record={'order_line_id':line['id'],'order_id':line['order_id'],'unit':line['unit'],
            'known_finished_qty':known,'planned_finished_qty':planned,'remaining_unscheduled_qty':max(0,line['quantity']-known-planned),
            'first_planned_finished_at':min(times) if times else None,'all_finished_at':end,
            'certainty':'unknown' if not complete else 'estimated' if any(e['estimated'] for e in future) else 'scheduled',
            'reason':None if complete else 'UNKNOWN_TIMING' if unknown else 'UNPLANNED_REMAINDER'}
        result['lines'].append(record);orders[line['order_id']].append(record)
    for identifier,lines in orders.items():
        completed=all(l['all_finished_at'] is not None for l in lines)
        result['orders'].append({'order_id':identifier,'first_planned_finished_at':min([l['first_planned_finished_at'] for l in lines if l['first_planned_finished_at']],default=None),
            'all_finished_at':max(l['all_finished_at'] for l in lines) if completed else None,
            'certainty':'unknown' if not completed else 'estimated' if any(l['certainty']=='estimated' for l in lines) else 'scheduled'})
    return result
