'use strict';
(() => {
 const $=s=>document.querySelector(s), kind=location.pathname.split('/').pop();
 const configs={
  customers:{title:'Khách Hàng',permission:'CUSTOMER_MANAGE',fields:[['name','Tên khách hàng','text',500,true],['address','Địa chỉ','text',10000],['contact','Người liên hệ','text',500],['phone','Điện thoại','text',200]]},
  products:{title:'Sản Phẩm',permission:'PRODUCT_MANAGE',fields:[['customer_id','Tên khách hàng','customer',100,true],['name','Tên sản phẩm','text',500,true],['code','Code Sản Phẩm','text',200],['type','Loại sản phẩm','select',0,true],['unit','Đơn vị','unit',100,true],['price','Đơn giá','number',0,true]]},
  suppliers:{title:'Nhà Cung Cấp',permission:'SUPPLIER_MANAGE',fields:[['name','Tên nhà cung cấp','text',500,true],['category','Loại nhà cung cấp','category',500]]}
 };
 const config=configs[kind];if(!config)return;
 let total=0,items=[],allItems=[],editing=null,filters=null,canManage=false,busy=false,loaded=false,currentPage=1,options={customers:[],units:[],categories:[]};
 const pageSize=50;
 function node(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
 async function api(url,method='GET',body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname));throw Error('Vui lòng đăng nhập.');}const data=await r.json();if(!r.ok){const detail=typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map(error=>error.loc.join('.')+': '+error.msg).join('; '):'Không thực hiện được yêu cầu.';throw Error(detail);}return data;}
 $('#heading').textContent=config.title;document.title=config.title+' · NAPACO';
 const tr=node('tr','');for(const text of ['Mã',...config.fields.map(f=>f[1]),'Thao tác'])tr.append(node('th',text));$('#head').append(tr);
 const numberFormat=new Intl.NumberFormat('vi-VN',{maximumFractionDigits:0});
 const productTypes={'1':'Định hình','2':'Bế'};
 $('#rows').closest('table').dataset.catalog=kind;
 function customerName(item){const found=options.customers.find(x=>x.id===(item.customer_id||item.source_customer_id));return found?.name||item.customer_name||item.customer_id||item.source_customer_id||'—';}
 function localFilter(){const q=$('#search').value.trim().toLocaleLowerCase();items=q?allItems.filter(item=>[item.id,item.name,item.code,item.customer_name,customerName(item),item.unit,item.category].some(v=>String(v??'').toLocaleLowerCase().includes(q))):allItems.slice();total=items.length;currentPage=1;render();}
 function render(){
  $('#rows').replaceChildren();
  const pages=Math.max(1,Math.ceil(total/pageSize));currentPage=Math.min(currentPage,pages);
  const start=(currentPage-1)*pageSize,visibleItems=kind==='products'?items.slice(start,start+pageSize):items;
  for(const item of visibleItems){const row=node('tr','');row.append(node('td',item.id));for(const f of config.fields){let value=f[0]==='customer_id'?customerName(item):(item[f[0]]??'');if(kind==='products'&&f[0]==='type')value=productTypes[String(value)]||value;if(f[0]==='price')value=numberFormat.format(Number(value)||0);row.append(node('td',value));}
   const actions=node('td','');if(canManage){const b=node('button','Sửa');b.type='button';b.onclick=()=>openEditor(item);actions.append(b);}else actions.textContent='Chỉ xem';row.append(actions);$('#rows').append(row);}
  if(!items.length){const row=node('tr',''),td=node('td','Không có dữ liệu phù hợp.');td.colSpan=config.fields.length+2;row.append(td);$('#rows').append(row);}
  $('#summary').textContent=loaded?'Có '+numberFormat.format(total)+' '+config.title+(total!==allItems.length?' phù hợp / '+numberFormat.format(allItems.length)+' đã tải':''):'';
  $('#prev').hidden=$('#next').hidden=kind!=='products';
  $('#prev').disabled=busy||currentPage<=1;$('#next').disabled=busy||currentPage>=pages;
  $('#count').textContent=kind==='products'?'Trang '+currentPage+'/'+pages+' · '+(total?start+1:0)+'–'+Math.min(start+pageSize,total)+' / '+total+' sản phẩm':total+' bản ghi';
 }
 $('#prev').onclick=()=>{if(!busy&&currentPage>1){currentPage--;render();}};
 $('#next').onclick=()=>{if(!busy&&currentPage*pageSize<total){currentPage++;render();}};
 async function fetchCatalog(catalog,query=''){
  const collected=[];let first;
  for(let page=1;;page++){
   const qs=new URLSearchParams({q:query,page,size:100});
   const data=await api('/api/master/'+catalog+'?'+qs);
   if(!first)first=data;
   collected.push(...data.items);
   if(collected.length>=data.total)break;
   if(!data.items.length)throw Error('Danh sách đã thay đổi trong lúc tải. Vui lòng bấm Tìm kiếm lại.');
  }
  return {...first,items:collected};
 }
 async function load(query=''){if(busy)return;busy=true;$('#searchForm button[type=submit]').disabled=true;$('#add').disabled=true;$('#message').textContent='Đang tải danh mục…';
  try{const data=await fetchCatalog(kind,query);const nextOptions={...options,customers:data.customers||options.customers,units:data.units||options.units,categories:data.categories||options.categories};
   // Older backend images return only catalog rows, without editor options.
   if(kind==='products'&&!Array.isArray(data.customers))nextOptions.customers=(await fetchCatalog('customers')).items;
   if(kind==='products'&&!Array.isArray(data.units))nextOptions.units=[...new Set(['Cái',...data.items.map(item=>item.unit).filter(Boolean)])];
   if(kind==='suppliers'&&!Array.isArray(data.categories))nextOptions.categories=[...new Set(data.items.map(item=>item.category).filter(Boolean))];
   allItems=data.items;options=nextOptions;
   if(kind==='products')allItems.sort((a,b)=>customerName(a).localeCompare(customerName(b),'vi')||String(a.customer_id||a.source_customer_id||'').localeCompare(String(b.customer_id||b.source_customer_id||''),'vi')||a.name.localeCompare(b.name,'vi')||a.id.localeCompare(b.id,'vi'));
   loaded=true;canManage=data.can_manage;$('#add').hidden=!canManage;$('#hint').textContent='Gõ từ khóa để lọc dữ liệu đã tải; bấm Tìm kiếm để lấy lại dữ liệu theo điều kiện.';$('#message').textContent='';localFilter();}
  catch(e){$('#message').textContent=e.message;}finally{busy=false;$('#searchForm button[type=submit]').disabled=false;$('#add').disabled=false;refreshOptions();render();}}
 $('#search').oninput=()=>{if(loaded)localFilter();};
 $('#searchForm').onsubmit=e=>{e.preventDefault();filters=$('#search').value.trim();load(filters);};
 function openEditor(item){editing=item;$('#recordForm').reset();$('#recordForm .error').textContent='';$('#editorTitle').textContent=(item?'Sửa ':'Thêm ')+config.title;$('#recordId').textContent=item?'Mã: '+item.id:'Mã được sinh tự động theo quy tắc hiện tại.';$('#fields').replaceChildren();
  for(const [name,label,type,max,required] of config.fields){const wrapper=node('label',label),input=document.createElement(type==='select'||type==='unit'||type==='category'?'select':'input');input.name=name;input.required=!!required;
   if(type==='select'){for(const [value,text] of Object.entries(productTypes)){const option=node('option',text);option.value=value;input.append(option);}}
   else if(type==='unit'||type==='category'){const values=type==='unit'?options.units:options.categories;values.forEach(value=>{const option=node('option',value);option.value=value;input.append(option);});if(item?.[name]&&!values.includes(item[name])){const option=node('option',item[name]);option.value=item[name];input.append(option);}}
   else if(type==='customer'){input.type='text';input.setAttribute('list','customerOptions');input.name='customer_name';const hidden=document.createElement('input');hidden.type='hidden';hidden.name='customer_id';hidden.value=item?.customer_id||item?.source_customer_id||'';input.oninput=()=>{const match=options.customers.find(x=>x.name===input.value||x.id===input.value);hidden.value=match?.id||'';};wrapper.append(input,hidden);}
   else{input.type=type;if(max)input.maxLength=max;if(type==='number'){input.min='0';input.step='1';input.inputMode='numeric';}}
   if(type!=='customer')input.value=item?(name==='price'?String(Math.round(Number(item[name])||0)):(item[name]??'')):(name==='type'?'1':name==='unit'?(options.units[0]||'Cái'):name==='price'?'0':name==='category'?(options.categories[0]||''):'');
   if(type==='customer'){input.value=item?customerName(item):'';input.readOnly=!!item;}
   wrapper.append(input);$('#fields').append(wrapper);
  }$('#editor').showModal();}
 function refreshOptions(){document.querySelector('#customerOptions')?.remove();document.querySelector('#unitOptions')?.remove();document.querySelector('#categoryOptions')?.remove();const add=(id,values)=>{const dl=document.createElement('datalist');dl.id=id;values.forEach(value=>dl.append(node('option',value)));document.body.append(dl);};if(kind==='products'){add('customerOptions',options.customers.map(x=>x.name));add('unitOptions',options.units);}if(kind==='suppliers')add('categoryOptions',options.categories);}
 $('#add').onclick=()=>openEditor(null);$('#cancel').onclick=()=>$('#editor').close();
 $('#recordForm').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;const payload=Object.fromEntries(new FormData(e.target));if(editing)payload.version=editing.version;
  delete payload.customer_name;try{const saved=await api('/api/master/'+kind+(editing?'/'+encodeURIComponent(editing.id):''),editing?'PUT':'POST',payload);$('#editor').close();await load(filters||'');$('#message').textContent='Đã lưu '+saved.id+'.';}catch(error){$('#recordForm .error').textContent=error.message;}finally{b.disabled=false;}};
 // Load the full catalog on entry; the search box filters locally until submit.
 window.NAPACO_IDENTITY.then(user=>{canManage=user.permissions.includes(config.permission);$('#add').hidden=!canManage;refreshOptions();load();}).catch(e=>$('#message').textContent=e.message);
})();
