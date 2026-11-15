from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
Key = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=100)]
Kg = Annotated[Decimal,Field(gt=0,max_digits=24,decimal_places=8,allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)


class ReserveInput(Input):
    receipt_id: Key
    order_line_id: Key
    standard_id: Key
    kg: Kg
    note: str = Field('',max_length=1000)


class EditInput(Input):
    version: int = Field(ge=1,strict=True)
    held_kg: Decimal = Field(ge=0,max_digits=24,decimal_places=8,allow_inf_nan=False)
    note: str = Field(min_length=1,max_length=1000)


class IssueInput(Input):
    version: int = Field(ge=1,strict=True)
    production_order_id: Key
    kg: Kg
    note: str = Field('',max_length=1000)


class ReturnInput(Input):
    kg: Kg
    note: str = Field(min_length=1,max_length=1000)


class ConfirmInput(Input):
    kg: Kg


class TransferInput(Input):
    order_line_id: Key
    standard_id: Key
    production_order_id: Key
    kg: Kg
    measured_remaining_kg: Kg
    note: str = Field(min_length=1,max_length=1000)
