"""Prepared phase-3 checks. Do not run until the user's deferred test session.

Uses rollback-only local MySQL fixtures. Google identity/export are doubles;
these cases cannot certify real Google OAuth or the rendered Drive PDF.
"""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from test_production_release import context
from test_material_handovers import handover_context,draft,issue,receive
from app.modules.production import sample_service as service,release_service
from app.modules.production.sample_schemas import EpisodeInput,SampleDraft,SampleSign,SampleVersion
from app.modules.production.models import ProductionSetup,FormingLog
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate
from app.modules.qc import mapping,jobs


@pytest.fixture
def sample_context(handover_context,monkeypatch):
    c=handover_context
    c.user.email='technical@example.test';c.receiver.email='qc@example.test'
    clock=SimpleNamespace(now=release_service.now()+timedelta(seconds=1))
    monkeypatch.setattr(release_service,'now',lambda:clock.now)
    c.clock=clock
    secret=Fernet(Fernet.generate_key())
    monkeypatch.setattr(service,'cipher',lambda:secret)
    monkeypatch.setattr(service,'identity',lambda request,db,user:{'user_id':user.id,'name':user.name,'email':user.email,
        'session':request.session,'google_subject':'google:'+user.id})
    monkeypatch.setattr(jobs,'enqueue',lambda *args,**kwargs:None)
    source={'spreadsheet_id':c.key,'sheet_id':0,'sheet_title':'Mẫu','title':'Sample fixture',
        'row_count':8,'column_count':6,'grid':{'rowData':[]},'merges':[],'theme':{},'truncated':False}
    fields=[{'id':'look','name':'Ngoại quan','kind':'INPUT','cell':'B2','assessment_cell':'C2','reviewed':True},
        {'id':'lsx','name':'Lệnh sản xuất','kind':'ERP','cell':'D2','source':'production_order_id','reviewed':True}]
    layout=mapping.validate(source,mapping.MappingInput(fields=fields,signature_cell='A5',signature_end_cell='C8'),'QC ĐẦU CA',approve=True)
    c.template=QCTemplate(id=str(uuid4()),form_code=c.key.upper(),form_name='Sample rollback template',
        check_type='QC ĐẦU CA',object_type='SETUP',product_id=c.key,spreadsheet_id=c.key,sheet_id=0,
        version=1,status='ACTIVE',created_by=c.user.id,approved_by=c.user.id,approved_at=clock.now,
        source_matches=True,source_snapshot=source,source_hash=mapping.source_hash(source),field_mapping=layout)
    c.db.add(c.template);c.db.flush()
    return c


def new_episode(c):
    return service.create_episode(c.db,c.user,c.key,EpisodeInput(run_version=c.run.version,
        machine_id=c.run.machine_id,valid_until=(c.clock.now+timedelta(hours=8)).replace(tzinfo=release_service.ZONE),note='Actual restart'))


def received_episode(c):
    receive(c,issue(c,draft(c)))
    return new_episode(c)


def sample_draft(c,episode,assessment='PASS',decision='normal'):
    return service.save(c.db,c.user,SampleDraft(setup_id=episode['id'],template_id=c.template.id,
        source_hash=c.template.source_hash,mapping_hash=mapping.digest(c.template.field_mapping),
        quantity=3,answers=[{'id':'look','actual':'Measured appearance','assessment':assessment}],
        conclusion='FAIL' if assessment=='FAIL' else 'PASS',decision=decision,note='Measured defect and sorting instructions',
        parent_folder_id='rollback-fake-folder'))


def signed(c,doc,role):
    user,request=(c.user,c.request) if role=='technical' else (c.receiver,c.receive_request)
    data=SampleSign(version=doc['version'],role=role,signature=[[(.1,.2),(.4,.6),(.8,.3)]])
    proof=service.confirm(c.db,user,request,doc['id'],data)
    return service.sign(c.db,user,request,doc['id'],data.model_copy(update={'confirmation':proof['confirmation']}))


def test_sample_cannot_start_from_pending_handover(sample_context):
    c=sample_context;issue(c,draft(c))
    with pytest.raises(HTTPException,match='NVL đã ký nhận'):new_episode(c)


def test_partial_draft_and_one_signature_never_open_bulk(sample_context):
    c=sample_context;episode=received_episode(c)
    doc=sample_draft(c,episode,assessment=None)
    with pytest.raises(HTTPException):signed(c,doc,'technical')
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=episode['id'])
    data=SampleDraft(setup_id=episode['id'],version=doc['version'],template_id=c.template.id,
        source_hash=c.template.source_hash,mapping_hash=mapping.digest(c.template.field_mapping),quantity=3,
        answers=[{'id':'look','actual':'Checked','assessment':'PASS'}],conclusion='PASS',decision='normal',parent_folder_id='fake-folder')
    doc=service.save(c.db,c.user,data,doc['id']);signed(c,doc,'technical')
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=episode['id'])


@pytest.mark.parametrize('decision,allowed',[('sort',True),('stop',False)])
def test_ng_is_preserved_and_sorting_does_not_require_all_pass(sample_context,decision,allowed):
    c=sample_context;episode=received_episode(c);doc=sample_draft(c,episode,'FAIL',decision)
    doc=signed(c,signed(c,doc,'technical'),'qc')
    assert doc['result']=='NG'
    if allowed:
        basis=service.gate(c.db,c.key,c.run.machine_id,setup_id=episode['id'])
        assert basis['decision']=='sort' and basis['result']=='NG' and basis['qc_id']==doc['id']
    else:
        with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=episode['id'])


def test_new_episode_and_expiry_require_new_sample(sample_context):
    c=sample_context;episode=received_episode(c);doc=signed(c,signed(c,sample_draft(c,episode),'technical'),'qc')
    assert service.gate(c.db,c.key,c.run.machine_id)['qc_id']==doc['id']
    c.clock.now+=timedelta(seconds=1);second=new_episode(c)
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=second['id'])
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=episode['id'])
    second_doc=signed(c,signed(c,sample_draft(c,second),'technical'),'qc')
    c.clock.now+=timedelta(hours=9)
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id,setup_id=second['id'])
    assert service.sample(c.db.get(QualityCheck,second_doc['id']))['state']=='signed'


def test_wrong_session_role_and_altered_strokes_cannot_replay_signature(sample_context):
    c=sample_context;episode=received_episode(c);doc=sample_draft(c,episode)
    data=SampleSign(version=doc['version'],role='technical',signature=[[(.1,.2),(.8,.4)]])
    proof=service.confirm(c.db,c.user,c.request,doc['id'],data)
    data=data.model_copy(update={'confirmation':proof['confirmation']})
    for changed,request in [(data,SimpleNamespace(session='another-session')),
            (data.model_copy(update={'role':'qc'}),c.request),
            (data.model_copy(update={'signature':[[(.2,.3),(.8,.4)]]}),c.request)]:
        with pytest.raises(HTTPException):service.sign(c.db,c.user,request,doc['id'],changed)


def test_used_sample_is_immutable_and_cannot_be_cancelled(sample_context):
    c=sample_context;episode=received_episode(c);doc=signed(c,signed(c,sample_draft(c,episode),'technical'),'qc')
    basis=service.gate(c.db,c.key,c.run.machine_id)
    # Represents a committed journal's immutable basis; no fabricated production quantity.
    log=FormingLog(id=c.key+'SAMPLE_LOG',production_order_id=c.key,setup_id=episode['id'],
        source={},shift_snapshot={service.SAMPLE:basis});c.db.add(log);c.db.flush()
    with pytest.raises(HTTPException):service.cancel(c.db,c.user,doc['id'],SampleVersion(version=doc['version'],note='Cannot erase used proof'))
    assert c.db.get(FormingLog,log.id).shift_snapshot[service.SAMPLE]['qc_id']==doc['id']


def test_cancelling_latest_sample_never_reopens_an_older_clearance(sample_context):
    c=sample_context;episode=received_episode(c)
    old=signed(c,signed(c,sample_draft(c,episode),'technical'),'qc')
    c.clock.now+=timedelta(seconds=1)
    latest=sample_draft(c,episode,'FAIL','stop')
    service.cancel(c.db,c.user,latest['id'],SampleVersion(version=latest['version'],note='Cancelled, require a new inspection'))
    with pytest.raises(HTTPException):service.gate(c.db,c.key,c.run.machine_id)
    assert service.sample(c.db.get(QualityCheck,old['id']))['state']=='signed'
