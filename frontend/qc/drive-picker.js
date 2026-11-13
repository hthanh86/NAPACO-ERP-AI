/* Session-local folder cache; backend remains authoritative for root and permissions. */
(() => {
  const cache=new Map(),ttl=5*60*1000;
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  window.QCDrivePicker={open({api,root,onSelect}){
    const modal=el('dialog');modal.className='drive-explorer';modal.setAttribute('aria-label','Chọn thư mục Google Drive công ty');
    const toolbar=el('div'),crumb=el('nav'),body=el('div'),footer=el('footer'),status=el('p'),search=el('input');
    toolbar.className='drive-toolbar';crumb.className='drive-breadcrumb';crumb.setAttribute('aria-label','Đường dẫn thư mục QC');body.className='drive-items';status.setAttribute('role','status');
    search.type='search';search.placeholder='Tìm trong thư mục đã tải';search.setAttribute('aria-label',search.placeholder);
    let current=null,picked=null,epoch=0,history=[],at=-1,list=false,loading=false;
    const key=id=>(window.NAPACO_USER?.id||'')+'|'+[...(window.NAPACO_USER?.permissions||[])].sort().join(',')+'|'+root+'|'+(id||root);
    const btn=(text,fn)=>{const b=el('button',text);b.type='button';b.onclick=fn;return b;};
    const back=btn('← Back',()=>go(history[--at],false)),forward=btn('Forward →',()=>go(history[++at],false)),up=btn('↑ Up',()=>go(current?.parent_id)),refresh=btn('↻ Refresh',()=>go(current?.current.id,false,true));
    const layout=btn('List',()=>{list=!list;layout.textContent=list?'Grid':'List';render();});
    toolbar.append(back,forward,up,refresh,search,layout);
    const selection=el('span'),cancel=btn('Hủy',()=>modal.close()),choose=btn('Chọn thư mục',()=>{const folder=picked||current?.current;if(folder){onSelect(folder);modal.close();}});
    footer.append(selection,cancel,choose);
    modal.append(el('h2','Chọn thư mục QC trên Google Drive'),toolbar,crumb,body,status,footer);document.body.append(modal);
    modal.addEventListener('close',()=>{epoch++;modal.remove();});
    function locks(){back.disabled=at<=0;forward.disabled=at>=history.length-1;up.disabled=!current?.parent_id;refresh.disabled=loading;choose.disabled=!current||loading;}
    function render(){
      if(!current)return;
      crumb.replaceChildren(...(current.breadcrumb||[]).map(part=>btn(part.name,()=>go(part.id))));
      body.classList.toggle('is-list',list);
      const query=search.value.trim().toLocaleLowerCase('vi');
      body.replaceChildren(...current.items.filter(f=>f.name.toLocaleLowerCase('vi').includes(query)).map(folder=>{
        const b=btn('📁 '+folder.name,()=>{picked=folder;for(const node of body.querySelectorAll('.drive-folder')){node.classList.toggle('selected',node===b);node.setAttribute('aria-pressed',String(node===b));}selection.textContent='Đã chọn: '+folder.name;});b.className='drive-folder';b.classList.toggle('selected',picked?.id===folder.id);b.setAttribute('aria-pressed',String(picked?.id===folder.id));
        b.ondblclick=()=>go(folder.id);b.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();go(folder.id);}};return b;
      }));
      if(current.next_page_token)body.append(btn('Tải thêm thư mục',()=>more()));
      selection.textContent='Đã chọn: '+(picked?.name||current.current.name);locks();
    }
    async function request(id,page=''){
      const params=new URLSearchParams();if(id)params.set('folder_id',id);if(page)params.set('page_token',page);
      return api('/api/qc/folders?'+params);
    }
    async function more(){
      if(loading||!current?.next_page_token)return;
      const captured=epoch,id=current.current.id;loading=true;locks();status.textContent='Đang tải thêm…';
      try{const data=await request(id,current.next_page_token);if(captured!==epoch||!modal.open)return;current={...current,items:[...current.items,...data.items],next_page_token:data.next_page_token};cache.set(key(id),{time:Date.now(),data:current});render();status.textContent='';}
      catch(error){if(captured===epoch)status.textContent=error.message;}
      finally{if(captured===epoch){loading=false;locks();}}
    }
    async function go(id='',push=true,force=false){
      const captured=++epoch;picked=null;search.value='';
      if(push){history=history.slice(0,at+1);history.push(id||root);at=history.length-1;}
      const saved=cache.get(key(id));
      if(saved&&!force){current=saved.data;render();status.textContent='Đã tải từ cache · Refresh để cập nhật.';if(Date.now()-saved.time<ttl){loading=false;locks();return;}}
      loading=true;locks();status.textContent='Đang tải thư mục…';
      try{const data=await request(id);if(captured!==epoch||!modal.open)return;current=data;cache.set(key(data.current.id),{time:Date.now(),data});render();status.textContent=data.items.length?'':'Thư mục không có thư mục con.';}
      catch(error){if(captured===epoch){current=null;body.replaceChildren();status.textContent=error.message;}}
      finally{if(captured===epoch){loading=false;locks();}}
    }
    search.oninput=render;modal.showModal();go();
  }};
})();
