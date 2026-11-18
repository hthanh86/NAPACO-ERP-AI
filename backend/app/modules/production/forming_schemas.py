"""Machine-first diary input; no second journal or material ledger."""
from typing import Literal
from pydantic import Field
from app.modules.production.run_schemas import ShiftInput
from app.modules.production.planning_schemas import Key,Input


class FormingInput(ShiftInput):
    machine_id:Key
    assignment_id:Key
    setup_id:Key|None=None
    episode_version:int|None=Field(None,ge=1,strict=True)
    source_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    note:str=Field(default='',max_length=2000)
    episode_action:Literal['continue','close']='continue'
    edit_reason:str=Field(default='',max_length=2000)


class EvidenceInput(Input):
    run_version:int=Field(ge=1,strict=True)
    machine_id:Key
    assignment_id:Key
    setup_id:Key|None=None
