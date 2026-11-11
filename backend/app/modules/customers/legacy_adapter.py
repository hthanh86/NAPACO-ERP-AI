"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.customers.models import Customer

TABLES = {
    'CUSTOMERS': (Customer, 'master', {'ID':'id','NAME':'name','ADDRESS':'address','CONTACTER':'contact','PHONE':'phone'}),
}
