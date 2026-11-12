'use strict';
const $=s=>document.querySelector(s);
let data, editing, resetting;
const matrixChanges=new Map();
let savingMatrix=false;
let userPage=1, userFilters={q:'',active:''}, loadingUsers=false;
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
 if(r.status===401){location.assign('/login?next=%2Fusers');throw Error('Vui lòng đăng nhập lại.');}
 const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Thông tin không hợp lệ. Vui lòng kiểm tra lại.');return value;
}
function button(text,action){const b=node('button',text);b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){$('#message').textContent=e.message;}finally{b.disabled=false;}};return b;}
async function load(){
 const params=new URLSearchParams({page:userPage,size:25,q:userFilters.q});if(userFilters.active)params.set('active',userFilters.active);
 loadingUsers=true;
 try{data=await api('/api/admin/users?'+params);render();if(!matrixChanges.size)renderRoles();}
 finally{loadingUsers=false;}
}
function render(){
 const users=data.users;
 $('#rows').replaceChildren();
 for(const u of users){const tr=document.createElement('tr'),name=node('td',u.name);name.append(node('small',u.id));tr.append(name,node('td',u.email||'—'),node('td',u.role));
 const status=node('td',''),badge=node('span',u.active?'Hoạt động':'Đã khóa');badge.className='badge'+(u.active?'':' locked');status.append(badge);tr.append(status,node('td',u.google_connected?'Đã kết nối':'Chưa kết nối'));
 const actions=node('td','');if(u.role==='LOCAL_ADMIN'||u.id===data.self_id){actions.textContent=u.id===data.self_id?'Tài khoản hiện tại':'Quản trị local';}else{
 actions.append(button('Sửa / Phân quyền',()=>openEditor(u)),button('Reset mật khẩu',()=>{resetting=u;$('#passwordForm').reset();$('#passwordForm .error').textContent='';$('#passwordUser').textContent=u.name+' · '+u.id;$('#passwordDialog').showModal();}),button(u.active?'Khóa':'Mở khóa',async()=>{
 if(!confirm((u.active?'Khóa và thu hồi mọi phiên đăng nhập của ':'Mở khóa cho ')+u.name+'?'))return;
 await api('/api/admin/users/'+encodeURIComponent(u.id)+'/'+(u.active?'disable':'enable'),'POST');await load();$('#message').textContent='Đã cập nhật trạng thái.';
 }));}tr.append(actions);$('#rows').append(tr);}
 if(!users.length){const td=node('td','Không có người dùng phù hợp.');td.colSpan=6;const tr=node('tr','');tr.append(td);$('#rows').append(tr);}$('#count').textContent='Trang '+userPage+' · '+data.total+' người dùng';
 $('#userPrev').disabled=userPage<=1;$('#userNext').disabled=userPage*25>=data.total;
}
function renderRoles(){
 $('#roles').replaceChildren();const select=$('#account [name=role]');select.replaceChildren();
 for(const r of data.roles){const option=node('option',r.role);option.value=r.role;select.append(option);}
 const table=node('table','');table.className='permission-matrix';const head=node('thead',''),heading=node('tr','');heading.append(node('th','Quyền / Vai trò'));
 for(const r of data.roles){const th=node('th',r.role);th.scope='col';heading.append(th);}heading.append(node('th','LOCAL_ADMIN'));head.append(heading);table.append(head);
 const body=node('tbody','');
 for(const permission of data.permissions){const row=node('tr',''),label=node('th',permission.label);label.scope='row';label.append(node('small',permission.code));row.append(label);
  for(const role of data.roles){const cell=node('td',''),checkbox=document.createElement('input');checkbox.type='checkbox';const expected=role.permissions.includes(permission.code);checkbox.checked=expected;checkbox.disabled=!data.can_delegate||savingMatrix;checkbox.setAttribute('aria-label',permission.label+' — '+role.role);
   checkbox.onchange=()=>{const key=role.role+'|'+permission.code;if(checkbox.checked===expected){matrixChanges.delete(key);cell.classList.remove('changed');}else{matrixChanges.set(key,{role:role.role,permission:permission.code,expected,allowed:checkbox.checked});cell.classList.add('changed');}matrixStatus();};cell.append(checkbox);row.append(cell);}
  const admin=node('td',''),check=document.createElement('input');check.type='checkbox';check.checked=true;check.disabled=true;check.setAttribute('aria-label',permission.label+' — LOCAL_ADMIN (toàn quyền)');admin.append(check);row.append(admin);body.append(row);
 }table.append(body);$('#roles').append(table);matrixStatus();
}
function matrixStatus(){$('#saveMatrix').disabled=!matrixChanges.size||savingMatrix;$('#discardMatrix').disabled=!matrixChanges.size||savingMatrix;$('#matrixStatus').textContent=!data.can_delegate?'Chỉ admin local được thay đổi ma trận quyền.':matrixChanges.size+' ô thay đổi';}
$('#discardMatrix').onclick=()=>{matrixChanges.clear();renderRoles();};
$('#saveMatrix').onclick=async()=>{
 if(!matrixChanges.size||savingMatrix)return;
 if(!confirm('Lưu '+matrixChanges.size+' ô quyền? Thay đổi áp dụng cho tất cả nhân viên thuộc các vai trò này và thu hồi phiên đăng nhập của họ.'))return;
 savingMatrix=true;matrixStatus();for(const input of document.querySelectorAll('.permission-matrix input'))input.disabled=true;
 try{await api('/api/admin/permissions','PUT',{changes:[...matrixChanges.values()]});matrixChanges.clear();await load();$('#message').textContent='Đã lưu ma trận quyền. Nhân viên thuộc vai trò thay đổi cần đăng nhập lại.';}
 catch(e){$('#message').textContent=e.message;}
 finally{savingMatrix=false;matrixStatus();for(const input of document.querySelectorAll('.permission-matrix tbody td:not(:last-child) input'))input.disabled=!data.can_delegate;}
};
window.addEventListener('beforeunload',event=>{if(matrixChanges.size){event.preventDefault();event.returnValue='';}});
function openEditor(u){editing=u||null;$('#account').reset();$('#account .error').textContent='';$('#title').textContent=u?'Sửa / phân quyền người dùng':'Thêm người dùng';for(const key of ['id','name','email','role']){if(u)$('#account [name='+key+']').value=u[key]||'';}$('#account [name=id]').readOnly=!!u;$('#editor').showModal();}
$('#add').onclick=()=>openEditor();
const searchUsers=button('Tìm kiếm',async()=>{if(loadingUsers)return;const filters={q:$('#search').value.trim(),active:$('#filter').value===''?'':String($('#filter').value==='active')};if(userPage===1&&JSON.stringify(filters)===JSON.stringify(userFilters))return;userFilters=filters;userPage=1;await load();});
$('#filter').closest('label').after(searchUsers);
$('#search').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();searchUsers.click();}};
const userPrev=button('← Trước',async()=>{if(!loadingUsers&&userPage>1){userPage--;await load();}});userPrev.id='userPrev';
const userNext=button('Sau →',async()=>{if(!loadingUsers&&userPage*25<data.total){userPage++;await load();}});userNext.id='userNext';
$('#count').before(userPrev);$('#count').after(userNext);
for(const b of document.querySelectorAll('dialog .cancel'))b.onclick=()=>b.closest('dialog').close();
$('#account').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const body=Object.fromEntries(new FormData(e.target));await api('/api/admin/users'+(editing?'/'+encodeURIComponent(editing.id):''),editing?'PUT':'POST',body);$('#editor').close();await load();$('#message').textContent='Đã lưu người dùng. Người dùng cần đăng nhập lại.';}catch(error){$('#account .error').textContent=error.message;}finally{b.disabled=false;}};
$('#passwordForm').onsubmit=async e=>{e.preventDefault();const form=e.target;if(form.password.value!==form.confirm.value){$('#passwordForm .error').textContent='Mật khẩu nhập lại không khớp.';return;}const b=e.submitter;b.disabled=true;try{await api('/api/admin/users/'+encodeURIComponent(resetting.id)+'/password','PUT',{password:form.password.value});form.reset();$('#passwordDialog').close();$('#message').textContent='Đã reset mật khẩu ERP và thu hồi các phiên đăng nhập. Chuyển mật khẩu mới cho người dùng qua kênh riêng.';}catch(error){$('#passwordForm .error').textContent=error.message;}finally{b.disabled=false;}};
$('#passwordDialog').addEventListener('close',()=>$('#passwordForm').reset());
load().catch(e=>{$('#message').textContent=e.message;$('#rows').replaceChildren();$('#add').disabled=true;});
