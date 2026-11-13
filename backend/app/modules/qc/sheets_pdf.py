"""Google copy/batch-fill/export pipeline. Only temporary copies are writable."""
from copy import deepcopy
import hashlib
import json
from urllib.parse import urlencode,urlsplit
import httpx
from fastapi import HTTPException
from app.core.performance import measure
from app.integrations.google import sheets
from app.integrations.google.oauth import google_json
from app.modules.qc import mapping


def persist(db, identifier, expected_revision=None, **updates):
    from app.modules.qc.evidence import locked
    from app.modules.qc.drive_bundle import JOB
    obj=locked(db,identifier)
    if expected_revision and mapping.digest(obj.form_data)!=expected_revision:
        raise HTTPException(409,'Phiếu đã thay đổi trong khi xuất PDF. Hãy xuất lại bản vừa ký.')
    obj.source={**(obj.source or {}),JOB:{**(obj.source or {}).get(JOB,{}),**updates}}
    db.commit()
    return obj


@measure('sheets.export_pdf')
def export(token, identifier, gid, rows, columns):
    url='https://docs.google.com/spreadsheets/d/'+identifier+'/export?'+urlencode({
        'format':'pdf','gid':gid,'size':'A4','portrait':'true','scale':4,'gridlines':'false',
        'sheetnames':'false','printtitle':'false','pagenumbers':'false','fzr':'false',
        'top_margin':.25,'bottom_margin':.25,'left_margin':.25,'right_margin':.25,
        'r1':0,'c1':0,'r2':rows,'c2':columns})
    headers={'Authorization':'Bearer '+token}
    try:
        with httpx.Client(timeout=60,follow_redirects=False) as client:
            for _ in range(4):
                response=client.get(url,headers=headers)
                if response.status_code not in {301,302,303,307,308}:break
                url=response.headers.get('location','');host=urlsplit(url)
                if host.scheme!='https' or not (host.hostname=='docs.google.com' or (host.hostname or '').endswith('.googleusercontent.com')):
                    raise HTTPException(502,'Google trả về địa chỉ export PDF không hợp lệ.')
                headers={'Authorization':'Bearer '+token} if host.hostname=='docs.google.com' else {}
        if response.status_code!=200 or len(response.content)>25*1024*1024:
            raise HTTPException(502,'Google chưa xuất được PDF hoặc PDF vượt giới hạn 25 MiB. Hãy thử lại.')
        return response.content
    except httpx.HTTPError:
        raise HTTPException(502,'Export PDF từ Google bị gián đoạn. Phiếu đã lưu; có thể thử lại.') from None


@measure('sheets.render_total')
def render(db,user,obj,token):
    from app.modules.qc.drive_bundle import JOB,call
    saved=deepcopy(obj.form_data);definition=saved['template'];layout=definition['mapping'];snap=definition['snapshot']
    if not saved.get('signer') or not saved['input'].get('signature') or not layout.get('signature_cell'):
        raise HTTPException(422,'Phiếu cần chữ ký OAuth và mapping vị trí ký đã duyệt trước khi xuất PDF.')
    revision=mapping.digest(saved)
    source=sheets.first_tab(db,user,definition['spreadsheet_id'],True)
    if mapping.source_hash(source)!=definition['source_hash'] or source['sheet_id']!=definition['sheet_id']:
        raise HTTPException(409,'Template Google gốc đã thay đổi so với phiên bản trên phiếu. Không xuất từ nguồn không khớp.')
    job=(obj.source or {}).get(JOB,{})
    key=hashlib.sha256((obj.id+revision).encode()).hexdigest()
    temporary=job.get('temp_copy_id') if job.get('temp_revision')==revision else None
    if not temporary:
        with measure('sheets.copy_template'):
            found=call(token,q=f"'{obj.drive_folder_id}' in parents and trashed=false and appProperties has {{ key='qc_temp' and value='{key}' }}",fields='files(id)',pageSize=10,includeItemsFromAllDrives='true')
            if found.get('files'):temporary=found['files'][0]['id']
            else:
                created=call(token,'/'+definition['spreadsheet_id']+'/copy',method='POST',body={
                    'name':'_QC_TEMP_'+obj.id,'parents':[obj.drive_folder_id],'appProperties':{'qc_temp':key}},fields='id')
                temporary=created['id']
        obj=persist(db,obj.id,expected_revision=revision,temp_copy_id=temporary,temp_revision=revision,temp_key=key,step='mapping')
    if temporary==definition['spreadsheet_id']:
        raise HTTPException(409,'Từ chối ghi vào template gốc.')
    copied=sheets.first_tab(db,user,temporary,True)
    identity_copy={**copied,'spreadsheet_id':source['spreadsheet_id'],'title':source['title']}
    if mapping.source_hash(identity_copy)!=definition['source_hash'] and job.get('temp_copy_id')!=temporary:
        raise HTTPException(409,'Bản sao Google không khớp template đã duyệt.')
    gid=copied['sheet_id'];base='https://sheets.googleapis.com/v4/spreadsheets/'+temporary
    values={};answers={a['id']:a for a in saved['input']['answers']}
    for field in layout['fields']:
        if field['kind']=='ERP':values[field['cell']]=saved['auto_values'].get(field['id'],'')
        elif field['kind']=='STANDARD':values[field['cell']]=field.get('value','')
        else:
            answer=answers[field['id']]
            values[field['cell']]='Không áp dụng' if answer['assessment']=='NA' else answer['actual']+(' '+field['unit'] if answer['actual'] and field.get('unit') else '')
            if field.get('assessment_cell'):values[field['assessment_cell']]={'PASS':'Đạt','FAIL':'Không đạt','NA':'N/A',None:''}[answer['assessment']]
    requests=[]
    for cell,value in values.items():
        row,col=mapping.position(cell)
        requests.append({'updateCells':{'start':{'sheetId':gid,'rowIndex':row,'columnIndex':col},
            'rows':[{'values':[{'userEnteredValue':{'stringValue':str(value)}}]}],'fields':'userEnteredValue'}})
    r0,c0,r1,c1=mapping.region(snap,layout['signature_cell'],layout.get('signature_end_cell'))
    area={'sheetId':gid,'startRowIndex':r0,'endRowIndex':r1,'startColumnIndex':c0,'endColumnIndex':c1}
    color_bytes=hashlib.sha256(saved['signer']['nonce'].encode()).digest()[:3]
    marker=tuple((32+int(b)%190)/255 for b in color_bytes)
    cell_format=mapping.cells(snap).get(layout['signature_cell'],{}).get('effectiveFormat',{})
    bg=cell_format.get('backgroundColor',{})
    style=cell_format.get('backgroundColorStyle',{})
    if style.get('themeColor'):
        bg=next((c.get('color',{}).get('rgbColor',{}) for c in snap.get('theme',{}).get('themeColors',[]) if c['colorType']==style['themeColor']),bg)
    else:bg=style.get('rgbColor',bg)
    has_background='backgroundColor' in cell_format or 'backgroundColorStyle' in cell_format
    background=tuple(bg.get(k,0) for k in ['red','green','blue']) if bg or has_background else (1,1,1)
    if r1-r0>1 or c1-c0>1:
        requests.extend([{'unmergeCells':{'range':area}},{'mergeCells':{'range':area,'mergeType':'MERGE_ALL'}}])
    requests.append({'repeatCell':{'range':area,'cell':{'userEnteredValue':{'stringValue':''},
        'userEnteredFormat':{'backgroundColor':dict(zip(['red','green','blue'],marker))}},
        'fields':'userEnteredValue,userEnteredFormat.backgroundColor'}})
    with measure('sheets.batch_mapping'):
        google_json(base+':batchUpdate',token=token,method='POST',body=json.dumps({'requests':requests}).encode(),headers={'Content-Type':'application/json'})
    ranges=["'"+copied['sheet_title'].replace("'","''")+"'!"+cell for cell in values]
    if ranges:
        with measure('sheets.verify_values'):
            query=urlencode([('ranges',r) for r in ranges]+[('valueRenderOption','UNFORMATTED_VALUE')])
            read=sheets.read_json(base+'/values:batchGet?'+query,token).get('valueRanges',[])
            def first(item):
                rows=item.get('values') or [[]]
                return str(rows[0][0]) if rows[0] else ''
            if len(read)!=len(values) or any(first(item)!=str(expected) for item,expected in zip(read,values.values())):
                raise HTTPException(502,'Google chưa phản ánh đủ dữ liệu QC vừa ghi. Chưa lưu PDF; hãy thử lại.')
    obj=persist(db,obj.id,expected_revision=revision,step='export')
    # Export the full approved grid, including logos/drawings anchored beyond text cells.
    last_row=snap['row_count'];last_col=snap['column_count']
    content=export(token,temporary,gid,last_row,last_col)
    from app.modules.qc.pdf_signature import apply_signature
    return apply_signature(content,saved,marker,background)


@measure('sheets.cleanup_temp')
def cleanup(db,obj,token):
    from app.modules.qc.drive_bundle import JOB,call
    job=(obj.source or {}).get(JOB,{})
    identifier=job.get('temp_copy_id')
    if not identifier:return
    if identifier==obj.form_data['template']['spreadsheet_id']:
        raise HTTPException(409,'Không được dọn template gốc.')
    item=call(token,'/'+identifier,fields='id,parents,appProperties,trashed',missing=True)
    if item and not item.get('trashed'):
        if obj.drive_folder_id not in item.get('parents',[]) or item.get('appProperties',{}).get('qc_temp')!=job.get('temp_key'):
            raise HTTPException(409,'Bản sao tạm không thuộc thao tác hiện tại; không tự dọn file này.')
        call(token,'/'+identifier,method='PATCH',body={'trashed':True},fields='id')
    from app.modules.qc.evidence import locked
    current=locked(db,obj.id)
    if (current.source or {}).get(JOB,{}).get('temp_copy_id')==identifier:
        current.source={**current.source,JOB:{**current.source[JOB],'temp_copy_id':None,'temp_key':None,'temp_revision':None}}
    db.commit()
