/* Durable backend staging: the browser only handles reception, never Drive work. */
(() => {
  async function api(url,options={}) {
    const response=await fetch(url,{cache:'no-store',...options});
    let data;try{data=await response.json();}catch{throw Error('Staging trả phản hồi không hợp lệ (HTTP '+response.status+').');}
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Không tiếp nhận được file staging.');
    return data;
  }
  window.QCStaging=class {
    constructor(entries,redraw){this.entries=[...entries];this.redraw=redraw;this.id=null;this.uploading=false;this.done=false;this.error='';this.stopped=false;this.run();}
    add(entries){this.entries.push(...entries);this.done=false;this.run();}
    async run(){
      if(this.uploading||this.stopped)return;
      this.uploading=true;this.done=false;this.error='';this.redraw();
      try{
        do{
        for(const entry of this.entries.filter(e=>e.removed&&e.stageFile&&!e.stageDeleted)){
          if(this.stopped)return;
          await api('/api/qc/staging/'+this.id+'/'+entry.stageFile,{method:'DELETE'});entry.stageDeleted=true;
        }
        const additions=this.entries.filter(e=>!e.stageFile&&!e.removed);
        if(additions.length){
          const data=await api('/api/qc/staging',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({staging_id:this.id,files:additions.map(e=>({name:e.file.name,size:e.file.size,mime:e.file.type||'application/octet-stream',modified:e.file.lastModified}))})});
          this.id=data.id;
          for(const entry of additions){const file=data.files.find(f=>f.name===entry.file.name&&f.size===entry.file.size&&f.modified===entry.file.lastModified);if(!file)throw Error('Không tìm thấy file đã đăng ký staging.');entry.stageFile=file.id;}
        }
        if(this.stopped||!this.id)return;
        const status=await api('/api/qc/staging/'+this.id);
        for(const entry of this.entries.filter(e=>e.stageFile&&!e.stageDeleted)){
          if(this.stopped)return;
          if(entry.removed){await api('/api/qc/staging/'+this.id+'/'+entry.stageFile,{method:'DELETE'});entry.stageDeleted=true;continue;}
          const saved=status.files.find(file=>file.id===entry.stageFile);
          if(!saved)throw Error('File không còn trong staging. Hãy chọn lại file.');
          entry.stageOffset=saved.offset;
          while(entry.stageOffset<entry.file.size&&!entry.removed&&!this.stopped){
            const end=entry.stageOffset+4*1024*1024;
            const data=await api('/api/qc/staging/'+this.id+'/'+entry.stageFile+'?offset='+entry.stageOffset,{method:'PUT',body:entry.file.slice(entry.stageOffset,end)});
            entry.stageOffset=data.offset;this.redraw();
          }
        }
        }while(!this.stopped&&this.entries.some(e=>(!e.removed&&!e.stageFile)||(e.removed&&e.stageFile&&!e.stageDeleted)));
        if(!this.stopped)this.done=true;
      }catch(error){this.error=error.message;}
      finally{this.uploading=false;this.redraw();}
    }
    remove(entry){
      entry.removed=true;
      this.done=false;this.run();
    }
    payload(){
      if(!this.done||this.error)throw Error(this.error||'Bằng chứng đang được tiếp nhận vào staging. Hãy chờ tiến độ hoàn tất trước khi lưu.');
      return this.id;
    }
    stop(){this.stopped=true;}
  };
})();
