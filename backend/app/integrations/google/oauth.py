import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
import urllib.request
import urllib.error
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select, delete
from app.core.database import get_db
from app.auth.models import User, LoginSession
from app.integrations.google.models import GoogleCredential, GoogleOAuthState
from app.auth.security import token_hash
from app.auth.access import safe_next

router=APIRouter()
REDIRECT='http://127.0.0.1:8000/auth/google/callback'
SCOPES='openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/drive'


def configured():
    return all(os.environ.get(k) for k in ['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_TOKEN_KEY'])


def cipher():
    if not configured():raise HTTPException(503,'Chưa cấu hình Google OAuth. Xem file Hướng dẫn kết nối Google và Drive trong thư mục dự án.')
    return Fernet(os.environ['GOOGLE_TOKEN_KEY'].encode())


def google_json(url,form=None,token=None,body=None,method=None,headers=None):
    extra=dict(headers or {})
    if form is not None:
        body=urllib.parse.urlencode(form).encode();extra['Content-Type']='application/x-www-form-urlencoded'
    if token:extra['Authorization']='Bearer '+token
    request=urllib.request.Request(url,data=body,headers=extra,method=method)
    try:
        with urllib.request.urlopen(request,timeout=45) as result:return json.load(result)
    except urllib.error.HTTPError as error:
        raise HTTPException(502,'Google từ chối thao tác (HTTP '+str(error.code)+'). Kiểm tra quyền Drive, tài khoản và cấu hình OAuth.') from None
    except (urllib.error.URLError,TimeoutError):
        raise HTTPException(502,'Chưa kết nối được dịch vụ Google. Dữ liệu nghiệp vụ chưa được ghi.') from None


@router.get('/api/google-status')
def status():
    return {'configured':configured()}


@router.get('/auth/google/start')
def start(request:Request,db=Depends(get_db)):
    if request.url.hostname=='localhost':
        return RedirectResponse('http://127.0.0.1:8000/auth/google/start',status_code=303)
    if not configured():
        return HTMLResponse('<meta charset="utf-8"><p>Chưa cấu hình Google OAuth. Hãy làm theo file <b>Huong dan ket noi Google va Drive.md</b>, lưu file JSON rồi chạy <b>Cau hinh Google.command</b>.</p><a href="/login">Về đăng nhập local</a>',status_code=503)
    state=secrets.token_urlsafe(40);verifier=secrets.token_urlsafe(64)
    db.execute(delete(GoogleOAuthState).where(GoogleOAuthState.expires_at<datetime.utcnow()))
    db.add(GoogleOAuthState(state_hash=token_hash(state),verifier=verifier,expires_at=datetime.utcnow()+timedelta(minutes=10)))
    db.commit()
    params={'client_id':os.environ['GOOGLE_CLIENT_ID'],'redirect_uri':REDIRECT,'response_type':'code','scope':SCOPES,
            'access_type':'offline','prompt':'consent','state':state,'include_granted_scopes':'true',
            'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),
            'code_challenge_method':'S256'}
    response=RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params),status_code=303)
    response.set_cookie('napaco_oauth_state',state,httponly=True,samesite='lax',max_age=600,path='/auth/google')
    response.set_cookie('napaco_oauth_next',safe_next(request.query_params.get('next')),httponly=True,samesite='lax',max_age=600,path='/auth/google')
    return response


@router.get('/auth/google/callback')
def callback(request:Request,db=Depends(get_db)):
    state=request.query_params.get('state','');cookie=request.cookies.get('napaco_oauth_state','')
    if not state or not hmac.compare_digest(state,cookie):raise HTTPException(400,'Phiên đăng nhập Google không khớp. Hãy bắt đầu lại.')
    pending=db.scalar(select(GoogleOAuthState).where(GoogleOAuthState.state_hash==token_hash(state)).with_for_update())
    if not pending or pending.expires_at<datetime.utcnow():raise HTTPException(400,'Phiên đăng nhập Google đã hết hạn.')
    if request.query_params.get('error'):raise HTTPException(400,'Anh chưa cấp quyền Google cho ứng dụng.')
    code=request.query_params.get('code','')
    if not code:raise HTTPException(400,'Thiếu mã xác thực Google.')
    secret=cipher()
    tokens=google_json('https://oauth2.googleapis.com/token',form={'client_id':os.environ['GOOGLE_CLIENT_ID'],
       'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'code':code,'code_verifier':pending.verifier,
       'grant_type':'authorization_code','redirect_uri':REDIRECT})
    identity=google_json('https://openidconnect.googleapis.com/v1/userinfo',token=tokens['access_token'])
    email=identity.get('email','').lower()
    if identity.get('email_verified') is not True:raise HTTPException(403,'Google chưa xác minh email này.')
    user=db.scalar(select(User).where(User.email==email,User.active.is_(True)))
    if not user:raise HTTPException(403,'Email Google chưa khớp nhân viên đang hoạt động trong danh mục. Không tự cấp tài khoản mới.')
    credentials=db.get(GoogleCredential,user.id)
    if not credentials:credentials=GoogleCredential(user_id=user.id);db.add(credentials)
    elif credentials.subject!=identity['sub']:raise HTTPException(403,'Định danh Google không khớp kết nối đã lưu.')
    credentials.subject=identity['sub'];credentials.encrypted_access=secret.encrypt(tokens['access_token'].encode()).decode()
    if tokens.get('refresh_token'):credentials.encrypted_refresh=secret.encrypt(tokens['refresh_token'].encode()).decode()
    credentials.expires_at=datetime.utcnow()+timedelta(seconds=int(tokens.get('expires_in',3600)))
    credentials.scopes=tokens.get('scope','')
    session=secrets.token_urlsafe(40)
    db.add(LoginSession(token_hash=token_hash(session),user_id=user.id,expires_at=datetime.utcnow()+timedelta(hours=8)))
    db.delete(pending);db.commit()
    response=RedirectResponse(safe_next(request.cookies.get('napaco_oauth_next') or '/?view=index'),status_code=303)
    response.delete_cookie('napaco_oauth_state',path='/auth/google')
    response.delete_cookie('napaco_oauth_next',path='/auth/google')
    # Google returns through a cross-site top-level redirect. Strict would omit
    # the new cookie on the following navigation to the protected ERP page.
    # Lax permits this GET; core.http still rejects cross-origin writes.
    response.set_cookie('napaco_session',session,httponly=True,samesite='lax',max_age=8*3600)
    return response


def access_token(db,user):
    secret=cipher();credentials=db.get(GoogleCredential,user.id)
    if not credentials:raise HTTPException(403,'Hãy đăng nhập bằng Google trên /login để sử dụng Drive đúng tài khoản của anh.')
    if credentials.expires_at<=datetime.utcnow()+timedelta(seconds=60):
        if not credentials.encrypted_refresh:raise HTTPException(403,'Cần đăng nhập Google lại để cấp quyền Drive.')
        result=google_json('https://oauth2.googleapis.com/token',form={'client_id':os.environ['GOOGLE_CLIENT_ID'],
          'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'refresh_token':secret.decrypt(credentials.encrypted_refresh.encode()).decode(),
          'grant_type':'refresh_token'})
        credentials.encrypted_access=secret.encrypt(result['access_token'].encode()).decode()
        credentials.expires_at=datetime.utcnow()+timedelta(seconds=int(result.get('expires_in',3600)))
        db.flush()
    return secret.decrypt(credentials.encrypted_access.encode()).decode()
