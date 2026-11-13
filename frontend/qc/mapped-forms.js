/* Optional approved template branch; the existing form/Drive workflow stays intact. */
(() => {
  const legacy=window.QCFormUI,$=id=>document.getElementById(id);
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  let entry=null,draft=null,record=null,epoch=0,loading=false,choices=[];
  async function api(url){
    const response=await fetch(url,{cache:'no-store'});let body;
    try{body=await response.json();}catch{throw Error('Không đọc được phản hồi máy chủ (HTTP '+response.status+'). Vui lòng thử lại.');}
    if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));
    return body;
  }
  const params=()=>new URLSearchParams({check_type:$('checkType').value,object_type:$('objectType').value,object_id:$('objectId').value});
  function mode(){
    const active=!!entry;
    $('legacyFormSection').hidden=$('legacyEvidenceSection').hidden=active;
    $('useLegacyForm').hidden=!active||!!record;
    $('openMappedForm').disabled=!active;
    $('result').readOnly=active;
    $('mappedSummary').textContent=active?(entry.code+' · v'+entry.version+(draft?' · '+draft.conclusion:' · Chưa nhập kết quả')):'Chọn template đã duyệt hoặc dùng biểu mẫu ERP hiện có.';
    $('mappedTemplate').disabled=!!record;
    $('findMappedTemplates').disabled=!!record||loading;
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
      $('mappedSummary').textContent=choices.length?'Có '+choices.length+' template ACTIVE phù hợp.':'Chưa có template ACTIVE phù hợp. Có thể dùng luồng biểu mẫu ERP hiện có.';
    }catch(error){if(current===epoch)$('mappedSummary').textContent=error.message;}
    finally{if(current===epoch){loading=false;$('findMappedTemplates').disabled=false;}}
  }
  function automatic(){
    if(record)return record.form_data.auto_values;
    const values={...entry.context,check_type:$('checkType').value,quantity:$('quantity').value,
      checked_at:$('checkedAt').value,staff_name:window.NAPACO_USER?.name||'',qc_id:'Cấp mã khi lưu'};
    return Object.fromEntries(entry.mapping.fields.filter(field=>field.kind==='ERP').map(field=>[field.id,String(values[field.source]??'')]));
  }
  function edit(){
    if(!entry)return;
    const readonly=!!record,auto=automatic(),modal=el('dialog');modal.className='qc-dialog mapped-dialog';
    const close=el('button','Đóng');close.type='button';close.onclick=()=>modal.close();
    modal.append(el('h2',entry.name+' · '+entry.code+' · v'+entry.version),close);
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
    const error=el('p');error.className='error';modal.append(error);
    if(!readonly){const apply=el('button','Áp dụng kết quả');apply.type='button';apply.onclick=()=>{
      try{
        const answers=inputs.map(({field,actual,assessment,note})=>{
          if(field.required&&!assessment.value)throw Error('Cần đánh giá '+field.name);
          if(field.required&&assessment.value!=='NA'&&!actual.value.trim())throw Error('Thiếu kết quả '+field.name);
          return {id:field.id,actual:assessment.value==='NA'?'':actual.value.trim(),assessment:assessment.value||null,note:note.value.trim()};
        });
        const evaluations=answers.map(answer=>answer.assessment).filter(Boolean);
        if(!evaluations.some(value=>value==='PASS'||value==='FAIL'))throw Error('Cần ít nhất một tiêu chí Đạt hoặc Không đạt để kết luận.');
        const expected=evaluations.includes('FAIL')?'FAIL':'PASS';
        if(conclusion.value!==expected)throw Error('Kết luận phải khớp đánh giá các tiêu chí áp dụng.');
        draft={template_id:entry.id,source_hash:entry.source_hash,mapping_hash:entry.mapping_hash,answers,conclusion:conclusion.value};
        $('result').value={PASS:'OK',FAIL:'NG',NA:'N/A'}[draft.conclusion];mode();modal.close();
      }catch(reason){error.textContent=reason.message;}
    };modal.append(apply);}
    modal.append(el('h3','Bản chụp template · chỉ đọc'),preview);
  }
  window.QCFormUI={...legacy,
    async init(){
      await legacy.init();$('openMappedForm').onclick=edit;$('findMappedTemplates').onclick=refresh;
      $('mappedTemplate').onchange=async()=>{
        const id=$('mappedTemplate').value;entry=draft=null;legacy.reset();mode();if(!id)return;
        const current=++epoch;loading=true;mode();
        try{const data=await api('/api/qc/templates/'+encodeURIComponent(id)+'/entry?'+params());if(current!==epoch)return;entry=data;$('standardUrl').value='';$('imageUrl').value='';$('result').value='';mode();edit();}
        catch(error){if(current===epoch)$('mappedSummary').textContent=error.message;}
        finally{if(current===epoch){loading=false;mode();}}
      };
      $('useLegacyForm').onclick=()=>{entry=draft=null;$('mappedTemplate').value='';$('result').value='';mode();};
    },
    reset(){epoch++;entry=draft=record=null;choices=[];loading=false;legacy.reset();$('mappedFormSection').hidden=false;$('mappedTemplate').replaceChildren(el('option','Chọn template đã duyệt'));$('mappedTemplate').options[0].value='';mode();},
    load(item,viewOnly){
      if(!item.template_id){entry=draft=record=null;legacy.load(item,viewOnly);$('mappedFormSection').hidden=true;mode();return;}
      legacy.reset();record=item;const saved=item.form_data;entry={...saved.template,id:saved.template.id,context:saved.context};draft={...saved.input,template_id:item.template_id};
      $('mappedFormSection').hidden=false;$('mappedTemplate').replaceChildren(el('option',entry.code+' · v'+entry.version));mode();$('openMappedForm').disabled=false;
    },
    payload(){if(entry){if(!draft)throw Error('Hãy nhập kết quả theo template đã chọn.');return {form:null,parent_folder_id:null,mapped_form:draft};}return legacy.payload();},
    files(){return entry?[]:legacy.files();},
    async uploadRecords(records,files,onDone){const indices=records.map((row,index)=>row.template_id?-1:index).filter(index=>index>=0);if(!indices.length){onDone?.();return true;}return legacy.uploadRecords(indices.map(index=>records[index]),indices.map(index=>files[index]),onDone);},
    busy(){return loading||legacy.busy();},
    invalidate(discard=false){
      if(discard){epoch++;entry=draft=record=null;loading=false;legacy.invalidate(true);mode();queueMicrotask(refresh);}
      else if(!entry)legacy.invalidate();
    }
  };
})();
