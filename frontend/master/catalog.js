'use strict';
(() => {
 const $=s=>document.querySelector(s), kind=location.pathname.split('/').pop();
 const configs={
  customers:{title:'Khách Hàng',permission:'CUSTOMER_MANAGE',fields:[['name','Tên khách hàng','text',500,true],['address','Địa chỉ','text',10000],['contact','Người liên hệ','text',500],['phone','Điện thoại','text',200]]},
  products:{title:'Sản Phẩm',permission:'PRODUCT_MANAGE',fields:[['name','Tên sản phẩm','text',500,true],['customer_id','Mã khách hàng','text',100,true],['code','Mã sản phẩm khách hàng','text',200],['type','Loại sản phẩm','select',0,true],['unit','Đơn vị','text',100,true],['price','Đơn giá','number',0,true]]},
  suppliers:{title:'Nhà Cung Cấp',permission:'SUPPLIER_MANAGE',fields:[['name','Tên nhà cung cấp','text',500,true],['category','Loại nhà cung cấp (ví dụ: Màng)','text',500]]}
 };
 const config=configs[kind];if(!config)return;
 let page=1,total=0,items=[],editing=null,filters=null,canManage=false,busy=false,loaded=false;
 function node(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
 async function api(url,method='GET',body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname));throw Error('Vui lòng đăng nhập.');}const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Thông tin không hợp lệ.');return data;}
 $('#heading').textContent=config.title;document.title=config.title+' · NAPACO';$('#customerFilterLabel').hidden=kind!=='products';
 const tr=node('tr','');for(const text of ['Mã',...config.fields.map(f=>f[1]),'Thao tác'])tr.append(node('th',text));$('#head').append(tr);
 function render(){
  $('#rows').replaceChildren();
  for(const item of items){const row=node('tr','');row.append(node('td',item.id));for(const f of config.fields)row.append(node('td',f[0]==='customer_id'?(item.customer_id||item.source_customer_id||'—'):(item[f[0]]??'')));
   const actions=node('td','');if(canManage){const b=node('button','Sửa');b.type='button';b.onclick=()=>openEditor(item);actions.append(b);}else actions.textContent='Chỉ xem';row.append(actions);$('#rows').append(row);}
  if(!items.length){const row=node('tr',''),td=node('td','Không có dữ liệu phù hợp.');td.colSpan=config.fields.length+2;row.append(td);$('#rows').append(row);}
  $('#count').textContent='Trang '+page+' · '+total+' bản ghi';$('#prev').disabled=busy||page<=1;$('#next').disabled=busy||page*25>=total;
 }
 async function load(){if(busy)return;busy=true;loaded=false;$('#searchForm button[type=submit]').disabled=true;$('#prev').disabled=true;$('#next').disabled=true;
  try{const qs=new URLSearchParams({...filters,page,size:25});const data=await api('/api/master/'+kind+'?'+qs);items=data.items;total=data.total;loaded=true;canManage=data.can_manage;$('#add').hidden=!canManage;$('#hint').textContent=canManage?'Có quyền thêm và sửa danh mục.':'Bạn có quyền xem. Admin cấp quyền quản lý danh mục qua ma trận quyền.';$('#message').textContent='';}
  catch(e){items=[];total=0;$('#message').textContent=e.message;}finally{busy=false;$('#searchForm button[type=submit]').disabled=false;render();}}
 $('#searchForm').onsubmit=e=>{e.preventDefault();const next={q:$('#search').value.trim(),customer_id:kind==='products'?$('#customerFilter').value.trim():''};if(loaded&&page===1&&filters&&JSON.stringify(filters)===JSON.stringify(next))return;filters=next;page=1;load();};
 $('#prev').onclick=()=>{if(page>1&&!busy){page--;load();}};$('#next').onclick=()=>{if(page*25<total&&!busy){page++;load();}};
 function openEditor(item){editing=item;$('#recordForm').reset();$('#recordForm .error').textContent='';$('#editorTitle').textContent=(item?'Sửa ':'Thêm ')+config.title;$('#recordId').textContent=item?'Mã: '+item.id:'Mã được sinh tự động theo quy tắc hiện tại.';$('#fields').replaceChildren();
  for(const [name,label,type,max,required] of config.fields){const wrapper=node('label',label),input=document.createElement(type==='select'?'select':'input');input.name=name;input.required=!!required;
   if(type==='select'){for(const [value,text] of [['1','Định Hình'],['2','Bế']]){const option=node('option',text);option.value=value;input.append(option);}}else{input.type=type;if(max)input.maxLength=max;if(type==='number'){input.min='0';input.step='0.0001';}}
   input.value=item?(item[name]??''):(name==='type'?'1':name==='unit'?'Cái':name==='price'?'0':'');if(item&&name==='customer_id'){input.value=item.customer_id||item.source_customer_id||'';input.readOnly=true;}
   wrapper.append(input);$('#fields').append(wrapper);
  }$('#editor').showModal();}
 $('#add').onclick=()=>openEditor(null);$('#cancel').onclick=()=>$('#editor').close();
 $('#recordForm').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;const payload=Object.fromEntries(new FormData(e.target));if(editing)payload.version=editing.version;
  try{const saved=await api('/api/master/'+kind+(editing?'/'+encodeURIComponent(editing.id):''),editing?'PUT':'POST',payload);$('#editor').close();if(filters)await load();$('#message').textContent='Đã lưu '+saved.id+'.';}catch(error){$('#recordForm .error').textContent=error.message;}finally{b.disabled=false;}};
 // Identity only on entry; catalog queries wait for explicit search.
 window.NAPACO_IDENTITY.then(user=>{canManage=user.permissions.includes(config.permission);$('#add').hidden=!canManage;}).catch(e=>$('#message').textContent=e.message);
})();
