"""Permission codes for the existing role/permission matrix."""
from app.core.config import LEGACY_CONFIG

MASTER_PERMISSIONS = {
    'CUSTOMER_MANAGE': 'Quản lý khách hàng',
    'PRODUCT_MANAGE': 'Quản lý sản phẩm',
    'SUPPLIER_MANAGE': 'Quản lý nhà cung cấp',
}
PERMISSION_LABELS = {
    'ORDER_CREATE': 'Tạo đơn hàng', 'ORDER_EDIT': 'Sửa đơn hàng',
    'FILM_PO_VIEW': 'Xem đơn nguyên liệu', 'FILM_PO_CREATE': 'Tạo đơn nguyên liệu',
    'FILM_PO_EDIT': 'Sửa đơn nguyên liệu', 'FILM_PO_ASSIGN': 'Phân bổ nguyên liệu',
    'FILM_PO_CANCEL': 'Hủy đơn nguyên liệu', 'NVL_RECEIVE': 'Nhận nguyên liệu',
    'NVL_STOCK_VIEW': 'Xem tồn kho', 'PRODUCTION_EDIT': 'Cập nhật sản xuất',
    'USER_MANAGE': 'Quản lý user', **MASTER_PERMISSIONS,
    'QC_VIEW': 'Xem danh sách và chi tiết QC',
    'QC_CREATE': 'Tạo phiếu QC', 'QC_EDIT': 'Sửa phiếu QC',
    'QC_TEMPLATE_MANAGE': 'Quản lý Template QC',
}
PERMISSION_CODES = set(LEGACY_CONFIG['PERMISSIONS'].values()) | set(PERMISSION_LABELS)
