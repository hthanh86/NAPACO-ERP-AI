"""Legacy-to-MySQL field mappings owned by this module."""
from app.auth.models import User

TABLES = {
    'EMPLOYEES': (User, 'master', {'ID':'id','NAME':'name','EMAIL':'email','ACCESS':'role'}),
}
