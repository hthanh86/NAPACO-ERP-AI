(() => {
  const $ = id => document.getElementById(id);
  const combinations = {'QC NVL':['NVL'], 'QC ĐẦU CA':['SETUP'], 'QC GIỮA CA':['HUT','CAT','EB'], 'QC CUỐI CA':['HUT','CAT','EB']};
  let user, selected = null, requestToken = null, requestPayload = '', saved = false, viewOnly = false;
  let objectPage = 1, objectQuery = '', objectEpoch = 0, objectItems = [], objectLoading = false;
  let listPage = 1, listParams = null, listEpoch = 0, listLoading = false, driveEpoch = 0;
  let drafts = [], saving = false;
  function element(tag, text) { const node = document.createElement(tag); if (text != null) node.textContent = text; return node; }
  async function api(url, options = {}) {
    const response = await fetch(url, {cache:'no-store', ...options});
    const body = await response.json();
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
    selected=null; requestToken=null; requestPayload=''; saved=false; viewOnly=false; driveEpoch++;
    $('qcForm').reset(); types(); resetObject(); $('checkedAt').value=localTime(); $('staff').value=user.name;
    $('editorHeading').textContent='Tạo Phiếu QC'; $('save').hidden=false; $('save').disabled=false;
    $('newCheck').hidden=false; $('closeEditor').hidden=true; $('topActions').hidden=true; $('formError').textContent='';
    $('save').textContent='Tạo Phiếu';
    $('driveResults').replaceChildren(); $('driveStatus').textContent=''; $('editor').hidden=false;
    for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=false;
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
  async function findDrive() {
    const query=$('driveSearch').value.trim();if(!query){$('driveStatus').textContent='Nhập tên file hoặc URL Google Drive.';return;}
    const epoch=++driveEpoch;$('findDrive').disabled=true;$('driveStatus').textContent='Đang tìm file…';$('driveResults').replaceChildren();
    try {
      const result=await api('/api/qc/drive?q='+encodeURIComponent(query));if(epoch!==driveEpoch)return;
      if(!result.success)throw Error(result.error || 'Không tìm được file Drive.');
      $('driveStatus').textContent=result.files.length ? 'Chọn file để lưu URL hồ sơ.' : 'Không tìm thấy file. Bạn có thể dán URL trực tiếp.';
      if(result.incomplete)$('driveStatus').textContent+=' Kết quả có thể chưa đầy đủ; hãy dùng từ khóa cụ thể hơn.';
      $('driveResults').replaceChildren(...result.files.map(file=>{
        const button=element('button',file.name + (file.updated ? ' · '+file.updated : ''));button.type='button';
        button.onclick=()=>{$('standardUrl').value=file.url;safeLink($('openStandard'),file.url);$('driveStatus').textContent='Đã chọn: '+file.name;};return button;
      }));
    }catch(error){if(epoch===driveEpoch)$('driveStatus').textContent=error.message;}
    finally{if(epoch===driveEpoch)$('findDrive').disabled=false;}
  }
  function formPayload() {
    if(!$('objectId').value){$('objectPicker').open=true;throw Error('Hãy chọn một bản ghi cần kiểm tra.');}
    if(!$('qcForm').reportValidity())throw Error('Hãy kiểm tra các trường bắt buộc; số lượng phải là số nguyên dương.');
    const payload=Object.fromEntries(new FormData($('qcForm')));
    if(!selected && drafts.some(draft=>draft.payload.object_id.toLowerCase()===payload.object_id.toLowerCase()))throw Error('Phiếu nhập này đã có trong danh sách chờ.');
    return payload;
  }
  function nextDraft() {
    if(saving || selected)return;
    if(saved){newForm();return;}
    try {
      if(drafts.length>=9)throw Error('Đang nhập phiếu thứ 10. Hãy bấm Tạo Phiếu để lưu lô.');
      const payload=formPayload();
      if(payload.check_type!=='QC NVL')throw Error('Tạo nhiều phiếu chỉ áp dụng cho IQC NVL.');
      drafts.push({payload,label:payload.object_id+' · '+payload.quantity+' · '+payload.result});
      newForm(true);$('editorHeading').textContent='Nhập phiếu '+(drafts.length+1)+' / 10';
    }catch(error){$('formError').textContent=error.message;}
  }
  async function save(event) {
    event.preventDefault();if(saved || viewOnly || saving)return;
    $('formError').textContent='';
    let payload, batch=false;
    try {
      const hasCurrent=['objectId','quantity','result','standardUrl','note','imageUrl'].some(id=>$(id).value.trim());
      const current=hasCurrent || !drafts.length || selected ? formPayload() : null;
      if(!selected && (drafts.length || current?.check_type==='QC NVL')) {
        const items=[...drafts.map(draft=>draft.payload),...(current?[current]:[])];
        if(items.length>10)throw Error('Tối đa 10 phiếu trong một lần tạo.');
        if(items.some(item=>item.check_type!=='QC NVL'))throw Error('Lô đang có phiếu IQC NVL; hãy hoàn tất lô này trước khi chọn loại kiểm tra khác.');
        payload={items};batch=true;
      }else payload=current;
    }catch(error){$('formError').textContent=error.message;return;}
    if(selected)payload.version=selected.version;
    const body=JSON.stringify(payload);
    if(body!==requestPayload){requestPayload=body;requestToken=crypto.randomUUID();}
    saving=true;objectEpoch++;driveEpoch++;
    const disabledStates=[...document.querySelectorAll('#qcForm input,#qcForm select,#qcForm textarea,#qcForm button,#drafts button')].map(node=>[node,node.disabled]);
    for(const [node] of disabledStates)node.disabled=true;
    try {
      const result=await api(selected ? '/api/qc/'+encodeURIComponent(selected.id) : batch?'/api/qc/batch':'/api/qc',{
        method:selected?'PUT':'POST',headers:{'Content-Type':'application/json','Idempotency-Key':requestToken},body});
      if(selected){selected=result;$('message').textContent='Đã lưu phiếu '+result.id+'.';}
      else {
        saved=true;drafts=[];const ids=batch?result.items.map(item=>item.id):[result.id];
        $('message').textContent='Đã tạo '+ids.length+' phiếu: '+ids.join(', ')+'.';$('editorHeading').textContent='Đã tạo phiếu QC';
        $('save').hidden=true;
      }
      if(listParams)await loadList(listPage);
    }catch(error){$('formError').textContent=error.message;}
    finally{
      saving=false;for(const [node,disabled] of disabledStates)node.disabled=disabled;
      if(!saved){$('findObjects').disabled=viewOnly;$('findDrive').disabled=viewOnly;}
      if(saved)for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=true;
      draftPanel();if(saved)$('newCheck').disabled=false;
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
        for(const [value,label] of [[row.standard_url,'Mở tiêu chuẩn'],[row.evidence,'Mở bằng chứng']]){
          const cell=element('td'),link=element('a',label);link.target='_blank';link.rel='noopener noreferrer';safeLink(link,value);cell.append(link);tr.append(cell);
        }
        const action=element('td'),button=element('button','Xem chi tiết');button.type='button';button.onclick=()=>openDetail(row.id);action.append(button);tr.append(action);return tr;
      }));$('summary').textContent=result.total+' phiếu QC';$('pageInfo').textContent='Trang '+page;
      $('previous').disabled=page===1;$('next').disabled=page*result.size>=result.total;
    }catch(error){if(epoch===listEpoch)$('message').textContent=error.message;}
    finally{if(epoch===listEpoch)listLoading=false;}
  }
  async function openDetail(id) {
    try {
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
      safeLink($('openStandard'),record.standard_url);safeLink($('openImage'),record.image_url);
      $('editor').scrollIntoView({behavior:'smooth'});
    }catch(error){$('message').textContent=error.message;}
  }
  async function init() {
    try {
      user=await window.NAPACO_IDENTITY;
      const view=location.pathname.split('/').pop();
      if(view==='ncr'){$('pending').hidden=false;return;}
      if(view==='create'){newForm();}
      else {$('listing').hidden=false;}
      $('checkType').onchange=()=>{if(drafts.length){$('checkType').value='QC NVL';$('formError').textContent='Hãy tạo hoặc bỏ các phiếu đang chờ trước khi đổi loại kiểm tra.';}types();resetObject();draftPanel();};$('objectType').onchange=resetObject;
      $('findObjects').onclick=()=>findObjects();$('objectPrevious').onclick=()=>findObjects(objectPage-1);$('objectNext').onclick=()=>findObjects(objectPage+1);
      $('objectSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findObjects();}};
      $('objectResults').onchange=()=>{const value=$('objectResults').value;const row=value===''?null:objectItems[Number(value)];$('objectId').value=row?.id||'';$('lsx').value=row?.production_order_id||'';};
      $('findDrive').onclick=findDrive;$('driveSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findDrive();}};
      $('standardUrl').oninput=()=>safeLink($('openStandard'),$('standardUrl').value);$('imageUrl').oninput=()=>safeLink($('openImage'),$('imageUrl').value);
      $('qcForm').onsubmit=save;$('newCheck').onclick=nextDraft;
      $('closeEditor').onclick=$('closeEditorTop').onclick=()=>{if(!saving){$('editor').hidden=true;driveEpoch++;objectEpoch++;}};
      window.addEventListener('beforeunload',event=>{if(drafts.length || saving){event.preventDefault();event.returnValue='';}});
      $('filters').onsubmit=e=>{e.preventDefault();listParams=[...new FormData($('filters'))].filter(([,value])=>value);loadList();};
      $('previous').onclick=()=>{if(!listLoading)loadList(listPage-1);};$('next').onclick=()=>{if(!listLoading)loadList(listPage+1);};
    }catch(error){$('message').textContent=error.message;}
  }
  init();
})();
