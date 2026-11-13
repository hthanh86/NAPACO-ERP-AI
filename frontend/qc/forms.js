/* Code-defined form editor, internal drawn signature and QC-scoped Drive picker. */
(() => {
  const $=id=>document.getElementById(id);
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  let catalog=[],rootFolder='',state={form:null,parent:null,files:[]},record=null,readonly=false,working=false,uploads=[];
  let staging=null;
  const business=()=> $('checkType').value==='QC NVL'?'NVL':'PRODUCT';
  function activeDefinition(){const saved=record?.form_data?.definition;return saved&&(saved.business||'NVL')===business()?saved:catalog.find(item=>item.business===business());}
  async function api(url,options={}){
    const start=performance.now();
    const response=await fetch(url,{cache:'no-store',...options});
    const operation=url.startsWith('/api/qc/folders')?'drive.folders':url.includes('/bundle')?'drive.bundle':url.includes('/uploads/chunk')?'drive.upload_chunk':url.includes('/uploads')?'drive.start_upload':'qc.form';
    let data;
    try{data=await response.json();}
    finally{console.info('QC_PERF_UI',{operation,ms:Math.round((performance.now()-start)*1000)/1000,status:response.status,trace:response.headers.get('X-QC-Trace')});}
    if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||'Không thực hiện được yêu cầu.'));error.status=response.status;throw error;}
    return data;
  }
  function button(text,fn){const node=el('button',text);node.type='button';node.onclick=fn;return node;}
  function dialog(title){
    const node=el('dialog');node.className='qc-dialog';node.append(el('h2',title));
    node.append(button('Đóng',()=>node.close()));node.addEventListener('close',()=>node.remove());document.body.append(node);node.showModal();return node;
  }
  function summary(){
    $('formSummary').textContent=state.form?`${state.form.code} · ${state.form.resin} · ${state.form.conclusion} · ${state.form.signature.length?'đã nhập và ký':'cần ký lại sau khi thay đổi'}`:'Chưa chọn biểu mẫu. QC NVL mới cần biểu mẫu đã ký.';
    $('folderSummary').textContent=record?.drive_folder_id?'Thư mục bằng chứng đã được tạo cho '+record.id:state.parent?.name||(rootFolder?'Chưa chọn thư mục cha. Mở Drive để chọn trong thư mục QC công ty.':'Chưa cấu hình thư mục QC công ty.');
    $('chooseFolder').disabled=readonly||!!record?.drive_folder_id||!rootFolder;
    $('chooseForm').disabled=!activeDefinition();
    if(!state.form&&!activeDefinition())$('formSummary').textContent='Nghiệp vụ này chưa có template QC đang ban hành.';
    $('fileSummary').replaceChildren(...state.files.map(entry=>{const row=el('li',entry.file.name+' · '+(entry.file.size/1024/1024).toFixed(1)+' MB · staging '+Math.round((entry.stageOffset||0)/Math.max(entry.file.size,1)*100)+'%');
      const remove=button('Bỏ file',()=>{if(!working){staging?.remove(entry);state.files=state.files.filter(item=>item!==entry);if(!state.files.length){staging?.stop();staging=null;}summary();}});remove.disabled=working;row.append(remove);return row;}));
    if(staging){const note=el('li',staging.error|| (staging.done?'Đã tiếp nhận an toàn. Có thể lưu phiếu và đóng tab sau khi nhận QC_ID.':'Đang tiếp nhận file vào staging…'));if(staging.error)note.append(button('Thử lại staging',()=>staging.run()));$('fileSummary').append(note);}
    $('downloadFormPdf').hidden=record?.template_id?!record.pdf_url:!record?.form_data;
    if(record?.form_data)$('downloadFormPdf').href='/api/qc/'+encodeURIComponent(record.id)+'/pdf';
    const canAppend=!!record&&(window.NAPACO_USER?.permissions.includes('QC_EDIT')||record.staff_id===window.NAPACO_USER?.id&&window.NAPACO_USER?.permissions.includes('QC_CREATE'));
    $('evidenceFiles').disabled=working||!!record&&!canAppend;
    $('saveEvidence').hidden=!canAppend;
    $('evidenceStatus').textContent=record?.sync?record.sync.status+' · '+record.sync.step+' · '+(record.sync.error||''):record?(record.evidence_pending?'Hồ sơ chưa hoàn tất · '+(record.evidence_step||'đang chờ')+' · '+(record.evidence_error||''):'Hồ sơ đã hoàn tất các file được đăng ký.') : '';
  }
  function editForm(){
    const definition=activeDefinition();
    if(!definition){$('formError').textContent='Chưa tải được biểu mẫu ERP.';return;}
    const modal=dialog(definition.name+' · '+definition.code),error=el('p');error.className='error';
    const resin=el('select');resin.setAttribute('aria-label','Loại nhựa');definition.resins.forEach(value=>resin.append(el('option',value)));
    resin.value=state.form?.resin||definition.resins[0];resin.disabled=readonly;modal.append(el('p','Loại nhựa'),resin,el('p',definition.applicability_note));
    const wrap=el('div');wrap.className='table-wrap';const table=el('table'),head=el('tr');
    for(const text of ['Hạng mục','Tiêu chuẩn','Phương pháp','Kết quả thực tế','Đánh giá','Dung sai / Ghi chú'])head.append(el('th',text));
    table.append(head);const inputs=[];
    for(const criterion of definition.criteria){
      const answer=state.form?.answers.find(item=>item.id===criterion.id),row=el('tr');
      for(const text of [criterion.name,criterion.standard,criterion.method])row.append(el('td',text));
      const actual=el('input');actual.maxLength=2000;actual.value=answer?.actual||'';actual.setAttribute('aria-label',criterion.name+' - kết quả');
      const valueCell=el('td');valueCell.append(actual,el('span',criterion.unit));row.append(valueCell);
      const assessment=el('select');for(const [value,label] of [['','Chọn'],['PASS','PASS'],['FAIL','FAIL'],['NA','Không áp dụng']]){const option=el('option',label);option.value=value;assessment.append(option);}assessment.value=answer?.assessment||'';
      assessment.setAttribute('aria-label',criterion.name+' - đánh giá');const assessmentCell=el('td');assessmentCell.append(assessment);row.append(assessmentCell);
      const note=el('textarea');note.maxLength=2000;note.value=answer?.note||'';note.placeholder=criterion.tolerance;note.setAttribute('aria-label',criterion.name+' - ghi chú');const noteCell=el('td');noteCell.append(note);row.append(noteCell);
      note.onfocus=()=>{note.placeholder='';};note.onblur=()=>{note.placeholder=criterion.tolerance;};
      for(const node of [actual,assessment,note])node.disabled=readonly;
      function applicability(){actual.disabled=readonly||assessment.value==='NA';}
      assessment.onchange=applicability;applicability();
      inputs.push({criterion,actual,assessment,note});table.append(row);
    }
    wrap.append(table);modal.append(wrap);
    const conclusion=el('select');conclusion.setAttribute('aria-label','Kết luận form');for(const value of ['PASS','FAIL'])conclusion.append(el('option',value));conclusion.value=state.form?.conclusion||'PASS';
    const note=el('textarea');note.maxLength=10000;note.value=state.form?.note||'';note.setAttribute('aria-label','Ghi chú form');
    conclusion.disabled=note.disabled=readonly;modal.append(el('p','Kết luận'),conclusion,el('p','Ghi chú'),note,el('p','Ký xác nhận nội bộ bằng chuột, trackpad hoặc cảm ứng'));
    const canvas=el('canvas');canvas.width=900;canvas.height=240;canvas.className='qc-signature';canvas.setAttribute('aria-label','Vùng ký xác nhận');modal.append(canvas);
    const context=canvas.getContext('2d');let strokes=structuredClone(state.form?.signature||[]),active=null;
    function draw(){context.clearRect(0,0,canvas.width,canvas.height);context.strokeStyle='#183a68';context.lineWidth=2.5;context.lineCap='round';for(const stroke of strokes){context.beginPath();stroke.forEach(([x,y],index)=>context[index?'lineTo':'moveTo'](x*canvas.width,y*canvas.height));context.stroke();}}
    function invalidate(){if(!readonly){strokes=[];draw();}}
    for(const node of [resin,conclusion,note,...inputs.flatMap(item=>[item.actual,item.assessment,item.note])])node.addEventListener('input',invalidate);
    function point(event){const rect=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];}
    canvas.onpointerdown=event=>{if(readonly)return;event.preventDefault();canvas.setPointerCapture(event.pointerId);active=[point(event)];strokes.push(active);};
    canvas.onpointermove=event=>{if(active){if(strokes.reduce((n,stroke)=>n+stroke.length,0)<15000)active.push(point(event));draw();}};
    canvas.onpointerup=canvas.onpointercancel=()=>{active=null;};draw();
    if(!readonly){modal.append(button('Xóa chữ ký',invalidate),button('Áp dụng biểu mẫu',()=>{
      try{
        const answers=inputs.map(({criterion,actual,assessment,note})=>({id:criterion.id,actual:assessment.value==='NA'?'':actual.value.trim(),assessment:assessment.value,note:note.value.trim()}));
        if(answers.some(item=>!item.assessment||(item.assessment!=='NA'&&!item.actual)))throw Error('Nhập kết quả cho các tiêu chí áp dụng và chọn đánh giá.');
        const applicable=answers.filter(item=>item.assessment!=='NA');if(!applicable.length)throw Error('Cần ít nhất một tiêu chí áp dụng.');
        const expected=applicable.some(item=>item.assessment==='FAIL')?'FAIL':'PASS';if(conclusion.value!==expected)throw Error('Kết luận phải khớp đánh giá các tiêu chí.');
        if(!strokes.some(stroke=>stroke.length>=2))throw Error('Hãy ký xác nhận.');
        state.form={code:definition.code,resin:resin.value,answers,conclusion:conclusion.value,note:note.value.trim(),signature:strokes};
        $('standardUrl').value=definition.code;$('result').value=conclusion.value==='PASS'?'OK':'NG';summary();modal.close();
      }catch(reason){error.textContent=reason.message;}
    }));}modal.append(error);
  }
  async function chooseFolder(){
    window.QCDrivePicker.open({api,root:rootFolder,onSelect:folder=>{state.parent=folder;summary();}});
  }
  async function transfer(entry,id,status){
    if(entry.complete)return;
    if(!entry.ticket){const result=await api('/api/qc/'+encodeURIComponent(id)+'/uploads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:entry.file.name,size:entry.file.size,modified:entry.file.lastModified,mime:entry.file.type||'application/octet-stream'})});if(result.complete){entry.complete=true;return;}entry.ticket=result.ticket;entry.offset=result.offset;}
    else{try{const result=await api('/api/qc/'+encodeURIComponent(id)+'/uploads/chunk?probe=true',{method:'PUT',headers:{'X-QC-Upload-Ticket':entry.ticket},body:new Blob([])});entry.offset=result.offset;if(result.complete){entry.complete=true;return;}}catch(error){if(error.status!==410)throw error;entry.ticket=null;entry.offset=0;return transfer(entry,id,status);}}
    while(entry.offset<entry.file.size){
      status.textContent=id+' · '+entry.file.name+' · '+Math.round(entry.offset/entry.file.size*100)+'%';
      const result=await api('/api/qc/'+encodeURIComponent(id)+'/uploads/chunk?offset='+entry.offset,{method:'PUT',headers:{'X-QC-Upload-Ticket':entry.ticket},body:entry.file.slice(entry.offset,entry.offset+4*1024*1024)});
      if(!result.complete&&result.offset<=entry.offset)throw Error('Drive chưa nhận thêm dữ liệu. Hãy bấm Thử lại upload.');entry.offset=result.offset;entry.complete=result.complete;
    }
  }
  async function uploadRecords(records,files,onDone){
    uploads=records.map((item,index)=>({record:item,files:files[index]||[]}));
    let panel=$('qcUploadPanel');if(!panel){panel=el('section');panel.id='qcUploadPanel';$('editor').append(panel);}panel.hidden=false;
    const status=el('p'),retry=button('Thử lại upload',run);panel.replaceChildren(el('h3','Hoàn tất hồ sơ Drive'),status,retry);
    async function run(){
      if(working)return;working=true;retry.disabled=true;
      try{
        for(const job of uploads){
          if(job.record.form_data||job.record.drive_folder_id||job.record.evidence_pending){status.textContent='Đang chuẩn bị PDF/thư mục '+job.record.id;
            if((job.record.pdf_pending??job.record.evidence_pending)||!job.record.drive_folder_id)job.record=await api('/api/qc/'+encodeURIComponent(job.record.id)+'/bundle',{method:'POST'});
            if(job.record.pdf_pending??job.record.evidence_pending)throw Error((job.record.evidence_step||'PDF')+': '+job.record.evidence_error+' Bằng chứng chưa được upload vì PDF chưa hoàn tất.');
            for(const entry of job.files)await transfer(entry,job.record.id,status);
            job.record=await api('/api/qc/'+encodeURIComponent(job.record.id)+'/completion');
            if(job.record.evidence_pending)throw Error(job.record.evidence_error||'Còn '+job.record.evidence_remaining+' bằng chứng đã đăng ký chưa hoàn tất. Chọn lại file còn thiếu để thử lại.');
            if(record?.id===job.record.id){record=job.record;summary();window.dispatchEvent(new CustomEvent('qc-evidence-updated',{detail:record}));}
          }
        }
        status.textContent='Đã hoàn tất PDF và các file bằng chứng.';retry.hidden=true;uploads=[];working=false;onDone?.();return true;
      }catch(reason){status.textContent='Phiếu QC đã lưu. '+reason.message+' Các file chưa xong vẫn được giữ trên màn hình này; bấm Thử lại upload.';return false;}
      finally{working=false;retry.disabled=false;}
    }return run();
  }
  window.QCFormUI={
    async init(){const config=await api('/api/qc/forms');catalog=config.items;rootFolder=config.root_folder_id;$('chooseForm').onclick=editForm;$('chooseFolder').onclick=chooseFolder;
      $('evidenceFiles').onchange=()=>{if(working)return;staging?.stop();state.files=[...$('evidenceFiles').files].map(file=>({file,offset:0,complete:false}));staging=state.files.length?new window.QCStaging(state.files,summary):null;summary();};
      $('saveEvidence').onclick=async()=>{if(!record||working)return;try{
        const manifest=state.files.map(e=>({name:e.file.name,size:e.file.size,modified:e.file.lastModified,mime:e.file.type||'application/octet-stream'}));
        if(!staging){if(record.sync){await api('/api/qc/'+encodeURIComponent(record.id)+'/retry-sync',{method:'POST'});$('evidenceStatus').textContent='PENDING · Đã yêu cầu worker thử lại.';return;}throw Error('Hãy chọn file để tiếp nhận staging trước.');}
        record=await api('/api/qc/'+encodeURIComponent(record.id)+'/queue-evidence',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({staging_id:staging.payload(),files:manifest,parent_folder_id:state.parent?.id||null})});
        state.files=[];staging=null;summary();window.dispatchEvent(new CustomEvent('qc-evidence-updated',{detail:record}));
      }catch(error){$('formError').textContent=error.message;}};
    },
    reset(){staging?.stop();staging=null;state={form:null,parent:null,files:[]};record=null;readonly=false;summary();const panel=$('qcUploadPanel');if(panel)panel.hidden=true;},
    load(item,viewOnly){record=item;readonly=viewOnly;state={form:item.form_data?structuredClone(item.form_data.input):null,parent:null,files:[]};$('evidenceFiles').disabled=viewOnly;summary();},
    payload(){return {form:state.form,parent_folder_id:state.parent?.id||null,staging_id:staging?.payload()||null,evidence_manifest:state.files.map(e=>({name:e.file.name,size:e.file.size,modified:e.file.lastModified,mime:e.file.type||'application/octet-stream'}))};},
    files(){return state.files;},uploadRecords,
    evidenceRecord(item){record=item;state.form=null;summary();},
    manifest(){return state.files.map(e=>({name:e.file.name,size:e.file.size,modified:e.file.lastModified,mime:e.file.type||'application/octet-stream'}));},
    busy(){return working||uploads.length>0||!!staging?.uploading;},
    invalidate(discard=false){if(state.form){if(discard){state.form=null;$('standardUrl').value='';}else state.form.signature=[];}summary();}
  };
})();
