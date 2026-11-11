from datetime import datetime
import json
import re
import secrets
from zoneinfo import ZoneInfo
import urllib.parse
from fastapi import HTTPException
from app.integrations.google.oauth import access_token, google_json
from app.core.config import LEGACY_CONFIG as CONFIG

BASE='https://www.googleapis.com/drive/v3/files'


def search(db,user,keyword):
    keyword=str(keyword or '').strip()
    if not keyword:return {'success':True,'files':[]}
    try:
        token=access_token(db,user)
        fields='id,name,webViewLink,mimeType,size,modifiedTime,trashed,resourceKey'
        if re.match(r'^https://(?:drive|docs)\.google\.com/',keyword):
            match=re.search(r'/d/([\w-]+)',keyword) or re.search(r'[?&]id=([\w-]+)',keyword)
            if not match:raise HTTPException(422,'Vui lòng dán liên kết tới một tệp cụ thể.')
            identifier=match.group(1);key=re.search(r'[?&]resourcekey=([\w-]+)',keyword,re.I)
            headers={'X-Goog-Drive-Resource-Keys':identifier+'/'+key.group(1)} if key else {}
            matches=[google_json(BASE+'/'+identifier+'?'+urllib.parse.urlencode({'supportsAllDrives':'true','fields':fields}),token=token,headers=headers)]
            incomplete=False
        else:
            literal=lambda value:"'"+value.replace('\\','\\\\').replace("'","\\'")+"'"
            conditions=['name contains '+literal(keyword),'fullText contains '+literal(keyword)]
            terms=re.findall(r'[^\W_]+',keyword,re.UNICODE)
            if 1<len(terms)<=8:conditions.append('('+' and '.join('fullText contains '+literal(x) for x in terms)+')')
            params={'q':"trashed = false and mimeType != 'application/vnd.google-apps.folder' and ("+' or '.join(conditions)+')',
                    'corpora':'allDrives','spaces':'drive','supportsAllDrives':'true','includeItemsFromAllDrives':'true',
                    'orderBy':'modifiedTime desc','pageSize':20,'fields':'nextPageToken,incompleteSearch,files('+fields+')'}
            matches=[];incomplete=False
            while True:
                page=google_json(BASE+'?'+urllib.parse.urlencode(params),token=token)
                matches+=page.get('files',[]);incomplete|=bool(page.get('incompleteSearch'))
                if not page.get('nextPageToken') or len(matches)>=20:break
                params['pageToken']=page['nextPageToken']
        files=[]
        for f in matches[:20]:
            if f.get('trashed') or f.get('mimeType')=='application/vnd.google-apps.folder':continue
            url=f.get('webViewLink') or 'https://drive.google.com/open?id='+f['id']
            if f.get('resourceKey') and 'resourcekey=' not in url.lower():url+=('&' if '?' in url else '?')+'resourcekey='+urllib.parse.quote(f['resourceKey'])
            files.append({'id':f['id'],'name':f['name'],'url':url,'mimeType':f.get('mimeType',''),'size':int(f.get('size',0)),
                          'updated':datetime.fromisoformat(f['modifiedTime'].replace('Z','+00:00')).astimezone(ZoneInfo(CONFIG['TIMEZONE'])).strftime('%d/%m/%Y') if f.get('modifiedTime') else ''})
        return {'success':True,'files':files,'incomplete':incomplete}
    except HTTPException as error:return {'success':False,'files':[],'error':error.detail}


def upload(db,user,name,mime,content):
    token=access_token(db,user)
    boundary='napaco_'+secrets.token_hex(20)
    if not re.fullmatch(r'[\w.+-]+/[\w.+-]+',mime):mime='application/octet-stream'
    metadata={'name':name,'parents':[CONFIG['ID_STORAGES']]}
    body=(('--'+boundary+'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode()+json.dumps(metadata,ensure_ascii=False).encode()+
          ('\r\n--'+boundary+'\r\nContent-Type: '+mime+'\r\n\r\n').encode()+content+('\r\n--'+boundary+'--\r\n').encode())
    result=google_json('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,webViewLink',
                       token=token,body=body,headers={'Content-Type':'multipart/related; boundary='+boundary})
    return {'id':result['id'],'url':result.get('webViewLink') or 'https://drive.google.com/open?id='+result['id']}


def undo_upload(db,user,identifier):
    # Compensation only for an ID created by this exact failed local transaction.
    token=access_token(db,user)
    google_json(BASE+'/'+identifier+'?supportsAllDrives=true',token=token,method='PATCH',body=b'{"trashed":true}',headers={'Content-Type':'application/json'})
