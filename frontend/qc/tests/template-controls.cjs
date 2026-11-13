const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
const node=()=>({value:'',hidden:false,disabled:false,textContent:'',children:[],
 get options(){return this.children;},replaceChildren(...children){this.children=children;},append(...children){this.children.push(...children);}});
const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
global.document={getElementById:$,createElement:()=>node()};
global.window={QCFormUI:{async init(){},reset(){},busy(){return false;}},addEventListener(){}};
const response=(body,ok=true)=>({ok,json:async()=>body});
const pending=[];
global.fetch=url=>new Promise(resolve=>pending.push({url,resolve}));
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/mapped-forms.js','utf8'));
const entry={id:'template',code:'QC_V1',version:1};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function options(items){assert.match(pending[0].url,/template-options/);pending.shift().resolve(response({items}));await tick();}
async function complete(){await options([entry]);assert.equal($('openMappedForm').disabled,true,'entry still loading');pending.shift().resolve(response(entry));await tick();}
(async()=>{
 await window.QCFormUI.init();window.QCFormUI.reset();$('objectId').value='NVL_1';
 let task=$('findMappedTemplates').onclick();
 assert.equal($('openMappedForm').disabled,true);assert.equal($('findMappedTemplates').disabled,true);
 await complete();await task;
 assert.equal($('openMappedForm').disabled,false,'enable entry and signature after automatic selection');
 assert.equal($('findMappedTemplates').disabled,false);
 task=$('findMappedTemplates').onclick();await options([]);await task;
 assert.equal($('openMappedForm').disabled,true);
 assert.match($('mappedSummary').textContent,/Không thể tạo QC/,'keep missing template error');
 task=$('findMappedTemplates').onclick();pending.shift().resolve(response({detail:'Không đủ quyền đọc template'},false));await task;
 assert.equal($('openMappedForm').disabled,true);assert.equal($('findMappedTemplates').disabled,false);
 assert.equal($('mappedSummary').textContent,'Không đủ quyền đọc template','keep API error');
 task=$('findMappedTemplates').onclick();await complete();await task;
 assert.equal($('openMappedForm').disabled,false,'successful retry unlocks entry');
 const old=$('findMappedTemplates').onclick();const oldRequest=pending.shift();
 $('objectId').value='NVL_2';task=$('findMappedTemplates').onclick();
 oldRequest.resolve(response({items:[entry]}));await old;
 assert.equal($('openMappedForm').disabled,true,'stale response must not unlock current request');
 assert.equal($('findMappedTemplates').disabled,true);
 await complete();await task;assert.equal($('openMappedForm').disabled,false);
 task=$('findMappedTemplates').onclick();const abandoned=pending.shift();
 $('objectId').value='';await $('findMappedTemplates').onclick();
 abandoned.resolve(response({items:[entry]}));await task;
 assert.equal($('openMappedForm').disabled,true);assert.equal($('findMappedTemplates').disabled,false);
 assert.equal(window.QCFormUI.busy(),false);
 console.log('PASS: automatic selection, loading guards, no match, API error, retry, stale responses and cleared object');
})().catch(error=>{console.error(error);process.exitCode=1;});
