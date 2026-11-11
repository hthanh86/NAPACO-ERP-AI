from datetime import date
from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, Field, model_validator

STATUSES = ['Chờ sản xuất', 'Đang làm khuôn', 'Đang sản xuất', 'Xong', 'Kết thúc', 'Hủy']
Number = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]


class LineInput(BaseModel):
    id: str | None = None
    product_id: str = Field(min_length=1, max_length=100)
    quantity: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)]
    price: Number
    unit: str = Field(min_length=1, max_length=100)
    delivery_date: date
    note: str = Field(default='', max_length=10000)
    staff_id: str | None = None
    status: str = 'Chờ sản xuất'

    @model_validator(mode='after')
    def valid(self):
        if self.status not in STATUSES:
            raise ValueError('Trạng thái không hợp lệ.')
        return self


class OrderInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    order_date: date
    po_number: str = Field(min_length=1, max_length=300)
    file_url: str = Field(default='', max_length=4000)
    version: int | None = None
    lines: list[LineInput] = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def valid(self):
        if not self.po_number.strip():
            raise ValueError('Số PO không được trống.')
        if self.file_url and not self.file_url.startswith('https://'):
            raise ValueError('Liên kết file phải bắt đầu bằng https://.')
        if any(x.delivery_date < self.order_date for x in self.lines):
            raise ValueError('Ngày giao không được trước ngày đặt.')
        ids = [x.id for x in self.lines if x.id]
        if len(ids) != len(set(ids)):
            raise ValueError('Mã chi tiết đơn hàng bị trùng.')
        return self
