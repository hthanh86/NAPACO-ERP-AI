const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => Number(n).toLocaleString('vi-VN',{maximumFractionDigits:4})+' ₫';
const fmtDate = s => s ? s.split('-').reverse().join('/') : '—';
const today = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let user, catalog, page=1, total=0, current=null, products=[], lines=[], requestKey=null, loading=false;
async function api(path, options={}) {
  const response = await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  const data = await response.json();
  if(!response.ok){
    if(response.status===401 && path!='/login'){ $('workspace').hidden=true; $('loginPanel').hidden=false; }
    const message = Array.isArray(data.detail) ? data.detail.map(x=>x.loc.join('.')+': '+x.msg).join('\n') : data.detail;
    throw new Error(message || 'Không thực hiện được yêu cầu.');
  }
  return data;
}
const options = (items,selected,blank='') => (blank?`<option value="">${esc(blank)}</option>`:'')+items.map(x=>`<option value="${esc(x.id)}" ${x.id===selected?'selected':''}>${esc(x.name)}</option>`).join('');
function showError(error){ $('message').className='error'; $('message').textContent=error.message; }
async function enter(){
  user=await api('/me'); catalog=await api('/catalog');
  $('userLabel').textContent=user.name; $('loginPanel').hidden=true; $('workspace').hidden=false;
  $('customerFilter').innerHTML=options(catalog.customers,'','Tất cả khách hàng');
  $('statusFilter').innerHTML='<option value="">Tất cả</option><option value="ACTIVE_ALL">Đang thực hiện</option>'+catalog.statuses.map(s=>`<option>${esc(s)}</option>`).join('');
  $('newOrder').hidden=!user.permissions.includes('ORDER_CREATE');
  const migration=await api('/migration-status');
  if(migration.quality?.lines_without_product_link || migration.quality?.products_without_customer_link){ $('quality').hidden=false; $('quality').textContent='Dữ liệu nguồn cần đối chiếu: '+migration.quality.products_without_customer_link+' sản phẩm chưa liên kết được khách hàng; '+migration.quality.lines_without_product_link+' dòng đơn hàng thiếu danh mục sản phẩm. Đã giữ nguyên mã nguồn. Xem reports/import-result.json để biết chi tiết.'; }
  await loadOrders();
}
async function loadOrders(){
  if(loading)return; loading=true; $('message').textContent='';
  $('ordersBody').innerHTML='<tr><td colspan="8" class="empty">Đang tải đơn hàng…</td></tr>';
  const params = new URLSearchParams({page,size:25});
  for(const [name,id] of [['q','search'],['customer_id','customerFilter'],['status','statusFilter'],['product_type','typeFilter'],['from_date','fromDate'],['to_date','toDate']]) if($(id).value)params.set(name,$(id).value);
  try{
    const start=performance.now(), data=await api('/orders?'+params);
    total=data.total; $('recordCount').textContent=total+' đơn';
    $('timing').textContent='Tải danh sách: '+Math.round(performance.now()-start)+' ms';
    $('ordersBody').innerHTML=data.items.length?data.items.map(o=>`<tr><td><strong>${esc(o.id)}</strong><small>${esc(o.po_number)}</small></td><td class="customer">${esc(o.customer_name)}</td><td>${fmtDate(o.order_date)}</td><td>${fmtDate(o.delivery_date)}</td><td>${o.lines.length}</td><td>${money(o.lines.reduce((v,x)=>v+Number(x.quantity)*Number(x.price),0))}</td><td><span class="status">${esc([...new Set(o.lines.map(x=>x.status))].join(' · '))}</span></td><td><button data-open="${esc(o.id)}">Xem / Sửa</button></td></tr>`).join(''):'<tr><td colspan="8" class="empty">Không có đơn hàng phù hợp.</td></tr>';
    $('pageInfo').textContent=`Trang ${page} / ${Math.max(1,Math.ceil(total/25))} · ${total} đơn hàng`;
    $('previous').disabled=page===1; $('next').disabled=page*25>=total;
  }catch(e){showError(e);$('ordersBody').innerHTML='<tr><td colspan="8" class="empty">Chưa tải được dữ liệu. Hãy thử lại.</td></tr>';}
  finally{loading=false;}
}
async function loadProducts(q=''){
  const cid=$('editCustomer').value;
  const found=cid?await api('/products?'+new URLSearchParams({customer_id:cid,q,limit:300})):[];
  const keep=products.filter(p=>lines.some(l=>l.product_id===p.id));
  products=[...new Map([...keep,...found].map(p=>[p.id,p])).values()];
}
function defaultDate(){const d=new Date(Date.now()+10*86400000);return d.toLocaleDateString('en-CA',{timeZone:'Asia/Ho_Chi_Minh'});}
function blankLine(){return {id:null,product_id:'',quantity:'1',price:'0',unit:'Cái',delivery_date:defaultDate(),staff_id:null,status:'Chờ sản xuất',note:''};}
function renderLines(){
  const editable=current?user.permissions.includes('ORDER_EDIT')&&!current.lines.some(l=>l.missing_catalog):user.permissions.includes('ORDER_CREATE');
  $('lineBody').innerHTML=lines.map((l,i)=>`<tr data-index="${i}"><td><select class="product" data-field="product_id" required ${l.id?'disabled':''}>${options(products.map(p=>({id:p.id,name:p.id+' · '+p.name+(p.code?' ['+p.code+']':'')})),l.product_id,'Chọn sản phẩm')}</select>${l.id?`<small>${esc(l.id)} · Đã chạy: ${esc(l.produced)} · Đã giao: ${esc(l.delivered)}</small>`:''}</td><td><input class="unit" data-field="unit" value="${esc(l.unit)}" maxlength="100" required></td><td><input type="number" min="0.0001" step="0.0001" data-field="quantity" value="${esc(l.quantity)}" required></td><td><input type="number" min="0" step="0.0001" data-field="price" value="${esc(l.price)}" required></td><td><input type="date" data-field="delivery_date" value="${esc(l.delivery_date)}" required></td><td><select data-field="staff_id">${options(catalog.staff,l.staff_id,'Chưa phân công')}</select></td><td><select data-field="status">${catalog.statuses.map(s=>`<option ${s===l.status?'selected':''}>${esc(s)}</option>`).join('')}</select></td><td><input class="note" data-field="note" value="${esc(l.note)}" maxlength="10000"></td><td>${!l.id?`<button type="button" data-remove="${i}" aria-label="Xóa dòng mới">✕</button>`:''}</td></tr>`).join('');
  if(!editable)$('lineBody').querySelectorAll('input,select,button').forEach(x=>x.disabled=true);
  updateTotal();
}
function updateTotal(){ $('formTotal').textContent=lines.length+' dòng sản phẩm · Tổng: '+money(lines.reduce((v,l)=>v+Number(l.quantity)*Number(l.price),0)); }
async function openOrder(id=null){
  try{
    current=id?await api('/orders/'+encodeURIComponent(id)):null;
    lines=current?structuredClone(current.lines):[]; products=[]; requestKey=crypto.randomUUID();
    const editable=current?user.permissions.includes('ORDER_EDIT')&&!current.lines.some(l=>l.missing_catalog):user.permissions.includes('ORDER_CREATE');
    $('dialogTitle').textContent=current?current.id+' · '+current.po_number:'Tạo đơn hàng';
    $('editCustomer').innerHTML=options(catalog.customers,current?.customer_id,'Chọn khách hàng');
    $('editCustomer').disabled=!!current || !editable;
    $('editPO').value=current?.po_number||''; $('editDate').value=current?.order_date||today(); $('editFile').value=current?.file_url||'';
    ['editPO','editDate','editFile'].forEach(id=>$(id).disabled=!editable);
    $('saveOrder').hidden=!editable; $('addLine').hidden=!editable; $('findProduct').hidden=!editable;
    $('formError').textContent=current?.lines.some(l=>l.missing_catalog)?'Đơn có dòng thiếu sản phẩm trong danh mục nguồn. Đang giữ ở chế độ xem; cần bổ sung danh mục trước khi sửa.':''; $('productSearch').value='';
    // Retain all existing products, even when they are outside the first search page.
    if(current)products=current.lines.map(l=>({id:l.product_id,name:l.product_name,code:l.product_code,unit:l.unit,price:l.price}));
    await loadProducts(); if(!current)lines=[blankLine()]; renderLines(); $('orderDialog').showModal();
  }catch(e){showError(e);}
}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();$('loginError').textContent='';const button=e.submitter;button.disabled=true;try{await api('/login',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});$('password').value='';await enter();}catch(error){$('loginError').textContent=error.message;}finally{button.disabled=false;}});
$('logout').onclick=async()=>{try{await api('/logout',{method:'POST'});location.reload();}catch(e){showError(e);}};
$('filters').onsubmit=e=>{e.preventDefault();page=1;loadOrders();};
$('reset').onclick=()=>{$('filters').reset();page=1;loadOrders();};
$('previous').onclick=()=>{if(page>1){page--;loadOrders();}}; $('next').onclick=()=>{if(page*25<total){page++;loadOrders();}};
$('ordersBody').onclick=e=>{const b=e.target.closest('[data-open]');if(b)openOrder(b.dataset.open);};
$('newOrder').onclick=()=>openOrder();
for(const id of ['closeDialog','cancelDialog'])$(id).onclick=()=>$('orderDialog').close();
$('editCustomer').onchange=async()=>{try{lines=[blankLine()];products=[];await loadProducts();renderLines();requestKey=crypto.randomUUID();}catch(e){$('formError').textContent=e.message;}};
$('findProduct').onclick=async()=>{try{await loadProducts($('productSearch').value);renderLines();}catch(e){$('formError').textContent=e.message;}};
$('addLine').onclick=()=>{lines.push(blankLine());renderLines();requestKey=crypto.randomUUID();};
$('lineBody').addEventListener('input',e=>{const field=e.target.dataset.field;if(!field)return;const i=Number(e.target.closest('tr').dataset.index);lines[i][field]=e.target.value|| (field==='staff_id'?null:'');requestKey=crypto.randomUUID();updateTotal();});
$('lineBody').addEventListener('change',e=>{if(e.target.dataset.field!=='product_id')return;const i=Number(e.target.closest('tr').dataset.index),p=products.find(p=>p.id===e.target.value);if(p){Object.assign(lines[i],{product_id:p.id,unit:p.unit,price:p.price});renderLines();}});
$('lineBody').onclick=e=>{const b=e.target.closest('[data-remove]');if(b){lines.splice(Number(b.dataset.remove),1);renderLines();requestKey=crypto.randomUUID();}};
$('orderForm').addEventListener('input',()=>{requestKey=crypto.randomUUID();});
$('orderForm').onsubmit=async e=>{
  e.preventDefault();$('formError').textContent='';$('saveOrder').disabled=true;
  const payload={customer_id:$('editCustomer').value,po_number:$('editPO').value,order_date:$('editDate').value,file_url:$('editFile').value,version:current?.version??null,lines:lines.map(l=>Object.fromEntries(['id','product_id','quantity','price','unit','delivery_date','staff_id','status','note'].map(k=>[k,l[k]??null])))};
  try{const saved=await api('/orders'+(current?'/'+encodeURIComponent(current.id):''),{method:current?'PUT':'POST',headers:current?{}:{'Idempotency-Key':requestKey},body:JSON.stringify(payload)});$('orderDialog').close();await loadOrders();$('message').className='success';$('message').textContent='Đã lưu '+saved.id+' vào MySQL local. Google Sheets không thay đổi.';}
  catch(error){$('formError').textContent=error.message;}
  finally{$('saveOrder').disabled=false;}
};
enter().catch(error=>{if(!error.message.includes('đăng nhập'))$('loginError').textContent=error.message;});
