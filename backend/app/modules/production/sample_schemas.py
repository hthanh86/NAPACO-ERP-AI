"""Sample inspection inputs reuse QC answers and signature coordinates."""
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from app.modules.production.run_schemas import SetupInput
from app.modules.production.planning_schemas import Input, Key
from app.modules.qc.schemas import MappedAnswer
from app.modules.materials.inventory.handover_schemas import HandoverSign


class EpisodeInput(SetupInput):
    valid_until: datetime
    source_forming_log_id: Key | None = None
    order_line_ids: list[Key] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def timezone_required(self):
        if not self.valid_until.tzinfo:raise ValueError('Giờ kết thúc đợt chạy cần múi giờ.')
        if len(set(self.order_line_ids))!=len(self.order_line_ids):raise ValueError('CTĐH bị lặp trong đợt chạy.')
        return self


class SampleDraft(Input):
    setup_id: Key
    version: int | None = Field(None,ge=1,strict=True)
    check_type: Literal['QC ĐẦU CA','QC GIỮA CA','QC CUỐI CA']='QC ĐẦU CA'
    template_id: str = Field(min_length=1,max_length=36)
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    mapping_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    quantity: int = Field(gt=0,le=1000000000,strict=True)
    answers: list[MappedAnswer] = Field(min_length=1,max_length=200)
    conclusion: Literal['PASS','FAIL']
    decision: Literal['normal','sort','stop']
    note: str = Field(default='',max_length=20000)
    parent_folder_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,255}$')

    @model_validator(mode='after')
    def decision_matches(self):
        if self.conclusion=='PASS' and self.decision!='normal':raise ValueError('Kết luận Đạt dùng quyết định Cho chạy hàng loạt.')
        if self.conclusion=='FAIL' and self.decision not in {'sort','stop'}:raise ValueError('NG cần chọn Cho chạy lọc hoặc Dừng chạy.')
        if self.conclusion=='FAIL' and not self.note.strip():raise ValueError('NG cần ghi tình trạng và phương án xử lý.')
        return self


class SampleSign(HandoverSign):
    role: Literal['technical','qc']


class SampleVersion(Input):
    version: int = Field(ge=1,strict=True)
    note: str = Field(min_length=1,max_length=2000)
