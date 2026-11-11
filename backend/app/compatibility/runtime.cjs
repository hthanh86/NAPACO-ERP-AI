/* Local execution adapter. Original UI and business source remain byte-for-byte intact.
 * No Google Sheets requests are made. Python supplies a transactional MySQL snapshot.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = input.frontendRoot || '/app/frontend';
const templatePaths = {"DonHang/OrderIndex_View": "orders/index", "DonHang/OrderList_View": "orders/list", "DonHang/OrderModal": "orders/create", "DonHang/OrderListBe_View": "orders/be", "DonHang/OrderMenu_View": "shared/menu", "KHO_NVL/FilmOrder_View": "materials/purchasing", "KHO_NVL/FilmReceipt_View": "materials/receiving", "KHO_NVL/FilmStock_View": "materials/inventory"};
const dirty = new Set(), uploads = [];
const properties = input.properties || {}, metadata = input.metadata || {}, notes = input.notes || {};
function revive(value) {
  if (value && typeof value === 'object' && value.__date) return new Date(value.__date);
  if (Array.isArray(value)) return value.map(revive);
  return value;
}
function encode(value) {
  if (value instanceof Date) return {__date: value.toISOString()};
  if (Array.isArray(value)) return value.map(encode);
  return value;
}
function formatDate(date, zone, pattern) {
  date = date instanceof Date ? date : new Date(date);
  if (!Number.isFinite(date.getTime())) throw new Error('Ngày không hợp lệ.');
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: zone || 'Asia/Ho_Chi_Minh', year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'
  }).formatToParts(date).map(x=>[x.type,x.value]));
  const tokens={yyyy:parts.year, yy:parts.year.slice(-2), MM:parts.month, dd:parts.day,
    HH:parts.hour, mm:parts.minute, ss:parts.second, SSS:String(date.getUTCMilliseconds()).padStart(3,'0')};
  return pattern.replace(/yyyy|SSS|yy|MM|dd|HH|mm|ss/g,k=>tokens[k]);
}
function parseDate(s, zone, pattern) {
  let iso=String(s).replace(' ','T');
  if (/^\d{2}\/\d{2}\/\d{4}/.test(iso)) iso=iso.slice(6,10)+'-'+iso.slice(3,5)+'-'+iso.slice(0,2)+iso.slice(10);
  if (iso.length===10) iso+='T00:00:00';
  if (!/[zZ]$|[+-]\d\d:\d\d$/.test(iso)) iso+='+07:00';
  return new Date(iso);
}
function escapeHtml(s) { return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
const books = new Map();
function copy(v) { return v instanceof Date ? new Date(v.getTime()) : v; }
function column(s) { return [...s.toUpperCase()].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0); }
class Range {
  constructor(sheet,r,c,rows=1,cols=1){Object.assign(this,{sheet,r,c,rows,cols});}
  getValues(){return Array.from({length:this.rows},(_,r)=>Array.from({length:this.cols},(_,c)=>copy(this.sheet.values[this.r-1+r]?.[this.c-1+c]??'')));}
  getDisplayValues(){return this.getValues().map(row=>row.map(v=>v instanceof Date?formatDate(v,'Asia/Ho_Chi_Minh','dd/MM/yyyy'):String(v??'')));}
  getValue(){return this.getValues()[0][0];}
  setValues(values){if(values.length!==this.rows||values.some(r=>r.length!==this.cols))throw new Error('Kích thước vùng ghi không khớp.');values.forEach((row,r)=>row.forEach((v,c)=>this.sheet.put(this.r-1+r,this.c-1+c,v)));return this;}
  setValue(value){return this.setValues([[value]]);}
  getNotes(){return Array.from({length:this.rows},(_,r)=>Array.from({length:this.cols},(_,c)=>notes[this.sheet.book.id]?.[this.sheet.name]?.[`${this.r-1+r}:${this.c-1+c}`]||''));}
  clearContent(){return this.setValues(Array.from({length:this.rows},()=>Array(this.cols).fill('')));}
  clearContents(){return this.clearContent();}
  setFontWeight(){return this;}
  setDataValidation(){return this;}
}
class Sheet {
  constructor(book,data){this.book=book;this.name=data.name;this.id=data.id;this.values=revive(data.values);}
  getName(){return this.name;} getSheetId(){return this.id;}
  getLastRow(){let n=this.values.length;while(n&&!this.values[n-1].some(v=>v!==''&&v!=null))n--;return n;}
  getLastColumn(){return this.values.reduce((n,r)=>Math.max(n,r.length),0);}
  getMaxRows(){return Math.max(1000,this.values.length);}
  getDataRange(){return this.getRange(1,1,Math.max(1,this.getLastRow()),Math.max(1,this.getLastColumn()));}
  getRange(r,c,rows=1,cols=1){
    if(typeof r==='string'){
      const m=r.match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d*)?)?$/i);if(!m)throw new Error('Vùng dữ liệu không hỗ trợ: '+r);
      c=column(m[1]);r=Number(m[2]);cols=m[3]?column(m[3])-c+1:1;rows=m[3]?Math.max(r,Number(m[4])||this.getLastRow())-r+1:1;
    }
    return new Range(this,r,c,rows,cols);
  }
  put(r,c,value){while(this.values.length<=r)this.values.push([]);while(this.values[r].length<=c)this.values[r].push('');this.values[r][c]=copy(value);dirty.add(this.book.id+'|'+this.name);}
  clearContents(){this.values=[];dirty.add(this.book.id+'|'+this.name);return this;}
}
class Book {
  constructor(data){this.id=data.id;this.sheets=data.sheets.map(x=>new Sheet(this,x));}
  getId(){return this.id;} getSpreadsheetTimeZone(){return 'Asia/Ho_Chi_Minh';}
  getSheetByName(name){return this.sheets.find(s=>s.name===name)||null;}
  getSheets(){return this.sheets;}
  insertSheet(name){const s=new Sheet(this,{name,id:Math.max(0,...this.sheets.map(s=>s.id))+1,values:[]});this.sheets.push(s);dirty.add(this.id+'|'+name);return s;}
  createDeveloperMetadataFinder(){let key='';const book=this;return {withKey(k){key=k;return this;},find(){return(metadata[book.id]||[]).filter(x=>x.metadataKey===key).map(x=>({getId:()=>x.metadataId,getValue:()=>x.metadataValue}));}};}
}
for(const data of input.books)books.set(data.id,new Book(data));
function getBook(id){const b=books.get(id);if(!b)throw new Error('Bảng dữ liệu chưa được chuyển vào MySQL local.');return b;}
function batchUpdate({requests},bookId){
  const book=getBook(bookId);
  for(const request of requests){
    if(request.appendDimension)continue;
    if(request.createDeveloperMetadata){const m=request.createDeveloperMetadata.developerMetadata;const entries=metadata[bookId]||(metadata[bookId]=[]);entries.push({...m,metadataId:1+Math.max(0,...entries.map(e=>e.metadataId))});continue;}
    if(request.deleteDeveloperMetadata){const id=request.deleteDeveloperMetadata.dataFilter.developerMetadataLookup.metadataId;metadata[bookId]=(metadata[bookId]||[]).filter(e=>e.metadataId!==id);continue;}
    const append=request.appendCells,update=request.updateCells;
    if(!append&&!update)throw new Error('Kiểu ghi dữ liệu chưa hỗ trợ: '+Object.keys(request)[0]);
    const spec=append||update, start=append?{sheetId:append.sheetId,rowIndex:null,columnIndex:0}:(update.start||{sheetId:update.range.sheetId,rowIndex:update.range.startRowIndex||0,columnIndex:update.range.startColumnIndex||0});
    const sheet=book.sheets.find(s=>s.id===start.sheetId);if(!sheet)throw new Error('Không tìm thấy bảng ghi dữ liệu.');
    const first=append?sheet.getLastRow():start.rowIndex;
    (spec.rows||[]).forEach((row,r)=>(row.values||[]).forEach((cell,c)=>{
      const ri=first+r,ci=(start.columnIndex||0)+c;
      if(spec.fields==='*'||!spec.fields||spec.fields.includes('userEnteredValue')){
        const v=cell.userEnteredValue||{};let value=v.stringValue??v.numberValue??v.boolValue??'';
        if(v.formulaValue!=null)throw new Error('Công thức mới phải được chuyển thành quy tắc nghiệp vụ trước khi ghi.');
        if(cell.userEnteredFormat?.numberFormat?.type==='DATE'&&typeof value==='number')value=parseDate(new Date(Math.round((value-25569)*86400000)).toISOString().slice(0,10),'Asia/Ho_Chi_Minh');
        sheet.put(ri,ci,value);
      }
      if(cell.note!==undefined){notes[bookId]??={};notes[bookId][sheet.name]??={};notes[bookId][sheet.name][`${ri}:${ci}`]=cell.note;dirty.add(bookId+'|'+sheet.name);}
    }));
  }
  return {};
}
const output = content=>({
  getContent:()=>content,
  setTitle(title){
    const tag='<title>'+escapeHtml(title)+'</title>';
    content=/<title[\s>]/i.test(content)?content.replace(/<title[^>]*>[\s\S]*?<\/title>/i,tag):content.replace('<head>','<head>'+tag);
    return this;
  },
  setXFrameOptionsMode(){return this;},
  addMetaTag(name,value){
    if(!content.includes('name="'+name+'"'))content=content.replace('<head>','<head><meta name="'+escapeHtml(name)+'" content="'+escapeHtml(value)+'">');
    return this;
  }
});
let context;
function template(filename){
  const file=path.resolve(root,(templatePaths[filename]||'__missing__')+'.html');if(!file.startsWith(root+'/'))throw new Error('Invalid template.');
  const body=fs.readFileSync(file,'utf8'),locals={};
  locals.evaluate=()=>{
    let code='let __out="";\n',last=0;
    for(const m of body.matchAll(/<\?([\s\S]*?)\?>/g)){
      code+='__out+='+JSON.stringify(body.slice(last,m.index))+';\n';
      const tag=m[1];code+=tag.startsWith('!=')?'__out+=String(('+tag.slice(2)+')??"");\n':tag.startsWith('=')?'__out+=__escape(('+tag.slice(1)+'));\n':tag+'\n';last=m.index+m[0].length;
    }
    code+='__out+='+JSON.stringify(body.slice(last))+';return __out;';
    const keys=Object.keys(locals).filter(k=>k!=='evaluate');
    context.__templateArgs=keys.map(k=>locals[k]);context.__templateFunction='(function('+keys.join(',')+'){'+code+'})';
    const fn=vm.runInContext(context.__templateFunction,context,{timeout:10000});
    return output(fn(...context.__templateArgs));
  };return locals;
}
function blob(data,mime='application/octet-stream',name='file'){
  const bytes=typeof data==='string'?Buffer.from(data):Buffer.from(data||[]);
  return {getBytes:()=>[...bytes],getName:()=>name,getContentType:()=>mime,bytes,mime,name};
}
const disabledDrive=()=>{throw new Error('Chưa cấp quyền Google Drive cho backend local. Chức năng này vẫn giữ nguyên giao diện nhưng cần cấu hình đăng nhập Google trước khi sử dụng.');};
context=vm.createContext({
  Date,Intl,Buffer:undefined,__escape:escapeHtml,CONFIG:input.config,
  console:{log(){},warn(){},error(){}},
  SpreadsheetApp:{openById:getBook,getActiveSpreadsheet:()=>null,flush(){},newDataValidation(){return{requireValueInRange(){return this;},setAllowInvalid(){return this;},build(){return{};}};}},
  Sheets:{Spreadsheets:{batchUpdate}},
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>properties[k]??null,getProperties:()=>({...properties}),setProperty(k,v){properties[k]=String(v);},setProperties(obj){Object.assign(properties,obj);}})},
  CacheService:{getScriptCache:()=>({get:()=>null,put(){},removeAll(){}})},
  LockService:{getScriptLock:()=>({waitLock(){},tryLock:()=>true,releaseLock(){}})},
  Session:{getActiveUser:()=>({getEmail:()=>input.user.email||''})},
  Utilities:{formatDate,parseDate,getUuid:()=>crypto.randomUUID(),newBlob:blob,
    base64Encode:data=>Buffer.from(data).toString('base64'),base64Decode:data=>[...Buffer.from(data,'base64')],
    base64EncodeWebSafe:data=>Buffer.from(data).toString('base64url'),
    DigestAlgorithm:{SHA_256:'sha256'},computeDigest:(algorithm,data)=>[...crypto.createHash(algorithm).update(data).digest()]},
  HtmlService:{createTemplateFromFile:template,createHtmlOutput:output,createHtmlOutputFromFile:f=>output(fs.readFileSync(path.join(root,(templatePaths[f]||'__missing__')+'.html'),'utf8')),XFrameOptionsMode:{ALLOWALL:'ALLOWALL'}},
  ScriptApp:{getService:()=>({getUrl:()=>input.appUrl})},
  Drive:{Files:{get:disabledDrive,list:disabledDrive}},
  DriveApp:{getFolderById:()=>({createFile(file){
    if(!input.driveReady) return disabledDrive();
    const placeholder='napaco-upload://'+crypto.randomUUID();
    uploads.push({placeholder,name:file.name,mime:file.mime,base64:file.bytes.toString('base64')});
    return {getUrl:()=>placeholder};
  }}),getFileByIdAndResourceKey:disabledDrive},
});
try{
  const files=["compatibility/legacy/config_helpers.js", "compatibility/legacy/sheet_access.js", "auth/legacy/authorization.js", "compatibility/legacy/spreadsheet_read.js", "modules/orders/legacy/service.js", "modules/orders/legacy/controller.js", "modules/materials/purchasing/legacy/service.js", "modules/materials/receiving/legacy/service.js", "modules/materials/inventory/legacy/stock.js", "modules/materials/inventory/legacy/returns.js"];
  for(const file of files)vm.runInContext(fs.readFileSync(path.join(__dirname,"..",file),"utf8"),context,{filename:file,timeout:10000});
  context.__identity=input.user;
  vm.runInContext(`
    CONFIG.DEBUG_MODE=false;
    createReadBook_=id=>SpreadsheetApp.openById(id);
    if(__identity.localAdmin){
      const originalStaff=OrderService.readOrderStaff_;
      OrderService.readOrderStaff_=function(book){
        const data=originalStaff.call(this,book);
        const employee={maNV:__identity.id,hoTen:__identity.name,phongBan:'Kinh doanh',role:'Admin',email:'',sdt:'',quyenTruyCap:'ADMIN',trangThai:'Đang hoạt động',display:__identity.id+' - '+__identity.name};
        data.matchedEmployee=employee;data.employeeByIdMap[employee.maNV]=employee;
        data.salesStaffList.push(employee);return data;
      };
      readUserPermissions_=()=>({userId:__identity.id,role:'ADMIN',hasRoleColumn:true,permissions:new Map(Object.values(CONFIG.PERMISSIONS).map(p=>[p,true]))});
    }
  `,context,{timeout:10000});
  context.__args=input.args||[];context.__method=input.method;
  let result;
  if(input.render){context.__params=input.params||{};result=vm.runInContext('doGet({parameter:__params}).getContent()',context,{timeout:10000});}
  else result=vm.runInContext('globalThis[__method](...__args)',context,{timeout:10000});
  const changed=[...dirty].map(key=>{const [id,name]=key.split('|');const sheet=getBook(id).getSheetByName(name);return{book:id,name,id:sheet.id,values:encode(sheet.values)};});
  process.stdout.write(JSON.stringify({ok:true,result,changed,properties,metadata,notes,uploads}));
}catch(error){process.stdout.write(JSON.stringify({ok:false,error:String(error.message||error)}));process.exitCode=0;}
