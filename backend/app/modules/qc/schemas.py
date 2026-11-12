from datetime import datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator

CheckType = Literal['QC NVL', 'QC ĐẦU CA', 'QC GIỮA CA', 'QC CUỐI CA']
ObjectType = Literal['NVL', 'SETUP', 'HUT', 'CAT', 'EB']


def document_url(value):
    value = value.strip()
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
                parsed.username or parsed.password or any(c.isspace() or ord(c) < 32 for c in value) or
                '\\' in value):
            raise ValueError()
    except ValueError:
        raise ValueError('URL phải là liên kết HTTP/HTTPS hợp lệ, không chứa thông tin đăng nhập.') from None
    return value


class QCInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    check_type: CheckType
    object_type: ObjectType
    object_id: str = Field(min_length=1, max_length=100)
    checked_at: datetime
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8, allow_inf_nan=False)
    result: str = Field(min_length=1, max_length=500)
    standard_url: str = Field(default='', max_length=10000)
    note: str = Field(default='', max_length=20000)
    image_url: str = Field(default='', max_length=10000)
    version: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator('quantity')
    @classmethod
    def whole_quantity(cls, value):
        if value != value.to_integral_value():
            raise ValueError('Số lượng kiểm tra phải là số nguyên dương.')
        return value

    @field_validator('standard_url', 'image_url')
    @classmethod
    def valid_url(cls, value):
        return document_url(value)


class QCBatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[QCInput] = Field(min_length=1, max_length=10)

    @field_validator('items')
    @classmethod
    def unique_iqc_receipts(cls, values):
        if any(item.check_type != 'QC NVL' or item.object_type != 'NVL' for item in values):
            raise ValueError('Tạo hàng loạt chỉ dùng cho IQC NVL.')
        ids = [item.object_id.casefold() for item in values]
        if len(set(ids)) != len(ids):
            raise ValueError('Một phiếu nhập NVL chỉ được xuất hiện một lần trong lô QC.')
        return values
