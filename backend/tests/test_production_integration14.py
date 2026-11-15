"""HTTP wiring on the real MySQL rollback fixtures; Google is not contacted."""
from uuid import uuid4
from datetime import datetime,timedelta
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_db
from app.auth.security import token_hash
from app.auth.models import User,LoginSession
from app.modules.materials.inventory.handover_service import create_issue
from test_production_release import context
from test_material_handovers import handover_context,draft
from test_production_samples import sample_context
from test_forming_diary import forming_context,payload


@pytest.fixture
def http14(forming_context):
    c=forming_context
    def database():yield c.db
    saved=dict(app.dependency_overrides)
    app.dependency_overrides[get_db]=database
    token=str(uuid4())
    c.db.add(LoginSession(token_hash=token_hash(token),user_id=c.user.id,expires_at=datetime.utcnow()+timedelta(hours=1)))
    c.db.commit()
    try:
        with TestClient(app) as client:
            client.cookies.set('napaco_session',token)
            yield c,client
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(saved)


def test_pages_release_sheet_and_work_queue_use_official_lsx(http14):
    c,client=http14
    for path in ['/production/schedule','/production/runs','/production/materials','/production/handovers','/production/samples','/production/forming']:
        response=client.get(path);assert response.status_code==200,(path,response.text)
    sheet=client.get('/api/production/runs/'+c.key+'/release-sheet')
    assert sheet.status_code==200 and c.run.official_code in sheet.text
    queue=client.get('/api/production/machines/'+c.run.machine_id+'/work').json()
    assert queue['items'][0]['official_code']==c.run.official_code
    data=client.get('/api/production/forming/context',params={'run_id':c.key,'machine_id':c.run.machine_id}).json()
    assert data['official_code']==c.run.official_code and data['sample_basis']['qc_id']==c.sample['id']


def test_http_diary_retry_does_not_duplicate_output_or_material(http14):
    c,client=http14;data=payload(c).model_dump(mode='json');key=str(uuid4());path='/api/production/forming/runs/'+c.key+'/logs'
    first=client.post(path,json=data,headers={'Idempotency-Key':key})
    assert first.status_code==201,first.text
    again=client.post(path,json=data,headers={'Idempotency-Key':key})
    assert again.status_code==201 and again.json()['id']==first.json()['id']
    result=client.get('/api/production/forming/runs/'+c.key+'/summary').json()
    assert result['count']==1 and result['items'][0]['good_qty']==8 and result['lots'][0]['consumed_kg']=='1.00000000'


def test_http_handover_signature_requires_real_google_identity(http14,monkeypatch):
    c,client=http14;doc=draft(c,2)
    # Undo only the test identity double for this endpoint check.
    from app.modules.materials.inventory import handover_service
    from app.modules.qc.signing import identity
    monkeypatch.setattr(handover_service,'identity',identity)
    response=client.post('/api/production/materials/handovers/'+doc['id']+'/confirm-signature',json={
        'version':doc['version'],'role':'issue','signature':[[(.1,.2),(.8,.4)]]})
    assert response.status_code==403,response.text


def test_http_forming_respects_existing_permission_matrix(http14):
    c,client=http14
    reader=User(id=c.key+'READ',name='No production grant',role='PH14_READER',active=True,source={})
    c.db.add(reader);c.db.flush()
    token=str(uuid4());c.db.add(LoginSession(token_hash=token_hash(token),user_id=reader.id,expires_at=datetime.utcnow()+timedelta(hours=1)))
    c.db.commit();client.cookies.set('napaco_session',token)
    assert client.get('/api/production/forming/machines').status_code==403
    assert client.post('/api/production/forming/runs/'+c.key+'/logs',json=payload(c).model_dump(mode='json'),
        headers={'Idempotency-Key':str(uuid4())}).status_code==403
