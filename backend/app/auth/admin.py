"""Permission-checked user administration; credentials never enter audit details."""
from argparse import Namespace
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, or_, func
from sqlalchemy.exc import IntegrityError
from app.auth.models import User, RolePermission, LoginSession
from app.auth.security import current_user, require, hash_password
from app.auth.manage_users import manage
from app.core.database import get_db
from app.core.models import Audit
from app.core.paths import FRONTEND_ROOT
from app.auth.permissions import PERMISSION_CODES, PERMISSION_LABELS
from app.compatibility.models import LegacyState
from app.integrations.google.models import GoogleCredential

router = APIRouter()


def manager(user=Depends(current_user), db=Depends(get_db)):
    require(db, user, 'USER_MANAGE')
    return user


class Account(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r'^\S+$')
    name: str = Field(min_length=1, max_length=300)
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(min_length=1, max_length=100)


class ResetPassword(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class Grant(BaseModel):
    allowed: bool


class PermissionChange(BaseModel):
    role: str = Field(min_length=1, max_length=100)
    permission: str = Field(min_length=1, max_length=100)
    allowed: bool
    expected: bool


class MatrixUpdate(BaseModel):
    changes: list[PermissionChange] = Field(min_length=1, max_length=500)


def audit(db, actor, action, target, details=None):
    db.add(Audit(user_id=actor.id, action=action, entity_id=target, details=details or {}))
    db.commit()


def editable(db, actor, identifier):
    target = db.get(User, identifier)
    if not target:
        raise HTTPException(404, 'Không tìm thấy người dùng.')
    if target.role == 'LOCAL_ADMIN' or target.id == actor.id:
        raise HTTPException(403, 'Không sửa tài khoản quản trị local hoặc chính tài khoản đang đăng nhập.')
    return target


@router.get('/users')
def page(actor=Depends(manager)):
    return FileResponse(FRONTEND_ROOT / 'auth/users.html')


@router.get('/api/admin/users')
def users(q: str = Query('', max_length=200), active: bool | None = None,
          page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
          actor=Depends(manager), db=Depends(get_db)):
    codes = PERMISSION_CODES | set(db.scalars(select(RolePermission.permission).distinct()))
    statement = select(User.id, User.name, User.email, User.role, User.active,
                       GoogleCredential.user_id.label('google_user_id')).outerjoin(GoogleCredential, GoogleCredential.user_id == User.id)
    if q.strip():
        statement = statement.where(or_(*[field.contains(q.strip(), autoescape=True) for field in [User.id, User.name, User.email]]))
    if active is not None:
        statement = statement.where(User.active.is_(active))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    result = []
    for row in db.execute(statement.order_by(User.id).offset((page-1)*size).limit(size)).mappings():
        account = dict(row)
        account['google_connected'] = account.pop('google_user_id') is not None
        result.append(account)
    return {'users': result, 'total': total, 'page': page, 'size': size, 'roles': manage(db, Namespace(action='roles')), 'self_id': actor.id,
            'can_delegate': actor.role == 'LOCAL_ADMIN',
            'permissions': [{'code': code, 'label': PERMISSION_LABELS.get(code, code)} for code in sorted(codes)]}


@router.put('/api/admin/permissions')
def update_matrix(payload: MatrixUpdate, actor=Depends(manager), db=Depends(get_db)):
    if actor.role != 'LOCAL_ADMIN':
        raise HTTPException(403, 'Chỉ quản trị local được thay đổi ma trận quyền.')
    state = db.scalar(select(LegacyState).where(LegacyState.id == 1).with_for_update())
    if not state:
        raise HTTPException(503, 'Chưa khởi tạo dữ liệu ERP.')
    from app.auth.manage_users import roles
    valid_roles = set(roles(db))
    grants = {(r.role, r.permission): r for r in db.scalars(select(RolePermission).with_for_update())}
    codes = PERMISSION_CODES | {permission for _, permission in grants}
    seen, affected = set(), set()
    for change in payload.changes:
        key = (change.role, change.permission)
        if change.role not in valid_roles or change.permission not in codes or key in seen:
            raise HTTPException(422, 'Vai trò, quyền không hợp lệ hoặc ô quyền bị lặp.')
        seen.add(key)
        previous = grants.get(key)
        if bool(previous and previous.allowed) != change.expected:
            raise HTTPException(409, 'Ma trận đã thay đổi. Tải lại trước khi lưu.')
    for change in payload.changes:
        if change.expected == change.allowed:
            continue
        previous = grants.get((change.role, change.permission))
        if previous:
            previous.allowed = change.allowed
        else:
            db.add(RolePermission(role=change.role, permission=change.permission, allowed=change.allowed))
        affected.add(change.role)
    if affected:
        db.execute(delete(LoginSession).where(LoginSession.user_id.in_(select(User.id).where(User.role.in_(affected)))))
        state.revision += 1
        audit(db, actor, 'ROLE_PERMISSION_MATRIX', '', {'changes': [c.model_dump() for c in payload.changes]})
    return {'ok': True}


@router.post('/api/admin/users')
@router.put('/api/admin/users/{identifier}')
def save(payload: Account, identifier: str = None, actor=Depends(manager), db=Depends(get_db)):
    if identifier is not None:
        editable(db, actor, identifier)
        if payload.id != identifier:
            raise HTTPException(422, 'Không được đổi mã nhân viên.')
    try:
        result = manage(db, Namespace(action='update' if identifier is not None else 'add', **payload.model_dump()), commit=False)
    except (ValueError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(422, str(error) if isinstance(error, ValueError) else 'Dữ liệu bị trùng.')
    audit(db, actor, 'USER_UPDATE' if identifier else 'USER_CREATE', payload.id, {'role': payload.role})
    return result


@router.post('/api/admin/users/{identifier}/{action}')
def status(identifier: str, action: str, actor=Depends(manager), db=Depends(get_db)):
    if action not in {'enable', 'disable'}:
        raise HTTPException(404, 'Thao tác không tồn tại.')
    editable(db, actor, identifier)
    result = manage(db, Namespace(action=action, id=identifier), commit=False)
    audit(db, actor, 'USER_' + action.upper(), identifier)
    return result


@router.put('/api/admin/users/{identifier}/password')
def reset(identifier: str, payload: ResetPassword, actor=Depends(manager), db=Depends(get_db)):
    target = editable(db, actor, identifier)
    target.password_hash = hash_password(payload.password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == identifier))
    audit(db, actor, 'USER_PASSWORD_RESET', identifier)
    return {'ok': True}


@router.put('/api/admin/roles/{role}/management')
def delegate(role: str, payload: Grant, actor=Depends(manager), db=Depends(get_db)):
    if actor.role != 'LOCAL_ADMIN':
        raise HTTPException(403, 'Chỉ quản trị local được cấp quyền quản lý user cho vai trò.')
    if role == 'LOCAL_ADMIN' or not db.scalar(select(RolePermission.role).where(RolePermission.role == role)):
        raise HTTPException(422, 'Vai trò không hợp lệ.')
    grant = db.get(RolePermission, (role, 'USER_MANAGE'))
    if grant:
        grant.allowed = payload.allowed
    else:
        db.add(RolePermission(role=role, permission='USER_MANAGE', allowed=payload.allowed))
    ids = select(User.id).where(User.role == role)
    db.execute(delete(LoginSession).where(LoginSession.user_id.in_(ids)))
    audit(db, actor, 'ROLE_USER_MANAGE', role, {'allowed': payload.allowed})
    return {'ok': True}
