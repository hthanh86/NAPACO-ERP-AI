from typing import Literal
from pydantic import Field
from app.modules.production.planning_schemas import Input,Key,Positive


class HistoryItem(Input):
    order_line_id:Key
    cavity:int=Field(gt=0,le=100000,strict=True)


class HistoryQuery(Input):
    standard_id:Key
    machine_id:Key
    items:list[HistoryItem]=Field(min_length=1,max_length=100)
    stage:Literal['forming','cutting','edge']='forming'
    unit:str=Field('',max_length=100)
    pull_mm:Positive|None=None
    allocation_ids:list[Key]=Field(default_factory=list,max_length=100)


class HistorySelection(Input):
    kind:Literal['approved_standard','latest','statistics','near_latest']
    context_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    run_id:Key|None=None
