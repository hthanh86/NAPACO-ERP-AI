from datetime import datetime,timedelta
import secrets
import urllib.parse
from cryptography.fernet import Fernet
from sqlalchemy import select,func
from fastapi import HTTPException
from app.auth.models import User
from app.modules.orders.models import Order
from app.integrations.google.models import GoogleCredential
from app.integrations.google import oauth as google_oauth, drive as google_drive
from app.compatibility import api as legacy_api
from test_legacy import RPC,web_order


def setup_google(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','test.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('GOOGLE_TOKEN_KEY',Fernet.generate_key().decode())


def test_oauth_state_email_allowlist_and_encrypted_token_storage(clients,monkeypatch):
    client,_,conn=clients;setup_google(monkeypatch)
    assert client.get('/auth/google/callback?state=bad&code=bad').status_code==400
    conn.execute(User.__table__.update().where(User.id=='_TEST_READER').values(email='reader@example.test'))
    response=client.get('/auth/google/start?next=%2F%3Fview%3Dfilm-stock',follow_redirects=False)
    assert response.status_code==303
    params=urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers['location']).query)
    assert params['code_challenge_method']==['S256']
    assert params['redirect_uri']==[google_oauth.REDIRECT]
    assert 'https://www.googleapis.com/auth/drive' in params['scope'][0]
    state=params['state'][0]
    def fake(url,**kwargs):
        if url.endswith('/token'):return {'access_token':'secret-access-test','refresh_token':'secret-refresh-test','expires_in':3600,'scope':google_oauth.SCOPES}
        return {'sub':'google-subject-test','email':'reader@example.test','email_verified':True}
    monkeypatch.setattr(google_oauth,'google_json',fake)
    result=client.get('/auth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'test-code'}),follow_redirects=False)
    assert result.status_code==303,result.text
    assert result.headers['location']=='/?view=film-stock'
    session_cookie=next(cookie for cookie in result.headers.get_list('set-cookie') if cookie.startswith('napaco_session='))
    assert 'SameSite=lax' in session_cookie
    assert 'HttpOnly' in session_cookie
    assert 'Path=/' in session_cookie
    assert client.get('/api/me').json()['id']=='_TEST_READER'
    encrypted=conn.execute(select(GoogleCredential.encrypted_access).where(GoogleCredential.user_id=='_TEST_READER')).scalar_one()
    assert 'secret-access-test' not in encrypted
    assert Fernet(google_oauth.os.environ['GOOGLE_TOKEN_KEY'].encode()).decrypt(encrypted.encode())==b'secret-access-test'
    assert client.get('/auth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'test-code'}),follow_redirects=False).status_code==400


def test_oauth_rejects_unlisted_employee(clients,monkeypatch):
    client,_,conn=clients;setup_google(monkeypatch)
    before=conn.scalar(select(func.count()).select_from(GoogleCredential))
    response=client.get('/auth/google/start',follow_redirects=False)
    state=urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers['location']).query)['state'][0]
    monkeypatch.setattr(google_oauth,'google_json',lambda url,**kw:{'access_token':'x','expires_in':3600} if url.endswith('/token') else
                        {'sub':'other','email':'not-an-employee@example.test','email_verified':True})
    result=client.get('/auth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'test-code'}),follow_redirects=False)
    assert result.status_code==403
    assert conn.scalar(select(func.count()).select_from(GoogleCredential))==before


def fake_credential(conn):
    conn.execute(GoogleCredential.__table__.insert().values(user_id='_TEST_ADMIN',subject='test',encrypted_access='fake',
        encrypted_refresh='fake',expires_at=datetime.utcnow()+timedelta(hours=1),scopes=google_oauth.SCOPES))


def test_original_upload_staging_and_url_persistence(clients,monkeypatch):
    client,_,conn=clients;fake_credential(conn)
    monkeypatch.setattr(legacy_api,'configured',lambda:True)
    calls=[]
    def upload(db,user,name,mime,data):
        calls.append((name,mime,data));return {'id':'test-file','url':'https://drive.google.com/file/d/test-file/view'}
    monkeypatch.setattr(google_drive,'upload',upload)
    rpc=RPC(client);rpc.call('getOrderFormData');payload=web_order()
    payload['poGroups'][0]['fileData']={'fileName':'test.pdf','mimeType':'application/pdf','base64':'dGVzdA=='}
    saved=rpc.call('saveOrderTransaction',payload)
    oid=saved['createdOrders'][0]['maDH']
    assert calls[0][2]==b'test'
    assert conn.execute(select(Order.file_url).where(Order.id==oid)).scalar_one()=='https://drive.google.com/file/d/test-file/view'
    assert not conn.execute(select(Order.file_url).where(Order.file_url.like('napaco-upload:%'))).all()


def test_upload_failure_compensates_only_files_created_in_that_transaction(clients,monkeypatch):
    client,_,conn=clients;fake_credential(conn)
    monkeypatch.setattr(legacy_api,'configured',lambda:True)
    called=[];undone=[]
    def upload(db,user,name,mime,data):
        called.append(name)
        if len(called)==2:raise HTTPException(502,'Upload failed in test')
        return {'id':'created-by-this-transaction','url':'https://drive.google.com/file/d/created/view'}
    monkeypatch.setattr(google_drive,'upload',upload)
    monkeypatch.setattr(google_drive,'undo_upload',lambda db,user,identifier:undone.append(identifier))
    rpc=RPC(client);rpc.call('getOrderFormData');before=conn.scalar(select(func.count()).select_from(Order))
    payload=web_order();payload['poGroups'].append(web_order('SECOND-TEST')['poGroups'][0])
    for group in payload['poGroups']:group['fileData']={'fileName':'test.pdf','mimeType':'application/pdf','base64':'dGVzdA=='}
    response=client.post('/api/legacy/saveOrderTransaction',json={'args':[payload],'revision':rpc.revision,'request_id':secrets.token_hex(16)})
    assert response.status_code==502
    assert undone==['created-by-this-transaction']
    assert conn.scalar(select(func.count()).select_from(Order))==before
