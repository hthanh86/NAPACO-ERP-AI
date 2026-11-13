"""QC-scoped Drive folders and resumable uploads; file metadata stays in Drive."""
import hashlib
import json
import re
import logging
import traceback
from urllib.parse import urlencode, urlsplit
import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from app.core.settings import get_setting
from app.integrations.google.oauth import access_token, google_json, cipher
from app.integrations.google.drive import BASE
from app.modules.qc.evidence import locked
from app.modules.qc.forms import document_id
from app.core.performance import measure, record, trace_id

FOLDER = 'application/vnd.google-apps.folder'
JOB = 'qc_bundle'
CHUNK_SIZE = 4 * 1024 * 1024


def call(token, path='', method=None, body=None, missing=False, **params):
    operation = 'drive.files_list' if not path and not body else 'drive.files_create' if method == 'POST' else 'drive.files_metadata'
    with measure(operation):
        return google_json(BASE + path + '?' + urlencode({'supportsAllDrives':'true', **params}),
            token=token, method=method, body=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json'}, allow_not_found=missing)


@measure('drive.folder_metadata')
def folder(token, identifier):
    if not re.fullmatch(r'[\w-]{1,255}', identifier):
        raise HTTPException(422, 'Mã thư mục không hợp lệ.')
    item = call(token, '/' + identifier, fields='id,name,mimeType,parents,trashed,capabilities(canAddChildren)')
    if item.get('trashed') or item.get('mimeType') != FOLDER:
        raise HTTPException(422, 'Cần chọn thư mục Drive đang hoạt động; không chọn shortcut hoặc file.')
    return item


@measure('drive.verify_scope')
def in_scope(db, token, identifier, writable=False):
    root = get_setting(db, 'QC_ROOT_FOLDER_ID')
    if not root:
        raise HTTPException(503, 'Chưa cấu hình QC_ROOT_FOLDER_ID trong system_settings.')
    # Verify access to the configured root as well as every ancestor. Shortcuts
    # are never followed. Repeated at save and upload, not just in the picker.
    folder(token, root)
    item = folder(token, identifier)
    current = item
    path = []
    seen = set()
    for _ in range(100):
        path.append({'id':current['id'],'name':current['name']})
        if current['id'] == root:
            if writable and not item.get('capabilities', {}).get('canAddChildren'):
                raise HTTPException(403, 'Tài khoản Google không có quyền thêm hồ sơ vào thư mục này.')
            return {**item,'breadcrumb':list(reversed(path))}
        if current['id'] in seen or not current.get('parents'):
            break
        seen.add(current['id'])
        current = folder(token, current['parents'][0])
    raise HTTPException(403, 'Thư mục được chọn nằm ngoài thư mục QC của công ty.')


@measure('drive.browse')
def browse(db, user, identifier=None, page_token=''):
    token = access_token(db, user)
    root = get_setting(db, 'QC_ROOT_FOLDER_ID')
    identifier = identifier or root
    current = in_scope(db, token, identifier)
    params = {'q':f"'{identifier}' in parents and trashed = false and mimeType = '{FOLDER}'",
              'pageSize':50, 'orderBy':'name', 'includeItemsFromAllDrives':'true',
              'fields':'nextPageToken,files(id,name)'}
    if page_token:
        params['pageToken'] = page_token
    page = call(token, **params)
    db.commit()
    return {'root_id':root, 'current':{'id':current['id'],'name':current['name']},
            'breadcrumb':current['breadcrumb'],
            'parent_id':current.get('parents', [None])[0] if identifier != root else None,
            'items':page.get('files', []), 'next_page_token':page.get('nextPageToken', '')}


@measure('drive.generate_id')
def generated_id(token):
    return google_json(BASE + '/generateIds?count=1&space=drive&type=files', token=token)['ids'][0]


def upload_key(identifier, data):
    return hashlib.sha256(json.dumps([identifier,data.name,data.size,data.modified], ensure_ascii=False).encode()).hexdigest()


def schedule(obj, user, parent, manifest=()):
    source = dict(obj.source or {})
    previous = source.get(JOB, {})
    source.pop('qc_evidence_task', None)
    job = {**previous, 'owner':user.id, 'pending':True, 'error':''}
    job['expected_uploads'] = sorted(set(previous.get('expected_uploads', [])) | {upload_key(obj.id, item) for item in manifest})
    job.setdefault('completed_uploads', [])
    job['step'] = 'folder'
    if not obj.drive_folder_id:
        job['parent'] = parent
    source[JOB] = job
    obj.source = source


def complete_upload(db, identifier, key):
    obj = locked(db, identifier)
    job = dict((obj.source or {}).get(JOB) or {})
    job['completed_uploads'] = sorted(set(job.get('completed_uploads', [])) | {key})
    job['step'] = 'complete' if not job.get('pending') and not (set(job.get('expected_uploads', [])) - set(job['completed_uploads'])) else 'evidence'
    obj.source = {**(obj.source or {}), JOB:job}
    db.commit()


def plan_uploads(db,user,identifier,files):
    obj=locked(db,identifier)
    job=dict((obj.source or {}).get(JOB) or {})
    job['expected_uploads']=sorted(set(job.get('expected_uploads',[])) | {upload_key(obj.id,item) for item in files})
    job.setdefault('completed_uploads',[])
    job['step']='evidence' if set(job['expected_uploads'])-set(job['completed_uploads']) else job.get('step','complete')
    obj.source={**(obj.source or {}),JOB:job}
    db.commit()
    return obj


@measure('drive.download_pdf')
def download_pdf(db,user,obj):
    job=(obj.source or {}).get(JOB,{})
    revision=hashlib.sha256(json.dumps(obj.form_data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if job.get('pending') or job.get('pdf_revision')!=revision or not job.get('pdf_id'):
        raise HTTPException(409,'PDF chưa hoàn tất cho phiên bản nội dung hiện tại. Hãy hoàn thiện hồ sơ/thử lại.')
    token=access_token(db,user)
    in_scope(db,token,obj.drive_folder_id)
    item=call(token,'/'+job['pdf_id'],fields='id,parents,mimeType,trashed')
    if item.get('trashed') or obj.drive_folder_id not in item.get('parents',[]) or item.get('mimeType')!='application/pdf':
        raise HTTPException(409,'PDF đã bị xóa/di chuyển hoặc không đúng định dạng.')
    try:
        with httpx.stream('GET',BASE+'/'+job['pdf_id']+'?alt=media&supportsAllDrives=true',
                          headers={'Authorization':'Bearer '+token},timeout=60) as response:
            if response.status_code!=200:raise HTTPException(502,'Không tải được PDF từ Drive.')
            content=bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content)>25*1024*1024:raise HTTPException(413,'PDF vượt giới hạn 25 MiB.')
    except httpx.HTTPError:
        raise HTTPException(502,'Kết nối tải PDF bị gián đoạn.') from None
    db.commit()
    if not content.startswith(b'%PDF-'):raise HTTPException(502,'Drive không trả về PDF hợp lệ.')
    return bytes(content)


@measure('drive.upload_http')
def http(method, url, token, **kwargs):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com' or not parsed.path.startswith('/upload/drive/v3/files'):
        raise HTTPException(502, 'Địa chỉ phiên upload Drive không hợp lệ.')
    try:
        with measure('drive.upload_transport', bytes=len(kwargs.get('content') or b''), method=method):
            with measure('google.http_request'):
                response = httpx.request(method, url, headers={'Authorization':'Bearer '+token, **kwargs.pop('headers', {})},
                                         timeout=120, follow_redirects=False, **kwargs)
        record('drive.upload_response', 0, ok=response.status_code in (200,201,308), status=response.status_code)
    except httpx.HTTPError:
        raise HTTPException(502, 'Kết nối upload Drive bị gián đoạn. Phiếu đã lưu; hãy thử lại.') from None
    if response.status_code not in (200, 201, 308):
        if method == 'PUT' and response.status_code in (404, 410):
            raise HTTPException(410, 'Phiên upload đã hết hạn. Hãy thử lại để mở phiên mới.')
        raise HTTPException(502, 'Upload Drive chưa thành công (HTTP '+str(response.status_code)+'). Phiếu QC đã lưu.')
    return response


@measure('drive.upload_pdf')
def upload_pdf(token, identifier, content):
    url = 'https://www.googleapis.com/upload/drive/v3/files/' + identifier + '?uploadType=media&supportsAllDrives=true'
    http('PATCH', url, token, content=content, headers={'Content-Type':'application/pdf'})


@measure('drive.prepare_bundle')
def prepare(db, user, identifier, progress=None):
    obj = locked(db, identifier)
    job = dict((obj.source or {}).get(JOB) or {})
    if not obj.form_data and not (obj.drive_folder_id or job.get('parent')):
        db.commit()
        raise HTTPException(422, 'Phiếu lịch sử chưa có biểu mẫu ERP đã ký.')
    try:
        if progress:progress('folder')
        token = access_token(db, user)
        if not obj.drive_folder_id:
            in_scope(db, token, job.get('parent') or '', writable=True)
            obj.drive_folder_id = generated_id(token)
            obj.source = {**(obj.source or {}), JOB:job}
            db.commit()  # Persist the ID before creating anything externally.
            obj = locked(db, identifier)
            job = dict((obj.source or {}).get(JOB) or {})
        existing = call(token, '/' + obj.drive_folder_id, missing=True, fields='id,mimeType,trashed,parents')
        if existing is None:
            parent = job.get('parent')
            in_scope(db, token, parent or '', writable=True)
            with measure('drive.create_qc_folder'):
                call(token, method='POST', body={'id':obj.drive_folder_id,'name':obj.id,'mimeType':FOLDER,'parents':[parent]}, fields='id')
        in_scope(db, token, obj.drive_folder_id, writable=True)
        job.pop('parent', None)
        if not obj.form_data:
            job.update(pending=False,error='',step='evidence' if set(job.get('expected_uploads',[]))-set(job.get('completed_uploads',[])) else 'complete')
            obj.source={**(obj.source or {}),JOB:job};db.commit()
            return obj  # Historical records without a form can receive evidence; no fabricated PDF.
        if not job.get('pdf_id'):
            job['pdf_id'] = generated_id(token)
        obj.source = {**(obj.source or {}), JOB:dict(job)}
        db.commit()
        obj = locked(db, identifier)
        job = dict((obj.source or {}).get(JOB) or {})
        revision = hashlib.sha256(json.dumps(obj.form_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if job.get('pdf_revision') != revision:
            job['step'] = 'pdf'
            # Keep the local mutable job separate from SQLAlchemy's JSON value.
            # Otherwise later updates can look unchanged and never reach MySQL.
            obj.source = {**(obj.source or {}), JOB:dict(job)}
            db.commit()
            if obj.template_id:
                from app.modules.qc.sheets_pdf import render
                content = render(db, user, obj, token,progress=progress)
                obj = locked(db, identifier)
                job = dict((obj.source or {}).get(JOB) or {})
                if hashlib.sha256(json.dumps(obj.form_data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=revision:
                    raise HTTPException(409,'Nội dung phiếu đã thay đổi khi đang xuất PDF. Hãy thử lại với bản vừa ký.')
            else:
                from app.modules.qc.pdf import render_pdf
                content = render_pdf(obj)
            pdf = call(token, '/' + job['pdf_id'], missing=True, fields='id,parents,trashed')
            if pdf is None:
                name = obj.id + '_Bien_Ban_Kiem_Tra.pdf' if obj.template_id else document_id(obj.id)+'.pdf'
                call(token, method='POST', body={'id':job['pdf_id'],'name':name,'mimeType':'application/pdf','parents':[obj.drive_folder_id]}, fields='id')
            elif pdf.get('trashed') or obj.drive_folder_id not in pdf.get('parents', []):
                raise HTTPException(409, 'PDF đã bị di chuyển hoặc xóa. Cần khôi phục file trong thư mục QC trước khi thử lại.')
            if progress:progress('upload_pdf')
            upload_pdf(token, job['pdf_id'], content)
            job['pdf_revision'] = revision
        job.update(pending=False, error='', step='evidence' if set(job.get('expected_uploads',[]))-set(job.get('completed_uploads',[])) else 'complete')
        obj.source = {**(obj.source or {}), JOB:job}
        db.commit()
        if obj.template_id:
            from app.modules.qc.sheets_pdf import cleanup
            cleanup(db, obj, token)
    except Exception as error:
        # Keep a useful stack location without exception text, tokens or payloads.
        frames=traceback.extract_tb(error.__traceback__)
        logging.getLogger('uvicorn.error').error('QC_BUNDLE_ERROR trace=%s type=%s frames=%s',
            trace_id(), type(error).__name__, ';'.join(f'{frame.name}:{frame.lineno}' for frame in frames))
        db.rollback()
        obj = locked(db, identifier)
        current = dict((obj.source or {}).get(JOB) or {})
        message = str(error.detail) if isinstance(error, HTTPException) else 'Chưa xuất/upload được PDF. Hãy thử lại trên phiếu đã lưu.'
        if isinstance(error, ImportError):
            message = 'Chưa cài thư viện PDF cho backend. Cần ReportLab và font DejaVu Sans.'
        current.update(pending=True, error=message, error_status=error.status_code if isinstance(error,HTTPException) else 500)
        obj.source = {**(obj.source or {}), JOB:current}
        db.commit()
    pending = bool((obj.source or {}).get(JOB, {}).get('pending'))
    record('drive.bundle_result', 0, ok=not pending, pending=pending)
    return obj


@measure('drive.start_upload')
def start_upload(db, user, obj, data, file_id=None):
    token = access_token(db, user)
    if not obj.drive_folder_id:
        raise HTTPException(409, 'Hãy thử tạo thư mục bằng chứng trước khi upload.')
    in_scope(db, token, obj.drive_folder_id, writable=True)
    if (obj.source or {}).get(JOB, {}).get('pending'):
        raise HTTPException(409, 'Hãy hoàn tất PDF trước khi upload bằng chứng.')
    key = upload_key(obj.id, data)
    found = call(token, q=f"'{obj.drive_folder_id}' in parents and trashed = false and appProperties has {{ key='qc_upload' and value='{key}' }}",
                 fields='files(id)', pageSize=1, includeItemsFromAllDrives='true')
    if found.get('files'):
        complete_upload(db, obj.id, key)
        return {'complete':True,'offset':data.size}
    file_id = file_id or generated_id(token)
    url = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true'
    response = http('POST', url, token, json={'id':file_id,'name':data.name,'parents':[obj.drive_folder_id],
                    'appProperties':{'qc_upload':key}}, headers={'X-Upload-Content-Type':data.mime,
                    'X-Upload-Content-Length':str(data.size)})
    session = response.headers.get('Location', '')
    # Validate before returning even an encrypted ticket.
    parsed = urlsplit(session)
    if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com' or not parsed.path.startswith('/upload/drive/v3/files'):
        raise HTTPException(502, 'Google không trả về phiên upload hợp lệ.')
    ticket = cipher().encrypt(json.dumps({'url':session,'qc':obj.id,'folder':obj.drive_folder_id,
              'user':user.id,'size':data.size,'mime':data.mime,'key':key}).encode()).decode()
    db.commit()
    return {'complete':False,'offset':0,'ticket':ticket,'chunk_size':CHUNK_SIZE}


@measure('drive.upload_chunk')
def upload_chunk(db, user, obj, ticket, offset, content, probe=False):
    try:
        state = json.loads(cipher().decrypt(ticket.encode(), ttl=7*24*3600))
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(422, 'Phiên upload không hợp lệ hoặc hết hạn. Hãy chọn lại file.') from None
    if state['qc'] != obj.id or state['folder'] != obj.drive_folder_id or state['user'] != user.id:
        raise HTTPException(403, 'Phiên upload không thuộc phiếu hoặc tài khoản này.')
    token = access_token(db, user)
    in_scope(db, token, obj.drive_folder_id, writable=True)
    total = state['size']
    if probe:
        range_header = 'bytes */'+str(total)
    else:
        if offset < 0 or not content or len(content) > CHUNK_SIZE or offset+len(content)>total:
            raise HTTPException(422, 'Đoạn upload không hợp lệ.')
        if offset+len(content)<total and len(content) % (256*1024):
            raise HTTPException(422, 'Đoạn upload giữa file phải là bội số 256 KiB.')
        range_header = f'bytes {offset}-{offset+len(content)-1}/{total}'
    record('drive.upload_chunk_info', 0, bytes=len(content), total_bytes=total, offset=offset, probe=probe)
    response = http('PUT', state['url'], token, content=content,
                    headers={'Content-Type':state['mime'],'Content-Range':range_header})
    db.commit()
    if response.status_code in (200, 201):
        if state.get('key'):
            complete_upload(db, obj.id, state['key'])
        return {'complete':True,'offset':total}
    match = re.fullmatch(r'bytes=0-(\d+)', response.headers.get('Range',''))
    return {'complete':False,'offset':int(match.group(1))+1 if match else 0}
