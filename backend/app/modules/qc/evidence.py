"""Resumable Drive work after the QC transaction has committed.

The generated folder ID is persisted before creation. Retrying a timed-out
request therefore reuses the same folder instead of creating another one.
"""
import json
import re
from urllib.parse import urlsplit, parse_qs, urlencode
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from app.integrations.google.drive import BASE
from app.integrations.google.oauth import access_token, google_json
from app.modules.qc.models import QualityCheck
from app.core.performance import measure

FOLDER = 'application/vnd.google-apps.folder'
TASK = 'qc_evidence_task'


def reference(url):
    parsed = urlsplit(url)
    if parsed.hostname not in {'drive.google.com', 'docs.google.com'}:
        return None  # Keep support for existing non-Drive evidence URLs.
    match = re.search(r'/(?:folders|d)/([\w-]+)(?:/|$)', parsed.path)
    params = parse_qs(parsed.query)
    identifier = match.group(1) if match else params.get('id', [''])[0]
    if not re.fullmatch(r'[\w-]+', identifier):
        raise HTTPException(422, 'Bằng chứng: hãy dùng liên kết đến một file hoặc thư mục Google Drive cụ thể.')
    resource_key = next((values[0] for key, values in params.items() if key.lower() == 'resourcekey'), '')
    if resource_key and not re.fullmatch(r'[\w-]+', resource_key):
        raise HTTPException(422, 'Resource key của bằng chứng Google Drive không hợp lệ.')
    return identifier, resource_key


def schedule(obj, user):
    source = dict(obj.source or {})
    previous = source.get(TASK)
    if previous and previous['url'] == obj.image_url:
        return
    source.pop(TASK, None)
    if obj.image_url and reference(obj.image_url):
        source[TASK] = {'operation': uuid4().hex, 'url': obj.image_url, 'user_id': user.id}
    obj.source = source


def locked(db, identifier):
    return db.scalar(select(QualityCheck).where(QualityCheck.id == identifier)
                     .with_for_update().execution_options(populate_existing=True))


def save_task(obj, task):
    obj.source = {**(obj.source or {}), TASK: task}


@measure('drive.process_legacy_evidence')
def process(db, user, identifier):
    obj = locked(db, identifier)
    task = dict((obj.source or {}).get(TASK) or {})
    if not task:
        db.commit()
        return
    if task.get('user_id') != user.id:
        task['error'] = 'Hãy thử lại bằng tài khoản đã gửi liên kết Drive, hoặc thay bằng liên kết bằng chứng khác.'
        save_task(obj, task)
        db.commit()
        return
    operation = task['operation']
    try:
        token = access_token(db, user)
        file_id, resource_key = reference(task['url'])
        headers = {'Content-Type': 'application/json'}
        if resource_key:
            headers['X-Goog-Drive-Resource-Keys'] = file_id + '/' + resource_key

        def call(path='', method=None, body=None, missing=False, **params):
            params = {'supportsAllDrives': 'true', **params}
            return google_json(BASE + path + '?' + urlencode(params), token=token, method=method,
                               body=json.dumps(body).encode() if body is not None else None,
                               headers=headers, allow_not_found=missing)

        item = call('/' + file_id, fields='id,name,mimeType,parents,trashed,resourceKey')
        if item.get('trashed'):
            raise HTTPException(422, 'File hoặc thư mục bằng chứng đang trong thùng rác.')
        if item['mimeType'] == FOLDER:
            if re.fullmatch(r'QC_\d{6}_\d{2}', item['name']) and item['name'] != obj.id:
                raise HTTPException(422, 'Thư mục đang mang mã phiếu ' + item['name'] + '. Hãy dùng thư mục riêng cho phiếu này.')
            if item['name'] != obj.id:
                call('/' + file_id, method='PATCH', body={'name': obj.id}, fields='id')
            folder_id = file_id
            folder_key = item.get('resourceKey') or resource_key
        else:
            if not task.get('folder_id'):
                # Preallocated IDs support retry even if files.create succeeded
                # on Google but the HTTP response was lost.
                generated = google_json(BASE + '/generateIds?' + urlencode({'count': 1, 'space': 'drive', 'type': 'files'}), token=token)
                task.update(folder_id=generated['ids'][0], parents=item.get('parents', []))
                save_task(obj, task)
                db.commit()
                obj = locked(db, identifier)
                if ((obj.source or {}).get(TASK) or {}).get('operation') != operation:
                    db.commit()
                    return
            folder_id = task['folder_id']
            folder = call('/' + folder_id, missing=True, fields='id,name,mimeType,trashed,resourceKey')
            if folder is None:
                body = {'id': folder_id, 'name': obj.id, 'mimeType': FOLDER}
                if task['parents']:
                    body['parents'] = task['parents']
                folder = call(method='POST', body=body, fields='id,resourceKey')
            elif folder.get('trashed') or folder.get('mimeType') != FOLDER:
                raise HTTPException(422, 'Thư mục bằng chứng đã thay đổi hoặc bị chuyển vào thùng rác.')
            elif folder['name'] != obj.id:
                call('/' + folder_id, method='PATCH', body={'name': obj.id}, fields='id')
            # Re-read parents: a previous timed-out move may already have worked.
            item = call('/' + file_id, fields='id,parents')
            parents = item.get('parents', [])
            if folder_id not in parents:
                params = {'addParents': folder_id}
                if parents:
                    params['removeParents'] = ','.join(parents)
                call('/' + file_id, method='PATCH', body={}, fields='id,parents', **params)
            folder_key = folder.get('resourceKey', '')
        obj.image_url = 'https://drive.google.com/drive/folders/' + folder_id
        if folder_key:
            obj.image_url += '?' + urlencode({'resourcekey': folder_key})
        source = dict(obj.source or {})
        source.pop(TASK, None)
        obj.source = source
        db.commit()
    except Exception as error:
        # QC is already saved. Keep the durable task for the next Save/retry;
        # never claim that the user needs to create the QC again.
        db.rollback()
        obj = locked(db, identifier)
        current = dict((obj.source or {}).get(TASK) or {})
        if current.get('operation') == operation:
            current['error'] = str(error.detail) if isinstance(error, HTTPException) else 'Chưa hoàn tất xử lý Drive. Hãy thử lưu lại phiếu.'
            save_task(obj, current)
        db.commit()
