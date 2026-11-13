# QC Template — Bước 2: Mapping, phê duyệt và sử dụng

## Hiện trạng đã kiểm tra

Trước khi sửa: MySQL revision 007; `QC_TEMPLATES` đã có QC_NVL_V1 DRAFT, chưa có mapping/phê duyệt. `qc_checks` đã có FORM_DATA JSON và chưa có TEMPLATE_ID. Bản gốc thực tế đọc được qua OAuth: tab index 0 `Phieu_IQC_A4`, 42 hàng × 8 cột, 7 tiêu chí với cột tiêu chuẩn, kết quả, đánh giá và các vùng gộp. Việc đọc khảo sát chỉ dùng GET, không sửa file hay phê duyệt template thật.

## Cấu trúc bổ sung

[Migration 008](backend/alembic/versions/008_qc_mapping.py) bổ sung:

- `QC_TEMPLATES.FIELD_MAPPING` JSON, `SOURCE_SNAPSHOT` JSON, `SOURCE_HASH` SHA-256.
- `APPROVED_BY` (FK users), `APPROVED_AT`, `SOURCE_CHECKED_AT`, `SOURCE_MATCHES`.
- `qc_checks.TEMPLATE_ID` nullable, FK tới QC_TEMPLATES. Hồ sơ cũ vẫn NULL; migration không UPDATE dữ liệu cũ.

Kết quả mới dùng FORM_DATA hiện hữu, phân biệt bằng `kind: google_template`: lưu template ID/code/version, Spreadsheet ID/SHEET_ID, danh tính phê duyệt, source hash/mapping hash, mapping, bản chụp nội dung/định dạng, dữ liệu tự điền từ MySQL, câu trả lời và kết luận. Không thêm bảng kết quả, MATERIAL_TYPE, QC_FILES hoặc chữ ký mới.

## Luồng quản lý

1. QC → Quản lý Template QC → Tra cứu → Sửa mẫu DRAFT đã đăng ký.
2. **Đọc Google · Đề xuất mapping**. ERP chỉ đọc tab index 0. Nhận diện các nhãn dữ liệu, bảng tiêu chí đánh số, cột tiêu chuẩn/kết quả/đánh giá và vùng gộp. Nhãn hoặc vị trí chưa rõ được cảnh báo, không tự quyết định.
3. Bảng mapping phân biệt `ERP` (nguồn MySQL cố định trong allowlist), `STANDARD` (nội dung cố định trong bản chụp), `INPUT` (kết quả QC). Màu xanh dương = ERP, vàng = tiêu chuẩn, xanh lá = kết quả.
4. Chọn trường địa chỉ ô trong bảng mapping, sau đó nhấn trực tiếp ô trên preview. Ô gộp luôn chuẩn hóa về góc trên bên trái. Có thể cấu hình nguồn ERP, kiểu text/number/date/boolean, đơn vị, bắt buộc, ô tiêu chuẩn và ô đánh giá. Trường/tên tiêu chí lấy từ Google Sheets; không thêm/xóa trường ở ERP. Mọi tiêu chí nhập kết quả đều có Không áp dụng.
5. Nội dung mẫu có sẵn trong ô kết quả không trở thành câu trả lời mặc định. Dung sai/phương pháp giữ nguyên từ Google trong bản chụp, không được ERP tự suy đoán.
6. Kiểm tra mapping rồi nhấn **Lưu · Phê duyệt và kích hoạt**. Đây là xác nhận trực tiếp của quản lý cho toàn bộ mapping; không cần tích từng trường hay phê duyệt/kích hoạt riêng. Đọc/đề xuất mapping đơn thuần không tự ban hành.
7. Khi Lưu, backend đọc lại nguồn, kiểm tra hash, địa chỉ hợp lệ, trùng ô/vùng gộp, ô tiêu chuẩn bị ghi đè, nguồn MySQL hợp lệ và ít nhất một tiêu chí kết quả. Chỉ khi hợp lệ mới lưu mapping, bản chụp, người/thời điểm phê duyệt và trạng thái ACTIVE trong cùng transaction. Lỗi kiểm tra thì không ban hành.
8. Template ACTIVE phù hợp mới hiện trong Tạo Phiếu QC. **Kích hoạt lại** chỉ dành cho mẫu đã duyệt bị ngừng trước đó; vẫn kiểm tra nguồn Google phải khớp.

Mọi thao tác quản lý dùng quyền QC_TEMPLATE_MANAGE hiện hữu. Ghi mapping/phê duyệt/trạng thái/thay đổi nguồn vào audit_log hiện có. Không cấp quyền tự động cho vai trò mới.

## Phiên bản và kiểm tra thay đổi nguồn

- Sau phê duyệt, khóa toàn bộ metadata, phạm vi áp dụng, mapping và bản chụp, kể cả khi INACTIVE.
- **Tạo phiên bản mới** gợi ý hậu tố V2 và số version tương ứng. Bắt buộc dùng Spreadsheet ID khác file đã phê duyệt; mapping và phê duyệt làm lại độc lập. Không có thao tác copy/ghi file Google từ ERP.
- **Kiểm tra thay đổi nguồn** đọc Google và đối chiếu hash. Nếu khác, chuyển INACTIVE và thông báo 409; không cập nhật đè bản chụp cũ. Khi chưa phê duyệt, quản lý có thể đọc/đề xuất/lưu lại mapping; sau phê duyệt phải tạo phiên bản mới.
- Hash bao gồm Spreadsheet ID, tab ID/tên, giá trị/công thức, định dạng, ô gộp, kích thước và theme của bản chụp. Với ô công thức, so sánh công thức thay vì kết quả tính động.
- ERP không đọc/phân tích Google mỗi lần tạo phiếu. Nguồn bên ngoài được kiểm tra tại phê duyệt, kích hoạt và khi quản lý chủ động kiểm tra; không có tác vụ giám sát nền. File Google thay đổi sau kích hoạt không làm thay đổi nội dung mẫu đang dùng trong ERP: nhân viên tiếp tục dùng bản chụp đã duyệt cho đến khi quản lý kiểm tra và ngừng mẫu.

## Luồng nhân viên QC

1. Chọn CHECK_TYPE, OBJECT_TYPE và OBJECT_ID như trước; giữ nguyên điều kiện IQC còn tồn, trong 15 ngày và chưa có QC.
2. ERP tải các template ACTIVE đã duyệt có CHECK_TYPE trùng, OBJECT_TYPE trống hoặc trùng, PRODUCT_ID trống hoặc nằm trong sản phẩm liên quan. Không lọc MATERIAL_TYPE. Các mẫu chung dùng được cho PET, PP, PS, PVC.
3. Chọn template trong mục **Google Sheets Template đã duyệt**, mở dialog. Thông tin MySQL hiển thị chỉ đọc; kết quả bắt đầu trống. Có bản xem trước template đã đóng băng.
4. NVL lấy theo quan hệ `film_receipts.line_id → film_order_lines → film_purchase_orders / film_materials`: PO, nhựa, nhà cung cấp, ngày nhận/sản xuất, số lượng, khổ/độ dày theo danh mục NVL liên kết với dòng đặt hàng. Mã/tên sản phẩm lấy qua order_lines. Không suy đoán dữ liệu thiếu hoặc đơn vị PO chưa có trong schema.
5. QC_ID hiển thị “Cấp mã khi lưu” trước khi ghi. Backend cấp mã bằng sequence/khóa hiện có rồi tự điền mã thật vào snapshot. Những dữ liệu MySQL bắt buộc bị thiếu sẽ chặn lưu, không bắt nhân viên tự nhập thay nguồn ERP.
6. Nhập kết quả và chọn Đạt/Không đạt/Không áp dụng cho từng tiêu chí. Chọn Không áp dụng thì không phải nhập kết quả, kể cả với mapping cũ chưa bật allow_na; backend xóa kết quả cũ của tiêu chí đó khi lưu phiếu mới. Kết luận chỉ có Đạt/Không đạt: có Không đạt → FAIL, có Đạt và không Không đạt → PASS. Cần ít nhất một tiêu chí áp dụng; toàn bộ N/A bị chặn, không hiểu thành PASS. Hồ sơ lịch sử có kết luận N/A vẫn được xem lại nguyên trạng. Không so sánh số đo với dung sai tự động.
7. **Áp dụng kết quả**, nhập đủ thông tin phiếu và **Tạo Phiếu**. Có thể dùng lô tối đa 10 như luồng cũ; lỗi một phiếu rollback toàn lô. Backend kiểm tra lại template còn ACTIVE, đúng đối tượng/sản phẩm và hash đúng bản đang nhập.
8. Mở phiếu trong danh sách QC để xem đúng snapshot và kết quả đã lưu, kể cả sau khi template bị ngừng hoặc có V2. Phiếu của nhánh mapping được giữ chỉ đọc trong Bước 2, không chuyển template hoặc ghi đè lịch sử.

Luồng biểu mẫu ERP cũ vẫn tồn tại. Nhánh mới không gọi chữ ký, PDF, thư mục hoặc upload; backend chặn các API bằng chứng/PDF cho phiếu có TEMPLATE_ID. Không sửa dữ liệu hoặc logic biểu mẫu ký đã có.

## Giới hạn

- Nhận diện bằng nhãn và cấu trúc bảng, không dùng AI bên ngoài. Sửa trường/tiêu chí tại Google Sheets rồi tải lại; ERP cho chỉnh liên kết ô và nguồn dữ liệu. Template đã ban hành vẫn cần tạo phiên bản mới khi đổi nội dung.
- Preview/mapping tab đầu tối đa 500 hàng × 60 cột. Mapping không được lưu khi vùng bị cắt; bản chụp tối đa 2 MiB để bảo vệ lưu JSON và lô QC.
- Giữ định dạng HTML theo khả năng Bước 1; ảnh/chart/rich text và bố cục in chưa mô phỏng đầy đủ.
- Trong file mẫu thực tế, tiêu đề có PET/PP/PS; hệ thống không tự sửa nội dung Google để thêm PVC. Mẫu QC_NVL_V1 vẫn áp dụng chung theo cấu hình ERP; quản lý cần rà soát nội dung chữ trước phê duyệt.

## Build và migration local

Không triển khai production. Sao lưu MySQL trước migration theo [hướng dẫn local](Huong%20dan%20chay%20va%20chuyen%20doi%20local.md). Build backend, chạy `alembic upgrade 008` từ image mới, rồi tạo lại riêng container backend; giữ nguyên MySQL và volume. Không dùng `down -v`.

Google vẫn dùng OAuth theo user và scope Drive hiện có; bật Sheets API cùng dự án theo [hướng dẫn Google](Huong%20dan%20ket%20noi%20Google%20va%20Drive.md). Nhân viên tạo phiếu từ snapshot không cần Google đọc file mỗi lần. Quản lý phê duyệt/kiểm tra nguồn cần quyền đọc Google.

## Source chính

- [mapping.py](backend/app/modules/qc/mapping.py): nhận diện, A1/ô gộp, validation và hash.
- [templates.py](backend/app/modules/qc/templates.py), [template_models.py](backend/app/modules/qc/template_models.py): mapping draft, phê duyệt, trạng thái, kiểm tra nguồn và bất biến.
- [template_runtime.py](backend/app/modules/qc/template_runtime.py): lọc mẫu, lấy dữ liệu PO/NVL, kiểm tra kết quả và tạo snapshot.
- [schemas.py](backend/app/modules/qc/schemas.py), [models.py](backend/app/modules/qc/models.py), [service.py](backend/app/modules/qc/service.py), [api.py](backend/app/modules/qc/api.py), [main.py](backend/app/main.py): tích hợp vào luồng QC/API hiện hữu.
- [sheets.py](backend/app/integrations/google/sheets.py): đọc thêm userEnteredValue để nhận diện công thức trong hash.
- [template-mapping.js](frontend/qc/template-mapping.js), [templates.js](frontend/qc/templates.js), [templates.html](frontend/qc/templates.html): quản lý mapping, chọn ô, phê duyệt và trạng thái.
- [mapped-forms.js](frontend/qc/mapped-forms.js), [qc.js](frontend/qc/qc.js), [index.html](frontend/qc/index.html): chọn template, dialog nhập và mở lại hồ sơ.
- [sheet-preview.js](frontend/qc/sheet-preview.js), [templates.css](frontend/qc/templates.css): địa chỉ/chọn ô và đánh dấu mapping.
- [008_qc_mapping.py](backend/alembic/versions/008_qc_mapping.py): migration chỉ bổ sung cấu trúc thiếu.
- [test_qc_mapping.py](backend/tests/test_qc_mapping.py): test đã chuẩn bị, chưa chạy.

## Kiểm tra thực tế

Đã đọc AGENTS.md, schema MySQL và template thực tế; rà soát diff của các file tích hợp. Editor không báo lỗi tại các module mapping/runtime và JavaScript mới đã kiểm tra. Người dùng yêu cầu **chỉ build để tự test**, vì vậy không chạy pytest, kiểm thử giao diện, phê duyệt/kích hoạt mẫu thật hoặc tạo phiếu thật.

- Build image cuối thành công; đã tạo lại riêng backend và xác nhận container `napaco-backend` đang Up. MySQL giữ nguyên container/volume, trạng thái healthy.
- Đã sao lưu trước migration tại `backups/napaco-before-qc-mapping-008-20261113.sql.gz`, kèm file SHA-256; quyền file sao lưu hạn chế theo umask 077.
- Lệnh `alembic upgrade 008` hoàn tất thành công trên MySQL local. Không phê duyệt/kích hoạt template thật, không tạo hồ sơ QC thật, không chạy pytest hay thao tác kiểm thử trên browser.
- Chưa xác nhận chức năng bằng kiểm thử thực thi theo yêu cầu người dùng. Build thành công không thay thế kiểm thử nghiệp vụ; người dùng tự kiểm tra luồng quản lý → phê duyệt → kích hoạt → tạo/mở lại phiếu theo hướng dẫn trên.

## Sửa lỗi tạo phiếu và rút gọn thao tác quản lý

- Log backend xác nhận NameError: apply_values gọi filled(db, ...) trong khi thiếu tham số db. Đã truyền session hiện hữu vào apply_values ở cả tạo và sửa; không mở kết nối mới, giữ transaction/lô QC.
- Các API frontend QC/mapped form/template bắt phản hồi không phải JSON và hiển thị lỗi HTTP dễ hiểu, thay vì Unexpected token.
- Đánh giá từng tiêu chí luôn có Không áp dụng; kết luận chỉ Đạt/Không đạt và chặn toàn bộ Không áp dụng. Không cập nhật đè mapping/snapshot đã duyệt hoặc hồ sơ cũ để áp dụng chính sách này.
- Lưu mapping đồng thời phê duyệt và ACTIVE; bỏ nút thêm/xóa trường, cột xác nhận từng trường và nút phê duyệt riêng. Đăng ký metadata template ban đầu vẫn tạo DRAFT cho tới khi quản lý đọc và lưu mapping.
- Không có migration hoặc thay đổi dữ liệu trực tiếp cho lần sửa này. Theo yêu cầu trước đó, chỉ build/cập nhật backend để người dùng tự test; không chạy pytest hoặc thử tạo phiếu thật.
- Bản sửa đã build thành công và tạo lại riêng container backend local. Đã rà soát diff, kiểm tra các nơi gọi apply_values và chẩn đoán editor; chưa xác nhận tạo phiếu bằng test thực thi theo lựa chọn của người dùng.
