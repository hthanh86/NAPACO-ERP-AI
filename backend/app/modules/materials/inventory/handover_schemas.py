from typing import Literal
from pydantic import Field,field_validator
from app.modules.materials.inventory.allocation_schemas import Input,Key,Kg
from app.modules.qc.schemas import Stroke


class HandoverDraft(Input):
    allocation_id:Key
    production_order_id:Key
    kg:Kg
    version:int=Field(ge=1,strict=True)
    note:str=Field('',max_length=1000)


class HandoverVersion(Input):
    version:int=Field(ge=1,strict=True)


class HandoverSign(HandoverVersion):
    role:Literal['issue','receipt']
    signature:list[Stroke]=Field(min_length=1,max_length=100)
    confirmation:str|None=Field(None,max_length=8192)

    @field_validator('signature')
    @classmethod
    def bounded(cls,strokes):
        if sum(map(len,strokes))>15000:raise ValueError('Chữ ký vượt 15000 điểm.')
        if not any(len(s)>=2 and len(set(s))>=2 for s in strokes):raise ValueError('Hãy ký; chữ ký không được chỉ có một điểm.')
        return strokes
