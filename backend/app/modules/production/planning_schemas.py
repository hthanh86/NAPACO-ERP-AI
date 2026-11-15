from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Positive = Annotated[float, Field(gt=0, le=1000000, allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class MachineInput(Input):
    id: Key
    name: Annotated[str, Field(min_length=1,max_length=200)]
    kind: Literal['automatic','semi_automatic','cutting','edge','unclassified']
    status: Literal['ready','running','maintenance','fault','inactive']
    max_width_mm: Positive | None = None
    max_pull_mm: Positive | None = None
    notes: str = Field('',max_length=2000)
    version: int | None = Field(None,ge=1)


class ItemInput(Input):
    product_id: Key
    cavity: int = Field(gt=0,le=100000,strict=True)
    edge: bool = False


class StandardInput(Input):
    code: Key
    name: str = Field(min_length=1,max_length=200)
    machine_id: Key
    material_id: Key
    mold_id: Key
    pull_mm: Positive
    seconds_per_cycle: Positive
    density: Positive  # g/cm³; original purchasing convention
    setup_minutes: float = Field(ge=0,le=100000,allow_inf_nan=False)
    waste_percent: float = Field(ge=0,le=100,allow_inf_nan=False)
    active: bool = True
    approved: bool = False
    items: list[ItemInput] = Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def distinct(self):
        if len({i.product_id for i in self.items}) != len(self.items):
            raise ValueError('Sản phẩm không được lặp trong cấu hình.')
        return self


class Span(Input):
    start: int = Field(ge=0,lt=1440,strict=True)
    end: int = Field(gt=0,le=1440,strict=True)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('Khoảng giờ phải tăng; ca qua đêm chia tại 00:00.')
        return self


def check_spans(spans):
    ordered = sorted(spans,key=lambda s:s.start)
    if any(a.end > b.start for a,b in zip(ordered,ordered[1:])):
        raise ValueError('Các khoảng giờ không được chồng nhau.')
    return ordered


class DayRule(Input):
    shifts: list[Span] = Field(default_factory=list,max_length=24)
    breaks: list[Span] = Field(default_factory=list,max_length=24)

    @model_validator(mode='after')
    def valid(self):
        self.shifts = check_spans(self.shifts)
        self.breaks = check_spans(self.breaks)
        if any(not any(s.start<=b.start and b.end<=s.end for s in self.shifts) for b in self.breaks):
            raise ValueError('Giờ nghỉ phải nằm trong một ca làm.')
        return self


class ExceptionInput(Input):
    day: date
    windows: list[Span] = Field(max_length=24)
    note: str = Field('',max_length=500)

    @model_validator(mode='after')
    def valid(self):
        self.windows = check_spans(self.windows)
        return self


class CalendarInput(Input):
    versions: dict[Key, Annotated[int,Field(ge=1)]] = Field(min_length=1,max_length=100)
    weekly: dict[Literal['0','1','2','3','4','5','6'],DayRule] | None = None
    inherit_default: bool = False
    exceptions: list[ExceptionInput] = Field(default_factory=list,max_length=93)
    remove_exceptions: list[date] = Field(default_factory=list,max_length=93)

    @model_validator(mode='after')
    def distinct(self):
        if self.inherit_default and self.weekly is not None:
            raise ValueError('Chọn lịch riêng hoặc kế thừa mặc định.')
        days = [e.day for e in self.exceptions]
        if len(set(days)) != len(days) or set(days)&set(self.remove_exceptions):
            raise ValueError('Ngày ngoại lệ trùng nhau.')
        return self
