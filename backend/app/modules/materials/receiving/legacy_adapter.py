"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.materials.receiving.models import FilmReceipt

TABLES = {
    'FILM_RECEIPTS': (FilmReceipt, 'operation', {'ID':'id','DATE':'receipt_date','PRODUCTION_DATE':'production_date','LINE_ID':'line_id','ROLLS':'rolls','QTY':'quantity','LOCATION':'location','STATUS':'status','USER':'staff_id','IQC_ID':'iqc_id','NOTE':'note'}),
}
