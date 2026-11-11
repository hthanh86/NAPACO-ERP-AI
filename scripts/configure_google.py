"""Import a user-supplied web OAuth client. Never prints the client secret."""
import base64
import json
import os
from pathlib import Path
import secrets

ROOT=Path(__file__).resolve().parents[1]


def configure(required=True):
    source=ROOT/'data/google-oauth-client.json'
    if not source.exists():
        if required:raise SystemExit('Chưa có data/google-oauth-client.json. Xem hướng dẫn kết nối Google và Drive.')
        return False
    client=json.loads(source.read_text()).get('web')
    if not client:raise SystemExit('Cần OAuth Client loại Web application.')
    callback='http://127.0.0.1:8000/auth/google/callback'
    if callback not in client.get('redirect_uris',[]):raise SystemExit('File OAuth chưa có redirect URI đúng theo hướng dẫn.')
    target=ROOT/'.google.env'
    existing={}
    if target.exists():existing=dict(line.split('=',1) for line in target.read_text().splitlines() if '=' in line)
    values={'GOOGLE_CLIENT_ID':client['client_id'],'GOOGLE_CLIENT_SECRET':client['client_secret'],
            'GOOGLE_TOKEN_KEY':existing.get('GOOGLE_TOKEN_KEY') or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}
    if any('\n' in v or '\r' in v or '$' in v for v in values.values()):raise SystemExit('Định dạng cấu hình không hợp lệ.')
    target.write_text('\n'.join(k+'='+v for k,v in values.items())+'\n');os.chmod(target,0o600);os.chmod(source,0o600)
    print('Đã nhận cấu hình OAuth. Không hiển thị client secret.',flush=True)
    return True


if __name__=='__main__':
    configure()
    from manage import compose
    compose('up','-d','backend')
    print('Mở http://127.0.0.1:8000/login và chọn Đăng nhập Google.')
