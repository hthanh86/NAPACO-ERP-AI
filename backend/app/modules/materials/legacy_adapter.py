"""Legacy-to-MySQL field mappings owned by this module."""
from app.modules.materials.models import FilmSupplier, FilmMaterial

TABLES = {
    'FILM_SUPPLIERS': (FilmSupplier, 'master', {'ID':'id','NAME':'name','TYPE':'category'}),
    'FILM_MATERIALS': (FilmMaterial, 'master', {'ID':'id','GRADE':'grade','COLOR':'color','ESD':'esd','THICKNESS':'thickness','WIDTH':'width'}),
}
