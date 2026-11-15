from datetime import date,datetime
from typing import Literal,Annotated
from pydantic import Field,model_validator
from app.modules.production.planning_schemas import Input,Key
from app.modules.production.run_schemas import RunInput,VersionInput
from app.modules.production.history_schemas import HistorySelection


class StagePolicy(Input):
    order_line_id:Key
    stage:Literal['cutting','edge']
    machine_id:Key|None=None
    seconds_per_unit:float=Field(gt=0,le=1000000,allow_inf_nan=False)
    setup_minutes:float=Field(ge=0,le=100000,allow_inf_nan=False)
    wait_minutes:float=Field(ge=0,le=100000,allow_inf_nan=False)
    unit:Key
    mode:Literal['all','rolling']='all'
    handoff_quantity:Annotated[int,Field(gt=0,le=1000000000,strict=True)]|None=None
    handoff_quantities:list[Annotated[int,Field(gt=0,le=1000000000,strict=True)]]=Field(default_factory=list,max_length=1000)
    hold_machine_while_waiting:bool=False
    history_selection:HistorySelection|None=None
    history_evidence:dict|None=None

    @model_validator(mode='after')
    def batch(self):
        if self.mode=='rolling' and self.handoff_quantity is None and not self.handoff_quantities:
            raise ValueError('Cuốn chiếu cần lượng bàn giao hoặc danh sách lượng từng lần.')
        if self.handoff_quantity is not None and self.handoff_quantities:
            raise ValueError('Chọn lượng đều hoặc danh sách lượng riêng.')
        if self.mode=='all' and (self.handoff_quantity is not None or self.handoff_quantities):
            raise ValueError('Chờ toàn bộ không chia lô bàn giao.')
        return self


class JobPolicy(Input):
    run_id:Key
    ready_at:datetime|None=None
    line_order:list[Key]=Field(default_factory=list,max_length=100)
    stages:list[StagePolicy]=Field(default_factory=list,max_length=200)
    waiting:bool=False

    @model_validator(mode='after')
    def distinct(self):
        if self.ready_at and self.ready_at.tzinfo is None:raise ValueError('ready_at cần múi giờ.')
        if len(set(self.line_order))!=len(self.line_order):raise ValueError('CTĐH ưu tiên bị lặp.')
        if len({(s.order_line_id,s.stage) for s in self.stages})!=len(self.stages):raise ValueError('Công đoạn bị lặp.')
        return self


class RunChange(Input):
    config:RunInput
    split_from:Key|None=None


class EndRun(VersionInput):
    run_id:Key


class RunMove(VersionInput):
    run_id:Key
    machine_id:Key


class StopInput(Input):
    id:Key
    run_id:Key
    version:int|None=Field(None,ge=1)
    at:datetime
    duration_seconds:Annotated[int,Field(gt=0,le=31536000,strict=True)]|None=None
    hold_machine:bool=True
    enabled:bool=True
    note:str=Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def zoned(self):
        if self.at.tzinfo is None:raise ValueError('Thời điểm dừng cần múi giờ.')
        return self


class ScheduleInput(Input):
    base_version:int=Field(ge=0,strict=True)
    planning_day:date|None=None
    day_version:int|None=Field(None,ge=0,strict=True)
    start:datetime
    end:datetime
    order:list[Key]=Field(default_factory=list,max_length=200)
    unschedule:list[Key]=Field(default_factory=list,max_length=200)
    jobs:list[JobPolicy]=Field(default_factory=list,max_length=200)
    changes:list[RunChange]=Field(default_factory=list,max_length=50)
    moves:list[RunMove]=Field(default_factory=list,max_length=50)
    end_runs:list[EndRun]=Field(default_factory=list,max_length=50)
    stops:list[StopInput]=Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def valid(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:raise ValueError('Khoảng lịch cần múi giờ.')
        if self.end<=self.start or (self.end-self.start).total_seconds()>92*86400:
            raise ValueError('Khoảng lịch tăng dần, tối đa 92 ngày.')
        for values in [self.order,self.unschedule,[j.run_id for j in self.jobs],[c.config.id for c in self.changes],
                       [m.run_id for m in self.moves],[e.run_id for e in self.end_runs],[s.id for s in self.stops]]:
            if len(set(values))!=len(values):raise ValueError('Thao tác hoặc ID bị lặp.')
        changed={c.config.id for c in self.changes}
        if set(self.unschedule)&(set(self.order)|{j.run_id for j in self.jobs}|changed|{m.run_id for m in self.moves}):
            raise ValueError('Không đồng thời gỡ và bố trí/sửa cùng lần chạy.')
        if changed & {m.run_id for m in self.moves}:raise ValueError('Không gửi hai cấu hình chuyển cho cùng lệnh.')
        if (changed|{m.run_id for m in self.moves}) & {e.run_id for e in self.end_runs}:
            raise ValueError('Không đồng thời sửa và kết thúc cùng lệnh.')
        return self


class ScheduleSaveInput(ScheduleInput):
    preview_hash:str=Field(pattern='^[0-9a-f]{64}$')
    confirmations:list[str]=Field(default_factory=list,max_length=200)


class CloseDayInput(Input):
    day:date
    day_version:int=Field(ge=0,strict=True)
    plan_version:int=Field(ge=1,strict=True)
    note:str=Field(min_length=1,max_length=2000)
