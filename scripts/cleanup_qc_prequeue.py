"""One-time, explicitly authorized local QC test cleanup (13 November 2026).
Run inside backend with /app on PYTHONPATH; --apply is required to mutate data.
Never selects current/queued QC or deletes shared Drive folders.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, delete, text, bindparam
from app.core.database import Session
from app.core.models import Audit
from app.compatibility.models import LegacyRequest
from app.modules.qc.models import QualityCheck
from app.modules.qc.job_models import QCJob
from app.modules.qc import mapping, drive_bundle
from app.auth.models import User
from app.integrations.google.oauth import access_token

IDS={*(f'QC_261112_{i:02}' for i in range(1,8)),*(f'QC_261113_{i:02}' for i in range(1,4))}

def refs(value):
    if isinstance(value,dict):
        own={value['id']} if isinstance(value.get('id'),str) and value['id'].startswith('QC_') else set()
        return own|set().union(*(refs(v) for v in value.values()),set())
    if isinstance(value,list):return set().union(*(refs(v) for v in value),set())
    return set()

def dump(row):return {col.key:getattr(row,col.key) for col in row.__table__.columns}
def fingerprint(row):return mapping.digest(json.loads(json.dumps(dump(row),default=str)))

def validate(db,rows):
    assert not db.scalar(select(QCJob.id).where(QCJob.qc_id.in_(IDS)).limit(1)), 'An allowlisted QC now has a queue job; abort.'
    for table,column in [('film_movements','qc_id'),('film_receipts','iqc_id'),('production_setups','IQC_QC_ID')]:
        statement=text(f'SELECT COUNT(*) FROM `{table}` WHERE `{column}` IN :ids').bindparams(bindparam('ids',expanding=True))
        assert not db.scalar(statement,{'ids':sorted(IDS)}), 'Business references exist; abort.'
    assert {r.id for r in rows}<=IDS

with Session() as db:
    rows=db.scalars(select(QualityCheck).where(QualityCheck.id.in_(IDS))).all()
    validate(db,rows)
    requests=[r for r in db.scalars(select(LegacyRequest)) if refs(r.result)&IDS]
    assert all(refs(r.result)<=IDS for r in requests),'Mixed queued/legacy request; abort.'
    audits=db.scalars(select(Audit).where(Audit.entity_id.in_(IDS),Audit.action.like('QC%'))).all()
    backup={'qc':[dump(r) for r in rows],'requests':[dump(r) for r in requests],'audit':[dump(r) for r in audits]}
    print({'qc_count':len(rows),'request_count':len(requests),'audit_count':len(audits),'apply':'--apply' in sys.argv})
    if '--apply' not in sys.argv or not rows:sys.exit(0)
    # Private recovery copy; never print signatures or session/upload data.
    directory=Path('/app/reports/private');directory.mkdir(exist_ok=True,mode=0o700)
    path=directory/('qc-prequeue-backup-'+datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')+'.json')
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:
        json.dump(backup,out,default=str,ensure_ascii=False);out.flush();os.fsync(out.fileno())
    fingerprints={r.id:fingerprint(r) for r in rows}
    folders=[(r.id,r.drive_folder_id) for r in rows if r.drive_folder_id]
    request_ids=[r.id for r in requests]

# Only the folders created for the exact QC_ID are trashed, never their parents
# or arbitrary historical evidence links (Scan/iCloud Photos/company QC root).
report={'backup':str(path),'drive_trashed':[],'drive_skipped':[]}
with Session() as db:
    token=access_token(db,db.get(User,'NV0001'))
    for qc,identifier in folders:
        try:
            item=drive_bundle.call(token,'/'+identifier,missing=True,fields='id,name,mimeType,parents,trashed')
            if item is None or item.get('trashed'):continue
            assert item['name']==qc and item['mimeType']==drive_bundle.FOLDER,'Folder identity mismatch'
            assert not db.scalar(select(QualityCheck.id).where(QualityCheck.drive_folder_id==identifier,QualityCheck.id.not_in(IDS)).limit(1)),'Folder shared with another QC'
            drive_bundle.in_scope(db,token,identifier)
            drive_bundle.call(token,'/'+identifier,method='PATCH',body={'trashed':True},fields='id,trashed')
            report['drive_trashed'].append({'qc':qc,'id':identifier})
        except Exception as error:
            report['drive_skipped'].append({'qc':qc,'id':identifier,'reason':getattr(error,'detail',str(error))})

with Session.begin() as db:
    rows=db.scalars(select(QualityCheck).where(QualityCheck.id.in_(IDS)).with_for_update()).all()
    validate(db,rows)
    assert {r.id:fingerprint(r) for r in rows}==fingerprints,'QC changed during cleanup; abort DB deletion.'
    if request_ids:db.execute(delete(LegacyRequest).where(LegacyRequest.id.in_(request_ids)))
    db.execute(delete(Audit).where(Audit.entity_id.in_(IDS),Audit.action.like('QC%')))
    result=db.execute(delete(QualityCheck).where(QualityCheck.id.in_(IDS)))
    db.add(Audit(user_id='NV0001',action='QC_TEST_PREQUEUE_CLEANUP',entity_id='qc-prequeue-20261113',details={'ids':sorted(IDS),'deleted':result.rowcount,'report':report}))
    report['qc_deleted']=result.rowcount
with os.fdopen(os.open(str(path)+'.result.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:json.dump(report,out,ensure_ascii=False)
print(report)
