from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from app.core.database import engine, get_db
from app.auth.security import current_user
from app.migrations.models import ImportRun
from app.compatibility.api import legacy_page

router = APIRouter()

@router.get('/')
def index(request:Request,db=Depends(get_db)):
    return legacy_page(request,db)


@router.get('/api/health')
def health():
    with engine.connect() as db:
        version = db.scalar(text('SELECT VERSION()'))
        revision = db.scalar(text('SELECT version_num FROM alembic_version'))
    return {'status': 'ok', 'database': 'MySQL ' + version, 'migration': revision, 'mode': 'local'}


@router.get('/api/migration-status')
def migration_status(user=Depends(current_user), db=Depends(get_db)):
    run = db.scalar(select(ImportRun).order_by(ImportRun.created_at.desc()))
    return {'imported': bool(run), 'counts': run.report['counts'] if run else {},
            'quality': run.report.get('quality', {}) if run else {},
            'reconciliation': run.report.get('reconciliation') if run else None}
