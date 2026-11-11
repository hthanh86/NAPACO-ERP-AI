"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.products.models import Product

TABLES = {
    'PRODUCTS': (Product, 'master', {'ID':'id','CUSTOMER_ID':'source_customer_id','NAME':'name','CODE_CUST':'code','TYPE':'type','UNIT':'unit','PRICE':'price'}),
}
