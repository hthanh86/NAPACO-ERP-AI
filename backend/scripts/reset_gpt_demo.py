"""Explicit local-only removal of the proven DEMO7/P14 datasets, after backup.

Preserve original orders/receipts, audit and document sequences. Reverse only
measured output added by the deleted journals; never reset all ERP data.
"""
import argparse,json
from pathlib import Path
from decimal import Decimal
from sqlalchemy import select,delete,update,func,or_
from sqlalchemy.orm import Session
from app.core import model_registry
from app.core.database import engine
from app.auth.models import User,LoginSession
from app.core.models import Audit
from app.modules.production.models import ProductionOrder as Run,ProductionSetup,FormingLog,ProductionWIP,CuttingLog,EBLog
from app.modules.production.run_models import ProductionOrderItem,ProductionAssignment,RunMaterial,ShiftItem,ShiftMaterial,DownstreamItem
from app.modules.production.schedule_models import SchedulePlan,ScheduleDay,RunStop
from app.modules.production.planning_models import ProductionStandard,ProductionStandardItem,Machine,MachineCalendarException
from app.modules.materials.inventory.models import FilmMovement
from app.modules.materials.inventory.allocation_models import MaterialAllocation,AllocationMovement
from app.modules.materials.inventory.handover_models import MaterialHandover
from app.modules.materials.inventory.allocation_service import lock_state
from app.modules.materials.purchasing.models import FilmPO,FilmLine
from app.modules.materials.receiving.models import FilmReceipt
from app.modules.materials.models import FilmMaterial
from app.modules.orders.models import Order,OrderLine
from app.modules.products.models import Product
from app.modules.customers.models import Customer
from app.modules.qc.models import QualityCheck
from app.modules.qc.template_models import QCTemplate
from app.modules.qc.job_models import QCJob

REPORT=Path('/app/reports/reset-gpt-demo-20261115.json')
def owned(value):return bool(value and (value.startswith('DEMO7') or value.startswith('P14')))
def scope(column):return or_(column.startswith('DEMO7',autoescape=True),column.startswith('P14',autoescape=True))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if engine.url.host!='mysql':raise RuntimeError('Chỉ chạy trên Docker local.')
    with Session(engine) as db:
        lock_state(db)
        runs=list(db.scalars(select(Run).where(scope(Run.id))))
        ids=[r.id for r in runs]
        if not ids:print('Không còn DEMO7/P14; không xóa thêm.');return
        standards=list(db.scalars(select(ProductionStandard).where(scope(ProductionStandard.code))))
        std=[s.id for s in standards]
        allocations=list(db.scalars(select(MaterialAllocation).where(MaterialAllocation.standard_id.in_(std))))
        aids=[a.id for a in allocations]
        assert not db.scalar(select(Run.id).where(Run.standard_id.in_(std),~Run.id.in_(ids)).limit(1)), 'Định mức giả có LSX ngoài phạm vi.'
        plans=[p for p in db.scalars(select(SchedulePlan)) if p.request.get('order') and all(owned(i) for i in p.request['order'])]
        pids=[p.id for p in plans]
        logs=list(db.scalars(select(FormingLog).where(FormingLog.production_order_id.in_(ids))));lids=[l.id for l in logs]
        setups=list(db.scalars(select(ProductionSetup.id).where(ProductionSetup.production_order_id.in_(ids))))
        movements=list(db.scalars(select(FilmMovement.id).where(FilmMovement.production_order_id.in_(ids))))
        qids=list(db.scalars(select(QualityCheck.id).where(QualityCheck.production_order_id.in_(ids))))
        report={'deleted_run_ids':ids,'deleted_plan_ids':pids,'deleted_logs':lids,'deleted_movements':movements,
            'deleted_allocations':aids,'deleted_qc':qids,'reversed_produced':{},'backup':'backups/napaco-pre-reset-gpt-demo-20261115.sql.gz'}
        for ct,total in db.execute(select(ShiftItem.order_line_id,func.sum(ShiftItem.good_qty)).where(ShiftItem.log_id.in_(lids)).group_by(ShiftItem.order_line_id)):
            line=db.get(OrderLine,ct)
            assert line and line.produced>=total,(ct,'Sản lượng không khớp, không tự hoàn nguyên.')
            report['reversed_produced'][ct]={'before':str(line.produced),'subtract':str(total),'after':str(line.produced-total)}
            if args.apply:line.produced-=total
        print(json.dumps(report,ensure_ascii=False))
        if not args.apply:return
        def remove(model,condition):db.execute(delete(model).where(condition),execution_options={'synchronize_session':False})
        remove(QCJob,QCJob.qc_id.in_(qids));remove(QualityCheck,QualityCheck.id.in_(qids))
        remove(DownstreamItem,DownstreamItem.forming_log_id.in_(lids))
        for model in [CuttingLog,EBLog]:remove(model,or_(model.order_ref.in_(lids),scope(model.id)))
        remove(ProductionWIP,ProductionWIP.forming_log_id.in_(lids))
        remove(ShiftItem,ShiftItem.log_id.in_(lids));remove(ShiftMaterial,ShiftMaterial.log_id.in_(lids))
        remove(FormingLog,FormingLog.id.in_(lids));remove(ProductionSetup,ProductionSetup.id.in_(setups))
        remove(MaterialHandover,MaterialHandover.run_id.in_(ids))
        # Refuse external uses before removing any allocation or stock evidence.
        assert not db.scalar(select(AllocationMovement.movement_id).where(AllocationMovement.allocation_id.in_(aids),~AllocationMovement.movement_id.in_(movements)).limit(1))
        remove(AllocationMovement,AllocationMovement.movement_id.in_(movements))
        remove(FilmMovement,FilmMovement.id.in_(movements))
        remove(RunMaterial,RunMaterial.run_id.in_(ids));remove(ProductionOrderItem,ProductionOrderItem.run_id.in_(ids))
        remove(ProductionAssignment,ProductionAssignment.run_id.in_(ids));remove(RunStop,RunStop.run_id.in_(ids))
        db.execute(update(Run).where(Run.id.in_(ids)).values(parent_run_id=None),execution_options={'synchronize_session':False})
        remove(Run,Run.id.in_(ids))
        for day in db.scalars(select(ScheduleDay)):
            pointers={p for p in [day.initial_plan_id,day.update_plan_id] if p}
            if pointers & set(pids):
                assert pointers<=set(pids),'Ngày có cả kế hoạch ngoài phạm vi.'
                db.delete(day)
        db.flush();remove(SchedulePlan,SchedulePlan.id.in_(pids))
        remove(MaterialAllocation,MaterialAllocation.id.in_(aids))
        remove(ProductionStandardItem,ProductionStandardItem.standard_id.in_(std));remove(ProductionStandard,ProductionStandard.id.in_(std))
        remove(MachineCalendarException,scope(MachineCalendarException.machine_id));remove(Machine,scope(Machine.id))
        remove(QCTemplate,scope(QCTemplate.form_code))
        remove(FilmReceipt,scope(FilmReceipt.id));remove(FilmLine,scope(FilmLine.id));remove(FilmPO,scope(FilmPO.id))
        remove(OrderLine,scope(OrderLine.id));remove(Order,scope(Order.id))
        remove(Product,scope(Product.id));remove(Customer,Customer.id=='P14');remove(FilmMaterial,scope(FilmMaterial.id))
        remove(LoginSession,scope(LoginSession.user_id));remove(User,scope(User.id))
        admin=db.scalar(select(User).where(User.role=='LOCAL_ADMIN',User.active.is_(True)).limit(1))
        db.add(Audit(user_id=admin.id,action='USER_REQUESTED_GPT_DEMO_RESET',entity_id='DEMO7+P14',details=report))
        db.commit()
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('Đã xóa đúng DEMO7/P14, giữ audit, sequence, đơn và lô gốc.')


if __name__=='__main__':main()
