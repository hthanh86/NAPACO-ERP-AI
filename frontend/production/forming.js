(() => {
  const $=id=>document.getElementById(id),root='/api/production/';
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  const number=value=>Number(value||0).toLocaleString('vi-VN',{maximumFractionDigits:8});
  const now=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date()).replace(' ','T');
  const local=value=>value?String(value).slice(0,19):'';
  const zoned=value=>value+'+07:00';
  const decisions={normal:'Cho chạy hàng loạt',sort:'Cho chạy lọc',stop:'Dừng chạy'};
  let busy=false,ctx=null,runId=null,editId=null,journal=null,workPage=1,workTotal=0,historyPage=1,historyTotal=0,itemInputs=[],sourceInputs=[],draftId=crypto.randomUUID(),pendingSave=null;
  const button=(label,action)=>{const b=node('button',label);b.type='button';b.onclick=()=>work(action);return b;};
  async function api(path,options={}){
    const response=await fetch(root+path,{cache:'no-store',...options});let body;
    try{body=await response.json();}catch{throw Error('Không đọc được phản hồi HTTP '+response.status);}
    if(!response.ok){const error=Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));error.status=response.status;throw error;}return body;
  }
  async function work(action){
    if(busy)return;busy=true;$('message').textContent='Đang xử lý…';$('save').disabled=true;
    const main=document.querySelector('main'),previousInert=main.inert;main.inert=true;
    try{await action();if($('message').textContent==='Đang xử lý…')$('message').textContent='Đã hoàn tất.';}
    catch(error){$('message').textContent=error.message;}
    finally{busy=false;$('save').disabled=!!ctx&&!ctx.sample_basis&&!pendingSave;main.inert=previousInert;}
  }
  function kg(value){if(!/^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(value))throw Error('Kg phải là số không âm, tối đa 8 chữ số thập phân.');const [whole,part='']=value.split('.');return BigInt(whole)*100000000n+BigInt(part.padEnd(8,'0'));}
  function decimal(value){const negative=value<0n;if(negative)value=-value;return (negative?'-':'')+(value/100000000n).toString()+'.'+(value%100000000n).toString().padStart(8,'0');}
  function available(source){return kg(source.opening_kg)+kg(source.input_kg)-kg(source.output_kg);}
  async function machines(){
    const options=[],q=$('machineQuery').value;let page=1;
    while(true){const data=await api('forming/machines?'+new URLSearchParams({q,page,size:100}));options.push(...data.items);if(page++*100>=data.total)break;}
    const previous=$('machine').value;$('machine').replaceChildren(node('option','Chọn máy'));$('machine').firstChild.value='';
    for(const m of options){const option=node('option',`${m.name} · ${m.id}`);option.value=m.id;$('machine').append(option);}
    if(options.some(m=>m.id===previous))$('machine').value=previous;
    $('machineHint').textContent=options.length?'Chọn máy để tải các CTĐH đang được phân công.':'Không có máy định hình phù hợp.';
  }
  async function loadWork(){
    const machine=$('machine').value;if(!machine)throw Error('Chọn máy trước.');
    const data=await api('machines/'+encodeURIComponent(machine)+'/work?'+new URLSearchParams({stage:'forming',page:workPage,size:100}));
    workTotal=data.total;$('workRows').replaceChildren();const groups=new Map();
    for(const item of data.items){if(!groups.has(item.run_id))groups.set(item.run_id,[]);groups.get(item.run_id).push(item);}
    for(const [id,items]of groups){const card=node('article');card.className='work-card';card.append(node('strong',`${items[0].official_code} · ${items[0].status}`));
      for(const item of items)card.append(node('p',`${item.order_line_id} · ${item.product_id} · còn ${number(item.remaining_qty)} cái`));
      card.append(button('Ghi nhật ký LSX '+items[0].official_code,()=>openEntry(id)));$('workRows').append(card);}
    if(!groups.size)$('workRows').textContent='Không có CTĐH còn thực hiện được, đã phát và đang gán cho máy này.';
    $('workPage').textContent=`Trang ${workPage} · ${workTotal} CTĐH–LSX`;$('workPrev').disabled=workPage<=1;$('workNext').disabled=workPage*100>=workTotal;
  }
  function contextPath(id,setup=null,editing=null,withInterval=false){
    const p=new URLSearchParams({run_id:id,machine_id:$('machine').value});if(setup)p.set('setup_id',setup);if(editing)p.set('edit_id',editing);
    if(withInterval){p.set('until',zoned($('end').value));p.set('since',zoned($('start').value));}return 'forming/context?'+p;
  }
  async function openEntry(id,editing=null){
    const selected=await api(contextPath(id,null,editing));ctx=selected;runId=id;editId=editing;draftId=editing||crypto.randomUUID();pendingSave=null;
    $('entryForm').reset();$('entry').hidden=false;$('entryTitle').textContent=(editing?'Sửa nhật ký · ':'Ghi nhật ký · ')+ctx.official_code;
    $('entryInfo').textContent=`${ctx.machine.name} · ${ctx.status} · cùng LSX qua nhiều ngày/máy`;
    $('start').value=local(ctx.defaults.start);$('end').value=local(ctx.defaults.end);$('endNow').checked=!editing;
    $('goodSheets').value=ctx.journal?.good_sheets??'';$('ngSheets').value=ctx.journal?.ng_sheets??0;
    const params=ctx.defaults.parameters;for(const [id,key]of [['actualSpeed','seconds_per_cycle'],['actualPull','pull_mm'],['actualWeight','sheet_weight_kg']])$(id).value=params[key]??'';
    $('pureMinutes').value=ctx.journal?.snapshot.pure_seconds==null?'':ctx.journal.snapshot.pure_seconds/60;
    $('setupMinutes').value=ctx.journal?.snapshot.setup_seconds==null?'':ctx.journal.snapshot.setup_seconds/60;
    $('note').value=ctx.journal?.snapshot.note||'';$('editReasonLabel').hidden=!editing;$('editReason').required=!!editing;
    $('episodeAction').value=ctx.journal?.snapshot.forming_entry_v1?.episode_action||'continue';$('episodeAction').disabled=!!editing;
    renderEpisodes();renderItems();renderSources(false);renderContext();await loadSummary();$('entry').scrollIntoView({block:'start'});
  }
  function renderEpisodes(){
    $('episode').replaceChildren();for(const episode of ctx.episodes.items){const option=node('option',`${episode.opened_at} → ${episode.valid_until}${episode.closed_at?' · Đã đóng':''}`);option.value=episode.id;$('episode').append(option);}
    if(ctx.episode&&!ctx.episodes.items.some(e=>e.id===ctx.episode.id)){const option=node('option',ctx.episode.opened_at+' · '+ctx.episode.valid_until);option.value=ctx.episode.id;$('episode').append(option);}
    if(ctx.episode)$('episode').value=ctx.episode.id;$('episode').disabled=!!editId;
  }
  function renderContext(){
    const basis=ctx.sample_basis;$('sampleInfo').textContent=basis?`${basis.qc_id} · ${basis.result} · ${decisions[basis.decision]} · đủ hai xác nhận`:(ctx.blocked_reason||'Chưa đủ điều kiện phiếu mẫu.');
    $('sampleLink').hidden=!basis;if(basis)$('sampleLink').href='/production/samples?qc_id='+encodeURIComponent(basis.qc_id);
    const reference=ctx.reference_parameters;$('referenceInfo').textContent=`Chỉ tham khảo kế hoạch: ${reference.seconds_per_cycle??'—'} giây/chu kỳ; bước kéo ${reference.pull_mm??'—'} mm; ${reference.sheet_weight_kg??'—'} kg/bìa.`;
    const weekday=(new Date($('start').value.slice(0,10)+'T12:00:00Z').getUTCDay()+6)%7,rule=ctx.calendar.weekly[String(weekday)]||{};
    $('calendarInfo').textContent='Nghỉ theo cấu hình: '+((rule.breaks||[]).map(p=>p.start+'–'+p.end).join(', ')||'chưa có khung nghỉ')+'. Không tự tách nhật ký; thời gian chạy thuần chỉ ghi khi có số thực tế.';
    const pending=ctx.lots.filter(l=>Number(l.pending_handover_kg)>0);
    $('pendingInfo').textContent=ctx.reconciliation_only?'NVL đã trả/chuyển hết. Chỉ chốt đối soát với sản lượng và tiêu hao bằng 0 trước khi kết thúc LSX.':pending.length?'Chưa được dùng: '+pending.map(l=>l.receipt_id+' chờ ký nhận '+number(l.pending_handover_kg)+' kg').join('; '):'';
    renderCycles();
  }
  function quantityInput(value,label){const input=node('input');input.type='number';input.min='0';input.max='1000000000';input.step='1';input.required=true;input.value=value;input.setAttribute('aria-label',label);return input;}
  function renderItems(){
    itemInputs=[];$('itemRows').replaceChildren();const count=new Map();for(const item of ctx.items)count.set(item.product_id,(count.get(item.product_id)||0)+1);
    for(const item of ctx.items){const saved=ctx.journal?.items.find(i=>i.order_line_id===item.order_line_id),row=node('tr'),good=quantityInput(saved?.good??'',item.order_line_id+' tốt'),ng=quantityInput(saved?.ng??0,item.order_line_id+' NG');
      const entry={item,good,ng,auto:!saved&&count.get(item.product_id)===1};good.oninput=ng.oninput=()=>{entry.auto=false;renderCycles();};
      row.append(node('td',item.order_line_id+' · '+item.name),node('td',`${item.cavity} · còn ${number(item.remaining_qty)}`));for(const input of [good,ng]){const td=node('td');td.append(input);row.append(td);}$('itemRows').append(row);itemInputs.push(entry);}
  }
  function renderCycles(){
    const good=Number($('goodSheets').value||0),ng=Number($('ngSheets').value||0);$('cyclesInfo').textContent=`Tổng ${number(good+ng)} bìa/chu kỳ; thời gian máy chỉ tính một lần cho LSX ghép.`;
    for(const entry of itemInputs)if(entry.auto&&$('goodSheets').value!==''){entry.good.value=good*entry.item.cavity;entry.ng.value=ng*entry.item.cavity;}
  }
  function renderSources(preserve=true){
    const old=new Map(sourceInputs.map(s=>[s.source.receipt_id,s.input.value]));sourceInputs=[];$('sourceRows').replaceChildren();const mode=$('materialMode').value;
    $('materialHeading').textContent=mode==='closing'?'Kg cuối kỳ':'Kg tiêu hao';$('derivedHeading').textContent=mode==='closing'?'Tiêu hao tính lại':'Cuối kỳ tính lại';
    for(const source of ctx.sources){const row=node('tr'),input=node('input'),derived=node('td');input.type='number';input.min='0';input.step='0.00000001';input.required=true;input.setAttribute('aria-label',source.receipt_id+(mode==='closing'?' kg cuối kỳ':' kg tiêu hao'));
      const saved=ctx.journal?.sources.find(s=>s.receipt_id===source.receipt_id);input.value=preserve?(old.get(source.receipt_id)??''):(saved?.[mode==='closing'?'closing_kg':'consumed_kg']??'');
      for(const value of [source.receipt_id,source.opening_kg,source.input_kg,source.output_kg,decimal(available(source))])row.append(node('td',value));
      const cell=node('td');cell.append(input);row.append(cell,derived);$('sourceRows').append(row);
      function reflect(){try{derived.textContent=input.value===''?'—':decimal(available(source)-kg(input.value));}catch{derived.textContent='Số kg chưa hợp lệ';}}
      input.oninput=reflect;reflect();sourceInputs.push({source,input});}
    if(!ctx.sources.length)$('sourceRows').append(node('tr','Chưa có nguồn NVL đã ký nhận còn được sử dụng.'));
  }
  async function refreshContext(){
    if(!runId)throw Error('Chọn LSX trước.');const old=ctx,updated=await api(contextPath(runId,$('episode').value,editId,true));
    if(updated.assignment_id!==old.assignment_id||updated.run_version!==old.run_version)throw Error('LSX/phân công đã đổi. Đóng màn hình nhập rồi chọn lại; giữ số kiểm đếm của bạn để đối chiếu.');
    ctx=updated;renderSources(true);renderContext();return old.source_hash!==updated.source_hash||old.sample_basis?.qc_id!==updated.sample_basis?.qc_id||old.sample_basis?.qc_version!==updated.sample_basis?.qc_version||old.episode?.version!==updated.episode?.version;
  }
  async function loadSummary(){if(!runId)return;const data=await api('forming/runs/'+encodeURIComponent(runId)+'/summary');$('summary').hidden=false;
    $('summaryInfo').textContent=`${data.official_code} · ${data.count} nhật ký · bìa tốt ${number(data.good_sheets)} / NG ${number(data.ng_sheets)} · ${number(Number(data.interval_seconds)/3600)} giờ trong các khoảng đã ghi (gồm nghỉ)`;
    $('summaryItems').replaceChildren(...data.items.map(i=>node('p',`${i.order_line_id}: tốt ${number(i.good_qty)}, NG ${number(i.ng_qty)}, còn ${number(i.remaining_qty)} cái${i.enabled?'':' · thành phần cũ'}`)));
    $('summaryLots').replaceChildren(...data.lots.map(l=>node('p',`${l.receipt_id}: đã nhận có chữ ký ${number(l.received_signed_kg)} kg; tiêu hao ${number(l.consumed_kg)} kg; còn dùng được ${number(l.usable_kg)} kg${Number(l.legacy_accounting_kg)>0?' · số lịch sử chưa xác minh '+number(l.legacy_accounting_kg)+' kg (không dùng làm nguồn mới)':''}`)));
  }
  async function save(){
    if(pendingSave){await submit(pendingSave);return;}
    if($('endNow').checked)$('end').value=now();
    if(!$('entryForm').reportValidity())return;
    if(await refreshContext())throw Error('Nguồn/phiếu mẫu/đợt đã thay đổi. Dữ liệu đã nạp lại; kiểm tra các số thực tế rồi nhấn Lưu lần nữa.');
    if(!ctx.sample_basis)throw Error(ctx.blocked_reason||'Chưa đủ xác nhận kiểm mẫu.');
    if(ctx.reconciliation_only&&(Number($('goodSheets').value)||Number($('ngSheets').value)))throw Error('NVL đã trả/chuyển hết; nhật ký này chỉ dùng đối soát, sản lượng phải bằng 0.');
    for(const source of sourceInputs)if(kg(source.input.value)>available(source.source))throw Error(source.source.receipt_id+': số kiểm đếm/tiêu hao vượt lượng có thể sử dụng.');
    const optional=id=>$(id).value===''?null:Number($(id).value);
    const payload={id:draftId,run_version:ctx.run_version,version:ctx.journal?.version??null,machine_id:ctx.machine.id,assignment_id:ctx.assignment_id,
      setup_id:ctx.episode.id,episode_version:ctx.episode.version,sample_qc_id:ctx.sample_basis.qc_id,sample_qc_version:ctx.sample_basis.qc_version,source_hash:ctx.source_hash,
      start:zoned($('start').value),end:zoned($('end').value),good_sheets:Number($('goodSheets').value),ng_sheets:Number($('ngSheets').value),
      items:itemInputs.map(i=>({order_line_id:i.item.order_line_id,good:Number(i.good.value),ng:Number(i.ng.value)})),
      sources:sourceInputs.map(s=>({receipt_id:s.source.receipt_id,consumed_kg:$('materialMode').value==='consumed'?s.input.value:null,closing_kg:$('materialMode').value==='closing'?s.input.value:null})),
      seconds_per_cycle:optional('actualSpeed'),pull_mm:optional('actualPull'),sheet_weight_kg:optional('actualWeight'),
      pure_seconds:optional('pureMinutes')==null?null:optional('pureMinutes')*60,setup_seconds:optional('setupMinutes')==null?null:optional('setupMinutes')*60,
      note:$('note').value,episode_action:$('episodeAction').value,edit_reason:$('editReason').value};
    pendingSave={payload,key:crypto.randomUUID(),runId,editId};await submit(pendingSave);
  }
  async function submit(request){
    const path='forming/runs/'+encodeURIComponent(request.runId)+'/logs'+(request.editId?'/'+encodeURIComponent(request.editId):'');let result;
    try{result=await api(path,{method:request.editId?'PUT':'POST',headers:{'Content-Type':'application/json','Idempotency-Key':request.key},body:JSON.stringify(request.payload)});}
    catch(error){if(error.status&&error.status<500)pendingSave=null;throw Error(error.message+' · Nếu mất kết nối, nhấn Lưu để gửi lại đúng thao tác; sửa ô nhập sẽ tạo yêu cầu mới.');}
    pendingSave=null;ctx=null;$('entry').hidden=true;$('message').textContent=`Đã lưu nhật ký · ${result.official_code}. ${request.payload.episode_action==='close'?'Đợt đã kết thúc; chạy lại cần phiếu mẫu mới.':'LSX tiếp tục; nghỉ trong đợt không bắt buộc kiểm mẫu lại.'}`;
    historyPage=1;const refreshed=await Promise.allSettled([loadSummary(),loadWork(),loadHistory()]);
    if(refreshed.some(result=>result.status==='rejected'))$('message').textContent+=' Nhật ký đã được ghi; một số bảng chưa tải lại được, hãy Tra cứu lại.';
  }
  async function loadHistory(){
    const byRun=$('historyByRun').checked;if(byRun&&!runId)throw Error('Chọn LSX trước khi tra cứu lũy kế theo LSX.');
    const params=new URLSearchParams({page:historyPage,size:25});if(byRun)params.set('run_id',runId);else if($('machine').value)params.set('machine_id',$('machine').value);else throw Error('Chọn máy trước.');
    if($('historyStart').value)params.set('start',$('historyStart').value);if($('historyEnd').value)params.set('end',$('historyEnd').value);
    const data=await api('forming/history?'+params);historyTotal=data.total;$('historyRows').replaceChildren();
    for(const row of data.items){const card=node('div',`${row.official_code||'LSX cũ'} · ${row.machine_id||'Chưa rõ máy'} · ${local(row.shift_start)} → ${local(row.shift_end)} · tốt ${number(row.good)} / NG ${number(row.ng)} · ${row.sample_qc_id||'Chưa có căn cứ mẫu mới'}`);card.className='history-card';card.append(button('Xem nhật ký',()=>openJournal(row.id)));$('historyRows').append(card);}
    $('historyPage').textContent=`Trang ${historyPage} · ${historyTotal} nhật ký`;$('historyPrev').disabled=historyPage<=1;$('historyNext').disabled=historyPage*25>=historyTotal;
  }
  async function openJournal(id){journal=await api('shifts/'+encodeURIComponent(id));const box=$('journalInfo');box.replaceChildren(node('p',`${journal.official_code||'LSX cũ'} · ${journal.actual_machine_id||'Chưa rõ máy'} · ${local(journal.start)} → ${local(journal.end)}`),node('p','Phiếu mẫu: '+(journal.sample_basis?.qc_id||'Lịch sử chưa có căn cứ mới')));
    for(const item of journal.items)box.append(node('p',`${item.order_line_id}: tốt ${number(item.good)}, NG ${number(item.ng)}`));
    for(const source of journal.sources)box.append(node('p',`${source.receipt_id}: ${source.opening_kg} + ${source.input_kg} − ${source.output_kg} − ${source.consumed_kg} = ${source.closing_kg} kg`));
    $('editJournal').disabled=!journal.sample_basis;$('journal').showModal();}
  $('machineSearch').onsubmit=e=>{e.preventDefault();work(machines);};
  $('machine').onchange=()=>work(async()=>{ctx=null;runId=null;editId=null;pendingSave=null;$('entry').hidden=true;$('summary').hidden=true;workPage=1;historyPage=1;historyTotal=0;$('historyByRun').checked=false;$('historyRows').replaceChildren();$('historyPage').textContent='Bấm Tra cứu để xem nhật ký của máy đã chọn.';$('historyPrev').disabled=$('historyNext').disabled=true;await loadWork();});
  $('refreshWork').onclick=()=>work(loadWork);$('workPrev').onclick=()=>work(async()=>{if(workPage>1){workPage--;await loadWork();}});$('workNext').onclick=()=>work(async()=>{if(workPage*100<workTotal){workPage++;await loadWork();}});
  $('goodSheets').oninput=$('ngSheets').oninput=renderCycles;
  $('end').oninput=()=>{$('endNow').checked=false;};$('start').onchange=()=>{if(ctx)renderContext();};
  $('refreshSources').onclick=()=>work(async()=>{pendingSave=null;if($('endNow').checked)$('end').value=now();await refreshContext();});
  $('episode').onchange=()=>work(async()=>{const selected=await api(contextPath(runId,$('episode').value));ctx=selected;renderSources(true);renderContext();});
  $('materialMode').onchange=()=>{for(const source of sourceInputs)if(source.input.value!==''){try{source.input.value=decimal(available(source.source)-kg(source.input.value));}catch{source.input.value='';}}renderSources(true);};
  $('entryForm').onsubmit=e=>{e.preventDefault();work(save);};$('entryForm').addEventListener('input',()=>{pendingSave=null;});
  $('cancelEntry').onclick=()=>{$('entry').hidden=true;ctx=null;pendingSave=null;};
  $('historySearch').onsubmit=e=>{e.preventDefault();historyPage=1;work(loadHistory);};$('historyPrev').onclick=()=>work(async()=>{if(historyPage>1){historyPage--;await loadHistory();}});$('historyNext').onclick=()=>work(async()=>{if(historyPage*25<historyTotal){historyPage++;await loadHistory();}});
  $('closeJournal').onclick=()=>$('journal').close();$('editJournal').onclick=()=>work(async()=>{const selected=journal;$('journal').close();if($('machine').value!==selected.actual_machine_id){await machines();$('machine').value=selected.actual_machine_id;}await openEntry(selected.run_id,selected.id);});
  $('historyStart').value=$('historyEnd').value=now().slice(0,10);
  // Opening this dedicated page is the activation condition for the small machine catalog.
  work(machines);
})();
