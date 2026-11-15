"""Retained, explicitly synthetic phase 1–4 scenarios in this local compose DB.

No existing business document is edited, no Drive request is made. Identity and
the clock are simulated only inside this process. Synthetic users cannot log in.
Reruns return the existing manifest; failures roll back the whole seed transaction.
"""
import argparse
import json
from copy import deepcopy
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from cryptography.fernet import Fernet
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core import model_registry
from app.core.database import engine
from app.auth.models import User
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.orders.models import Order,OrderLine
from app.modules.materials.models import FilmMaterial
from app.modules.materials.purchasing.models import FilmPO,FilmLine
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.inventory.allocation_models import MaterialAllocation
from app.modules.materials.inventory import allocation_service as inventory,handover_service as handovers
from app.modules.materials.inventory.handover_schemas import HandoverSign
from app.modules.production.models import ProductionOrder,ProductionSetup
from app.modules.production.planning_models import Machine,ProductionStandard,ProductionStandardItem
from app.modules.production.run_models import ProductionOrderItem,RunMaterial
from app.modules.production.run_schemas import RunInput,VersionInput
from app.modules.production.forming_schemas import FormingInput
from app.modules.production.sample_schemas import EpisodeInput,SampleDraft,SampleSign,SampleVersion
from app.modules.production.schedule_schemas import ScheduleInput,ScheduleSaveInput
from app.modules.production import run_service as runs,release_service as release,sample_service as samples,forming_service as forming,schedule_service as schedule,schedule_daily
from app.modules.materials.inventory.handover_sources import source_hash,source_contexts
from app.modules.qc import mapping,jobs
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate

PREFIX='P14'
NOTE='[P14 - DỮ LIỆU GIẢ LOCAL] Không phải sản xuất/chữ ký Google thực tế.'
REPORT=Path('/app/reports/production-phase14-demo.json')
STROKES=[[(.1,.2),(.3,.6),(.8,.4)]]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',required=True,action='store_true');parser.parse_args()
    if engine.url.host!='mysql':raise RuntimeError('Chỉ chạy trong Docker compose local.')
    if REPORT.exists():
        print('Giữ nguyên dữ liệu P14; manifest đã có tại',REPORT);return
    actual_now=release.now();clock=SimpleNamespace(now=actual_now-timedelta(days=1,hours=2))
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=clock.now.replace(tzinfo=runs.ZONE)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    cipher=Fernet(Fernet.generate_key())
    def identity(request,db,user):
        return {'user_id':user.id,'name':user.name,'email':user.email,'google_subject':'SYNTHETIC-LOCAL:'+user.id,
            'session':request.session,'simulation':True}
    def mark_confirmation(value):
        proof=json.loads(cipher.decrypt(value.encode()));proof['method']='synthetic_local_test'
        return cipher.encrypt(json.dumps(proof).encode()).decode()
    manifest={'prefix':PREFIX,'synthetic':True,'note':NOTE,'created_at':actual_now.isoformat(),'cases':{}}
    with Session(engine,expire_on_commit=False) as db,patch.object(release,'now',lambda:clock.now),\
            patch.object(runs,'datetime',Clock),patch.object(handovers,'now',lambda:clock.now),\
            patch.object(handovers,'identity',identity),patch.object(samples,'identity',identity),\
            patch.object(handovers,'cipher',lambda:cipher),patch.object(samples,'cipher',lambda:cipher),\
            patch.object(jobs,'enqueue',lambda *args,**kwargs:None):
        inventory.lock_state(db)
        if db.get(Customer,PREFIX):raise RuntimeError('Đã có P14 nhưng thiếu manifest; dừng để giữ dữ liệu, không tạo lặp.')
        issuer=User(id='P14_TECH',name='[GIẢ LOCAL] Kỹ thuật/người cấp',role='LOCAL_ADMIN',active=False,email='p14-tech@example.test',source={'simulation':True})
        receiver=User(id='P14_QC',name='[GIẢ LOCAL] QC/người nhận',role='LOCAL_ADMIN',active=False,email='p14-qc@example.test',source={'simulation':True})
        db.add_all([issuer,receiver,Customer(id=PREFIX,name='[GIẢ LOCAL] Kiểm tra giai đoạn 1–4')]);db.flush()
        db.add_all([Product(id='P14_SP_A',customer_id=PREFIX,name='[GIẢ LOCAL] Sản phẩm A',unit='Cái'),
            Product(id='P14_SP_B',customer_id=PREFIX,name='[GIẢ LOCAL] Sản phẩm B',unit='Cái'),
            FilmMaterial(id='P14_FILM',grade='PET',width=500,thickness=.5)]);db.flush()
        machine_ids=['P14_A_DH01','P14_A_DH02','P14_AB_DH','P14_QUEUE_DH','P14_PASS_DH','P14_SORT_DH','P14_STOP_DH','P14_RESTART_DH','P14_NVL_DH','P14_DRAFT_DH','P14_CAT']
        calendar={str(i):{'shifts':[{'start':0,'end':1440}],'breaks':[{'start':720,'end':780}]} for i in range(7)}
        db.add_all([Machine(id=m,name='[GIẢ LOCAL] '+m,kind='cutting' if m=='P14_CAT' else 'semi_automatic',status='ready',calendar=calendar,notes=NOTE) for m in machine_ids]);db.flush()
        standards={}
        for name,items in [('A',[('A',4)]),('B',[('B',2)]),('AB',[('A',4),('B',2)])]:
            row=ProductionStandard(id=str(uuid4()),code='P14_'+name,revision=1,machine_id='P14_A_DH01',material_id='P14_FILM',mold_id='P14_MOLD',name=NOTE,
                active=True,created_by=issuer.id,parameters={'seconds_per_cycle':4,'pull_mm':500,'sheet_weight_kg':.175,'setup_minutes':0,'waste_percent':0,'density':1.4},
                snapshot={'machine':{'id':'P14_A_DH01','kind':'semi_automatic'},'material':{'id':'P14_FILM','width':500,'thickness':.5},'mold':{'id':'P14_MOLD','Dai_Khuon':400}})
            db.add(row);db.flush();standards[name]=row
            db.add_all([ProductionStandardItem(standard_id=row.id,product_id='P14_SP_'+product,cavity=cavity,edge=False,
                snapshot={'name':'[GIẢ LOCAL] Sản phẩm '+product,'product_id':'P14_SP_'+product,'unit':'Cái','route':['forming','cutting']}) for product,cavity in items]);db.flush()
        source={'spreadsheet_id':'P14_LOCAL_SNAPSHOT_ONLY','sheet_id':0,'sheet_title':'Mẫu giả local','title':'P14 mẫu giả, chưa xuất Drive',
            'row_count':8,'column_count':6,'grid':{'rowData':[]},'merges':[],'theme':{},'truncated':False}
        layout=mapping.validate(source,mapping.MappingInput(fields=[{'id':'look','name':'Ngoại quan','kind':'INPUT','cell':'B2','assessment_cell':'C2','reviewed':True},
            {'id':'lsx','name':'Lệnh sản xuất','kind':'ERP','cell':'D2','source':'production_order_id','reviewed':True}],signature_cell='A5',signature_end_cell='C8'),'QC ĐẦU CA',approve=True)
        # Product-scoped snapshots avoid replacing existing users' template choices.
        templates={}
        for product in ['A','B']:
            row=QCTemplate(id=str(uuid4()),form_code='P14_LOCAL_'+product,form_name='[GIẢ LOCAL] Mẫu kiểm thử '+product,check_type='QC ĐẦU CA',object_type='SETUP',
                product_id='P14_SP_'+product,spreadsheet_id=source['spreadsheet_id'],sheet_id=0,version=1,status='ACTIVE',created_by=issuer.id,
                approved_by=issuer.id,approved_at=clock.now,source_matches=True,source_snapshot=source,source_hash=mapping.source_hash(source),field_mapping=layout)
            db.add(row);templates[product]=row
        db.flush()
        # AB contains two CTĐH of product A; its shared template stays scoped to
        # synthetic products, without registering a global fake template.
        cases={}
        definitions=[('DRAFT','P14_DRAFT_DH','A'),('NVL','P14_NVL_DH','A'),('A','P14_A_DH01','A'),('AB','P14_AB_DH','AB'),
            ('QUEUE_A','P14_QUEUE_DH','A'),('QUEUE_B','P14_QUEUE_DH','B'),('PASS','P14_PASS_DH','A'),('SORT','P14_SORT_DH','A'),
            ('STOP','P14_STOP_DH','A'),('RESTART','P14_RESTART_DH','A')]
        for name,machine,kind in definitions:
            key='P14_'+name;standard=standards['A' if kind=='AB' else kind]
            db.add(Order(id=key,customer_id=PREFIX,po_number=key,source={'simulation':True}));db.flush()
            entries=[('A',4),('A',4)] if kind=='AB' else [(kind,4 if kind=='A' else 2)]
            lines=[]
            for index,(product,cavity) in enumerate(entries):
                line=OrderLine(id=key+'_CT_'+('AB'[index] if kind=='AB' else product),order_id=key,product_id='P14_SP_'+product,quantity=1000,produced=0,unit='Cái')
                db.add(line);lines.append((line,cavity))
            db.add(FilmPO(id=key,status='Đang đặt'));db.flush()
            db.add(FilmLine(id=key,po_id=key,material_id='P14_FILM',resin='PET',quantity=100,status='Nhận một phần'));db.flush()
            db.add(FilmReceipt(id=key+'_LOT',line_id=key,quantity=100,status='OK',receipt_date=clock.now.strftime('%Y-%m-%d')));db.flush()
            allocation=inventory.reserve(db,issuer,SimpleNamespace(receipt_id=key+'_LOT',order_line_id=lines[0][0].id,standard_id=standard.id,kg=Decimal(20),note=NOTE))
            config=RunInput(id=key,standard_id=standard.id,machine_id=machine,group_id=key if kind=='AB' else '',group_confirmed=kind=='AB',
                items=[{'order_line_id':line.id,'quantity':100,'cavity':cavity} for line,cavity in lines],materials=[{'allocation_id':allocation['id'],'kg':'20'}],note=NOTE)
            runs.save_run(db,issuer,config)
            cases[name]=SimpleNamespace(run=db.get(ProductionOrder,key),config=config,allocation=db.get(MaterialAllocation,allocation['id']),lines=lines,kind=kind)
            manifest['cases'][name]={'run_id':key,'machine':machine,'ctdh':[line.id for line,cavity in lines],'lot':key+'_LOT','handovers':[],'logs':[],'samples':[]}
        def plan():
            base=schedule.latest(db);_,day=schedule_daily.source(db)
            raw=deepcopy(base.request) if base else {'start':clock.now.replace(tzinfo=runs.ZONE).isoformat(),'end':(actual_now+timedelta(days=3)).replace(tzinfo=runs.ZONE).isoformat(),'order':[],'jobs':[]}
            # Keep existing jobs and append only these synthetic LSX.
            raw['order']=list(dict.fromkeys(raw['order']+list(c.run.id for c in cases.values())))
            raw['jobs']+= [{'run_id':c.run.id,'stages':[{'order_line_id':line.id,'stage':'cutting','machine_id':'P14_CAT',
                'seconds_per_unit':1,'setup_minutes':0,'wait_minutes':0,'unit':'Cái','mode':'rolling','handoff_quantity':4} for line,cavity in c.lines]} for c in cases.values()]
            raw.update(base_version=base.version if base else 0,planning_day=schedule_daily.today(),day_version=day['version'])
            data=ScheduleInput(**raw);preview=schedule.preview(db,issuer,data)
            return schedule.save(db,issuer,ScheduleSaveInput(**data.model_dump(),preview_hash=preview['preview_hash'],confirmations=[w['code'] for w in preview['warnings']]))
        initial=plan();manifest['initial_plan']=initial['id']
        for name,c in cases.items():
            if name!='DRAFT':release.release(db,issuer,c.run.id,VersionInput(version=c.run.version,note=NOTE))
            manifest['cases'][name]['official_code']=c.run.official_code
        def handover(name,kg,state='received'):
            c=cases[name];doc=handovers.create_issue(db,issuer,c.allocation.id,SimpleNamespace(version=c.allocation.version,production_order_id=c.run.id,kg=Decimal(kg),note=NOTE))
            for role,user in ([('issue',issuer),('receipt',receiver)] if state=='received' else [('issue',issuer)] if state=='awaiting_receipt' else []):
                request=SimpleNamespace(session='SYNTHETIC:'+user.id)
                data=HandoverSign(version=doc['version'],role=role,signature=STROKES)
                proof=handovers.confirm_signature(db,user,request,handovers.lock(db,doc['id']),data)
                doc=handovers.sign(db,user,request,doc['id'],data.model_copy(update={'confirmation':mark_confirmation(proof['confirmation'])}))
            manifest['cases'][name]['handovers'].append({'id':doc['id'],'state':state,'kg':kg})
            return doc
        def sample(name,assessment='PASS',decision='normal',signed=True):
            c=cases[name]
            episode=samples.create_episode(db,issuer,c.run.id,EpisodeInput(run_version=c.run.version,machine_id=c.run.machine_id,
                valid_until=(actual_now+timedelta(hours=12)).replace(tzinfo=runs.ZONE),note=NOTE))
            template=templates['B' if c.kind=='B' else 'A']
            doc=samples.save(db,issuer,SampleDraft(setup_id=episode['id'],template_id=template.id,source_hash=template.source_hash,mapping_hash=mapping.digest(template.field_mapping),
                quantity=3,answers=[{'id':'look','actual':NOTE,'assessment':assessment}],conclusion='FAIL' if assessment=='FAIL' else 'PASS',decision=decision,note=NOTE,parent_folder_id='P14_LOCAL_NO_DRIVE'))
            if signed:
                for role,user in [('technical',issuer),('qc',receiver)]:
                    request=SimpleNamespace(session='SYNTHETIC:'+user.id);data=SampleSign(version=doc['version'],role=role,signature=STROKES)
                    proof=samples.confirm(db,user,request,doc['id'],data)
                    doc=samples.sign(db,user,request,doc['id'],data.model_copy(update={'confirmation':mark_confirmation(proof['confirmation'])}))
                obj=db.get(QualityCheck,doc['id']);obj.source={**(obj.source or {}),'simulation':True,'qc_bundle':{'pending':False,'error':'Dữ liệu giả local; chưa xuất Google Drive.'}}
            c.episode=episode;c.sample=doc
            manifest['cases'][name]['samples'].append({'id':doc['id'],'state':doc['state'],'decision':decision,'setup_id':episode['id']})
            return doc
        def log(name,close=True):
            c=cases[name];start=clock.now+timedelta(seconds=1);clock.now+=timedelta(minutes=15)
            context=source_contexts(db,[c.run.id])[c.run.id]
            data=FormingInput(run_version=c.run.version,machine_id=c.run.machine_id,assignment_id=release.assignment(db,c.run.id,'forming').id,
                setup_id=c.episode['id'],episode_version=samples.info(db.get(ProductionSetup,c.episode['id']))['version'],sample_qc_id=c.sample['id'],sample_qc_version=c.sample['version'],source_hash=source_hash(context),
                start=start.replace(tzinfo=runs.ZONE),end=clock.now.replace(tzinfo=runs.ZONE),good_sheets=5,ng_sheets=0,
                items=[{'order_line_id':line.id,'good':10 if c.kind=='AB' else 5*cavity,'ng':0} for line,cavity in c.lines],sources=[{'receipt_id':c.run.id+'_LOT','consumed_kg':'1'}],episode_action='close' if close else 'continue',note=NOTE)
            result=forming.save(db,issuer,c.run.id,data);manifest['cases'][name]['logs'].append(result['id'])
            return result
        handover('NVL',5);handover('NVL',3,'awaiting_receipt');handover('NVL',2,'draft')
        for name in ['A','AB','QUEUE_B','PASS','SORT','STOP','RESTART']:handover(name,10)
        sample('A');log('A')
        clock.now=actual_now-timedelta(hours=1)
        c=cases['A'];config=c.config.model_copy(update={'machine_id':'P14_A_DH02','version':c.run.version,'note':NOTE+' Đổi máy cùng LSX'})
        # Use the native planning mutation and retain its saved version/history.
        base=schedule.latest(db);_,day=schedule_daily.source(db)
        raw={**base.request,'base_version':base.version,'planning_day':schedule_daily.today(),'day_version':day['version'],
            'changes':[{'config':config.model_dump(mode='json')}]}
        data=ScheduleInput(**raw);preview=schedule.preview(db,issuer,data)
        saved=schedule.save(db,issuer,ScheduleSaveInput(**data.model_dump(),preview_hash=preview['preview_hash'],confirmations=[w['code'] for w in preview['warnings']]))
        manifest['updated_plan']=saved['id'];manifest['cases']['A']['machine']='P14_A_DH02'
        sample('A');log('A')
        # Finish all recorded examples before now, keep ready/draft forms open.
        sample('AB');log('AB');sample('QUEUE_B');log('QUEUE_B')
        sample('RESTART');log('RESTART');sample('RESTART',signed=False)
        sample('PASS');sample('SORT','FAIL','sort');sample('STOP','FAIL','stop')
        inventory.audit(db,issuer,'PRODUCTION_LOCAL_SYNTHETIC_DATA',PREFIX,{'note':NOTE,'manifest':manifest})
        db.commit()
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
    print('Đã giữ lại',len(cases),'LSX giả; manifest:',REPORT)


if __name__=='__main__':main()
