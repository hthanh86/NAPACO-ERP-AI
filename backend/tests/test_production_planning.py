"""Stage-1 contract tests in isolated SQLite memory, never the ERP database.

Does not prove MySQL DDL/FOR UPDATE behavior; run MySQL acceptance after approved migration.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.core.http import configure_http
from app.auth.models import User, LoginSession, RolePermission
from app.auth.security import token_hash
from app.migrations.models import SourceRow
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.materials.models import FilmMaterial
from app.modules.production.planning_api import router
from app.modules.production.planning_models import ProductionStandard, ProductionStandardItem, Machine
from app.core.config import LEGACY_CONFIG


@pytest.fixture
def planning():
    engine = create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def foreign_keys(connection,record):
        connection.execute('PRAGMA foreign_keys=ON')
    names = ['system_settings','users','login_sessions','role_permissions','customers','products','film_materials','source_rows',
             'audit_log','production_machines','production_standards','production_standard_items','production_calendar_exceptions']
    Base.metadata.create_all(engine,tables=[Base.metadata.tables[n] for n in names])
    with Session(engine) as db:
        db.add_all([User(id='admin',name='Test',role='LOCAL_ADMIN',active=True),User(id='reader',name='Read',role='READER',active=True)])
        db.add(Customer(id='C1',name='Customer'));db.flush()
        db.add_all([Product(id='P1',customer_id='C1',name='First',unit='Cái'),Product(id='P2',customer_id='C1',name='Second',unit='Cái')])
        db.add(FilmMaterial(id='F1',grade='PET',width=500,thickness=0.5))
        db.add_all([LoginSession(token_hash=token_hash(role),user_id=role,expires_at=datetime.utcnow()+timedelta(hours=1)) for role in ['admin','reader']])
        headers=['MaCC','Ma_Khuon','TenCC','LoaiCC','MaSP','Dai_Khuon','Rong_Khuon','Cavity','Trang_Thai']
        db.add_all([SourceRow(book='master',sheet=LEGACY_CONFIG['SHEET_NAMES']['TOOLS'],row_number=1,cells=headers),
            SourceRow(book='master',sheet=LEGACY_CONFIG['SHEET_NAMES']['TOOLS'],row_number=2,cells=['CC1','K1','Mold',LEGACY_CONFIG['MOLD_TYPES']['FORMING'],'P1',400,400,4,'SanSang'])])
        db.commit()
    app=FastAPI();app.include_router(router);configure_http(app)
    def override():
        with Session(engine,expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db]=override
    with TestClient(app) as client:
        client.cookies.set('napaco_session','admin')
        yield SimpleNamespace(client=client,engine=engine)
    engine.dispose()


def machine(identifier='DH1',kind='semi_automatic'):
    return {'id':identifier,'name':identifier,'kind':kind,'status':'ready','max_width_mm':600,'max_pull_mm':600}


def standard():
    return {'code':'STD1','name':'Mixed run','machine_id':'DH1','material_id':'F1','mold_id':'CC1',
            'pull_mm':500,'seconds_per_cycle':4,'density':1.4,'setup_minutes':15,'waste_percent':3,
            'items':[{'product_id':'P1','cavity':4,'edge':True},{'product_id':'P2','cavity':2,'edge':False}]}


def test_api_permissions_and_machine_conflict(planning):
    c=planning.client
    c.cookies.clear()
    assert c.get('/api/production/machines').status_code==401
    c.cookies.set('napaco_session','reader')
    assert c.get('/api/production/machines').status_code==403
    assert c.post('/api/production/machines',json=machine()).status_code==403
    c.cookies.set('napaco_session','admin')
    r=c.post('/api/production/machines',json=machine());assert r.status_code==201,r.text
    assert c.post('/api/production/machines',json=machine()).status_code==409
    payload={**machine(),'name':'New','version':1}
    assert c.put('/api/production/machines/DH1',json=payload).json()['version']==2
    assert c.put('/api/production/machines/DH1',json=payload).status_code==409
    assert c.get('/api/production/machines?q=New&size=1').json()['total']==1
    assert c.get('/api/production/machines?size=101').status_code==422
    assert c.put('/api/production/machines/DH1',json={**payload,'id':'Other','version':2}).status_code==422


def test_standard_revision_routes_and_shared_weight(planning):
    c=planning.client
    c.post('/api/production/machines',json=machine())
    response=c.post('/api/production/standards',json=standard());assert response.status_code==201,response.text
    first=response.json()
    assert first['parameters']['sheet_weight_kg']==pytest.approx(0.175)
    assert first['snapshot']['machine']['max_width_mm']==600
    route=c.get('/api/production/standards/'+first['id']+'/route').json()
    assert route['items'][0]['stages']==['forming','cutting','edge']
    assert route['items'][1]['cavity']==2
    c.put('/api/production/machines/DH1',json={**machine(kind='automatic'),'version':1})
    response=c.post('/api/production/standards/'+first['id']+'/revisions',json={**standard(),'seconds_per_cycle':5})
    assert response.status_code==201,response.text
    second=response.json()
    assert second['revision']==2
    assert second['items'][0]['snapshot']['route']==['forming_cutting','edge']
    assert c.get('/api/production/standards/'+first['id']).json()['parameters']['seconds_per_cycle']==4
    assert c.get('/api/production/standards/'+first['id']+'/route').json()==route
    assert c.post('/api/production/standards/'+first['id']+'/revisions',json=standard()).status_code==409
    assert c.get('/api/production/standards').json()['total']==1
    assert c.get('/api/production/standards?history=true&product_id=P2').json()['total']==2
    assert c.post('/api/production/standards',json=standard()).status_code==409
    assert c.post('/api/production/standards',json={**standard(),'code':'bad','pull_mm':300}).status_code==422
    duplicate=standard();duplicate['code']='duplicate';duplicate['items'].append(duplicate['items'][0])
    assert c.post('/api/production/standards',json=duplicate).status_code==422
    with Session(planning.engine) as db:
        assert len(db.scalars(select(ProductionStandard)).all())==2
        assert len(db.scalars(select(ProductionStandardItem)).all())==4


def test_calendars_atomic_versions_break_override_and_restore(planning):
    c=planning.client
    for identifier in ['DH1','DH2']:assert c.post('/api/production/machines',json=machine(identifier)).status_code==201
    weekly={'0':{'shifts':[{'start':480,'end':1020}],'breaks':[{'start':720,'end':780}]}}
    response=c.put('/api/production/calendars',json={'versions':{'DH1':1,'DH2':1},'weekly':weekly})
    assert response.status_code==200,response.text
    params={'machine_id':['DH1','DH2'],'start':'2026-11-16','end':'2026-11-16'}
    result=c.get('/api/production/availability',params=params).json()
    assert len(result['machines'][0]['windows'])==2
    assert result['machines'][0]['windows'][0]['end']=='2026-11-16T12:00:00+07:00'
    # First machine passes its lock; second stale version must abort the entire operation.
    response=c.put('/api/production/calendars',json={'versions':{'DH1':2,'DH2':1},'weekly':{}})
    assert response.status_code==409
    with Session(planning.engine) as db:
        assert db.get(Machine,'DH1').version==2
        assert db.get(Machine,'DH1').calendar=={'_explicit':True,**weekly}
    exception={'day':'2026-11-16','windows':[{'start':480,'end':1020}],'note':'Run through break'}
    assert c.put('/api/production/calendars',json={'versions':{'DH1':2},'exceptions':[exception]}).status_code==200
    result=c.get('/api/production/availability',params=params).json()
    assert len(result['machines'][0]['windows'])==1
    assert len(result['machines'][1]['windows'])==2
    assert result['machines'][0]['windows'][0]['source']=='exception'
    assert c.put('/api/production/calendars',json={'versions':{'DH1':3},'remove_exceptions':['2026-11-16']}).status_code==200
    assert len(c.get('/api/production/availability',params=params).json()['machines'][0]['windows'])==2
    assert c.get('/api/production/availability',params={**params,'end':'2027-11-16'}).status_code==422
    invalid={'0':{'shifts':[{'start':480,'end':720},{'start':600,'end':780}]}}
    assert c.put('/api/production/calendars',json={'versions':{'DH1':4},'weekly':invalid}).status_code==422
    assert c.put('/api/production/machines/DH1',json={**machine(),'status':'maintenance','version':4}).status_code==200
    assert c.get('/api/production/availability',params=params).json()['machines'][0]['windows']==[]


def test_formula_endpoint_and_reference_search(planning):
    c=planning.client
    response=c.get('/api/production/film-calculation.js')
    assert response.status_code==200
    assert 'function filmCalculation' in response.text
    assert c.get('/api/production/references/molds?q=K1').json()['items'][0]['MaCC']=='CC1'
    assert c.get('/api/production/references/products?q=First').json()['total']==1
    assert c.get('/api/production/references/materials?q=PET').json()['total']==1
