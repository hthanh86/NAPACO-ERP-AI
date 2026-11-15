"""Local A/B walkthrough fixtures only; never a Google OAuth verification.

Business orders, receipts, allocations, plans, handover drafts and journals are
entered through the UI. This process supplies explicitly synthetic signatures
and a shared QC template snapshot while no Google account is connected.
"""
import argparse
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from cryptography.fernet import Fernet
from sqlalchemy import select
from app.core import model_registry
from app.core.database import Session, engine
from app.auth.models import User
from app.modules.materials.inventory import handover_service as handovers
from app.modules.materials.inventory.handover_models import MaterialHandover
from app.modules.materials.inventory.handover_schemas import HandoverSign
from app.modules.production import sample_service as samples
from app.modules.production import release_service as release
from app.modules.production.sample_schemas import SampleSign, SampleDraft
from app.modules.production.models import ProductionSetup
from app.modules.qc import mapping, jobs
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate

RUNS = {'f49365c3-1b8f-4ea1-aa55-570e7e2b8fed', '56b04ec8-2631-4688-9e07-34343c0610d7'}
NOTE = '[GIẢ LOCAL A/B 15-11] Chữ ký mô phỏng; không xác thực Google, không xuất Drive.'
STROKES = [[(.1, .2), (.3, .6), (.8, .4)]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['template', 'issue', 'receipt', 'draft', 'sample'])
    parser.add_argument('--next-day', action='store_true')
    args = parser.parse_args()
    if engine.url.host != 'mysql':
        raise RuntimeError('Chỉ chạy Docker MySQL local.')
    cipher = Fernet(Fernet.generate_key())

    def identity(request, db, user):
        return dict(user_id=user.id, name=user.name, email=user.email,
                    google_subject='SYNTHETIC-LOCAL:' + user.id,
                    session=request.session, simulation=True)

    def marked(proof):
        value = json.loads(cipher.decrypt(proof.encode()))
        value['method'] = 'synthetic_local_test'
        value['simulation'] = True
        return cipher.encrypt(json.dumps(value).encode()).decode()

    business_now = release.now
    with Session.begin() as db, patch.object(release, 'now', lambda: business_now() + timedelta(days=1 if args.next_day else 0)), \
            patch.object(handovers, 'identity', identity), \
            patch.object(samples, 'identity', identity), \
            patch.object(handovers, 'cipher', lambda: cipher), \
            patch.object(samples, 'cipher', lambda: cipher), \
            patch.object(jobs, 'enqueue', lambda *a, **k: None):
        actors = []
        for key, name in [('TH_AB_ISSUER', 'Người cấp / kỹ thuật'), ('TH_AB_RECEIVER', 'Người nhận / QC')]:
            actor = db.get(User, key)
            if actor is None:
                actor = User(id=key, name='[GIẢ LOCAL A/B] ' + name, active=False,
                             role='LOCAL_ADMIN', email=key.lower() + '@example.test',
                             source={'simulation': True, 'note': NOTE})
                db.add(actor)
            actors.append(actor)
        db.flush()
        if args.action == 'template':
            template = db.scalar(select(QCTemplate).where(QCTemplate.form_code == 'TH_AB_LOCAL_1511'))
            if template is None:
                source = dict(spreadsheet_id='TH_AB_LOCAL_SNAPSHOT_ONLY', sheet_id=0,
                              sheet_title='Mẫu thực hành A-B', title=NOTE, row_count=8,
                              column_count=6, grid={'rowData': []}, merges=[], theme={}, truncated=False)
                layout = mapping.validate(source, mapping.MappingInput(fields=[
                    dict(id='look', name='Ngoại quan', kind='INPUT', cell='B2', assessment_cell='C2', reviewed=True),
                    dict(id='lsx', name='Lệnh sản xuất', kind='ERP', cell='D2', source='production_order_id', reviewed=True)
                ], signature_cell='A5', signature_end_cell='C8'), 'QC ĐẦU CA', approve=True)
                template = QCTemplate(id=str(uuid4()), form_code='TH_AB_LOCAL_1511', form_name=NOTE,
                                      check_type='QC ĐẦU CA', object_type='SETUP', product_id='SP0006',
                                      spreadsheet_id=source['spreadsheet_id'], sheet_id=0, version=1,
                                      status='ACTIVE', created_by=actors[0].id, approved_by=actors[0].id,
                                      approved_at=datetime.utcnow(), source_matches=True,
                                      source_snapshot=source, source_hash=mapping.source_hash(source), field_mapping=layout)
                db.add(template)
            print('Shared QC template fixture:', template.id)
        elif args.action in {'issue', 'receipt'}:
            for row in db.scalars(select(MaterialHandover).where(MaterialHandover.run_id.in_(RUNS))):
                expected = 'draft' if args.action == 'issue' else 'awaiting_receipt'
                if row.state != expected:
                    continue
                actor = actors[0 if args.action == 'issue' else 1]
                request = SimpleNamespace(session='SYNTHETIC:' + actor.id)
                data = HandoverSign(version=row.version, role=args.action, signature=STROKES)
                proof = handovers.confirm_signature(db, actor, request, row, data)
                result = handovers.sign(db, actor, request, row.id, data.model_copy(update={'confirmation': marked(proof['confirmation'])}))
                print('Synthetic handover', row.id, result['state'])
        elif args.action == 'draft':
            template = db.scalar(select(QCTemplate).where(QCTemplate.form_code == 'TH_AB_LOCAL_1511'))
            for setup in db.scalars(select(ProductionSetup).where(ProductionSetup.production_order_id.in_(RUNS))):
                if samples.info(setup).get('closed_at'):
                    continue
                if db.scalar(select(QualityCheck.id).where(QualityCheck.object_id == setup.id)):
                    continue
                doc = samples.save(db, actors[0], SampleDraft(
                    setup_id=setup.id, template_id=template.id, source_hash=template.source_hash,
                    mapping_hash=mapping.digest(template.field_mapping), quantity=3,
                    answers=[dict(id='look', actual='Mẫu giả: không rách, đủ hình', assessment='PASS')],
                    conclusion='PASS', decision='normal', note=NOTE, parent_folder_id='TH_AB_LOCAL_NO_DRIVE'))
                print('Synthetic sample draft', doc['id'], setup.id)
        else:
            checks = db.scalars(select(QualityCheck).where(QualityCheck.template_id.in_(
                select(QCTemplate.id).where(QCTemplate.form_code == 'TH_AB_LOCAL_1511')))).all()
            for row in checks:
                doc = samples.record(db, row)
                for role, actor in zip(['technical', 'qc'], actors):
                    if doc['form_data'][samples.SAMPLE]['signatures'].get(role):
                        continue
                    request = SimpleNamespace(session='SYNTHETIC:' + actor.id)
                    data = SampleSign(version=doc['version'], role=role, signature=STROKES)
                    proof = samples.confirm(db, actor, request, row.id, data)
                    doc = samples.sign(db, actor, request, row.id, data.model_copy(update={'confirmation': marked(proof['confirmation'])}))
                row.source = {**(row.source or {}), 'simulation': True,
                              'qc_bundle': {'pending': False, 'error': NOTE}}
                print('Synthetic sample', row.id, doc['state'])


if __name__ == '__main__':
    main()
