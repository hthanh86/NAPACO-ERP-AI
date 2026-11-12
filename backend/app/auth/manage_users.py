"""Local operator tool for Google employee accounts. Never displays credentials."""
import argparse
import json
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from app.core import model_registry
from app.core.database import Session
from app.auth.models import User, RolePermission, LoginSession
from app.integrations.google.models import GoogleCredential


def roles(db):
    return sorted((set(db.scalars(select(RolePermission.role).distinct())) |
                   set(db.scalars(select(User.role).distinct()))) - {'LOCAL_ADMIN'})


def manage(db, args, commit=True):
    if args.action == 'roles':
        grants = {}
        for role, permission in db.execute(select(RolePermission.role, RolePermission.permission).where(RolePermission.allowed.is_(True))):
            grants.setdefault(role, []).append(permission)
        return [{'role': role, 'permissions': sorted(grants.get(role, []))} for role in roles(db)]
    if args.action == 'list':
        return [{'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role, 'active': u.active,
                 'google_connected': db.get(GoogleCredential, u.id) is not None}
                for u in db.scalars(select(User).order_by(User.id))]
    user = db.get(User, args.id)
    if user and user.role == 'LOCAL_ADMIN':
        raise ValueError('Công cụ này chỉ quản lý nhân viên; không sửa tài khoản quản trị local.')
    if args.action in {'add', 'update'}:
        if args.action == 'add' and user:
            raise ValueError('Mã nhân viên đã tồn tại. Dùng update để cập nhật.')
        if args.action == 'update' and not user:
            raise ValueError('Không tìm thấy nhân viên.')
        email = args.email.strip().lower()
        if len(email) > 254 or email.count('@') != 1 or any(c.isspace() for c in email) or not all(email.split('@')):
            raise ValueError('Email không hợp lệ.')
        if not args.name.strip() or len(args.name.strip()) > 300 or not args.id.strip() or len(args.id) > 100:
            raise ValueError('Mã hoặc tên nhân viên không hợp lệ.')
        if args.role not in roles(db):
            raise ValueError('Vai trò không hợp lệ. Chạy roles để xem danh sách.')
        duplicate = db.scalar(select(User).where(User.email == email, User.id != args.id))
        if duplicate:
            raise ValueError('Email đã thuộc nhân viên khác.')
        if not user:
            user = User(id=args.id, name=args.name.strip(), email=email, role=args.role, active=True, source={})
            db.add(user)
        else:
            if user.email != email:
                db.execute(delete(GoogleCredential).where(GoogleCredential.user_id == user.id))
                user.password_hash = None
            user.name, user.email, user.role = args.name.strip(), email, args.role
    else:
        if not user:
            raise ValueError('Không tìm thấy nhân viên.')
        user.active = args.action == 'enable'
        if args.action == 'disable':
            db.execute(delete(GoogleCredential).where(GoogleCredential.user_id == user.id))
    # Revoke existing sessions whenever the account or its access changes.
    db.execute(delete(LoginSession).where(LoginSession.user_id == args.id))
    if commit:
        db.commit()
    else:
        db.flush()
    return {'id': user.id, 'email': user.email, 'role': user.role, 'active': user.active, 'result': 'Đã cập nhật; cần đăng nhập lại.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ['list', 'roles']:
        sub.add_parser(action)
    for action in ['add', 'update', 'disable', 'enable']:
        command = sub.add_parser(action)
        command.add_argument('id')
        if action in {'add', 'update'}:
            for field in ['name', 'email', 'role']:
                command.add_argument('--' + field, required=True)
    args = parser.parse_args()
    with Session() as db:
        try:
            print(json.dumps(manage(db, args), ensure_ascii=False, indent=2))
        except (ValueError, IntegrityError) as error:
            db.rollback()
            parser.exit(1, (str(error) if isinstance(error, ValueError) else 'Dữ liệu trùng hoặc không hợp lệ.') + '\n')


if __name__ == '__main__':
    main()
