"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.orders.models import Order, OrderLine

TABLES = {
    'ORDERS': (Order, 'operation', {'ID':'id','CUSTOMER_ID':'customer_id','ORDER_DATE':'order_date','DELIVERY_DATE':'delivery_date','PO_NUMBER':'po_number','FILE_URL':'file_url'}),
    'ORDER_DETAILS': (OrderLine, 'operation', {'ID':'id','ORDER_ID':'order_id','PRODUCT_ID':'source_product_id','QTY_ORDER':'quantity','PRICE':'price','QTY_RUN':'produced','QTY_DELIVERED':'delivered','QTY_REMAINING':'remaining_source','NOTE':'note','DELIVERY_DATE':'delivery_date','STAFF_ID':'staff_id','STATUS':'status','UNIT':'unit','KANBAN_ZONE':'zone','PRIORITY_ORDER':'priority','FILM_LINE_ID':'film_line_id'}),
}
