"""Frozen QC/production schema derived from the operation workbook headers.

Keep historical references as indexed strings: source rows may be incomplete.
No foreign keys are inferred from DH_ID or polymorphic QC references.
"""
import sqlalchemy as sa

metadata = sa.MetaData()


def field(key, name, kind='text', index=False):
    types = {'id': sa.String(100), 'text': sa.String(500), 'long': sa.Text(),
             'number': sa.Numeric(24, 8), 'date': sa.Date(),
             'datetime': sa.DateTime(), 'time': sa.Time()}
    return sa.Column(name, types[kind], key=key, primary_key=key == 'id',
                     nullable=key != 'id', index=index)


def table(name, fields):
    return sa.Table(name, metadata, *[field(*spec) for spec in fields],
                    sa.Column('source', sa.JSON(), nullable=False))


production_orders = table('production_orders', [
    ('id', 'ID_Lenh_SX', 'id'), ('issued_at', 'Ngay_Ra_Lenh', 'datetime'),
    ('group_id', 'Ma_Nhom_Ghep'), ('stage', 'Cong_Doan'),
    ('order_line_id', 'ID_Chi_Tiet_PO', 'id', True), ('material_id', 'MaNVL'),
    ('product_id', 'Ma_SP', 'id', True), ('machine_id', 'Ma_May_Chay'),
    ('quantity', 'Tong_SL_Can_Chay', 'number'), ('cutting_tool_id', 'Ma_Dao'),
    ('mold_id', 'Ma_Khuon'), ('cavity', 'So_Cavity', 'number'),
    ('speed', 'Toc_Do_s_bia', 'number'), ('planned_sheets', 'So_Bia_Du_Kien', 'number'),
    ('planned_hours', 'TG_Chay_Thuan_Gio', 'number'), ('setup_minutes', 'TG_Dung_Setup_Phut', 'number'),
    ('planned_start', 'TG_Bat_Dau_Du_Kien', 'datetime'), ('planned_end', 'TG_Ket_Thuc_Du_Kien', 'datetime'),
    ('good', 'SL_Luy_Ke_Dat', 'number'), ('ng', 'SL_Luy_Ke_NG', 'number'), ('status', 'Trang_Thai'),
])
production_setups = table('production_setups', [
    ('id', 'SETUP_ID', 'id'), ('checked_at', 'Ngay_Gio', 'datetime'),
    ('production_order_id', 'ID_Lenh_SX', 'id', True), ('stage', 'Cong_Doan'),
    ('machine_id', 'MAY_ID'), ('tool_id', 'KHUON_DAO_ID'), ('cavity', 'Cavity', 'number'),
    ('result', 'Ket_Qua'), ('qc_id', 'IQC_QC_ID'), ('staff_id', 'Nguoi_Setup'), ('note', 'Ghi_Chu', 'long'),
])
forming_logs = table('forming_logs', [
    ('id', 'ID_Nhat_Ky', 'id'), ('production_order_id', 'ID_Lenh_SX', 'id', True),
    ('setup_id', 'SETUP_ID', 'id', True), ('run_date', 'Ngay_Chay', 'date'), ('staff_id', 'Ma_Cong_Nhan'),
    ('planned_sheets', 'SL_Bia_Du_Kien', 'number'), ('planned_kg', 'KG_Mang_Du_Kien', 'number'),
    ('mold_id', 'Ma_Khuon'), ('movement_id', 'MV_NVL_ID', 'id', True),
    ('speed', 'Toc_Do_May', 'number'), ('film_pull', 'Keo_Mang', 'number'),
    ('cavity', 'So_Cavity', 'number'), ('start_time', 'Gio_Bat_Dau', 'time'),
    ('end_time', 'Gio_Ket_Thuc', 'time'), ('good', 'SL_Bia_Thuc_Te_Dat', 'number'),
    ('ng', 'SL_NG_Trong_Ca', 'number'), ('setup_duration', 'Thoi_gian_len_khuon', 'number'),
    ('sheet_weight', 'Trong_Luong_bia', 'number'), ('note', 'Ghi_Chu', 'long'),
])
production_wip = table('production_wip', [
    ('id', 'WIP_ID', 'id'), ('forming_log_id', 'NKH_ID', 'id', True),
    ('created_at', 'Ngay_Gio_Tao', 'datetime'), ('sheets', 'SL_Bia', 'number'), ('note', 'Ghi chú', 'long'),
])
cutting_logs = table('cutting_logs', [
    ('id', 'CUT_ID', 'id'), ('run_date', 'Ngày', 'date'), ('order_ref', 'DH_ID', 'id', True),
    ('wip_id', 'WIP_ID', 'id', True), ('setup_id', 'SETUP_ID', 'id', True),
    ('machine_id', 'MAY_ID'), ('tool_id', 'CUT_TOOL_ID'), ('bowls', 'Số bát', 'number'),
    ('input_sheets', 'SL bìa Input', 'number'), ('cut_sheets', 'SL bìa đã cắt', 'number'),
    ('good', 'SL OK', 'number'), ('ng', 'SL NG', 'number'),
    ('start_time', 'Từ giờ', 'time'), ('end_time', 'Đến giờ', 'time'),
    ('staff_id', 'Người cắt'), ('inspector_id', 'Người kiểm'), ('note', 'Ghi chú', 'long'),
])
eb_logs = table('eb_logs', [
    ('id', 'EB_ID', 'id'), ('run_date', 'Ngày', 'date'), ('order_ref', 'DH_ID', 'id', True),
    ('wip_id', 'WIP_ID', 'id', True), ('setup_id', 'SETUP_ID', 'id', True),
    ('machine_id', 'MAY_ID'), ('tool_id', 'EB_TOOL_ID'), ('good', 'SL OK', 'number'), ('ng', 'SL NG', 'number'),
    ('start_time', 'Từ giờ', 'time'), ('end_time', 'Đến giờ', 'time'),
    ('staff_id', 'Nhan_Vien'), ('note', 'Ghi chú', 'long'),
])
qc_checks = table('qc_checks', [
    ('id', 'QC_ID', 'id'), ('checked_at', 'Ngay_Gio', 'datetime', True),
    ('check_type', 'CHECK_TYPE', 'text', True), ('object_type', 'OBJECT_TYPE', 'text', True),
    ('production_order_id', 'LSX_ID', 'id', True), ('object_id', 'OBJECT_ID', 'id', True),
    ('standard_url', 'Tieu_Chuan_STD', 'long'), ('quantity', 'So_Luong', 'number'),
    ('result', 'Ket_Qua'), ('staff_id', 'Nguoi_QC'), ('ncr_id', 'NCR_ID'),
    ('note', 'Ghi_Chu', 'long'), ('image_url', 'Hinh_Anh', 'long'),
])
