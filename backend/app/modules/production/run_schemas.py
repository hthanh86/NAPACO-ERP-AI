from datetime import datetime
from uuid import uuid4
from decimal import Decimal
from typing import Annotated,Literal
from pydantic import Field,model_validator
from app.modules.production.planning_schemas import Input,Key,Positive,DayRule
from app.modules.production.history_schemas import HistorySelection
Kg=Annotated[Decimal,Field(ge=0,max_digits=24,decimal_places=8,allow_inf_nan=False)]
Qty=Annotated[int,Field(ge=0,le=1000000000,strict=True)]


class RunItemInput(Input):
    order_line_id:Key
    quantity:Annotated[int,Field(gt=0,le=1000000000,strict=True)]
    cavity:Annotated[int,Field(gt=0,le=100000,strict=True)]


class RunMaterialInput(Input):
    allocation_id:Key
    kg:Annotated[Decimal,Field(gt=0,max_digits=24,decimal_places=8,allow_inf_nan=False)]


class PlanningMaterialInput(Input):
    resin:str=Field(min_length=1,max_length=100)
    density:Positive
    thickness:Positive
    width:Positive
    color:str=Field('',max_length=500)
    grade:str=Field('',max_length=500)


class RunInput(Input):
    id:Key=Field(default_factory=lambda:str(uuid4()))
    standard_id:Key
    planning_material:PlanningMaterialInput|None=None
    mold_geometry_confirmed:bool|None=None
    machine_id:Key
    group_id:str=Field('',max_length=100)
    group_confirmed:bool=False
    parent_run_id:Key|None=None
    items:list[RunItemInput]=Field(min_length=1,max_length=100)
    materials:list[RunMaterialInput]=Field(default_factory=list,max_length=100)
    planned_cycles:Annotated[int,Field(gt=0,le=1000000000,strict=True)]|None=None
    seconds_per_cycle:Positive|None=None
    pull_mm:Positive|None=None
    sheet_weight_kg:Positive|None=None
    film_width_mm:Positive|None=None
    setup_minutes:float|None=Field(None,ge=0,le=100000,allow_inf_nan=False)
    waste_percent:float|None=Field(None,ge=0,le=100,allow_inf_nan=False)
    history_selection:HistorySelection|None=None
    note:str=Field(min_length=1,max_length=2000)
    version:int|None=Field(None,ge=1)

    @model_validator(mode='after')
    def distinct(self):
        if len({i.order_line_id for i in self.items})!=len(self.items):raise ValueError('CTĐH bị lặp.')
        if len({i.allocation_id for i in self.materials})!=len(self.materials):raise ValueError('Phân bổ bị lặp.')
        if len(self.items)>1 and (not self.group_id or not self.group_confirmed):raise ValueError('Cần mã nhóm và xác nhận ghép của người lập kế hoạch.')
        return self


class VersionInput(Input):
    version:int=Field(ge=1,strict=True)
    note:str=Field(min_length=1,max_length=2000)


class SetupInput(Input):
    id:Key=Field(default_factory=lambda:str(uuid4()))
    run_version:int=Field(ge=1,strict=True)
    stage:Literal['forming','cutting','edge']='forming'
    machine_id:Key
    order_line_id:Key|None=None
    tool_id:str=Field('',max_length=100)
    note:str=Field(min_length=1,max_length=2000)


class BindMaterialInput(VersionInput):
    allocation_id:Key
    planned_kg:Kg


class ShiftItemInput(Input):
    order_line_id:Key
    good:Qty
    ng:Qty


class ShiftSourceInput(Input):
    receipt_id:Key
    consumed_kg:Kg|None=None
    closing_kg:Kg|None=None

    @model_validator(mode='after')
    def sufficient(self):
        if self.consumed_kg is None and self.closing_kg is None:raise ValueError('Nhập tiêu hao hoặc cuối ca.')
        return self


class ShiftInput(Input):
    id:Key=Field(default_factory=lambda:str(uuid4()))
    setup_id:Key|None=None
    assignment_id:Key|None=None
    sample_qc_id:Key|None=None
    sample_qc_version:int|None=Field(None,ge=1,strict=True)
    source_hash:str|None=Field(None,pattern=r'^[a-f0-9]{64}$')
    run_version:int=Field(ge=1,strict=True)
    version:int|None=Field(None,ge=1)
    start:datetime
    end:datetime
    good_sheets:Qty
    ng_sheets:Qty
    seconds_per_cycle:Positive|None=None
    pull_mm:Positive|None=None
    sheet_weight_kg:Positive|None=None
    items:list[ShiftItemInput]=Field(min_length=1,max_length=100)
    sources:list[ShiftSourceInput]=Field(default_factory=list,max_length=100)
    note:str=Field(min_length=1,max_length=2000)
    pure_seconds:float|None=Field(None,ge=0,le=100000000,allow_inf_nan=False)
    setup_seconds:float|None=Field(None,ge=0,le=100000000,allow_inf_nan=False)

    @model_validator(mode='after')
    def distinct(self):
        for values,attr in [(self.items,'order_line_id'),(self.sources,'receipt_id')]:
            if len({getattr(i,attr) for i in values})!=len(values):raise ValueError('Dòng bị lặp.')
        if not self.start.tzinfo or not self.end.tzinfo:raise ValueError('Thời gian cần múi giờ, ví dụ +07:00.')
        if self.end<=self.start:raise ValueError('Giờ kết thúc phải sau bắt đầu.')
        if self.pure_seconds is not None and self.pure_seconds>(self.end-self.start).total_seconds():raise ValueError('Chạy thuần không vượt khoảng ca.')
        if (self.pure_seconds or 0)+(self.setup_seconds or 0)>(self.end-self.start).total_seconds():raise ValueError('Setup và chạy thuần không vượt khoảng ca.')
        return self


class DownstreamInput(Input):
    setup_id:Key|None=None
    id:Key
    stage:Literal['cutting','edge']
    forming_log_id:Key
    machine_id:Key
    wip_id:str=Field('',max_length=100)
    start:datetime
    end:datetime
    items:list[ShiftItemInput]=Field(min_length=1,max_length=100)
    note:str=Field(min_length=1,max_length=2000)
    pure_seconds:float|None=Field(None,ge=0,le=100000000,allow_inf_nan=False)
    setup_seconds:float|None=Field(None,ge=0,le=100000000,allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        if not self.start.tzinfo or not self.end.tzinfo or self.end<=self.start:raise ValueError('Giờ cần múi giờ và tăng dần.')
        if len({i.order_line_id for i in self.items})!=len(self.items):raise ValueError('CTĐH bị lặp.')
        if self.pure_seconds is not None and self.pure_seconds>(self.end-self.start).total_seconds():raise ValueError('Chạy thuần không vượt khoảng công đoạn.')
        if (self.pure_seconds or 0)+(self.setup_seconds or 0)>(self.end-self.start).total_seconds():raise ValueError('Setup và chạy thuần không vượt khoảng công đoạn.')
        return self


class CalendarDefaultInput(Input):
    version:int=Field(ge=0,strict=True)
    weekly:dict[Literal['0','1','2','3','4','5','6'],DayRule]
