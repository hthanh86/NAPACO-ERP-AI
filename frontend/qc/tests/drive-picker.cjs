const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.className='';this.events={};this.open=false;this.classList={toggle:(name,on)=>{const s=new Set(this.className.split(' ').filter(Boolean));if(on)s.add(name);else s.delete(name);this.className=[...s].join(' ');}};}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(name,fn){this.events[name]=fn;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
  querySelectorAll(selector){return this.children.flatMap(n=>[(n.className||'').split(' ').includes(selector.slice(1))?n:null,...n.querySelectorAll(selector)]).filter(Boolean);}
  showModal(){this.open=true;}
  close(){this.open=false;this.events.close?.();}
}
global.window={NAPACO_USER:{id:'qa'}};global.document={body:new Node('body'),createElement:tag=>new Node(tag)};
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/drive-picker.js','utf8'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  let requests=0,selected;
  const tree={root:{current:{id:'root',name:'QC'},breadcrumb:[{id:'root',name:'QC'}],items:[{id:'child',name:'Child'}]},child:{current:{id:'child',name:'Child'},parent_id:'root',breadcrumb:[{id:'root',name:'QC'},{id:'child',name:'Child'}],items:[]}};
  const api=async url=>{requests++;const id=new URL(url,'http://local').searchParams.get('folder_id')||'root';return tree[id];};
  window.QCDrivePicker.open({api,root:'root',onSelect:x=>selected=x});await tick();
  const modal=document.body.children[0],toolbar=modal.children[1],body=modal.children[3],footer=modal.children[5];
  const folder=body.children[0];folder.onclick();assert.equal(requests,1);assert.equal(body.children[0],folder,'single click must preserve element for native double click');
  folder.ondblclick();await tick();assert.equal(requests,2);assert.equal(footer.children[0].textContent,'Đã chọn: Child');
  toolbar.children[0].onclick();await tick();assert.equal(requests,2,'Back must use cache');
  toolbar.children[1].onclick();await tick();assert.equal(requests,2,'Forward must use cache');
  toolbar.children[3].onclick();await tick();assert.equal(requests,3,'Refresh must query backend');
  footer.children[2].onclick();assert.equal(selected.id,'child');assert.equal(document.body.children.length,0);
  let releaseA,releaseB;
  const slow=async url=>{const id=new URL(url,'http://local').searchParams.get('folder_id');if(!id)return {current:{id:'race',name:'Race'},items:[{id:'A',name:'A'},{id:'B',name:'B'}]};return new Promise(r=>{if(id==='A')releaseA=r;else releaseB=r;});};
  window.QCDrivePicker.open({api:slow,root:'race',onSelect(){}});await tick();
  const race=document.body.children[0],area=race.children[3],a=area.children[0],b=area.children[1];a.ondblclick();b.ondblclick();
  releaseB({current:{id:'B',name:'B'},items:[]});await tick();releaseA({current:{id:'A',name:'A'},items:[]});await tick();
  assert.equal(race.children[5].children[0].textContent,'Đã chọn: B','stale response must not replace current folder');race.close();
  console.log('Drive dialog: selection/double-click/back/forward/cache/refresh/stale-response passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
