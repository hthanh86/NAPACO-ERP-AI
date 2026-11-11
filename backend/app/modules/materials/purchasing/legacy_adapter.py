"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.materials.purchasing.models import FilmPO, FilmLine

TABLES = {
    'FILM_PO': (FilmPO, 'operation', {'ID':'id','DATE':'order_date','SUPPLIER':'supplier_id','USER':'staff_id','NOTE':'note','STATUS':'status'}),
    'FILM_LINES': (FilmLine, 'operation', {'ID':'id','PO_ID':'po_id','MATERIAL_ID':'material_id','RESIN':'resin','QTY':'quantity','PRICE':'price','NOTE':'note','STATUS':'status','DELIVERY':'delivery_date','DATE':'order_date','SUPPLIER':'supplier_id'}),
}
