const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
global.window={};
const records=[],writes=[],registrations=[];let release,delay=true;
global.fetch=async(url,options={})=>{
 let body;
 if(options.method==='POST'){
  const input=JSON.parse(options.body);registrations.push(input);
  assert.equal(input.staging_id,records.length?'stage':null);
  for(const file of input.files){if(!records.some(f=>f.name===file.name))records.push({...file,id:'f'+records.length,offset:0,ready:file.size===0});}
  body={id:'stage',files:structuredClone(records)};
 }else if(options.method==='PUT'){
  const id=url.split('/').at(-1).split('?')[0],file=records.find(f=>f.id===id);writes.push(id);
  if(delay){delay=false;await new Promise(resolve=>release=resolve);}
  file.offset+=options.body.size;file.ready=file.offset===file.size;body={offset:file.offset};
 }else if(options.method==='DELETE'){const index=records.findIndex(f=>f.id===url.split('/').at(-1));records.splice(index,1);body={};}
 else body={files:structuredClone(records)};
 return {ok:true,json:async()=>body};
};
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/staging.js','utf8'));
const entry=name=>({file:{name,size:3,type:'image/jpeg',lastModified:1,slice:()=>({size:3})}});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function finish(stage){for(let i=0;i<50&&stage.uploading;i++)await tick();assert.equal(stage.uploading,false);assert.equal(stage.error,'');assert.equal(stage.done,true);}
(async()=>{
 const a=entry('a.jpg'),b=entry('b.jpg'),c=entry('c.jpg');const stage=new window.QCStaging([a],()=>{});
 while(!release)await tick();stage.add([b]);assert.equal(stage.done,false);release();await finish(stage);
 assert.equal(stage.payload(),'stage');assert.equal(records.length,2);assert.equal(writes.filter(id=>id===a.stageFile).length,1);
 stage.add([c]);await finish(stage);assert.equal(records.length,3);assert.equal(registrations.length,3);
 assert.equal(writes.length,3,'completed files are never uploaded again when appending');
 stage.remove(b);await finish(stage);assert.equal(records.length,2);assert(!records.some(f=>f.name==='b.jpg'));
 console.log('PASS: append during reception and after completion, keep staging ID, no repeated uploads, remove one file');
})().catch(error=>{console.error(error);process.exitCode=1;});
