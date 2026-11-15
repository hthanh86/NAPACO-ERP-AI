(() => {
  'use strict';
  const $=id=>document.getElementById(id),root='/api/production/materials/',keys=new Map();
  const states={draft:'Nháp',awaiting_receipt:'Chờ bàn giao',received:'Đã nhận',cancelled:'Đã hủy'};
  let current=null,page=1,total=0,busy=false,strokes=[],active=null,proofPayload=null,proofFingerprint='';
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const button=(text,call)=>{const b=node('button',text);b.type='button';b.onclick=()=>guard(call);return b;};
  async function api(path,options={}) {
    const r=await fetch(root+path,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});
    if(r.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname+location.search));throw Error('Phiên đăng nhập đã hết.');}
    let data;try{data=await r.json();}catch{throw Error('Máy chủ không trả dữ liệu hợp lệ.');}
    if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;
  }
  async function write(path,payload) {
    const key=JSON.stringify([path,payload]);if(!keys.has(key))keys.set(key,crypto.randomUUID());
    const result=await api(path,{method:'POST',headers:{'Idempotency-Key':keys.get(key)},body:JSON.stringify(payload)});keys.delete(key);return result;
  }
  async function guard(call) {
    if(busy)return;busy=true;controls();
    try{await call();}catch(e){($('document').open?$('error'):$('message')).textContent=e.message;}
    finally{busy=false;controls();}
  }
  function controls() {
    for(const id of ['sign','clear','cancel','reload','balances'])$(id).disabled=busy;
    $('signing').hidden=!current||!['draft','awaiting_receipt'].includes(current.state);
    $('cancel').hidden=!current||current.state!=='draft';
  }
  function draw(canvas,values) {
    const c=canvas.getContext('2d');c.clearRect(0,0,canvas.width,canvas.height);c.strokeStyle='#183a68';c.lineWidth=2.5;c.lineCap='round';
    for(const s of values){c.beginPath();s.forEach(([x,y],i)=>c[i?'lineTo':'moveTo'](x*canvas.width,y*canvas.height));c.stroke();}
  }
  function savedProof(target,proof) {
    target.replaceChildren();if(!proof){target.append(node('p','Chưa ký'));return;}
    const c=node('canvas');c.width=900;c.height=240;target.append(c,node('p',proof.name+' · '+(proof.email||'')),node('p',proof.signed_at));draw(c,proof.signature);
  }
  async function search() {
    const data=await api('handovers?'+new URLSearchParams({q:$('q').value,state:$('state').value,page,size:25}));total=data.total;$('rows').replaceChildren();
    for(const r of data.items){const tr=node('tr');for(const v of [r.official_code,r.receipt_id,r.quantity,states[r.state]])tr.append(node('td',v));const td=node('td');td.append(button('Mở phiếu',()=>open(r.id)));tr.append(td);$('rows').append(tr);}
    $('count').textContent=`${total} phiếu · Trang ${page}`;$('prev').disabled=page===1;$('next').disabled=page*25>=total;$('message').textContent='';
  }
  async function open(id) {
    current=await api('handovers/'+encodeURIComponent(id));strokes=[];active=null;proofPayload=null;proofFingerprint='';draw($('signature'),strokes);
    $('heading').textContent='Phiếu bàn giao · '+current.snapshot.official_code;
    $('info').textContent=`${states[current.state]} · Lô ${current.snapshot.receipt_id} · CTĐH ${current.snapshot.order_line_id} · ${current.quantity} kg`;
    $('note').textContent=current.snapshot.note;$('error').textContent='';$('balanceRows').replaceChildren();
    savedProof($('issuer'),current.issue_signature);savedProof($('receiver'),current.receipt_signature);
    $('signRole').textContent=current.state==='draft'?'Ký cấp NVL — xuất kho và chờ bàn giao':'Ký nhận NVL — xác nhận thực nhận để sản xuất';
    $('sheet').href=root+'handovers/'+encodeURIComponent(current.id)+'/sheet';controls();if(!$('document').open)$('document').showModal();
  }
  function point(e){const r=$('signature').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
  $('signature').onpointerdown=e=>{if(busy||strokes.length>=100)return;e.preventDefault();$('signature').setPointerCapture(e.pointerId);active=[point(e)];strokes.push(active);proofPayload=null;};
  $('signature').onpointermove=e=>{if(active&&!busy&&active.length<3000&&strokes.reduce((n,s)=>n+s.length,0)<15000){active.push(point(e));draw($('signature'),strokes);}};
  $('signature').onpointerup=$('signature').onpointercancel=()=>active=null;
  $('clear').onclick=()=>{if(busy)return;strokes=[];active=null;proofPayload=null;draw($('signature'),strokes);};
  $('sign').onclick=()=>guard(async()=>{
    if(!strokes.some(s=>s.length>=2&&s.some(p=>p[0]!==s[0][0]||p[1]!==s[0][1])))throw Error('Hãy ký xác nhận; chữ ký không được chỉ có một điểm.');
    const role=current.state==='draft'?'issue':'receipt',payload={version:current.version,role,signature:strokes};
    const fingerprint=JSON.stringify([current.id,payload]);
    if(!proofPayload||fingerprint!==proofFingerprint){const proof=await api('handovers/'+encodeURIComponent(current.id)+'/confirm-signature',{method:'POST',body:JSON.stringify(payload)});proofPayload={...payload,confirmation:proof.confirmation};proofFingerprint=fingerprint;}
    const result=await write('handovers/'+encodeURIComponent(current.id)+'/sign',proofPayload);await open(result.id);
  });
  $('cancel').onclick=()=>guard(async()=>{if(!confirm('Hủy phiếu nháp? Phần giữ trở lại trạng thái chưa lập phiếu.'))return;const result=await write('handovers/'+encodeURIComponent(current.id)+'/cancel',{version:current.version});await open(result.id);});
  $('reload').onclick=()=>guard(()=>open(current.id));
  $('balances').onclick=()=>guard(async()=>{const data=await api('runs/'+encodeURIComponent(current.run_id)+'/balance');$('balanceRows').replaceChildren(node('h3','NVL theo LSX '+data.official_code));
    for(const lot of data.lots)$('balanceRows').append(node('p',`Lô ${lot.receipt_id}: đã nhận có chữ ký ${lot.received_signed_kg} kg; chờ bàn giao ${lot.pending_handover_kg} kg; còn dùng được ${lot.usable_kg} kg; lịch sử chưa có chữ ký mới ${lot.legacy_measured_carry_kg??'chưa xác định'} kg.`));});
  $('search').onsubmit=e=>{e.preventDefault();page=1;guard(search);};$('prev').onclick=()=>{if(page>1){page--;guard(search);}};$('next').onclick=()=>{if(page*25<total){page++;guard(search);}};
  $('close').onclick=()=>{$('document').close();if(total)guard(search);};
  const initial=new URLSearchParams(location.search).get('document_id');if(initial)guard(()=>open(initial));
})();
