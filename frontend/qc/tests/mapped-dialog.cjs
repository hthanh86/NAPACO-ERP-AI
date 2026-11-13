const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
 constructor(tag='div',text=''){this.tag=tag;this.textContent=text;this.children=[];this.value='';this.dataset={};this.attrs={};this.classList={add(){}};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
 get firstChild(){return this.children[0];}get options(){return this.children;}
 setAttribute(k,v){this.attrs[k]=v;}addEventListener(){}showModal(){}close(){this.closed=true;}remove(){}
 reportValidity(){return true;}getContext(){return {clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){}};}
 querySelectorAll(){return walk(this).filter(n=>n.dataset.cell);}
}
const walk=n=>[n,...n.children.flatMap(walk)],nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
global.document={getElementById:$,createElement:t=>new Node(t),body:new Node('body')};
const cells={};
global.window={QCFormUI:{async init(){},reset(){},evidenceRecord(){}},NAPACO_USER:{id:'owner',name:'QC',email:'qc@example.com'},addEventListener(){},
 QCSheetPreview:{render(node){for(const address of ['E11','F11','G11','E19','E21','E5']){const cell=new Node('td');cell.dataset.cell=address;cell.append(new Node('div'));node.append(cell);cells[address]=cell;}}}};
global.FormData=class{[Symbol.iterator](){return Object.entries({quantity:$('quantity').value,note:$('note').value,result:$('result').value})[Symbol.iterator]();}};
let request;global.fetch=async(url,options)=>{request=JSON.parse(options.body);return {ok:true,json:async()=>({confirmation:'signed'})};};
vm.runInThisContext(fs.readFileSync('/app/frontend/qc/mapped-forms.js','utf8'));
const fields=[{id:'width',kind:'INPUT',name:'Khổ rộng màng (Width)',standard:'Theo đơn đặt hàng (PO)',unit:'mm',cell:'E11',assessment_cell:'F11',data_type:'number',required:true},
 {id:'conclusion',kind:'ERP',source:'conclusion',cell:'E19'},{id:'note',kind:'ERP',source:'qc_note',cell:'E21'},
 {id:'quantity',kind:'ERP',source:'quantity',cell:'E5'}];
const record={id:'QC_TEST',template_id:'template',criterion_note_cells:{width:{cell:'G11',base:'± 2 mm'}},form_data:{template:{id:'template',code:'QC_V1',version:1,name:'QC',mapping:{fields,signature_cell:'E25'},snapshot:{}},
 context:{material_id:'PET',width:'640',color:'Trong',grade:'A'},auto_values:{conclusion:'Đạt',note:'Ghi chú cũ',quantity:'3'},
 input:{answers:[{id:'width',actual:'640',assessment:'PASS'}],conclusion:'PASS',signature:[[[.1,.2],[.8,.7]]]},signer:{user_id:'owner'}}};
const dialog=()=>document.body.children.at(-1),find=(label)=>walk(dialog()).find(n=>n.attrs['aria-label']===label);
(async()=>{
 await window.QCFormUI.init();$('quantity').value='3';$('note').value='Ghi chú cũ';$('objectType').value='NVL';
 window.QCFormUI.load(record,false);$('openMappedForm').onclick();
 assert.equal($('qcNoteSection').hidden,true);
 assert.equal(find('Ghi chú phiếu QC').disabled,true);assert.equal(find('Kết luận QC').disabled,true);
 assert.equal(cells.E19.firstChild.textContent,'Đạt');assert.equal(cells.E21.firstChild.textContent,'Ghi chú cũ');
 assert(walk(dialog()).some(n=>n.textContent==='Dữ liệu chuẩn đối chiếu'));
 assert(walk(dialog()).some(n=>n.textContent==='Khổ đặt: 640 mm'));
 assert(walk(dialog()).some(n=>n.textContent==='Theo đơn đặt hàng (PO)'));
 $('resignMapped').onclick();
 const note=find('Ghi chú phiếu QC'),conclusion=find('Kết luận QC');assert.equal(note.disabled,false);
 const criterionNote=walk(dialog()).find(n=>n.tag==='textarea'&&n!==note);
 assert.equal(criterionNote.placeholder,'± 2 mm');assert.equal(cells.G11.firstChild.textContent,'');
 criterionNote.value='siêu chuẩn';criterionNote.oninput();assert.equal(cells.G11.firstChild.textContent,'siêu chuẩn');
 note.value='NG: cách ly và xử lý';note.oninput();assert.equal(cells.E21.firstChild.textContent,note.value);
 assert.equal($('note').value,'Ghi chú cũ','dialog changes remain local until Apply succeeds');
 conclusion.value='FAIL';conclusion.onchange();assert.equal(cells.E19.firstChild.textContent,'Không đạt');
 const assessment=walk(dialog()).find(n=>n.tag==='select'&&n!==conclusion);assessment.value='FAIL';assessment.onchange();
 await walk(dialog()).find(n=>n.tag==='button'&&n.textContent==='Áp dụng kết quả').onclick();
 assert.equal(request.note,note.value);assert.equal(request.result,'NG');assert.equal(request.mapped_form.conclusion,'FAIL');
 assert.equal(request.mapped_form.answers[0].note,'siêu chuẩn');
 assert.equal($('note').value,note.value);assert.equal($('result').value,'NG');assert.equal(dialog().closed,true);
 assert.equal(record.form_data.auto_values.note,'Ghi chú cũ','preserve saved snapshot');
 window.QCFormUI.reset();assert.equal($('qcNoteSection').hidden,false,'keep external note available without a mapped template');
 console.log('PASS: reference cards/order standard, read-only history, live mapped conclusion/note, signed Apply payload and original snapshot');
})().catch(error=>{console.error(error);process.exitCode=1;});
