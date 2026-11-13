"""QC-scoped Drive folders and resumable uploads; file metadata stays in Drive."""
import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit
import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from app.core.settings import get_setting
from app.integrations.google.oauth import access_token, google_json, cipher
from app.integrations.google.drive import BASE
from app.modules.qc.evidence import locked
from app.modules.qc.forms import document_id

FOLDER = 'application/vnd.google-apps.folder'
JOB = 'qc_bundle'
CHUNK_SIZE = 4 * 1024 * 1024


def call(token, path='', method=None, body=None, missing=False, **params):
    return google_json(BASE + path + '?' + urlencode({'supportsAllDrives':'true', **params}),
        token=token, method=method, body=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'}, allow_not_found=missing)


def folder(token, identifier):
    if not re.fullmatch(r'[\w-]{1,255}', identifier):
        raise HTTPException(422, 'Mã thư mục không hợp lệ.')
    item = call(token, '/' + identifier, fields='id,name,mimeType,parents,trashed,capabilities(canAddChildren)')
    if item.get('trashed') or item.get('mimeType') != FOLDER:
        raise HTTPException(422, 'Cần chọn thư mục Drive đang hoạt động; không chọn shortcut hoặc file.')
    return item


def in_scope(db, token, identifier, writable=False):
    root = get_setting(db, 'QC_ROOT_FOLDER_ID')
    if not root:
        raise HTTPException(503, 'Chưa cấu hình QC_ROOT_FOLDER_ID trong system_settings.')
    # Verify access to the configured root as well as every ancestor. Shortcuts
    # are never followed. Repeated at save and upload, not just in the picker.
    folder(token, root)
    item = folder(token, identifier)
    current = item
    seen = set()
    for _ in range(100):
        if current['id'] == root:
            if writable and not item.get('capabilities', {}).get('canAddChildren'):
                raise HTTPException(403, 'Tài khoản Google không có quyền thêm hồ sơ vào thư mục này.')
            return item
        if current['id'] in seen or not current.get('parents'):
            break
        seen.add(current['id'])
        current = folder(token, current['parents'][0])
    raise HTTPException(403, 'Thư mục được chọn nằm ngoài thư mục QC của công ty.')


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
            'parent_id':current.get('parents', [None])[0] if identifier != root else None,
            'items':page.get('files', []), 'next_page_token':page.get('nextPageToken', '')}


def generated_id(token):
    return google_json(BASE + '/generateIds?count=1&space=drive&type=files', token=token)['ids'][0]


def schedule(obj, user, parent):
    source = dict(obj.source or {})
    previous = source.get(JOB, {})
    source.pop('qc_evidence_task', None)
    job = {**previous, 'owner':user.id, 'pending':True, 'error':''}
    if not obj.drive_folder_id:
        job['parent'] = parent
    source[JOB] = job
    obj.source = source


def http(method, url, token, **kwargs):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com' or not parsed.path.startswith('/upload/drive/v3/files'):
        raise HTTPException(502, 'Địa chỉ phiên upload Drive không hợp lệ.')
    try:
        response = httpx.request(method, url, headers={'Authorization':'Bearer '+token, **kwargs.pop('headers', {})},
                                 timeout=120, follow_redirects=False, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(502, 'Kết nối upload Drive bị gián đoạn. Phiếu đã lưu; hãy thử lại.') from None
    if response.status_code not in (200, 201, 308):
        if method == 'PUT' and response.status_code in (404, 410):
            raise HTTPException(410, 'Phiên upload đã hết hạn. Hãy thử lại để mở phiên mới.')
        raise HTTPException(502, 'Upload Drive chưa thành công (HTTP '+str(response.status_code)+'). Phiếu QC đã lưu.')
    return response


def upload_pdf(token, identifier, content):
    url = 'https://www.googleapis.com/upload/drive/v3/files/' + identifier + '?uploadType=media&supportsAllDrives=true'
    http('PATCH', url, token, content=content, headers={'Content-Type':'application/pdf'})


def prepare(db, user, identifier):
    obj = locked(db, identifier)
    job = dict((obj.source or {}).get(JOB) or {})
    if not obj.form_data:
        db.commit()
        raise HTTPException(422, 'Phiếu lịch sử chưa có biểu mẫu ERP đã ký.')
    try:
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
            call(token, method='POST', body={'id':obj.drive_folder_id,'name':obj.id,'mimeType':FOLDER,'parents':[parent]}, fields='id')
        in_scope(db, token, obj.drive_folder_id, writable=True)
        job.pop('parent', None)
        if not job.get('pdf_id'):
            job['pdf_id'] = generated_id(token)
        obj.source = {**(obj.source or {}), JOB:job}
        db.commit()
        obj = locked(db, identifier)
        job = dict((obj.source or {}).get(JOB) or {})
        revision = hashlib.sha256(json.dumps(obj.form_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if job.get('pdf_revision') != revision:
            from app.modules.qc.pdf import render_pdf
            content = render_pdf(obj)
            pdf = call(token, '/' + job['pdf_id'], missing=True, fields='id,parents,trashed')
            if pdf is None:
                call(token, method='POST', body={'id':job['pdf_id'],'name':document_id(obj.id)+'.pdf','mimeType':'application/pdf','parents':[obj.drive_folder_id]}, fields='id')
            elif pdf.get('trashed') or obj.drive_folder_id not in pdf.get('parents', []):
                raise HTTPException(409, 'PDF đã bị di chuyển hoặc xóa. Cần khôi phục file trong thư mục QC trước khi thử lại.')
            upload_pdf(token, job['pdf_id'], content)
            job['pdf_revision'] = revision
        job.update(pending=False, error='')
        obj.source = {**(obj.source or {}), JOB:job}
        db.commit()
    except Exception as error:
        db.rollback()
        obj = locked(db, identifier)
        current = dict((obj.source or {}).get(JOB) or {})
        message = str(error.detail) if isinstance(error, HTTPException) else 'Chưa xuất/upload được PDF. Hãy thử lại trên phiếu đã lưu.'
        if isinstance(error, ImportError):
            message = 'Chưa cài thư viện PDF cho backend. Cần ReportLab và font DejaVu Sans.'
        current.update(pending=True, error=message)
        obj.source = {**(obj.source or {}), JOB:current}
        db.commit()
    return obj


def start_upload(db, user, obj, data):
    token = access_token(db, user)
    if not obj.drive_folder_id:
        raise HTTPException(409, 'Hãy thử tạo thư mục bằng chứng trước khi upload.')
    in_scope(db, token, obj.drive_folder_id, writable=True)
    if (obj.source or {}).get(JOB, {}).get('pending'):
        raise HTTPException(409, 'Hãy hoàn tất PDF trước khi upload bằng chứng.')
    key = hashlib.sha256(json.dumps([obj.id,data.name,data.size,data.modified], ensure_ascii=False).encode()).hexdigest()
    found = call(token, q=f"'{obj.drive_folder_id}' in parents and trashed = false and appProperties has {{ key='qc_upload' and value='{key}' }}",
                 fields='files(id)', pageSize=1, includeItemsFromAllDrives='true')
    if found.get('files'):
        return {'complete':True,'offset':data.size}
    file_id = generated_id(token)
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
              'user':user.id,'size':data.size,'mime':data.mime}).encode()).decode()
    db.commit()
    return {'complete':False,'offset':0,'ticket':ticket,'chunk_size':CHUNK_SIZE}


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
    response = http('PUT', state['url'], token, content=content,
                    headers={'Content-Type':state['mime'],'Content-Range':range_header})
    db.commit()
    if response.status_code in (200, 201):
        return {'complete':True,'offset':total}
    match = re.fullmatch(r'bytes=0-(\d+)', response.headers.get('Range',''))
    return {'complete':False,'offset':int(match.group(1))+1 if match else 0}
