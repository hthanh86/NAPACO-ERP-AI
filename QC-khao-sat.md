# Khảo sát phân hệ QC — 12/11/2026

> Đây là kết quả khảo sát trước triển khai. Sau khi người dùng xác nhận chuyển các bảng liên quan, sửa khóa EB thành `EB_ID` và chốt mã `QC_yymmdd_xx`, migration 004 đã được áp dụng trên local. Trạng thái hiện tại xem [Bàn giao QC](./QC-ban-giao.md).

## Kết quả đã xác minh

Đã đọc source liên quan và metadata MySQL local trong container `napaco-backend`/`napaco-mysql84`. Database đang ở Alembic revision `003`. Chưa ghi dữ liệu, sửa schema, chạy migration hoặc triển khai ứng dụng.

- Backend: FastAPI, SQLAlchemy, PyMySQL; Alembic quản lý migration.
- Frontend: HTML/JavaScript; giao diện cũ qua lớp compatibility, màn hình mới có thể dùng API FastAPI và sidebar dùng chung.
- Xác thực: cookie session `napaco_session`, bảng `login_sessions` và `users`.
- Phân quyền: `role_permissions`, khóa chính `(role, permission)`; backend dùng `require()`. Chưa có mã quyền QC trong catalog source. Không tự cấp quyền cho role hiện có.
- Drive: OAuth và credential theo `user.id` đã có; tái sử dụng `drive.search(db, user, keyword)`, trả tối đa 20 file mỗi lần tìm. Chưa kiểm thử tài khoản Google thực tế trong khảo sát này.

## Bảng nghiệp vụ và nguồn nhập liệu

| Nghiệp vụ | Thực trạng MySQL local |
|---|---|
| Nhận NVL | Bảng `film_receipts`, PK `id`; index `line_id`; không có FK. Có `iqc_id`, chưa có `production_order_id` hoặc `LSX_ID`. |
| Cấp/trả NVL | Bảng `film_movements`, PK `id`; index `production_order_id`, `receipt_id`; không có FK. Có `qc_id`. |
| Nhân viên | Bảng `users`; email unique. |
| Ma trận quyền | Bảng `role_permissions`. |
| QC | Chỉ có nguồn `QC-FM-01_KIEMTRA` trong `source_rows`, 1 dòng tiêu đề, chưa có dòng phiếu QC. Chưa có bảng nghiệp vụ QC riêng. |
| SETUP | Nguồn `06.SETUP_MAU`, 1 dòng tiêu đề; chưa có bảng nghiệp vụ riêng. |
| Hút | Nguồn `05.NHAT_KY_HUT`, 1 dòng tiêu đề; chưa có bảng nghiệp vụ riêng. |
| Cắt | Nguồn `SX-FM-01D_CAT_LOG`, tổng 6 dòng gồm tiêu đề; chưa có bảng nghiệp vụ riêng. Chưa đánh giá tính hợp lệ của từng dòng dữ liệu. |
| Bế | Nguồn `SX-FM-01E_EB_LOG`, tổng 6 dòng gồm tiêu đề; chưa có bảng nghiệp vụ riêng. Chưa đánh giá tính hợp lệ của từng dòng dữ liệu. |
| Lệnh sản xuất | Nguồn `03.LenhSX`, 1 dòng tiêu đề; chưa có bảng nghiệp vụ riêng. |
| NCR/CAPA | Nguồn `QC-FM-03_NCR_CAPA`, tổng 4 dòng gồm tiêu đề; chưa có bảng nghiệp vụ riêng. Giai đoạn này chỉ làm menu. |

`source_rows` lưu bản chụp nhập liệu dạng JSON, có unique `(book, sheet, row_number)`. Theo thiết kế tại `compatibility/store.py`, đây là baseline nhập liệu bất biến, không phải nơi ghi nghiệp vụ mới. Tên sheet ở trên là giá trị trong bảng này, không phải tên bảng MySQL.

## Cấu trúc QC thực tế trong nguồn đã nhập

`QC_ID`, `Ngay_Gio`, `CHECK_TYPE`, `LSX_ID`, `OBJECT_ID`, `Tieu_Chuan_STD`, `So_Luong`, `Ket_Qua`, `Nguoi_QC`, `NCR_ID`, `Ghi_Chu`, `Hinh_Anh`.

Chưa có `OBJECT_TYPE`. Đây là tiêu đề nguồn JSON, chưa có kiểu dữ liệu/ràng buộc/index MySQL riêng cho từng trường QC. Không có API, form hay trang danh sách QC trong source hiện tại.

## Quan hệ đã thấy và xung đột cần quyết định

- SETUP dùng `SETUP_ID`, `ID_Lenh_SX`, `Cong_Doan`.
- Hút dùng `ID_Nhat_Ky`, `ID_Lenh_SX`, `SETUP_ID`.
- Cắt dùng `CUT_ID`, `DH_ID`, `WIP_ID`, `SETUP_ID`.
- Bế **cũng dùng `CUT_ID`**, không có `EB_ID` trong tiêu đề nguồn hiện tại. Không tự đổi tên hay sinh lại khóa lịch sử.
- CAT/EB có thể suy LSX qua `SETUP_ID` nếu bản ghi SETUP tồn tại. Nguồn SETUP hiện chưa có dòng dữ liệu; chưa thể xác minh đường liên kết đó bằng dữ liệu thực tế. Không mặc định `DH_ID` là mã LSX hoặc mã chi tiết đơn hàng.
- `order_lines` là chi tiết đơn hàng, không tự coi là bảng lệnh sản xuất.
- NVL chưa có liên kết LSX trực tiếp; cho phép LSX trống theo yêu cầu.
- Chưa có dữ liệu SETUP để xác định tập giá trị thực tế của `Cong_Doan`; mã đối tượng `NVL/SETUP/HUT/CAT/EB` chỉ là đề xuất từ yêu cầu.
- Chưa xác minh được quy tắc sinh `QC_ID` và tập giá trị `Ket_Qua` từ dữ liệu vì nguồn QC chỉ có tiêu đề.

## Phương án triển khai đề xuất — chưa thực hiện

1. Tạo bảng nghiệp vụ QC riêng, bảo toàn toàn bộ trường nguồn và bổ sung `OBJECT_TYPE`; kiểu dữ liệu, index, quy tắc sinh mã và validation phải được chốt trước migration. Không tạo `SHIFT_ID`, `CHECK_TIME`, `STD_VERSION` hoặc bảng disposition.
2. Chuẩn bị mapping/bảng nghiệp vụ tối thiểu cho LSX, SETUP, HUT, CAT và EB để tìm kiếm/phân trang qua MySQL; giữ nguyên khóa nguồn, kể cả `CUT_ID` của EB. Chuyển đổi bằng migration/import có đối soát; không sửa baseline `source_rows`. Đây là phần vượt giả định chỉ thêm một cột vào bảng QC có sẵn nên cần xác nhận phạm vi.
3. Với CAT/EB, tự điền LSX qua SETUP khi có liên kết hợp lệ; không suy từ `DH_ID`. Cần xác nhận cách xử lý bản ghi lịch sử thiếu SETUP trước khi cho lưu QC gắn đối tượng đó.
4. Tái sử dụng session và ma trận quyền; đề xuất quyền `QC_VIEW` cho danh sách/chi tiết/tìm đối tượng, `QC_CREATE`, `QC_EDIT`. Menu NCR/CAPA chỉ hiển thị đang phát triển, chưa có thao tác dữ liệu. Không tự cấp quyền role, không có chức năng xóa QC.
5. Tái sử dụng Drive OAuth theo người dùng; thêm API tìm file được kiểm tra quyền QC, hỗ trợ URL HTTP(S) hợp lệ. Không thay đổi trạng thái kho hay sản xuất khi QC NG.
6. API dự kiến: danh sách/chi tiết/tạo/cập nhật QC, tìm đối tượng theo loại, tìm Drive. Chống lưu lặp ở backend và nút lưu; kiểm tra đối tượng và LSX ở backend. Trang danh sách chỉ truy vấn khi người dùng xác nhận bộ lọc, phân trang server.

## File dự kiến chịu tác động

- Module mới dưới `backend/app/modules/qc/`: API, schema, service, model QC; các model nguồn sản xuất đặt trong module sở hữu được thống nhất sau xác nhận phạm vi.
- Migration mới dưới `backend/alembic/versions/`, model registration tại `backend/app/core/model_registry.py`, lắp router tại `backend/app/main.py`.
- Catalog quyền tại `backend/app/auth/permissions.py`; kiểm tra quyền dùng lại `backend/app/auth/security.py`, không thay thuật toán phân quyền.
- Màn hình mới dưới `frontend/qc/`, sidebar tại `frontend/shared/navigation.js`; đối chiếu cách shell hiện tại dựng menu trước khi chỉnh `frontend/shared/menu.html` nếu cần.
- Test QC có mục tiêu dưới `backend/tests/`; dữ liệu test rollback, không ghi production.

## Trạng thái kiểm tra

- Đã xác minh schema, PK/FK/index liên quan, revision migration, tên nguồn đã nhập và tiêu đề bảy nguồn QC/sản xuất/NCR bằng truy vấn chỉ đọc.
- Chưa chạy test nghiệp vụ QC vì chưa triển khai.
- Chưa kiểm thử OAuth/Drive trực tiếp, chưa đánh giá dữ liệu lịch sử CAT/EB/NCR.
- `git status` không chạy được vì Command Line Tools của macOS thiếu đường dẫn hợp lệ; chưa có diff ứng dụng để kiểm tra. Thay đổi workspace duy nhất của nhiệm vụ đến thời điểm này là báo cáo này.

## Cần xác nhận để tiếp tục

1. Có triển khai thêm các bảng nghiệp vụ tối thiểu QC/LSX/SETUP/HUT/CAT/EB trên database local này, hay hệ thống có database/source mới hơn đã chứa chúng?
2. Có giữ `CUT_ID` làm mã nguồn EB và để LSX trống khi đối tượng CAT/EB chưa truy ra SETUP hợp lệ, hay cần quy tắc liên kết khác?
3. Quy tắc sinh `QC_ID` và tập giá trị `Ket_Qua` mong muốn là gì? Đề xuất để duyệt: mã `QC-YYYYMMDD-000001` theo sequence dùng chung, kết quả `OK`/`NG`, người QC lấy từ session. Đây là đề xuất mới, chưa phải quy tắc được xác minh.
