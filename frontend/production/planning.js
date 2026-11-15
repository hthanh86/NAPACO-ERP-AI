/* Native management UI; no database query until explicit search/load. */
(() => {
  const $ = id => document.getElementById(id), base = '/api/production/';
  const kinds = {automatic:'Định hình tự động',semi_automatic:'Định hình bán tự động',cutting:'Máy cắt',edge:'Máy ép biên',unclassified:'Chưa phân loại'};
  const statuses = {ready:'Sẵn sàng',running:'Đang chạy',maintenance:'Bảo dưỡng',fault:'Lỗi',inactive:'Ngừng sử dụng'};
  let page=1,total=0,items=[],machineEditing=null,standardEditing=null,standardItems=[],pickerKind='',pickerPage=1,pickerTotal=0,busy=false,request=0,pickerRequest=0;
  const selected = new Map();
  const sf=$('standardForm'), mf=$('machineForm');
  const field=(form,name)=>form.elements.namedItem(name);
  function node(tag,text){const n=document.createElement(tag); if(text!==undefined)n.textContent=text;return n;}
  function button(text,fn){const n=node('button',text);n.type='button';n.onclick=fn;return n;}
  function message(text,error=false){$('message').textContent=text;$('message').dataset.error=error;}
  async function api(path,options={}) {
    const response=await fetch(base+path,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});
    let data;try{data=await response.json();}catch{throw Error('Không đọc được phản hồi máy chủ.');}
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
    return data;
  }
  async function guard(fn,dialog) {
    if(busy)return;busy=true;
    try{await fn();}catch(e){if(dialog)dialog.querySelector('.error').textContent=e.message;else if($('picker').open)$('pickerMessage').textContent=e.message;else message(e.message,true);}finally{busy=false;}
  }
  function summary(){ $('selectedMachines').textContent=selected.size?'Máy đã chọn: '+[...selected.keys()].join(', '):'Chưa chọn máy.'; }
  async function search() {
    const token=++request,kind=$('catalog').value;
    const result=await api(kind+'?'+new URLSearchParams({q:$('query').value,page,size:25,history:$('history').checked}));
    if(token!==request)return;
    items=result.items;total=result.total;
    $('headers').replaceChildren(...(kind==='machines'?['Chọn lịch','Mã / tên','Loại','Trạng thái','Thao tác']:['Mã / tên','Phiên bản','Máy','Sử dụng','Thao tác']).map(t=>node('th',t)));
    $('rows').replaceChildren();
    for(const item of items){
      const row=node('tr');
      if(kind==='machines'){
        const cell=node('td'),check=node('input');check.type='checkbox';check.checked=selected.has(item.id);
        check.onchange=()=>{if(check.checked)selected.set(item.id,item.version);else selected.delete(item.id);summary();};cell.append(check);row.append(cell);
        [item.id+' · '+item.name,kinds[item.kind],statuses[item.status]].forEach(t=>row.append(node('td',t)));
      }else [item.code+' · '+item.name,item.revision,item.machine_id,item.active?'Có':'Ngừng'].forEach(t=>row.append(node('td',t)));
      const action=node('td');action.append(button(kind==='machines'?'Sửa máy':'Xem / tạo phiên bản',()=>guard(()=>kind==='machines'?openMachine(item):openStandard(item.id))));row.append(action);$('rows').append(row);
    }
    $('count').textContent=`${total} bản ghi · Trang ${page}`;$('prev').disabled=page===1;$('next').disabled=page*25>=total;summary();
  }
  function openMachine(item=null){machineEditing=item;mf.reset();mf.querySelector('.error').textContent='';for(const name of ['id','name','kind','status','max_width_mm','max_pull_mm','notes'])field(mf,name).value=item?.[name]??(name==='kind'?'unclassified':name==='status'?'ready':'');field(mf,'id').readOnly=!!item;$('machineDialog').showModal();}
  function renderItems(){
    $('standardItems').replaceChildren();
    standardItems.forEach((item,index)=>{
      const row=node('div');row.append(node('span',item.product_id+' · '+(item.name||'')));
      const label=node('label','Cavity riêng'),cavity=node('input');cavity.type='number';cavity.min=1;cavity.max=100000;cavity.required=true;cavity.value=item.cavity;cavity.oninput=()=>item.cavity=Number(cavity.value);label.append(cavity);row.append(label);
      const edgeLabel=node('label','Có ép biên'),edge=node('input');edge.type='checkbox';edge.checked=item.edge;edge.onchange=()=>item.edge=edge.checked;edgeLabel.append(edge);row.append(edgeLabel,button('Bỏ',()=>{standardItems.splice(index,1);renderItems();}));$('standardItems').append(row);
    });
  }
  async function openStandard(id=null){
    sf.reset();sf.querySelector('.error').textContent='';$('route').textContent='';$('weight').textContent='';standardEditing=id;standardItems=[];
    if(id){
      const data=await api('standards/'+id);
      const values={...data,...data.parameters};for(const name of ['code','name','machine_id','material_id','mold_id','pull_mm','seconds_per_cycle','density','setup_minutes','waste_percent'])field(sf,name).value=values[name];field(sf,'active').checked=data.active;field(sf,'approved').checked=false;$('route').textContent=data.snapshot.approval?.approved?'Phiên bản gốc đã duyệt. Phiên bản mới cần xác nhận duyệt riêng.':'Phiên bản gốc chưa có xác nhận duyệt.';
      standardItems=data.items.map(i=>({product_id:i.product_id,name:i.snapshot.name,cavity:i.cavity,edge:i.edge}));
      $('weight').textContent='Trọng lượng bìa đã chốt: '+data.parameters.sheet_weight_kg+' kg/bìa';
      const route=await api('standards/'+id+'/route');const names={forming:'Định hình',cutting:'Cắt',forming_cutting:'Định hình + Cắt liền',edge:'Ép biên'};
      $('route').textContent=route.items.map(i=>i.product_id+': '+i.stages.map(s=>names[s]).join(' → ')+' · '+i.cavity+' '+i.product_unit+'/bìa').join('\n');
      $('standardHeading').textContent=data.code+' · phiên bản '+data.revision+' (lưu để tạo phiên bản tiếp theo)';
    }else $('standardHeading').textContent='Bộ định mức mới';
    field(sf,'code').readOnly=!!id;renderItems();$('standardDialog').showModal();
  }
  async function pickerSearch(){
    const token=++pickerRequest,kind=pickerKind;
    const path=kind==='machines'?'machines':'references/'+kind;
    const data=await api(path+'?'+new URLSearchParams({q:$('pickerQuery').value,page:pickerPage,size:25}));
    if(token!==pickerRequest)return;
    pickerTotal=data.total;$('pickerResults').replaceChildren();$('pickerMessage').textContent='';
    for(const item of data.items){
      const title=kind==='molds'?[item.MaCC,item.Ma_Khuon,item.TenCC,item.MaSP,item.Trang_Thai]:kind==='materials'?[item.id,item.grade,item.color,`${item.thickness} × ${item.width} mm`]:[item.id,item.name,item.code,kind==='machines'?kinds[item.kind]:item.unit];
      $('pickerResults').append(button(title.filter(Boolean).join(' · '),()=>{
        if(kind==='products'){
          if(standardItems.some(i=>i.product_id===item.id)){$('pickerMessage').textContent='Sản phẩm đã có trong cấu hình.';return;}
          standardItems.push({product_id:item.id,name:item.name,cavity:1,edge:false});renderItems();
        }else field(sf,{machines:'machine_id',materials:'material_id',molds:'mold_id'}[kind]).value=kind==='molds'?item.MaCC:item.id;
        $('picker').close();
      }));
    }
    $('pickerCount').textContent=`${pickerTotal} bản ghi · Trang ${pickerPage}`;$('pickerPrev').disabled=pickerPage===1;$('pickerNext').disabled=pickerPage*25>=pickerTotal;
  }
  document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{pickerKind=b.dataset.pick;pickerPage=1;$('pickerQuery').value='';$('pickerResults').replaceChildren();$('pickerMessage').textContent='Nhập từ khóa và bấm Tìm kiếm.';$('pickerPrev').disabled=true;$('pickerNext').disabled=true;$('pickerCount').textContent='';$('picker').showModal();});
  document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
  $('pickerSearch').onsubmit=e=>{e.preventDefault();pickerPage=1;guard(pickerSearch);};
  $('pickerPrev').onclick=()=>{if(pickerPage>1){pickerPage--;guard(pickerSearch);}};$('pickerNext').onclick=()=>{if(pickerPage*25<pickerTotal){pickerPage++;guard(pickerSearch);}};
  $('search').onclick=()=>{page=1;guard(search);};$('query').onkeydown=e=>{if(e.key==='Enter'){$('search').click();}};
  $('catalog').onchange=()=>{++request;page=1;items=[];total=0;$('rows').replaceChildren();$('headers').replaceChildren();$('count').textContent='Bấm Tìm kiếm để tải dữ liệu.';$('prev').disabled=true;$('next').disabled=true;};
  $('prev').onclick=()=>{if(page>1){page--;guard(search);}};$('next').onclick=()=>{if(page*25<total){page++;guard(search);}};
  $('new').onclick=()=>guard(()=>$('catalog').value==='machines'?openMachine():openStandard());
  mf.onsubmit=e=>{e.preventDefault();guard(async()=>{
    const payload=Object.fromEntries(new FormData(mf));for(const k of ['max_width_mm','max_pull_mm'])payload[k]=payload[k]?Number(payload[k]):null;
    payload.version=machineEditing?.version??null;
    const result=await api('machines'+(machineEditing?'/'+encodeURIComponent(machineEditing.id):''),{method:machineEditing?'PUT':'POST',body:JSON.stringify(payload)});
    if(selected.has(result.id))selected.set(result.id,result.version);summary();$('machineDialog').close();message('Đã lưu máy.');await search();
  },$('machineDialog'));};
  sf.onsubmit=e=>{e.preventDefault();guard(async()=>{
    const payload=Object.fromEntries(new FormData(sf));for(const k of ['pull_mm','seconds_per_cycle','density','setup_minutes','waste_percent'])payload[k]=Number(payload[k]);payload.active=field(sf,'active').checked;payload.approved=field(sf,'approved').checked;
    payload.items=standardItems.map(({product_id,cavity,edge})=>({product_id,cavity,edge}));
    const result=await api('standards'+(standardEditing?'/'+standardEditing+'/revisions':''),{method:'POST',body:JSON.stringify(payload)});
    $('standardDialog').close();message(`Đã lưu ${result.code} phiên bản ${result.revision}; ${result.parameters.sheet_weight_kg} kg/bìa.`);await search();
  },$('standardDialog'));};
  const weekdays=['Thứ Hai','Thứ Ba','Thứ Tư','Thứ Năm','Thứ Sáu','Thứ Bảy','Chủ Nhật'];
  weekdays.forEach((day,index)=>{const row=node('tr');row.append(node('td',day));for(const type of ['shifts','breaks']){const cell=node('td'),input=node('input');input.id=`${type}${index}`;input.placeholder='08:00-12:00,13:00-17:00';cell.append(input);row.append(cell);}$('week').append(row);});
  function minute(text,end=false){if(!/^\d{2}:\d{2}$/.test(text))throw Error('Giờ phải theo dạng HH:MM.');const [h,m]=text.split(':').map(Number);if(m>59||h>24||(h===24&&(!end||m!==0)))throw Error('Giờ không hợp lệ.');return h*60+m;}
  function spans(value){return value.trim()?value.split(',').map(piece=>{const parts=piece.trim().split('-');if(parts.length!==2)throw Error('Khoảng giờ phải dạng 08:00-12:00.');return {start:minute(parts[0].trim()),end:minute(parts[1].trim(),true)};}):[];}
  const clock=value=>String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0');
  const spanText=values=>values.map(s=>clock(s.start)+'-'+clock(s.end)).join(',');
  function versions(){if(!selected.size)throw Error('Chọn máy trong danh sách Máy trước.');return Object.fromEntries(selected);}
  function dateRange(){const start=$('start').value,end=$('end').value;if(!start||!end)throw Error('Chọn từ ngày và đến ngày.');return {start,end};}
  async function saveCalendar(payload){const data=await api('calendars',{method:'PUT',body:JSON.stringify({versions:versions(),...payload})});for(const [id,version]of Object.entries(data.versions)){selected.set(id,version);const item=items.find(i=>i.id===id);if(item)item.version=version;}message('Đã lưu lịch cho máy đã chọn.');}
  $('saveWeek').onclick=()=>guard(async()=>{const weekly={};for(let d=0;d<7;d++)weekly[d]={shifts:spans($('shifts'+d).value),breaks:spans($('breaks'+d).value)};await saveCalendar({weekly});});
  $('saveException').onclick=()=>guard(async()=>{if(!$('exceptionDay').value)throw Error('Chọn ngày ngoại lệ.');await saveCalendar({exceptions:[{day:$('exceptionDay').value,windows:spans($('exceptionWindows').value),note:$('exceptionNote').value}]});});
  $('removeException').onclick=()=>guard(async()=>{if(!$('exceptionDay').value)throw Error('Chọn ngày cần bỏ ngoại lệ.');await saveCalendar({remove_exceptions:[$('exceptionDay').value]});});
  $('loadCalendar').onclick=()=>guard(async()=>{versions();const id=[...selected.keys()][0];const data=await api('calendars/'+encodeURIComponent(id)+'?'+new URLSearchParams(dateRange()));selected.set(id,data.version);const item=items.find(i=>i.id===id);if(item)item.version=data.version;
    for(let d=0;d<7;d++)for(const type of ['shifts','breaks'])$(type+d).value=spanText(data.weekly[d]?.[type]||[]);
    $('exceptions').textContent=`Lịch của ${id}\n`+data.exceptions.map(e=>`${e.day}: ${spanText(e.windows)||'Nghỉ cả ngày'} · ${e.note}`).join('\n');message('Đã nạp lịch '+id+'.');});
  $('availability').onclick=()=>guard(async()=>{versions();const params=new URLSearchParams(dateRange());for(const id of selected.keys())params.append('machine_id',id);const data=await api('availability?'+params);$('windows').textContent=data.machines.map(m=>m.machine_id+'\n'+(m.windows.map(w=>w.start+' → '+w.end+(w.source==='exception'?' (ngoại lệ)':'')).join('\n')||'Không có khoảng được chạy.')).join('\n\n');});
  const inherit=button('Cho máy đã chọn dùng mặc định chung',()=>guard(async()=>{await saveCalendar({inherit_default:true});}));
  $('loadCalendar').after(inherit);
  const settings=document.createElement('a');settings.href='/production/calendar-settings';settings.textContent='Thiết lập giờ làm / nghỉ mặc định';$('loadCalendar').before(settings);
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Ho_Chi_Minh'}).format(new Date());$('start').value=today;$('end').value=today;$('exceptionDay').value=today;$('prev').disabled=true;$('next').disabled=true;
})();
