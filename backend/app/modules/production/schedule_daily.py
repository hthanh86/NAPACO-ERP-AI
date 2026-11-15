"""Daily pointers to immutable schedule snapshots; caller owns ERP transaction."""
from datetime import datetime,timezone
from sqlalchemy import select
from app.modules.production.schedule_models import ScheduleDay,SchedulePlan
from app.modules.production.planning_service import ZONE
from app.modules.materials.inventory.allocation_service import fail,audit

SCOPE='forming'


def today():return datetime.now(ZONE).date()
def utc(value):return value.replace(tzinfo=timezone.utc) if value else None


def get_day(db,day,lock=False):
    query=select(ScheduleDay).where(ScheduleDay.day==day,ScheduleDay.scope==SCOPE)
    return db.scalar(query.with_for_update() if lock else query)


def metadata(row,day=None):
    return {'date':row.day if row else day or today(),'version':row.version if row else 0,
        'initial_plan_id':row.initial_plan_id if row else None,'initial_closed_at':utc(row.initial_closed_at) if row else None,
        'initial_closed_by':row.initial_closed_by if row else None,'update_plan_id':row.update_plan_id if row else None,
        'updated_at':utc(row.updated_at) if row else None,'scope':SCOPE}


def check_request(db,data,lock=False):
    day=today()
    if data.planning_day is not None and data.planning_day!=day:fail('Ngày lập kế hoạch đã thay đổi; tải lại bản cập nhật của ngày hiện tại.',409)
    row=get_day(db,day,lock)
    if data.day_version is not None and data.day_version!=(row.version if row else 0):
        fail('Phiên bản bản chốt/cập nhật theo ngày đã thay đổi; tải lại.',409)
    return metadata(row,day)


def source(db,day=None):
    """Reading a new day seeds a draft only; no implicit INSERT or close."""
    day=day or today();row=get_day(db,day)
    previous=row if row and row.update_plan_id else db.scalar(select(ScheduleDay).where(
        ScheduleDay.scope==SCOPE,ScheduleDay.day<day,ScheduleDay.update_plan_id.is_not(None)).order_by(ScheduleDay.day.desc()).limit(1))
    plan=db.get(SchedulePlan,previous.update_plan_id) if previous else db.scalar(select(SchedulePlan).order_by(SchedulePlan.version.desc()).limit(1))
    status=metadata(row,day);status['draft_from_day']=previous.day if previous and previous.day!=day else None
    status['source_plan_id']=plan.id if plan else None
    return plan,status


def update(db,user,plan,data):
    check_request(db,data,lock=True);day=today();row=get_day(db,day,True)
    if not row:row=ScheduleDay(day=day,scope=SCOPE,version=0);db.add(row)
    row.update_plan_id=plan.id;row.version+=1;row.updated_at=datetime.now(timezone.utc).replace(tzinfo=None);row.updated_by=user.id
    audit(db,user,'PRODUCTION_DAY_UPDATE',str(day),{'plan_id':plan.id,'version':row.version})
    db.flush();return metadata(row)


def close(db,user,data):
    if data.day!=today():fail('Chỉ chốt ngày điều hành hiện tại; ngày lịch sử chọn để xem/so sánh, không chốt ngược.')
    row=get_day(db,data.day,True)
    if (row.version if row else 0)!=data.day_version:fail('Bản cập nhật theo ngày đã thay đổi; tải lại trước khi chốt.',409)
    if row and row.initial_plan_id:fail('Bản đầu ngày đã chốt và được giữ nguyên.',409)
    plan,_=source(db,data.day)
    if not plan:fail('Chưa có bản kế hoạch đã lưu để chốt.')
    latest=db.scalar(select(SchedulePlan).order_by(SchedulePlan.version.desc()).limit(1))
    if plan.version!=data.plan_version or latest.id!=plan.id:fail('Kế hoạch đã thay đổi; tải lại bản cập nhật trước khi chốt.',409)
    if not plan.context:fail('Bản cũ chưa chụp đủ ngữ cảnh. Tính thử và lưu bản cập nhật mới trước khi chốt.')
    if not row:
        row=ScheduleDay(day=data.day,scope=SCOPE,version=0,updated_at=datetime.now(timezone.utc).replace(tzinfo=None),updated_by=user.id)
        db.add(row)
    if not row.update_plan_id:row.update_plan_id=plan.id
    row.initial_plan_id=plan.id;row.initial_closed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    row.initial_closed_by=user.id;row.version+=1
    audit(db,user,'PRODUCTION_DAY_CLOSE',str(row.day),{'plan_id':plan.id,'version':row.version,'note':data.note})
    db.flush();return metadata(row)
