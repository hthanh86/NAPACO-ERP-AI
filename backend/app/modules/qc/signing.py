"""Session-bound internal acknowledgements; never trust signer identity from the browser."""
from datetime import datetime, timezone
import json
from uuid import uuid4
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from app.auth.security import current_user, require, token_hash
from app.core.database import get_db
from app.integrations.google.oauth import cipher
from app.integrations.google.models import GoogleCredential
from app.modules.qc.mapping import digest
from app.modules.qc.schemas import QCInput

router = APIRouter()


def identity(request, db, user):
    try:
        proof = json.loads(cipher().decrypt(request.cookies.get('napaco_google_proof','').encode(), ttl=8*3600))
        credential = db.get(GoogleCredential, user.id)
        if (not credential or proof['user'] != user.id or proof['subject'] != credential.subject or
                proof['session'] != token_hash(request.cookies.get('napaco_session',''))):
            raise ValueError()
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(403, 'Cần đăng nhập/kết nối lại Google từ ERP để ký xác nhận bằng đúng tài khoản hiện tại.') from None
    return {'user_id':user.id,'name':user.name,'email':user.email,'google_subject':credential.subject,
            'session':proof['session']}


def content_hash(data):
    values = data.model_dump(mode='json', include={'check_type','object_type','object_id','checked_at','quantity','result','note','mapped_form'})
    values['mapped_form'].pop('confirmation', None)
    return digest(values)


def context_hash(values):
    return digest({key:value for key,value in values.items() if key not in {
        'qc_id','check_type','checked_at','quantity','staff_name','qc_note','conclusion','signer_name','signed_at'}})


def verify(request, db, user, data):
    if not data.mapped_form:
        return
    actor = identity(request, db, user)
    entered = data.mapped_form
    try:
        signed = json.loads(cipher().decrypt((entered.confirmation or '').encode(), ttl=8*3600))
        if (signed['user_id'] != user.id or signed['session'] != actor['session'] or
                signed['google_subject'] != actor['google_subject'] or signed['content_hash'] != content_hash(data)):
            raise ValueError()
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(422, 'Nội dung QC hoặc phiên ký đã thay đổi. Hãy mở biểu mẫu và ký xác nhận lại.') from None
    entered._signer = signed


@router.post('/api/qc/signatures/confirm')
def confirm(data: QCInput, request: Request, qc_id: str | None = Query(None,max_length=100), user=Depends(current_user), db=Depends(get_db)):
    from app.modules.qc.api import allowed
    allowed(db, user, 'QC_CREATE','QC_EDIT')
    actor = identity(request, db, user)
    if not data.mapped_form or not any(len(stroke) >= 2 and len(set(map(tuple, stroke))) >= 2 for stroke in data.mapped_form.signature):
        raise HTTPException(422, 'Hãy ký xác nhận; chữ ký không được để trống hoặc chỉ có một điểm.')
    if qc_id:
        require(db,user,'QC_EDIT')
        from app.modules.qc.models import QualityCheck
        obj=db.get(QualityCheck,qc_id)
        if not obj or obj.template_id!=data.mapped_form.template_id or obj.object_id!=data.object_id:
            raise HTTPException(422,'Phiếu và nội dung đang ký không khớp.')
        values=obj.form_data['context']
    else:
        from app.modules.qc.template_runtime import selection
        values,_=selection(db,data.check_type,data.object_type,data.object_id)
    signed = {**actor,'signed_at':datetime.now(timezone.utc).isoformat(),'nonce':uuid4().hex,
              'method':'google_oauth_internal_drawn','content_hash':content_hash(data),'context_hash':context_hash(values)}
    token = cipher().encrypt(json.dumps(signed).encode()).decode()
    return {'confirmation':token,'name':actor['name'],'email':actor['email'],'signed_at':signed['signed_at']}
