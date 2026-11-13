(() => {
  const $ = id => document.getElementById(id);
  const combinations = {'QC NVL':['NVL'], 'QC ĐẦU CA':['SETUP'], 'QC GIỮA CA':['HUT','CAT','EB'], 'QC CUỐI CA':['HUT','CAT','EB']};
  let user, selected = null, requestToken = null, requestPayload = '', saved = false, viewOnly = false;
  let objectPage = 1, objectQuery = '', objectEpoch = 0, objectItems = [], objectLoading = false;
  let listPage = 1, listParams = null, listEpoch = 0, listLoading = false, driveEpoch = 0;
  let drafts = [], saving = false, queueAccepted = false;
  let pollTimer=null;
  function element(tag, text) { const node = document.createElement(tag); if (text != null) node.textContent = text; return node; }
  async function api(url, options = {}) {
    const response = await fetch(url, {cache:'no-store', ...options});
    let body;
    try {body = await response.json();}
    catch {throw Error('Máy chủ trả về phản hồi không hợp lệ (HTTP ' + response.status + '). Vui lòng thử lại; nếu lỗi lặp lại, cần kiểm tra log backend.');}
    if (!response.ok) {
      if (response.status === 401) location.assign('/login?next=' + encodeURIComponent(location.pathname));
      throw Error(typeof body.detail === 'string' ? body.detail : (body.detail || []).map(x => x.loc.slice(1).join('.') + ': ' + x.msg).join('; ') || 'Không thực hiện được yêu cầu.');
    }
    return body;
  }
  function safeLink(node, value) {
    try { const url = new URL(value); if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw Error(); node.href=url.href; node.hidden=false; }
    catch {node.removeAttribute('href'); node.hidden=true;}
  }
  function resetObject() {
    objectEpoch++; objectItems=[]; objectQuery=''; objectPage=1; objectLoading=false;
    $('objectResults').replaceChildren(); $('objectId').value=''; $('lsx').value='';
    $('objectSearch').value=''; $('objectHint').textContent='Nhập từ khóa rồi tìm đối tượng.';
    $('objectPrevious').disabled=true; $('objectNext').disabled=true; $('findObjects').disabled=false;
    $('objectPicker').open=true;
    const nvl=$('objectType').value==='NVL';
    $('objectSearchTitle').textContent=nvl?'Mã NVL / sản phẩm / nhựa / nhà cung cấp':'Mã đối tượng / LSX / máy';
    $('objectSearch').placeholder=nvl?'Để trống để xem NVL chưa IQC trong 15 ngày':'Nhập từ khóa rồi nhấn Tìm đối tượng';
    if(nvl)$('objectHint').textContent='Nhấn Tìm đối tượng để xem NVL phù hợp; có thể nhập từ khóa để thu hẹp kết quả.';
  }
  function types(value) {
    $('objectType').replaceChildren(...combinations[$('checkType').value].map(kind => {const option=element('option',kind);option.value=kind;return option;}));
    if (value) $('objectType').value=value;
  }
  function localTime() {
    const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,19);
  }
  function integerValue(value) {
    const match=String(value??'').match(/^(-?)(\d+)(?:\.(\d+))?$/);
    if(!match)return '';
    const amount=BigInt(match[2]) + (Number((match[3]||'0')[0])>=5 ? 1n : 0n);
    return (match[1]||'')+amount.toString();
  }
  function draftPanel() {
    if(!selected && !saved)$('editorHeading').textContent=drafts.length?'Nhập phiếu '+(drafts.length+1)+' / 10':'Tạo Phiếu QC';
    $('draftPanel').hidden=selected!==null || drafts.length===0;
    $('draftSummary').textContent=`${drafts.length} phiếu đang chờ. Tối đa 10 phiếu/lần; bấm Tạo Phiếu để lưu toàn bộ.`;
    $('drafts').replaceChildren(...drafts.map((draft,index)=>{
      const row=element('li',draft.label),remove=element('button','Bỏ khỏi lô');remove.type='button';
      remove.onclick=()=>{if(!saving){drafts.splice(index,1);draftPanel();}};row.append(remove);return row;
    }));
    $('newCheck').hidden=selected!==null || (!saved && $('checkType').value!=='QC NVL');
    $('newCheck').disabled=!saved && drafts.length>=9;
  }
  function newForm(keepDrafts=false) {
    if(!keepDrafts)drafts=[];
    selected=null; requestToken=null; requestPayload=''; saved=false; queueAccepted=false; viewOnly=false; driveEpoch++;
    $('qcForm').reset(); types(); resetObject(); $('checkedAt').value=localTime(); $('staff').value=user.name;
    $('editorHeading').textContent='Tạo Phiếu QC'; $('save').hidden=false; $('save').disabled=false;
    $('newCheck').hidden=false; $('closeEditor').hidden=true; $('topActions').hidden=true; $('formError').textContent='';
    $('save').textContent='Tạo Phiếu';
    $('editor').hidden=false;
    for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=false;
    window.QCFormUI.reset();
    $('objectPrevious').disabled=true; $('objectNext').disabled=true;
    safeLink($('openStandard'),''); safeLink($('openImage'),'');
    draftPanel();
  }
  async function findObjects(page=1) {
    const query=page===1 ? $('objectSearch').value.trim() : objectQuery;
    if (!query && $('objectType').value!=='NVL') {$('objectHint').textContent='Hãy nhập từ khóa tìm kiếm.';return;}
    const epoch=++objectEpoch;objectLoading=true; $('findObjects').disabled=true; $('objectPrevious').disabled=true; $('objectNext').disabled=true;
    const params=new URLSearchParams({check_type:$('checkType').value,object_type:$('objectType').value,q:query,page:String(page)});
    try {
      const result=await api('/api/qc/objects?'+params);
      if(epoch!==objectEpoch)return;
      objectPage=page;objectQuery=query;objectItems=result.items;
      const available=result.items.filter(row=>!drafts.some(draft=>draft.payload.object_id.toLowerCase()===row.id.toLowerCase()));
      const placeholder=element('option','— Chọn bản ghi —'); placeholder.value='';
      $('objectResults').replaceChildren(placeholder,...available.map(row=>{
        const label=$('objectType').value==='NVL' ? [row.id,(row.products||[]).join(', '),[row.resin,row.specification].filter(Boolean).join(' · '),row.supplier].filter(Boolean).join(' | ')
          : [row.id,row.production_order_id && 'LSX: '+row.production_order_id,row.date,row.reference,row.info].filter(Boolean).join(' · ');
        const option=element('option',label);option.title=label;option.value=String(objectItems.indexOf(row));return option;
      }));$('objectResults').value='';
      $('objectHint').textContent=`Trang ${page} · ${available.length} kết quả`+($('objectType').value==='NVL'?' · NVL còn tồn, chưa IQC, nhập trong 15 ngày gần nhất.':'');
      $('objectPrevious').disabled=page===1;$('objectNext').disabled=!result.has_more;
    } catch(error) {if(epoch===objectEpoch)$('objectHint').textContent=error.message;}
    finally {if(epoch===objectEpoch){objectLoading=false;$('findObjects').disabled=false;}}
  }
  function formPayload() {
    if(!$('objectId').value){$('objectPicker').open=true;throw Error('Hãy chọn một bản ghi cần kiểm tra.');}
    if(!$('qcForm').reportValidity())throw Error('Hãy kiểm tra các trường bắt buộc; số lượng phải là số nguyên dương.');
    const payload={...Object.fromEntries(new FormData($('qcForm'))),...window.QCFormUI.payload()};
    if(!payload.mapped_form && payload.check_type==='QC NVL' && (!selected||selected.form_data) && (!payload.form||!payload.form.signature.length))throw Error('Hãy nhập và ký biểu mẫu QC NVL.');
    if((payload.form||payload.mapped_form) && !selected?.drive_folder_id && !payload.parent_folder_id)throw Error('Hãy mở Drive và chọn thư mục cha để lưu hồ sơ QC.');
    if(!selected && drafts.some(draft=>draft.payload.object_id.toLowerCase()===payload.object_id.toLowerCase()))throw Error('Phiếu nhập này đã có trong danh sách chờ.');
    return payload;
  }
  async function nextDraft() {
    if(saving || selected || window.QCFormUI.busy())return;
    if(saved){newForm();return;}
    try {
      if(drafts.length>=9)throw Error('Đang nhập phiếu thứ 10. Hãy bấm Tạo Phiếu để lưu lô.');
      if(!$('qcForm').reportValidity())throw Error('Hãy kiểm tra các trường bắt buộc.');
      await window.QCFormUI.prepare?.();
      const payload=formPayload();
      if(payload.check_type!=='QC NVL')throw Error('Tạo nhiều phiếu chỉ áp dụng cho IQC NVL.');
      drafts.push({payload,files:window.QCFormUI.files(),label:payload.object_id+' · '+payload.quantity+' · '+payload.result});
      newForm(true);$('editorHeading').textContent='Nhập phiếu '+(drafts.length+1)+' / 10';
    }catch(error){$('formError').textContent=error.message;}
  }
  async function save(event) {
    event.preventDefault();if(saved || viewOnly || saving || window.QCFormUI.busy())return;
    $('formError').textContent='';
    let payload, batch=false;
    try {
      const hasCurrent=['objectId','quantity','result','standardUrl','note','imageUrl'].some(id=>$(id).value.trim());
      if(hasCurrent||!drafts.length||selected){
        if(!$('qcForm').reportValidity())throw Error('Hãy kiểm tra các trường bắt buộc.');
        await window.QCFormUI.prepare?.();
      }
      const current=hasCurrent || !drafts.length || selected ? formPayload() : null;
      if(!selected && (drafts.length || current?.check_type==='QC NVL')) {
        const items=[...drafts.map(draft=>draft.payload),...(current?[current]:[])];
        if(items.length>10)throw Error('Tối đa 10 phiếu trong một lần tạo.');
        if(items.some(item=>item.check_type!=='QC NVL'))throw Error('Lô đang có phiếu IQC NVL; hãy hoàn tất lô này trước khi chọn loại kiểm tra khác.');
        payload={items};batch=true;
      }else payload=current;
    }catch(error){$('formError').textContent=error.message;return;}
    if(selected)payload.version=selected.version;
    const files=batch?[...drafts.map(draft=>draft.files),...(payload.items.length>drafts.length?[window.QCFormUI.files()]:[])]:[window.QCFormUI.files()];
    const body=JSON.stringify(payload);
    if(body!==requestPayload){requestPayload=body;requestToken=crypto.randomUUID();}
    saving=true;objectEpoch++;driveEpoch++;
    $('message').textContent='Đang lưu phiếu QC và ghi nhận hồ sơ xử lý nền. Vui lòng chờ hệ thống xác nhận…';
    const disabledStates=[...document.querySelectorAll('#qcForm input,#qcForm select,#qcForm textarea,#qcForm button,#drafts button')].map(node=>[node,node.disabled]);
    for(const [node] of disabledStates)node.disabled=true;
    let createdPrefix = null, completedRecords=[];
    try {
      const result=await api(selected ? '/api/qc/'+encodeURIComponent(selected.id) : batch?'/api/qc/batch':'/api/qc',{
        method:selected?'PUT':'POST',headers:{'Content-Type':'application/json','Idempotency-Key':requestToken},body});
      const received=batch?result.items:[result];
      if(received.every(item=>item.sync)){
        saved=true;drafts=[];queueAccepted=true;
        $('message').textContent='Đã lưu phiếu QC. Worker đang tiếp tục hoàn thiện hồ sơ.';
        const prefix=received[0].id.match(/^QC_\d{6}/)?.[0]||received[0].id;
        location.assign('/qc/list?'+new URLSearchParams({q:prefix}));return;
      }
      if(selected){
        selected=result;$('imageUrl').value=result.image_url||'';safeLink($('openImage'),result.evidence);
        window.QCFormUI.load(result,viewOnly);
        $('message').textContent='Đã lưu phiếu '+result.id+'.';
        if(result.evidence_pending)$('formError').textContent='Phiếu đã lưu, bằng chứng chưa xử lý xong: '+result.evidence_error+' Bấm Lưu phiếu để thử lại.';
      }
      else {
        saved=true;drafts=[];const ids=batch?result.items.map(item=>item.id):[result.id];
        createdPrefix = ids[0].match(/^QC_\d{6}/)?.[0] || ids[0];
        $('message').textContent='Đã tạo '+ids.length+' phiếu: '+ids.join(', ')+'.';$('editorHeading').textContent='Đã tạo phiếu QC';
        $('save').hidden=true;
      }
      completedRecords=batch?result.items:[result];
      if(listParams)await loadList(listPage);
    }catch(error){$('message').textContent='';$('formError').textContent=error.message;}
    finally{
      saving=false;for(const [node,disabled] of disabledStates)node.disabled=disabled;
      if(!saved){$('findObjects').disabled=viewOnly;}
      if(saved)for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=true;
      draftPanel();if(saved)$('newCheck').disabled=false;
    }
    if(completedRecords.length){
      await window.QCFormUI.uploadRecords(completedRecords,files,()=>{
        if(createdPrefix)location.assign('/qc/list?'+new URLSearchParams({q:createdPrefix}));
        else if(listParams)loadList(listPage);
      });
    }
  }
  async function loadList(page=1) {
    if(!listParams)return;
    const epoch=++listEpoch;listLoading=true;$('previous').disabled=true;$('next').disabled=true;
    const params=new URLSearchParams(listParams);params.set('page',String(page));
    try {
      const result=await api('/api/qc?'+params);if(epoch!==listEpoch)return;listPage=page;
      $('rows').replaceChildren(...result.items.map(row=>{
        const tr=element('tr');
        const whole=integerValue(row.quantity);
        for(const value of [row.id,row.checked_at?.replace('T',' '),row.check_type,row.object_type,row.production_order_id,whole?BigInt(whole).toLocaleString('vi-VN'):'',row.result,row.staff_name])tr.append(element('td',value??''));
        const sync=element('td'),labels={PENDING:'Chờ xử lý',PROCESSING:'Đang hoàn thiện hồ sơ',COMPLETED:'Đã lưu đầy đủ',FAILED:'Lỗi đồng bộ'};
        sync.append(element('strong',row.sync_status?row.sync_status+' · '+labels[row.sync_status]:'Hồ sơ trước queue'));
        if(row.sync_step)sync.append(element('p',row.sync_step));
        if(row.sync_error)sync.append(element('p',row.sync_error));
        if(['FAILED','PENDING','COMPLETED'].includes(row.sync_status)&&(user.permissions.includes('QC_EDIT')||row.staff_id===user.id&&user.permissions.includes('QC_CREATE'))){
          const retry=element('button',row.sync_status==='COMPLETED'?'Đồng bộ lại hồ sơ':'Thử lại đồng bộ');retry.type='button';retry.onclick=async()=>{retry.disabled=true;try{await api('/api/qc/'+encodeURIComponent(row.id)+'/retry-sync',{method:'POST'});await loadList(listPage);}catch(error){$('message').textContent=error.message;retry.disabled=false;}};sync.append(retry);
        }
        tr.append(sync);
        for(const [value,label] of [[row.evidence,'Mở bằng chứng']]){
          const cell=element('td'),link=element('a',label);link.target='_blank';link.rel='noopener noreferrer';safeLink(link,value);cell.append(link);tr.append(cell);
          if(label==='Mở bằng chứng' && row.evidence_pending)cell.append(element('p','Chờ xử lý Drive · mở chi tiết để thử lại'));
        }
        const action=element('td'),button=element('button','Xem chi tiết');button.type='button';button.onclick=()=>openDetail(row.id);action.append(button);tr.append(action);return tr;
      }));$('summary').textContent=result.total+' phiếu QC';$('pageInfo').textContent='Trang '+page;
      $('previous').disabled=page===1;$('next').disabled=page*result.size>=result.total;
      clearTimeout(pollTimer);
      if(result.items.some(row=>['PENDING','PROCESSING'].includes(row.sync_status)))pollTimer=setTimeout(()=>{if(!document.hidden&&!listLoading)loadList(listPage);},5000);
    }catch(error){if(epoch===listEpoch)$('message').textContent=error.message;}
    finally{if(epoch===listEpoch)listLoading=false;}
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&listParams&&!listLoading)loadList(listPage);});
  async function openDetail(id) {
    try {
      if(window.QCFormUI.busy())throw Error('Hãy hoàn tất upload hoặc giữ nguyên màn hình để thử lại.');
      const record=await api('/api/qc/'+encodeURIComponent(id));newForm();selected=record;
      $('checkType').value=record.check_type;
      if(!combinations[record.check_type]){
        const option=element('option',record.check_type || 'Loại kiểm tra lịch sử chưa xác định');option.value=record.check_type||'';$('checkType').append(option);$('checkType').value=option.value;
      }
      if(combinations[record.check_type])types(record.object_type);
      else $('objectType').replaceChildren();
      for(const node of $('qcForm').querySelectorAll('[name]'))if(record[node.name]!=null)node.value=record[node.name];
      $('quantity').value=integerValue(record.quantity);
      $('checkedAt').value=record.checked_at||'';$('lsx').value=record.production_order_id||'';$('staff').value=record.staff_name||'Chưa xác định';$('ncr').value=record.ncr_id||'';
      $('editorHeading').textContent='Phiếu '+record.id;$('closeEditor').hidden=false;
      viewOnly=!user.permissions.includes('QC_EDIT');
      for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=viewOnly;
      $('closeEditor').disabled=false;$('save').hidden=viewOnly;
      $('topActions').hidden=false;$('saveTop').hidden=viewOnly;$('closeEditorTop').disabled=false;
      $('save').textContent='Lưu phiếu';$('objectPicker').open=false;draftPanel();
      safeLink($('openStandard'),record.standard_url);safeLink($('openImage'),record.evidence);
      window.QCFormUI.load(record,viewOnly);
      if(record.evidence_pending)$('formError').textContent='Bằng chứng chưa xử lý xong: '+record.evidence_error+' Bấm Lưu phiếu để thử lại.';
      $('editor').scrollIntoView({behavior:'smooth'});
    }catch(error){$('message').textContent=error.message;}
  }
  async function init() {
    try {
      user=await window.NAPACO_IDENTITY;
      const view=location.pathname.split('/').pop();
      if(view==='ncr'){$('pending').hidden=false;return;}
      await window.QCFormUI.init();
      if(view==='create'){newForm();}
      else {$('listing').hidden=false;}
      $('checkType').onchange=()=>{if(drafts.length){$('checkType').value='QC NVL';$('formError').textContent='Hãy tạo hoặc bỏ các phiếu đang chờ trước khi đổi loại kiểm tra.';}window.QCFormUI.invalidate(true);types();resetObject();draftPanel();};$('objectType').onchange=()=>{window.QCFormUI.invalidate(true);resetObject();};
      $('findObjects').onclick=()=>findObjects();$('objectPrevious').onclick=()=>findObjects(objectPage-1);$('objectNext').onclick=()=>findObjects(objectPage+1);
      $('objectSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findObjects();}};
      $('objectResults').onchange=()=>{window.QCFormUI.invalidate(true);const value=$('objectResults').value;const row=value===''?null:objectItems[Number(value)];$('objectId').value=row?.id||'';$('lsx').value=row?.production_order_id||'';};
      for(const id of ['quantity','checkedAt','note','result'])$(id).addEventListener('input',()=>window.QCFormUI.invalidate());
      $('qcForm').onsubmit=save;$('newCheck').onclick=nextDraft;
      $('closeEditor').onclick=$('closeEditorTop').onclick=()=>{if(!saving&&!window.QCFormUI.busy()){$('editor').hidden=true;driveEpoch++;objectEpoch++;}};
      window.addEventListener('beforeunload',event=>{if(!queueAccepted&&(drafts.length || saving || window.QCFormUI.busy())){event.preventDefault();event.returnValue='';}});
      $('filters').onsubmit=e=>{e.preventDefault();listParams=[...new FormData($('filters'))].filter(([,value])=>value);loadList();};
      $('previous').onclick=()=>{if(!listLoading)loadList(listPage-1);};$('next').onclick=()=>{if(!listLoading)loadList(listPage+1);};
      if(view==='list') {
        const fields=$('filters').elements;
        const query=new URLSearchParams(location.search).get('q');
        if(query) {
          fields.namedItem('q').value=query;
          // Newly created codes must remain visible even for a backdated inspection.
        } else {
          const parts=Object.fromEntries(new Intl.DateTimeFormat('en', {timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
          const year=Number(parts.year),month=Number(parts.month)-1,day=Number(parts.day);
          const lastDay=new Date(Date.UTC(year,month,0)).getUTCDate();
          fields.namedItem('date_from').value=new Date(Date.UTC(year,month-1,Math.min(day,lastDay))).toISOString().slice(0,10);
          fields.namedItem('date_to').value=parts.year+'-'+parts.month+'-'+parts.day;
        }
        const pending=new URLSearchParams(location.search).get('evidence_pending');
        if(pending)$('message').textContent='Phiếu QC đã lưu. Bằng chứng chưa xử lý xong cho '+pending+'. Mở chi tiết và bấm Lưu phiếu để thử lại.';
        $('filters').requestSubmit();
      }
    }catch(error){$('message').textContent=error.message;}
  }
  init();
})();
