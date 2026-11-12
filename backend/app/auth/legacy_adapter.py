"""Legacy-to-MySQL field mappings owned by this module."""
from app.auth.models import User
from app.auth.models import RolePermission
from app.auth.permissions import PERMISSION_CODES
from sqlalchemy import select

TABLES = {
    'EMPLOYEES': (User, 'master', {'ID':'id','NAME':'name','EMAIL':'email','ACCESS':'role'}),
}


def permission_rows(db):
    """Project current MySQL grants into the existing runtime's read format."""
    grants = {(role, permission): allowed for role, permission, allowed in
              db.execute(select(RolePermission.role, RolePermission.permission, RolePermission.allowed))}
    roles = sorted(({role for role, _ in grants} | set(db.scalars(select(User.role).distinct()))) - {'LOCAL_ADMIN'})
    codes = sorted(PERMISSION_CODES | {permission for _, permission in grants})
    return [['Ma_Chuc_Nang', *roles]] + [
        [permission, *['1' if grants.get((role, permission), False) else '0' for role in roles]]
        for permission in codes]
