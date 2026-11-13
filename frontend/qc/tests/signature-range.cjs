const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
 constructor(tag='div'){this.tag=tag;this.children=[];this.style={};this.dataset={};this.value='';this.attrs={};const values=new Set();this.classList={add:(...v)=>v.forEach(x=>values.add(x)),remove:(...v)=>v.forEach(x=>values.delete(x)),toggle:(v,on)=>on?values.add(v):values.delete(v),contains:v=>values.has(v)};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
 querySelectorAll(){return walk(this).filter(n=>n.dataset.cell);}contains(node){return walk(this).includes(node);}
 closest(){return this.dataset.cell?this:null;}
}
const walk=n=>[n,...n.children.flatMap(walk)],nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
const docEvents={},events={};let hit=null;
global.document={getElementById:$,createElement:t=>new Node(t),addEventListener:(name,handler)=>docEvents[name]=handler,removeEventListener:name=>delete docEvents[name],elementFromPoint:()=>hit};
const snapshot={row_count:30,column_count:6,grid:{rowMetadata:Array.from({length:30},()=>({pixelSize:25}))},merges:[{startRowIndex:21,endRowIndex:23,startColumnIndex:1,endColumnIndex:4}]};
let row={id:'template'};
const admin={selected:()=>row,busy:()=>false,async api(){return {...row,snapshot,source_hash:'hash',sources:{},mapping:{fields:[],...(row.approved_at?{signature_cell:'B22',signature_end_cell:'F25'}:{})}};},update(data){row=data;},message(){},work(){},refresh(){}};
global.window={QCTemplateAdmin:admin,addEventListener:(name,handler)=>events[name]=handler};
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/sheet-preview.js','utf8'));
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/template-mapping.js','utf8'));
(async()=>{
 const range=window.QCSheetPreview.range;
 assert.deepEqual(range(snapshot,'C23'),{r0:21,c0:1,r1:23,c1:4,start:'B22',end:'D23'});
 assert.equal(range(snapshot,'A0'),null);assert.equal(range(snapshot,'G22'),null);
 await events['qc-template-selected']();$('signatureCell').onfocus();
 const cell=address=>$('mappingPreview').querySelectorAll().find(n=>n.dataset.cell===address);
 cell('F25').onpointerdown({button:0,preventDefault(){}});hit=cell('B22');docEvents.pointermove({preventDefault(){}});
 assert.equal($('signatureCell').value,'B22');assert.equal($('signatureEndCell').value,'F25');
 assert(cell('B22').classList.contains('signature-range'));assert(cell('E24').classList.contains('signature-range'));
 assert(!cell('A22').classList.contains('signature-range'));assert.match($('signatureRangeInfo').textContent,/B22:F25/);
 docEvents.pointerup();assert.equal(docEvents.pointermove,undefined);
 $('signatureCell').value='E26';$('signatureEndCell').value='F28';$('signatureCell').oninput();
 assert(!cell('B22').classList.contains('signature-range'));assert(cell('F28').classList.contains('signature-range'));
 row={id:'released',approved_at:'2026-11-13'};await events['qc-template-selected']();
 assert.equal($('signatureCell').disabled,true);assert.match($('signatureRangeInfo').textContent,/phiên bản mới/);
 const before=$('signatureCell').value;cell('A1').onpointerdown({button:0,preventDefault(){}});assert.equal($('signatureCell').value,before);
 console.log('PASS: reverse drag, merged cells, shaded selection, typed range updates, pointer cleanup and immutable approved region');
})().catch(error=>{console.error(error);process.exitCode=1;});
