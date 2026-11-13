# Quản lý Google Sheets Template QC — Bước 1

## Phạm vi

Màn hình `/qc/templates`, bên trong nhóm QC của sidebar dùng chung. API và màn hình yêu cầu quyền `QC_TEMPLATE_MANAGE` trong ma trận Role × Permission hiện có. LOCAL_ADMIN kế thừa cơ chế toàn quyền hiện hành; không tự cấp quyền mới cho các vai trò nhân viên. Người có USER_MANAGE có thể cấp quyền này qua màn hình User.

Chỉ đăng ký, sửa metadata, chuyển DRAFT/INACTIVE, kiểm tra kết nối và xem trước. ACTIVE được biểu diễn trong schema để dùng ở giai đoạn sau nhưng backend từ chối kích hoạt ở Bước 1. Danh sách chỉ tải khi nhấn Tra cứu hoặc sau thao tác lưu. Mỗi trang 20 mẫu, API tối đa 50.

Biểu mẫu đang dùng trong [forms.py](backend/app/modules/qc/forms.py), dữ liệu `qc_checks`, tạo phiếu, ký, PDF và bằng chứng QC không đổi. Template mới không được nối vào luồng tạo phiếu. Không có mapping, dữ liệu kết quả mới hoặc thư mục/upload Drive trong chức năng này.

## MySQL và áp dụng local

Đã xác minh MySQL local trước triển khai: migration hiện tại 006; không có bảng template tương đương. [Migration 007](backend/alembic/versions/007_qc_templates.py) chỉ tạo `QC_TEMPLATES`, có khóa ngoại đến `users.id`, `products.id`, FORM_CODE unique và STATUS DRAFT/ACTIVE/INACTIVE. Không sửa bảng QC hiện có, không tự gán quyền.

Các cột: TEMPLATE_ID UUID, FORM_CODE, FORM_NAME, CHECK_TYPE, OBJECT_TYPE nullable, PRODUCT_ID nullable, SPREADSHEET_ID, SHEET_ID tự đọc, VERSION, STATUS, CREATED_BY, CREATED_AT, UPDATED_AT. Không có MATERIAL_TYPE, FIELD_MAPPING hay thông tin phê duyệt. Bước 2 có thể thêm cột JSON mapping/thông tin phê duyệt bằng migration bổ sung; không cần đổi khóa hoặc thiết kế bảng. FORM_CODE duy nhất: tạo phiên bản mẫu mới bằng mã mới. UPDATED_AT có microsecond dùng phát hiện thay đổi đồng thời; lỗi 409 yêu cầu tải lại.

Theo [hướng dẫn Docker local](Huong%20dan%20chay%20va%20chuyen%20doi%20local.md), sao lưu trước khi áp dụng. Không dùng `down -v`, không tái tạo MySQL. Sau khi build thành công, chạy migration từ image mới rồi tạo lại riêng backend:

```sh
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env build backend
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env run --rm --no-deps backend alembic upgrade 007
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env up -d --no-deps --force-recreate backend
```

Migration downgrade bị chặn để tránh xóa template ngoài ý muốn. Chỉ chạy migration trên môi trường local được giao. Thư mục frontend được mount trực tiếp.

## Google và thao tác

1. Bật Google Sheets API và Google Drive API trong đúng dự án OAuth. Xem [hướng dẫn Google](Huong%20dan%20ket%20noi%20Google%20va%20Drive.md). Không thay client secret, redirect URI hay scope hiện tại.
2. Đăng nhập/kết nối Google đúng tài khoản nhân viên ERP. Chia sẻ file Sheets với email này, tối thiểu quyền đọc. Mọi lần đọc dùng token theo user, refresh bằng cơ chế OAuth hiện hữu; token không trả ra frontend.
3. Vào QC → Quản lý Template QC → Thêm template mới. Mặc định QC_NVL_V1, QC NVL, phiên bản 1, áp dụng chung PET/PP/PS/PVC. Để trống sản phẩm; OBJECT_TYPE để trống hoặc NVL. Backend kiểm tra các điều kiện này cho QC_NVL_V1.
4. Nhập Spreadsheet ID hoặc URL chuẩn `https://docs.google.com/spreadsheets/d/ID/edit`. Không dùng link xuất bản `/d/e/...`, file Excel hoặc shortcut Drive. `gid` trong URL không được dùng để chọn tab: luôn đọc index 0.
5. Kiểm tra kết nối, Xem trước Template, rồi Đăng ký template. Mỗi lần lưu backend xác minh lại nguồn, chuẩn hóa ID và tự lưu SHEET_ID; không tin thông tin kiểm tra từ trình duyệt. Không tự tạo bản ghi QC_NVL_V1 khi chưa có file thật.
6. Tra cứu để mở sửa; lưu DRAFT/INACTIVE. Preview bản đã lưu luôn kiểm tra quyền Google hiện tại. Nếu thứ tự tab gốc thay đổi, preview đọc tab index 0 hiện tại; SHEET_ID được cập nhật khi lưu lại template.

API: GET `/api/qc/templates` (q/page/size), POST `/api/qc/templates`, PUT `/api/qc/templates/{id}`, POST `/api/qc/templates/inspect` (spreadsheet, preview), GET `/api/qc/templates/{id}/preview`. Tất cả yêu cầu QC_TEMPLATE_MANAGE. Sửa cần expected_updated_at từ bản ghi vừa đọc. Không có API xóa hay kích hoạt.

## Giới hạn preview

Đọc metadata để xác định tab index 0, sau đó chỉ yêu cầu một range rõ tên tab, tối đa 500 hàng × 60 cột (A1:BH500), giới hạn phản hồi 12 MiB. ERP thông báo khi lưới gốc vượt vùng đọc. Hàng/cột trống cuối không dựng thừa nếu Google không trả nội dung/định dạng. Ô gộp cắt theo biên vùng xem trước.

Giữ nội dung đã định dạng, kết quả công thức, ô gộp, màu RGB/theme, đường viền, font cơ bản, căn lề, wrap, kích thước hàng/cột và trạng thái ẩn trong khả năng HTML table. Nội dung ô được gán bằng textContent; không thực thi HTML/công thức, không tải hyperlink hay hình ảnh từ ô. Chưa mô phỏng ảnh/chart, rich text, góc xoay chữ, độ tràn ô và bố cục in chính xác.

Lỗi tách riêng: URL/ID sai; file Excel/không phải Sheets; tab index 0 không phải GRID; thùng rác; file thiếu/không được chia sẻ (Google không luôn phân biệt được); thiếu quyền Google/Workspace; token hết hạn; API chưa bật; quota; lỗi mạng. Không sửa dữ liệu Google để thử quyền.

## Kiểm tra

Kiểm thử tập trung trong [test_qc_templates.py](backend/tests/test_qc_templates.py): quyền riêng ở mọi route; QC_EDIT không đủ; tạo/sửa/trùng mã/xung đột; chặn ACTIVE; phạm vi QC_NVL_V1; lỗi Google không lưu bản ghi; HTTP Google chỉ GET; range chỉ tab index 0; giới hạn preview; URL không hợp lệ; lỗi Google cụ thể. Google được giả lập, MySQL nằm trong transaction rollback theo fixture hiện có.

Lệnh sau chỉ chạy khi được đồng ý kiểm thử theo AGENTS.md:

```sh
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env exec -T backend pytest -q tests/test_qc_templates.py tests/test_google.py tests/test_qc.py tests/test_iqc.py
```

Kiểm thử Google thật cần URL/ID template và tài khoản được chia sẻ. Không dùng kết quả Google giả lập để kết luận kết nối file thật thành công.

## Trạng thái bàn giao local

- Đã build image backend và tạo lại riêng container backend thành công.
- Đã sao lưu MySQL trước migration tại `backups/napaco-before-qc-templates-007-20261113.sql.gz`, kèm SHA-256. Không xóa volume hoặc dữ liệu.
- Đã áp dụng migration 007 và đọc lại schema: đủ 14 cột, FORM_CODE unique, PRODUCT_ID tham chiếu products và CREATED_BY tham chiếu users.
- Đã rà soát diff các file tích hợp so với HEAD; editor không báo lỗi ở các file mới đã kiểm tra. Git hệ thống lỗi thiếu Xcode Command Line Tools nên diff được đọc bằng Python từ Git objects, với source mount chỉ đọc.
- Chưa chạy test chức năng/tự động: đã gửi câu hỏi xác nhận theo mục 8 AGENTS.md và đang chờ trả lời. Chưa xác minh Google thật vì chưa được cung cấp URL/ID template.

## Source thay đổi

- [templates.py](backend/app/modules/qc/templates.py): phân quyền, trang quản lý, danh sách, kiểm tra kết nối/preview, đăng ký/sửa có kiểm soát xung đột.
- [template_models.py](backend/app/modules/qc/template_models.py): model bảng QC_TEMPLATES.
- [sheets.py](backend/app/integrations/google/sheets.py): đọc Google Drive metadata và tab index 0, lỗi cụ thể, giới hạn vùng đọc.
- [main.py](backend/app/main.py), [model_registry.py](backend/app/core/model_registry.py): đăng ký router trước route QC động và đăng ký model.
- [permissions.py](backend/app/auth/permissions.py), [navigation.js](frontend/shared/navigation.js): quyền và menu theo cơ chế hiện có.
- [templates.html](frontend/qc/templates.html), [templates.js](frontend/qc/templates.js), [templates.css](frontend/qc/templates.css): màn hình quản lý.
- [sheet-preview.js](frontend/qc/sheet-preview.js): renderer ô Sheets chỉ đọc, định dạng và ô gộp.
- [007_qc_templates.py](backend/alembic/versions/007_qc_templates.py): migration bổ sung bảng.
- [test_qc_templates.py](backend/tests/test_qc_templates.py): kiểm thử tập trung đã chuẩn bị, chưa chạy.
- [Hướng dẫn Google](Huong%20dan%20ket%20noi%20Google%20va%20Drive.md) và tài liệu này: cấu hình, triển khai, phạm vi và giới hạn.
