/* Optional approved template branch; the existing form/Drive workflow stays intact. */
(() => {
  const legacy=window.QCFormUI,$=id=>document.getElementById(id);
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  let entry=null,draft=null,record=null,epoch=0,loading=false,choices=[],recordReadonly=true,canEditRecord=false;
  let legacyRecord=false;
  async function api(url,options={}){
    const response=await fetch(url,{cache:'no-store',...options});let body;
    try{body=await response.json();}catch{throw Error('Không đọc được phản hồi máy chủ (HTTP '+response.status+'). Vui lòng thử lại.');}
    if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:(body.detail||[]).map(item=>item.loc?.includes('quantity')?'Số lượng kiểm tra phải là số nguyên dương.':item.msg).join('; ')||'Không thực hiện được yêu cầu.');
    return body;
  }
  const params=()=>new URLSearchParams({check_type:$('checkType').value,object_type:$('objectType').value,object_id:$('objectId').value});
  function mode(){
    const active=!!entry;
    $('legacyFormSection').hidden=!legacyRecord;$('legacyEvidenceSection').hidden=false;
    $('useLegacyForm').hidden=true;
    $('openMappedForm').disabled=!active||loading;
    $('result').readOnly=active;
    $('mappedSummary').textContent=active?(entry.code+' · v'+entry.version+(draft?' · '+draft.conclusion+' · '+(draft.confirmation||recordReadonly&&record?.form_data.signer?'Đã ký xác nhận':draft.signature?.length?'Giữ nét ký · xác nhận nội dung khi lưu':'Chưa có chữ ký'):' · Chưa nhập kết quả')):'Chọn đối tượng để xác định Google Sheets Template áp dụng.';
    $('mappedTemplate').disabled=true;
    $('findMappedTemplates').disabled=!!record||loading;
    $('resignMapped').hidden=!record||!canEditRecord;
    $('resignMapped').disabled=loading;
    $('mappedPdf').hidden=!record?.pdf_url;
    if(record?.pdf_url)$('mappedPdf').href=record.pdf_url;
  }
  async function refresh(){
    if(record)return;
    if(entry){entry=draft=null;$('result').value='';legacy.reset();mode();}
    const current=++epoch;choices=[];$('mappedTemplate').replaceChildren(el('option','Chọn template đã duyệt'));$('mappedTemplate').options[0].value='';
    if(!$('objectId').value){$('mappedSummary').textContent='Chọn đối tượng cần kiểm tra trước.';return;}
    loading=true;mode();
    try{
      const data=await api('/api/qc/template-options?'+params());if(current!==epoch)return;
      choices=data.items;
      for(const item of choices){const option=el('option',item.code+' · v'+item.version+' · '+item.name);option.value=item.id;$('mappedTemplate').append(option);}
      if(choices.length===1){
        const data=await api('/api/qc/templates/'+encodeURIComponent(choices[0].id)+'/entry?'+params());
        if(current!==epoch)return;entry=data;$('mappedTemplate').value=data.id;mode();
      }else $('mappedSummary').textContent='Chưa xác định được một template duy nhất. Không thể tạo QC.';
    }catch(error){if(current===epoch)$('mappedSummary').textContent=error.message;}
    finally{if(current===epoch){loading=false;$('findMappedTemplates').disabled=false;}}
  }
  function automatic(){
    if(record)return record.form_data.auto_values;
    const values={...entry.context,check_type:$('checkType').value,quantity:$('quantity').value,
      checked_at:$('checkedAt').value,staff_name:window.NAPACO_USER?.name||'',qc_id:'Cấp mã khi lưu',
      qc_note:$('note').value,signer_name:window.NAPACO_USER?.name||'',signed_at:'Xác nhận khi ký'};
    return Object.fromEntries(entry.mapping.fields.filter(field=>field.kind==='ERP').map(field=>[field.id,String(values[field.source]??'')]));
  }
  function edit(){
    if(!entry)return;
    const readonly=!!record&&recordReadonly,auto=automatic(),modal=el('dialog');modal.className='qc-dialog mapped-dialog';
    const close=el('button','Đóng');close.type='button';close.onclick=()=>modal.close();
    modal.append(el('h2',entry.name+' · '+entry.code+' · v'+entry.version),close);
    const quantity=el('input'),quantityLabel=el('label','Số lượng kiểm tra *');
    quantity.type='number';quantity.min='1';quantity.step='1';quantity.required=true;
    quantity.value=$('quantity').value;quantity.disabled=readonly;quantityLabel.append(quantity);modal.append(quantityLabel);
    modal.addEventListener('close',()=>modal.remove());document.body.append(modal);modal.showModal();
    const context=el('details');context.open=true;context.append(el('summary','Dữ liệu đối tượng từ MySQL'));
    const contextGrid=el('dl');contextGrid.className='mapped-context';
    const labels={qc_id:'Mã QC',object_id:'Phiếu nhập / đối tượng',resin:'Nhựa theo PO',material_id:'Mã NVL',supplier_name:'Nhà cung cấp',
      po_id:'Đơn đặt NVL',po_line_id:'Chi tiết PO',width:'Khổ đặt',thickness:'Độ dày đặt',grade:'Phẩm cấp',color:'Màu',esd:'ESD',
      po_quantity:'Số lượng đặt',received_quantity:'Số lượng nhận',product_ids:'Mã sản phẩm',product_names:'Tên sản phẩm',receipt_date:'Ngày nhận',production_date:'Ngày sản xuất'};
    const values=record?.form_data.context||entry.context;
    for(const [key,label] of Object.entries(labels))if(values[key]!=null&&values[key]!==''){contextGrid.append(el('dt',label),el('dd',String(values[key])));}
    context.append(contextGrid);modal.append(context);
    const preview=el('div');preview.className='sheet-preview';window.QCSheetPreview.render(preview,entry.snapshot,{selectable:true});
    const nodeAt=cell=>[...preview.querySelectorAll('[data-cell]')].find(node=>node.dataset.cell===cell);
    for(const field of entry.mapping.fields){
      const cell=nodeAt(field.cell);if(cell){cell.classList.add('map-'+field.kind);if(field.kind==='ERP')cell.firstChild.textContent=auto[field.id]||'—';if(field.kind==='INPUT')cell.firstChild.textContent='';}
    }
    const table=el('table'),head=el('tr');for(const label of ['Tiêu chí','Tiêu chuẩn / đơn vị','Kết quả thực tế','Đánh giá','Ghi chú'])head.append(el('th',label));table.append(head);
    const inputs=[];
    for(const field of entry.mapping.fields.filter(field=>field.kind==='INPUT')){
      const old=draft?.answers.find(answer=>answer.id===field.id),row=el('tr'),actual=el('input'),assessment=el('select'),note=el('textarea');
      actual.maxLength=2000;actual.value=old?.actual||'';actual.setAttribute('aria-label',field.name+' · kết quả');
      if(field.data_type==='number'){actual.type='number';actual.step='any';}else if(field.data_type==='date')actual.type='date';
      if(field.data_type==='boolean'){actual.placeholder='true / false';}
      for(const [value,label] of [['','Chọn đánh giá'],['PASS','Đạt'],['FAIL','Không đạt'],['NA','Không áp dụng']]){const option=el('option',label);option.value=value;assessment.append(option);}
      assessment.value=old?.assessment||'';note.value=old?.note||'';note.maxLength=2000;
      actual.disabled=assessment.disabled=note.disabled=readonly;
      function reflect(){
        actual.disabled=readonly||assessment.value==='NA';
        if(nodeAt(field.cell))nodeAt(field.cell).firstChild.textContent=assessment.value==='NA'?'N/A':actual.value;
        if(field.assessment_cell&&nodeAt(field.assessment_cell))nodeAt(field.assessment_cell).firstChild.textContent=assessment.value;
      }
      assessment.onchange=()=>{if(assessment.value==='NA')actual.value='';reflect();};actual.oninput=reflect;reflect();
      row.append(el('td',field.name+(field.required?' *':'')),el('td',[field.standard,field.unit].filter(Boolean).join(' · ')));
      for(const node of [actual,assessment,note]){const cell=el('td');cell.append(node);row.append(cell);}table.append(row);
      inputs.push({field,actual,assessment,note});
    }
    const wrap=el('div');wrap.className='table-wrap';wrap.append(table);modal.append(wrap,el('p','Chọn đánh giá theo kết quả kiểm tra. ERP không suy đoán dung sai; N/A không phải Đạt.'));
    const conclusion=el('select');for(const [value,label] of [['','Chọn kết luận'],['PASS','Đạt'],['FAIL','Không đạt'],...(readonly&&draft?.conclusion==='NA'?[['NA','N/A (hồ sơ lịch sử)']]:[])]){const option=el('option',label);option.value=value;conclusion.append(option);}
    conclusion.value=draft?.conclusion||'';conclusion.disabled=readonly;modal.append(el('p','Kết luận'),conclusion);
    modal.append(el('p','Chữ ký xác nhận nội bộ · không phải chữ ký số có chứng thư số'));
    const canvas=el('canvas');canvas.width=900;canvas.height=240;canvas.className='qc-signature';canvas.setAttribute('aria-label','Vùng ký xác nhận QC');modal.append(canvas);
    const pen=canvas.getContext('2d');let strokes=structuredClone(draft?.signature||[]),currentStroke=null;
    function draw(){pen.clearRect(0,0,900,240);pen.strokeStyle='#183a68';pen.lineWidth=2.5;pen.lineCap='round';for(const stroke of strokes){pen.beginPath();stroke.forEach(([x,y],index)=>pen[index?'lineTo':'moveTo'](x*900,y*240));pen.stroke();}}
    function invalidateSignature(){if(!readonly){strokes=[];draw();}}
    function point(event){const box=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))];}
    canvas.onpointerdown=event=>{if(readonly||loading)return;event.preventDefault();canvas.setPointerCapture(event.pointerId);currentStroke=[point(event)];strokes.push(currentStroke);};
    canvas.onpointermove=event=>{if(currentStroke&&strokes.reduce((n,s)=>n+s.length,0)<15000){currentStroke.push(point(event));draw();}};
    canvas.onpointerup=canvas.onpointercancel=()=>{currentStroke=null;};draw();
    const signer=record?.form_data.signer;
    modal.append(el('p',readonly&&signer?'Người ký: '+signer.name+' · '+(signer.email||'')+' · '+signer.signed_at:'Ký bằng phiên Google hiện tại: '+(window.NAPACO_USER?.email||'Cần kết nối Google.')));
    if(!readonly){const clear=el('button','Xóa và ký lại');clear.type='button';clear.onclick=invalidateSignature;modal.append(clear);}
    const error=el('p');error.className='error';modal.append(error);
    if(!readonly){const apply=el('button','Áp dụng kết quả');apply.type='button';apply.onclick=async()=>{
      try{
        if(!quantity.reportValidity())throw Error('Hãy nhập số lượng kiểm tra là số nguyên dương.');
        $('quantity').value=quantity.value;
        const answers=inputs.map(({field,actual,assessment,note})=>{
          if(field.required&&!assessment.value)throw Error('Cần đánh giá '+field.name);
          if(field.required&&assessment.value!=='NA'&&!actual.value.trim())throw Error('Thiếu kết quả '+field.name);
          return {id:field.id,actual:assessment.value==='NA'?'':actual.value.trim(),assessment:assessment.value||null,note:note.value.trim()};
        });
        const evaluations=answers.map(answer=>answer.assessment).filter(Boolean);
        if(!evaluations.some(value=>value==='PASS'||value==='FAIL'))throw Error('Cần ít nhất một tiêu chí Đạt hoặc Không đạt để kết luận.');
        const expected=evaluations.includes('FAIL')?'FAIL':'PASS';
        if(conclusion.value!==expected)throw Error('Kết luận phải khớp đánh giá các tiêu chí áp dụng.');
        if(!strokes.some(stroke=>stroke.length>=2&&new Set(stroke.map(p=>p.join(','))).size>=2))throw Error('Hãy ký xác nhận trước khi áp dụng.');
        if(!entry.mapping.signature_cell)throw Error('Quản lý cần phê duyệt vùng chữ ký của template trước.');
        const next={template_id:entry.id,source_hash:entry.source_hash,mapping_hash:entry.mapping_hash,answers,conclusion:conclusion.value,signature:strokes,
          reuse_signature:!!record&&JSON.stringify(strokes)===JSON.stringify(record.form_data.input.signature)};
        const payload={...Object.fromEntries(new FormData($('qcForm'))),form:null,mapped_form:next,result:expected==='PASS'?'OK':'NG'};
        const currentEpoch=epoch;loading=true;apply.disabled=true;
        const confirmed=await api('/api/qc/signatures/confirm'+(record?'?qc_id='+encodeURIComponent(record.id):''),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if(currentEpoch!==epoch)return;
        draft={...next,confirmation:confirmed.confirmation};
        $('result').value=expected==='PASS'?'OK':'NG';mode();modal.close();
      }catch(reason){error.textContent=reason.message;}finally{loading=false;apply.disabled=false;mode();}
    };modal.append(apply);}
    modal.append(el('h3','Bản chụp template · chỉ đọc'),preview);
  }
  window.QCFormUI={...legacy,
    async init(){
      await legacy.init();$('openMappedForm').onclick=edit;$('findMappedTemplates').onclick=refresh;
      $('resignMapped').textContent='Sửa nội dung';
      $('resignMapped').onclick=()=>{if(!canEditRecord)return;recordReadonly=false;if(draft){if(record?.form_data.signer?.user_id!==window.NAPACO_USER?.id)draft.signature=[];draft.confirmation=null;}edit();};
      $('mappedTemplate').onchange=async()=>{
        const id=$('mappedTemplate').value;entry=draft=null;legacy.reset();mode();if(!id)return;
        const current=++epoch;loading=true;mode();
        try{const data=await api('/api/qc/templates/'+encodeURIComponent(id)+'/entry?'+params());if(current!==epoch)return;entry=data;$('standardUrl').value='';$('imageUrl').value='';$('result').value='';mode();edit();}
        catch(error){if(current===epoch)$('mappedSummary').textContent=error.message;}
        finally{if(current===epoch){loading=false;mode();}}
      };
      $('useLegacyForm').onclick=()=>{entry=draft=null;$('mappedTemplate').value='';$('result').value='';mode();};
    },
    reset(){epoch++;entry=draft=record=null;legacyRecord=false;choices=[];loading=false;recordReadonly=true;canEditRecord=false;legacy.reset();$('mappedFormSection').hidden=false;$('mappedTemplate').replaceChildren(el('option','Template tự động theo đối tượng'));$('mappedTemplate').options[0].value='';mode();},
    load(item,viewOnly){
      if(!item.template_id){entry=draft=record=null;legacyRecord=true;legacy.load(item,viewOnly);$('mappedFormSection').hidden=true;mode();return;}
      legacyRecord=false;
      legacy.reset();record=item;recordReadonly=true;canEditRecord=!viewOnly;const saved=item.form_data;entry={...saved.template,id:saved.template.id,context:saved.context};
      if(!entry.mapping.signature_cell&&item.signature_mapping_extension){entry.mapping=item.signature_mapping_extension;entry.mapping_hash=item.signature_mapping_hash;}
      draft={...saved.input,template_id:item.template_id};
      legacy.evidenceRecord(item);
      $('mappedFormSection').hidden=false;$('mappedTemplate').replaceChildren(el('option',entry.code+' · v'+entry.version));mode();$('openMappedForm').disabled=false;
    },
    payload(){if(entry){if(!draft?.confirmation)throw Error('Hãy xác nhận nội dung QC trước khi lưu.');return {...legacy.payload(),form:null,mapped_form:draft};}if(!legacyRecord)throw Error('Cần một Google Sheets Template đã duyệt phù hợp trước khi tạo QC.');return legacy.payload();},
    async prepare(){
      if(!entry||draft?.confirmation)return;
      if(!draft?.signature?.some(stroke=>stroke.length>=2))throw Error('Hãy nhập kết quả và ký xác nhận lần đầu trước khi lưu.');
      draft={...draft,template_id:entry.id,source_hash:entry.source_hash,mapping_hash:entry.mapping_hash,
        reuse_signature:!!record&&JSON.stringify(draft.signature)===JSON.stringify(record.form_data.input.signature)};
      const current=epoch;loading=true;mode();
      try{
        const payload={...Object.fromEntries(new FormData($('qcForm'))),form:null,mapped_form:draft};
        const confirmed=await api('/api/qc/signatures/confirm'+(record?'?qc_id='+encodeURIComponent(record.id):''),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if(current!==epoch)throw Error('Đối tượng QC đã thay đổi trong khi xác nhận.');
        draft={...draft,confirmation:confirmed.confirmation};
      }finally{loading=false;mode();}
    },
    files(){return legacy.files();},
    async uploadRecords(records,files,onDone){return legacy.uploadRecords(records,files,onDone);},
    busy(){return loading||legacy.busy();},
    invalidate(discard=false){
      if(discard){epoch++;entry=draft=record=null;loading=false;legacy.invalidate(true);mode();queueMicrotask(refresh);}
      else if(entry){if(draft)draft.confirmation=null;if(record&&canEditRecord)recordReadonly=false;mode();}
      else legacy.invalidate();
    }
  };
  window.addEventListener('qc-evidence-updated',event=>{if(record?.id===event.detail.id){record=event.detail;mode();if(record.drive_folder_id){$('openImage').href='https://drive.google.com/drive/folders/'+encodeURIComponent(record.drive_folder_id);$('openImage').hidden=false;}}});
})();
