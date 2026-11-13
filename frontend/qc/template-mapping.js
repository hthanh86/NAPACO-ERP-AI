(() => {
  const $=id=>document.getElementById(id), admin=window.QCTemplateAdmin;
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  let fields=[], snapshot=null, sourceHash=null, sources={}, pick=null, epoch=0, dirty=false;
  const frozen=()=>!!admin.selected()?.approved_at;
  function mark(){
    const nodes=$('mappingPreview').querySelectorAll('[data-cell]');
    for(const cell of nodes){cell.classList.remove('map-ERP','map-STANDARD','map-INPUT');cell.removeAttribute('title');}
    const byCell=new Map([...nodes].map(node=>[node.dataset.cell,node]));
    for(const field of fields)for(const key of ['cell','standard_cell','assessment_cell']){
      const node=byCell.get(field[key]);
      if(node){node.classList.add('map-'+(key==='standard_cell'?'STANDARD':field.kind));node.title=field.name+' · '+key;}
    }
  }
  function selectedCell(cell){
    if(frozen()||admin.busy()||!pick)return;
    fields[pick.index][pick.key]=cell;fields[pick.index].reviewed=false;dirty=true;renderFields();mark();
    $('mappingPick').textContent='Đã chọn '+cell+' cho '+fields[pick.index].name;
  }
  function renderPreview(){
    if(snapshot)window.QCSheetPreview.render($('mappingPreview'),snapshot,{selectable:true,onSelect:selectedCell});
    else $('mappingPreview').replaceChildren();
    mark();
  }
  function renderFields(){
    $('mappingFields').replaceChildren(...fields.map((field,index)=>{
      const tr=el('tr');
      function input(key,type='text'){
        const node=el('input');node.type=type;node.disabled=frozen();
        if(type==='checkbox')node.checked=!!field[key];else node.value=field[key]??'';
        node.setAttribute('aria-label',field.name+' · '+key);
        node.onchange=()=>{field[key]=type==='checkbox'?node.checked:node.value.trim();dirty=true;if(key!=='reviewed'){field.reviewed=false;renderFields();}mark();};
        return node;
      }
      function select(key,options){
        const node=el('select');node.disabled=frozen();
        for(const [value,label] of options){const option=el('option',label);option.value=value;node.append(option);}
        node.value=field[key]||'';node.onchange=()=>{
          field[key]=node.value;field.reviewed=false;dirty=true;
          if(key==='kind') {field.source=null;field.standard_cell=null;field.assessment_cell=null;field.allow_na=false;}
          renderFields();mark();
        };return node;
      }
      function td(...nodes){const cell=el('td');cell.append(...nodes);tr.append(cell);}
      const name=input('name'),identifier=input('id');name.readOnly=identifier.readOnly=true;td(name,identifier);
      const kind=select('kind',[['ERP','Tự điền MySQL'],['STANDARD','Tiêu chuẩn cố định'],['INPUT','Kết quả QC nhập']]);
      const source=select('source',[['','Chọn nguồn'],...Object.entries(sources)]);source.hidden=field.kind!=='ERP';td(kind,source);
      for(const key of ['cell','standard_cell','assessment_cell']){
        const node=input(key);node.maxLength=5;node.placeholder='Chọn ô trên preview';
        node.onfocus=()=>{pick={index,key};$('mappingPick').textContent='Đang chọn '+key+' cho '+field.name+' — nhấn ô trên preview.';};
        node.hidden=key!=='cell'&&field.kind!=='INPUT';td(node);
      }
      td(select('data_type',[['text','Văn bản'],['number','Số'],['date','Ngày'],['boolean','Có / Không']]),input('unit'));
      const required=el('label','Bắt buộc');required.prepend(input('required','checkbox'));
      td(required,...(field.kind==='INPUT'?[el('span','Luôn có Không áp dụng')]:[]));
      return tr;
    }));
    const row=admin.selected();
    $('mappingStatus').textContent=row?.approved_at?'Đã phê duyệt '+row.approved_at+' · '+row.approved_by+' · '+row.status+' · Bất biến; thay đổi cần phiên bản mới.':'Kiểm tra mapping rồi Lưu để phê duyệt và kích hoạt ngay. Thay đổi trường/tiêu chí tại Google Sheets rồi tải lại.';
    for(const id of ['suggestMapping','saveMapping'])$(id).disabled=frozen();
    $('activateTemplate').disabled=!frozen()||row?.status==='ACTIVE';
  }
  async function load(){
    const current=++epoch,row=admin.selected();pick=null;dirty=false;$('mappingPanel').hidden=!row;
    if(!row)return;
    try{
      const data=await admin.api('/api/qc/templates/'+encodeURIComponent(row.id)+'/mapping');
      if(current!==epoch)return;
      admin.update(data);snapshot=data.snapshot;sourceHash=data.source_hash;sources=data.sources;
      fields=(data.mapping?.fields||[]).map(clean);renderFields();renderPreview();$('mappingWarnings').textContent='';
    }catch(error){admin.message(error.message);}
  }
  function clean(field){return Object.fromEntries(['id','name','kind','cell','source','data_type','unit','required','allow_na','standard_cell','assessment_cell','reviewed'].map(key=>[key,field[key]??({unit:'',data_type:'text',required:true,allow_na:false,reviewed:false}[key]??null)]));}
  async function refreshAfter(action){
    const row=admin.selected(),data=await admin.api('/api/qc/templates/'+encodeURIComponent(row.id)+'/'+action.path,
      {method:action.method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_updated_at:row.updated_at,...action.body})});
    admin.update(data);await admin.refresh();return data;
  }
  $('suggestMapping').onclick=()=>admin.work(async()=>{
    const data=await refreshAfter({path:'suggest'});
    // Suggestions do not modify the registered template until explicitly saved.
    snapshot=data.snapshot;sourceHash=data.source_hash;sources=data.sources;fields=data.fields.map(clean);dirty=true;
    renderFields();renderPreview();$('mappingWarnings').textContent=data.warnings.join(' ');
    admin.message('Đã tải '+fields.length+' trường từ Google Sheets. Kiểm tra rồi Lưu để phê duyệt và kích hoạt.');
  });
  $('saveMapping').onclick=()=>{
    const body={fields:structuredClone(fields),source_hash:sourceHash};
    admin.work(async()=>{await refreshAfter({path:'mapping',method:'PUT',body});await load();admin.message('Đã lưu, phê duyệt và kích hoạt template.');});
  };
  function release(path,body={},text='Đã cập nhật template.'){
    if(dirty){admin.message('Hãy lưu mapping trước khi đổi trạng thái hoặc kiểm tra nguồn.');return;}
    admin.work(async()=>{try{await refreshAfter({path,body});await load();admin.message(text);}catch(error){await load();await admin.refresh();throw error;}});
  }
  $('activateTemplate').onclick=()=>release('status',{status:'ACTIVE'},'Đã kích hoạt template đã duyệt.');
  $('deactivateTemplate').onclick=()=>release('status',{status:'INACTIVE'},'Đã ngừng kích hoạt. Hồ sơ cũ giữ nguyên.');
  $('verifyTemplate').onclick=()=>release('verify',{},'Nguồn Google vẫn khớp bản chụp đã lưu.');
  $('newVersion').onclick=()=>admin.newVersion();
  window.addEventListener('qc-template-selected',load);
  window.addEventListener('qc-template-work-finished',()=>{if(admin.selected())renderFields();});
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
})();
