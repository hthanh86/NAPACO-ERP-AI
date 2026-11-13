from datetime import datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, PrivateAttr
from typing import Annotated


class CriterionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(max_length=50)
    actual: str = Field(default='', max_length=2000)
    assessment: Literal['PASS', 'FAIL', 'NA']
    note: str = Field(default='', max_length=2000)


Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Point = tuple[Coordinate, Coordinate]
Stroke = Annotated[list[Point], Field(min_length=1, max_length=3000)]


class FormInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    code: str = Field(max_length=100)
    resin: Literal['PET', 'PP', 'PS', 'PVC']
    answers: list[CriterionInput] = Field(min_length=1, max_length=50)
    conclusion: Literal['PASS', 'FAIL']
    note: str = Field(default='', max_length=10000)
    signature: list[Stroke] = Field(min_length=1, max_length=100)

    @field_validator('signature')
    @classmethod
    def bounded_signature(cls, strokes):
        if sum(len(stroke) for stroke in strokes) > 15000:
            raise ValueError('Chữ ký vượt giới hạn 15000 điểm.')
        return strokes

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


class MappedAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64)
    actual: str = Field(default='', max_length=2000)
    assessment: Literal['PASS','FAIL','NA'] | None = None
    note: str = Field(default='', max_length=2000)


class MappedFormInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template_id: str = Field(min_length=1, max_length=36)
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    mapping_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    answers: list[MappedAnswer] = Field(min_length=1, max_length=200)
    conclusion: Literal['PASS','FAIL']
    signature: list[Stroke] = Field(default_factory=list, max_length=100)
    confirmation: str | None = Field(default=None, max_length=4096)
    reuse_signature: bool = False
    _signer: dict | None = PrivateAttr(default=None)

    @field_validator('signature')
    @classmethod
    def bounded_signature(cls, strokes):
        if sum(map(len, strokes)) > 15000:
            raise ValueError('Chữ ký vượt giới hạn 15000 điểm.')
        return strokes


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
    form: FormInput | None = None
    mapped_form: MappedFormInput | None = None
    parent_folder_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,255}$')
    evidence_manifest: list['UploadInput'] = Field(default_factory=list, max_length=500)
    staging_id: str | None = Field(default=None,pattern=r'^[0-9a-f-]{36}$')

    @field_validator('quantity', mode='before')
    @classmethod
    def required_quantity(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Hãy nhập số lượng kiểm tra là số nguyên dương.')
        return value

    @field_validator('quantity')
    @classmethod
    def whole_quantity(cls, value):
        if value != value.to_integral_value():
            raise ValueError('Số lượng kiểm tra phải là số nguyên dương.')
        return value

    @field_validator('standard_url')
    @classmethod
    def valid_standard(cls, value):
        from app.modules.qc.forms import REGISTRY
        if value in REGISTRY:
            return value
        return document_url(value)

    @field_validator('image_url')
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


class UploadInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=5*1024**4)
    modified: int = Field(ge=0)
    mime: str = Field(default='application/octet-stream', pattern=r'^[\w.+-]+/[\w.+-]+$')

    @field_validator('name')
    @classmethod
    def safe_name(cls, value):
        if any(ord(char)<32 for char in value) or '/' in value or '\\' in value:
            raise ValueError('Tên file không hợp lệ.')
        return value


QCInput.model_rebuild()
QCBatchInput.model_rebuild()
