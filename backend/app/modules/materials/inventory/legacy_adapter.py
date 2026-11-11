"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.materials.inventory.models import FilmMovement

TABLES = {
    'FILM_MOVEMENTS': (FilmMovement, 'operation', {'ID':'id','DATE':'moved_at','TYPE':'kind','ORDER_ID':'production_order_id','RECEIPT_ID':'receipt_id','QC_ID':'qc_id','QTY':'quantity','ISSUER':'issuer_id','RECEIVER':'receiver_id','NOTE':'note'}),
}
