/* Shared measured-history picker. All matching/statistics are supplied by backend. */
window.ProductionHistory={mount(host,{targets,apply,clear,error}){
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const box=el('section'),heading=el('h3','Gợi ý từ nhật ký'),select=el('select'),search=el('button','Tìm lịch sử phù hợp'),reset=el('button','Bỏ nguồn gợi ý / nhập thủ công'),body=el('div'),state=el('p');
  box.className='history-panel';search.type=reset.type='button';box.append(heading,el('p','Chọn công đoạn rồi bấm Tìm. Chỉ thời gian chạy thuần đã đo được dùng tính tốc độ. Định mức đang áp dụng không bị cập nhật.'),select,search,reset,state,body);host.append(box);
  const refresh=()=>{const list=targets();const previous=select.value;select.replaceChildren(...list.map((t,i)=>new Option(t.label,String(i))));if(previous&&Number(previous)<list.length)select.value=previous;return list;};
  select.onfocus=refresh;refresh();let busy=false;
  reset.onclick=()=>{clear();state.textContent='Đã bỏ nguồn gợi ý. Các giá trị hiện tại được giữ để sửa thủ công.';body.replaceChildren();};
  search.onclick=async()=>{if(busy)return;busy=true;search.disabled=true;body.replaceChildren();try{
    const list=refresh(),target=list[Number(select.value)||0];if(!target||!target.query.standard_id||!target.query.machine_id||!target.query.items.length)throw Error('Chọn định mức, máy, CTĐH và cavity trước khi tìm.');
    state.textContent='Đang tìm lịch sử…';const before=JSON.stringify(target.query);
    const res=await fetch('/api/production/run-suggestions',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(target.query)}),data=await res.json();if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
    state.textContent=data.warnings.join(' ')||`${data.samples} lần chạy phù hợp.`;
    const fmt=v=>v==null?'Chưa biết':Number(v).toLocaleString('vi-VN',{maximumFractionDigits:5});
    const labels={seconds_per_cycle:'Giây/chu kỳ',seconds_per_unit:'Giây/đơn vị',setup_minutes:'Setup phút',consumption_kg_per_cycle:'Tiêu hao kg/chu kỳ',yield_percent:'Tỷ lệ đạt %',waste_percent:'Hao hụt %'};
    const add=(title,values,selection,note)=>{const card=el('div');card.append(el('h4',title),el('p',note));for(const [key,val] of Object.entries(values).filter(([,value])=>typeof value==='number'))card.append(el('p',`${labels[key]||key}: ${fmt(val)}`));const button=el('button','Áp dụng vào nháp');button.type='button';button.onclick=()=>{try{const now=targets().find(t=>t.key===target.key);if(!now||JSON.stringify(now.query)!==before)throw Error('Cấu hình đã đổi; tìm lại lịch sử.');apply(now,values,selection);state.textContent='Đã áp dụng vào nháp. Có thể sửa trước khi lưu; backend kiểm tra lại nguồn gợi ý.';}catch(e){error(e.message);}};card.append(button);body.append(card);};
    if(target.query.stage==='forming'&&data.approved_standard){const approved=data.approved_standard;add(`Định mức đã duyệt · ${approved.code} / v${approved.revision}`,approved.parameters,{kind:'approved_standard',context_hash:data.context_hash,run_id:null},`Duyệt bởi ${approved.approval.by} · ${approved.approval.at}. Không cập nhật từ nhật ký.`);}if(target.query.stage==='forming')add(`Định mức đang áp dụng · ${data.standard.code} / v${data.standard.revision}`,data.standard.parameters,null,data.standard.note);
    const sample=(kind,title)=>{const s=data[kind];if(s)add(title+' · '+s.run_id,s.values,{kind,context_hash:data.context_hash,run_id:s.run_id},`${s.at} · ${s.journals} nhật ký · ${s.unit}. Khớp: ${s.criteria_matched.join(', ')}. Khác: ${s.criteria_different.join(', ')||'không'}. Nguồn: ${s.journal_ids.join(', ')}${s.complete_run?'':' · Lần chạy còn mở, dữ liệu một phần'}`);};
    sample('latest','Lần phù hợp gần nhất');
    const chosen={};for(const [key,s] of Object.entries(data.statistics)){body.append(el('p',`${labels[key]||key}: thường đạt ${fmt(s.typical)}; dao động ${fmt(s.min)}–${fmt(s.max)}; ${s.samples} lần chạy${s.eligible_default?'':' · ít mẫu'}`));if(s.eligible_default)chosen[key]=s.typical;}
    if(Object.keys(chosen).length)add('Thống kê phù hợp gần đây',chosen,{kind:'statistics',context_hash:data.context_hash,run_id:null},`Nguồn: ${data.sample_runs.map(s=>s.run_id).join(', ')}. Trung vị từng lần chạy; không trộn mẫu gần giống.`);
    sample('near_latest','Chỉ gần giống · cần người lập kế hoạch quyết định');
    const reasons=Object.entries(data.excluded).filter(([,n])=>n).map(([k,n])=>`${k}: ${n}`);if(reasons.length)body.append(el('p','Mẫu loại: '+reasons.join('; ')));
  }catch(e){state.textContent='';error(e.message);}finally{busy=false;search.disabled=false;}};
  return {reset(){body.replaceChildren();state.textContent='';refresh();}};
}};
