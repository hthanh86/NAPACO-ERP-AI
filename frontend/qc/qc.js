(() => {
  const $ = id => document.getElementById(id);
  const combinations = {'QC NVL':['NVL'], 'QC ĐẦU CA':['SETUP'], 'QC GIỮA CA':['HUT','CAT','EB'], 'QC CUỐI CA':['HUT','CAT','EB']};
  let user, selected = null, requestToken = null, requestPayload = '', saved = false, viewOnly = false;
  let objectPage = 1, objectQuery = '', objectEpoch = 0, objectItems = [], objectLoading = false;
  let listPage = 1, listParams = null, listEpoch = 0, listLoading = false, driveEpoch = 0;
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
  }
  function types(value) {
    $('objectType').replaceChildren(...combinations[$('checkType').value].map(kind => {const option=element('option',kind);option.value=kind;return option;}));
    if (value) $('objectType').value=value;
  }
  function localTime() {
    const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,19);
  }
  function newForm() {
    selected=null; requestToken=null; requestPayload=''; saved=false; viewOnly=false; driveEpoch++;
    $('qcForm').reset(); types(); resetObject(); $('checkedAt').value=localTime(); $('staff').value=user.name + ' ('+user.id+')';
    $('editorHeading').textContent='Tạo Phiếu QC'; $('save').hidden=false; $('save').disabled=false;
    $('newCheck').hidden=true; $('closeEditor').hidden=true; $('formError').textContent='';
    $('driveResults').replaceChildren(); $('driveStatus').textContent=''; $('editor').hidden=false;
    for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=false;
    $('objectPrevious').disabled=true; $('objectNext').disabled=true;
    safeLink($('openStandard'),''); safeLink($('openImage'),'');
  }
  async function findObjects(page=1) {
    const query=page===1 ? $('objectSearch').value.trim() : objectQuery;
    if (!query) {$('objectHint').textContent='Hãy nhập từ khóa tìm kiếm.';return;}
    const epoch=++objectEpoch;objectLoading=true; $('findObjects').disabled=true; $('objectPrevious').disabled=true; $('objectNext').disabled=true;
    const params=new URLSearchParams({check_type:$('checkType').value,object_type:$('objectType').value,q:query,page:String(page)});
    try {
      const result=await api('/api/qc/objects?'+params);
      if(epoch!==objectEpoch)return;
      objectPage=page;objectQuery=query;objectItems=result.items;
      const placeholder=element('option','— Chọn bản ghi —'); placeholder.value='';
      $('objectResults').replaceChildren(placeholder,...result.items.map((row,index)=>{
        const option=element('option',[row.id,row.production_order_id && 'LSX: '+row.production_order_id,row.date,row.reference,row.info].filter(Boolean).join(' · '));option.value=String(index);return option;
      }));$('objectResults').value='';
      $('objectHint').textContent=`Trang ${page} · ${result.items.length} kết quả`;
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
  async function save(event) {
    event.preventDefault();if(saved || viewOnly || $('save').disabled)return;
    $('formError').textContent='';if(!$('objectId').value){$('formError').textContent='Hãy chọn một bản ghi cần kiểm tra.';return;}
    const payload=Object.fromEntries(new FormData($('qcForm')));
    if(selected)payload.version=selected.version;
    const body=JSON.stringify(payload);
    if(body!==requestPayload){requestPayload=body;requestToken=crypto.randomUUID();}
    $('save').disabled=true;
    try {
      const result=await api(selected ? '/api/qc/'+encodeURIComponent(selected.id) : '/api/qc',{
        method:selected?'PUT':'POST',headers:{'Content-Type':'application/json','Idempotency-Key':requestToken},body});
      saved=true;$('message').textContent='Đã lưu phiếu '+result.id+'.';$('editorHeading').textContent=result.id;
      $('save').hidden=true;$('newCheck').hidden=!user.permissions.includes('QC_CREATE');
      if(listParams)await loadList(listPage);
    }catch(error){$('formError').textContent=error.message;}
    finally{$('save').disabled=false;}
  }
  async function loadList(page=1) {
    if(!listParams)return;
    const epoch=++listEpoch;listLoading=true;$('previous').disabled=true;$('next').disabled=true;
    const params=new URLSearchParams(listParams);params.set('page',String(page));
    try {
      const result=await api('/api/qc?'+params);if(epoch!==listEpoch)return;listPage=page;
      $('rows').replaceChildren(...result.items.map(row=>{
        const tr=element('tr');
        for(const value of [row.id,row.checked_at?.replace('T',' '),row.check_type,[row.object_type,row.object_id].filter(Boolean).join(' · '),row.production_order_id,row.quantity,row.result,row.staff_id])tr.append(element('td',value??''));
        const document=element('td'), link=element('a','Mở hồ sơ');link.target='_blank';link.rel='noopener noreferrer';safeLink(link,row.standard_url);document.append(link);tr.append(document);
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
      $('checkedAt').value=record.checked_at||'';$('lsx').value=record.production_order_id||'';$('staff').value=record.staff_id||'';$('ncr').value=record.ncr_id||'';
      $('editorHeading').textContent='Phiếu '+record.id;$('closeEditor').hidden=false;
      viewOnly=!user.permissions.includes('QC_EDIT');
      for(const node of $('qcForm').querySelectorAll('input,select,textarea,button'))node.disabled=viewOnly;
      $('closeEditor').disabled=false;$('save').hidden=viewOnly;
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
      $('checkType').onchange=()=>{types();resetObject();};$('objectType').onchange=resetObject;
      $('findObjects').onclick=()=>findObjects();$('objectPrevious').onclick=()=>findObjects(objectPage-1);$('objectNext').onclick=()=>findObjects(objectPage+1);
      $('objectSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findObjects();}};
      $('objectResults').onchange=()=>{const value=$('objectResults').value;const row=value===''?null:objectItems[Number(value)];$('objectId').value=row?.id||'';$('lsx').value=row?.production_order_id||'';};
      $('findDrive').onclick=findDrive;$('driveSearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findDrive();}};
      $('standardUrl').oninput=()=>safeLink($('openStandard'),$('standardUrl').value);$('imageUrl').oninput=()=>safeLink($('openImage'),$('imageUrl').value);
      $('qcForm').onsubmit=save;$('newCheck').onclick=newForm;$('closeEditor').onclick=()=>{$('editor').hidden=true;driveEpoch++;objectEpoch++;};
      $('filters').onsubmit=e=>{e.preventDefault();listParams=[...new FormData($('filters'))].filter(([,value])=>value);loadList();};
      $('previous').onclick=()=>{if(!listLoading)loadList(listPage-1);};$('next').onclick=()=>{if(!listLoading)loadList(listPage+1);};
    }catch(error){$('message').textContent=error.message;}
  }
  init();
})();
