"""Reusable weekly default in existing system_settings; machines may inherit it."""
import json
from sqlalchemy import select
from app.core.settings import SystemSetting
from app.modules.materials.inventory.allocation_service import lock_state,audit,fail
KEY='PRODUCTION_WEEKLY_DEFAULT_V1'


def read_default(db):
    setting=db.get(SystemSetting,KEY)
    if not setting:return {'version':0,'weekly':{}}
    try:return json.loads(setting.value)
    except (ValueError,TypeError):fail('Thiết lập lịch chung không hợp lệ; cần đối soát.',503)


def effective_week(db,machine,default=None):
    if machine.calendar and machine.calendar.get('_explicit'):
        return {k:v for k,v in machine.calendar.items() if k!='_explicit'}
    if machine.calendar:return machine.calendar
    return (default if default is not None else read_default(db))['weekly']


def save_default(db,user,data):
    lock_state(db)
    setting=db.scalar(select(SystemSetting).where(SystemSetting.key==KEY).with_for_update())
    old=read_default(db)
    if old['version']!=data.version:fail('Thiết lập đã thay đổi, nạp lại trước khi lưu.',409)
    result={'version':old['version']+1,'weekly':{k:v.model_dump() for k,v in data.weekly.items()}}
    if not setting:setting=SystemSetting(key=KEY);db.add(setting)
    setting.value=json.dumps(result,ensure_ascii=False)
    audit(db,user,'PRODUCTION_CALENDAR_DEFAULT',KEY,{'version':result['version']})
    return result
