# Bàn giao QC và các bảng sản xuất liên quan

## Trạng thái

Đã áp dụng Alembic revision `004` trên MySQL **local**, sao lưu trước migration và nhập dữ liệu Excel có đối soát. Đã build lại image backend local và khởi động lại backend. Không đổi dependency hoặc cấu hình bí mật; không triển khai production.

## Bảng đã bổ sung

| Nguồn Excel | Bảng MySQL mới | Số bản ghi đã nhập |
|---|---|---:|
| `03.LenhSX` | `production_orders` | 0 |
| `06.SETUP_MAU` | `production_setups` | 0 |
| `05.NHAT_KY_HUT` | `forming_logs` | 0 |
| `SX-FM-01C_WIP` | `production_wip` | 0 |
| `SX-FM-01D_CAT_LOG` | `cutting_logs` | 1 |
| `SX-FM-01E_EB_LOG` | `eb_logs` | 1 |
| `QC-FM-01_KIEMTRA` | `qc_checks` | 0 |

Mỗi bảng giữ đủ các cột được mô tả trong Excel, cùng JSON `source` để đối soát nguồn theo quy ước hiện có. Tên cột nghiệp vụ giữ theo tiêu đề Excel; thuộc tính Python dùng tên tiếng Anh. Schema chi tiết, kiểu dữ liệu và index được ghi rõ tại [snapshot v004](./backend/app/migrations/snapshots/v004.py).

- Bảng EB sử dụng cột **`EB_ID`**, sửa lỗi tiêu đề `CUT_ID` từ nguồn. Giá trị mã lịch sử như `CUT_261020_01` được giữ nguyên; không tự đổi thành mã khác.
- Bảng QC bổ sung **`OBJECT_TYPE`**. Không thêm `SHIFT_ID`, `CHECK_TIME`, `STD_VERSION` hoặc bảng disposition.
- Không thay đổi cấu trúc các bảng hiện có. Không tạo bảng NCR/CAPA: giai đoạn này chỉ có menu đang phát triển.
- Chưa đặt FK cho tham chiếu lịch sử chưa được xác minh. `OBJECT_ID` là tham chiếu đa nguồn, không gắn FK vào một bảng duy nhất. Backend xác thực nguồn và LSX trước khi lưu QC mới.
- Các nguồn có 0 bản ghi ở trên chỉ có tiêu đề trong Excel, không phải nhập bị thiếu.
- Bốn dòng CAT và bốn dòng EB (dòng Excel 3–6) thiếu mã nên chưa được đưa vào bảng nghiệp vụ. Dữ liệu vẫn nguyên trong Excel và `source_rows`; không tự sinh mã, gộp vào dòng trước hoặc xóa dữ liệu. Cần bổ sung mã thực tế trước khi nhập bổ sung những dòng này.
- Đã kiểm tra các ô mã bị thiếu: không có ô gộp hoặc công thức tại những vị trí đó; đây là các ô trống thực tế.

**Không có bảng bắt buộc nào cần tự đoán danh sách cột vì thiếu mô tả Excel.** Kiểu dữ liệu được xác định từ mục đích cột và các giá trị nguồn hiện có. Vì nhiều nguồn chưa có dữ liệu, chưa xác minh được tập giá trị lịch sử của `Cong_Doan`, `CHECK_TYPE`, `Ket_Qua` hoặc quy tắc quy đổi `DH_ID`.

## Chức năng QC

- Menu QC có Tạo Phiếu QC, Tạo Phiếu NCR/CAPA và Danh sách QC.
- Tạo phiếu cho `QC NVL`, `QC ĐẦU CA`, `QC GIỮA CA`, `QC CUỐI CA`; kiểm tra đúng nguồn NVL/SETUP/HUT/CAT/EB.
- Tìm đối tượng theo từ khóa và phân trang server; không tải toàn bộ lịch sử khi mở form. Đổi loại kiểm tra/đối tượng sẽ xóa lựa chọn không còn phù hợp và bỏ qua phản hồi tìm kiếm cũ.
- LSX lấy từ đối tượng hoặc SETUP liên quan. Không suy LSX từ `DH_ID`. Cho phép trống khi nguồn không có liên kết; nếu nguồn chỉ định LSX nhưng LSX đó không tồn tại thì backend từ chối và báo rõ.
- Ngày giờ, số lượng, kết quả, hồ sơ, hình ảnh và ghi chú có trong form. Người QC lấy từ session; `NCR_ID` lịch sử chỉ hiển thị, chưa tạo liên kết mới.
- Kết quả là nội dung nhập theo nghiệp vụ, có gợi ý `OK`/`NG`; không ép chuyển đổi các giá trị lịch sử khác.
- Hồ sơ cho phép dán URL HTTP(S) hoặc tìm/chọn file qua Google Drive của người đang đăng nhập. Không dùng credential quản trị thay người dùng.
- Mã phiếu mới theo `QC_yymmdd_xx`, ngày hiện tại theo múi giờ Việt Nam. Sequence dùng chung được khóa trong transaction; hai chữ số cho phép tối đa 99 phiếu/ngày. Nếu đạt giới hạn, hệ thống báo lỗi thay vì tạo mã sai định dạng.
- Lưu lặp dùng `Idempotency-Key` và bảng `legacy_requests` hiện có; thao tác sửa dùng version đối chiếu nội dung để tránh ghi đè phiếu đã được sửa ở nơi khác. Audit dùng `audit_log` hiện có.
- Danh sách lọc mã QC, loại QC, loại đối tượng, OBJECT_ID, LSX và khoảng ngày; bấm Tra cứu mới tải dữ liệu. Chi tiết hỗ trợ xem/sửa và mở tài liệu.
- QC NG chỉ ghi kết quả và ghi chú. Không sửa kho, số lượng NG, trạng thái LSX, không tự tạo NCR/CAPA.

## Quyền

Tái sử dụng `users`, `role_permissions`, session và `require()`:

| Mã quyền | Phạm vi |
|---|---|
| `QC_VIEW` | Danh sách, xem chi tiết |
| `QC_CREATE` | Tạo QC, tìm đối tượng, tìm Drive |
| `QC_EDIT` | Sửa QC, tìm đối tượng, tìm Drive |

`LOCAL_ADMIN` theo cơ chế hiện có được truy cập toàn bộ. Không tự cấp quyền cho role khác. Quản trị viên có thể cấp các quyền QC tại màn hình User; để xem và sửa phiếu từ danh sách, cần cả `QC_VIEW` và `QC_EDIT`. Chưa có quyền/thao tác xóa QC. Mục NCR/CAPA đang phát triển hiển thị cho tài khoản có một trong các quyền QC, chưa có nghiệp vụ cần quyền riêng.

## API

| API | Chức năng |
|---|---|
| `GET /api/qc` | Danh sách có lọc/phân trang |
| `GET /api/qc/{id}` | Chi tiết QC |
| `POST /api/qc` | Tạo QC; header UUID `Idempotency-Key` bắt buộc |
| `PUT /api/qc/{id}` | Sửa QC; `version` bắt buộc |
| `GET /api/qc/objects` | Tìm đối tượng theo loại, từ khóa, trang |
| `GET /api/qc/drive` | Tìm file qua credential Google hiện có của người dùng |

## File tạo và sửa

- [Migration 004](./backend/alembic/versions/004_qc_production.py), [snapshot schema](./backend/app/migrations/snapshots/v004.py), [bộ nhập](./backend/app/migrations/import_qc_production.py).
- [Module production](./backend/app/modules/production/): model LSX/SETUP/HUT/WIP/CAT/EB.
- [Module QC](./backend/app/modules/qc/): model, schema đầu vào, service, API.
- [Đăng ký model](./backend/app/core/model_registry.py), [lắp router](./backend/app/main.py), [catalog quyền](./backend/app/auth/permissions.py).
- [Giao diện QC](./frontend/qc/), [sidebar JavaScript](./frontend/shared/navigation.js), [CSS sidebar](./frontend/shared/navigation.css).
- [Test QC](./backend/tests/test_qc.py), [khảo sát trước triển khai](./QC-khao-sat.md), báo cáo bàn giao này.

## Kiểm tra thực tế

- **15 test pass**: `python -m pytest -q tests/test_qc.py tests/test_google.py -p no:cacheprovider --disable-warnings` trong container backend local.
- Bao phủ tám tổ hợp QC/đối tượng, sai nguồn ID, tổ hợp loại sai, URL sai, số âm/NaN, giả mạo người QC/LSX, xác thực quyền, tìm kiếm/lọc/phân trang, replay và xung đột idempotency, sửa đồng thời bằng version, chuẩn hóa số/thời gian qua MySQL, QC NG không thay trạng thái NVL, contract import và alias EB.
- Tìm Drive trong test QC được giả lập để kiểm tra sử dụng đúng tài khoản và quyền; chưa kiểm thử tìm file trực tiếp bằng OAuth tài khoản thật.
- Kiểm tra cú pháp JavaScript đạt; VS Code không báo lỗi ở các file đã kiểm tra.
- Đối soát sau test: không còn user, QC, audit hoặc request QC thử nghiệm. Bảng CAT/EB giữ đúng 1 bản ghi mỗi bảng; các bảng mới còn lại giữ đúng 0.
- Chạy lại bộ nhập nhận biết snapshot đã áp dụng, không tạo bản ghi trùng.
- Đối soát migration: số dòng tất cả bảng nghiệp vụ cũ không đổi; `import_runs` có thêm đúng một bản ghi nhập liệu.
- Chưa kiểm thử tải đồng thời bằng nhiều kết nối độc lập hoặc kiểm thử toàn bộ giao diện qua tài khoản đăng nhập thật. Trình duyệt mở trang QC đã chuyển về đăng nhập đúng cơ chế session.
- Không chạy được Git CLI vì macOS thiếu Command Line Tools hợp lệ; đã rà soát các thay đổi có mục tiêu và kiểm tra lỗi/cú pháp/test liên quan.

## Sao lưu và báo cáo nhập

- [Bản sao lưu trước migration](./reports/napaco-before-qc-004.sql) có quyền đọc/ghi chỉ chủ sở hữu; thư mục reports được Git ignore.
- [Báo cáo nhập và đối soát](./reports/qc-import-004.json) ghi các dòng thiếu mã, số dòng đã nhập và revision `004`.
- Bộ nhập mặc định chỉ kiểm tra. `python -m app.migrations.import_qc_production --apply` chỉ nhập khi các bảng đích còn trống và snapshot chưa được nhập; không hỗ trợ tự nhập đè dữ liệu đã có. Nếu cần nhập bổ sung các dòng vừa sửa mã trong Excel, phải dùng bước nhập bổ sung được đối soát riêng.

## Sử dụng

1. Đăng nhập ứng dụng local và mở menu **QC → Tạo Phiếu QC**.
2. Chọn loại kiểm tra, loại đối tượng; nhập từ khóa và nhấn **Tìm đối tượng** rồi chọn bản ghi. LSX tự hiển thị khi nguồn có liên kết.
3. Nhập ngày giờ, số lượng, kết quả, hồ sơ và ghi chú; nhấn **Lưu phiếu QC**. Với nguồn LSX/SETUP/HUT đang trống, cần có bản ghi nghiệp vụ thật trước khi chọn chúng.
4. Vào **QC → Danh sách QC**, chọn bộ lọc và nhấn **Tra cứu**; mở chi tiết để xem/sửa theo quyền.
5. Nếu chưa nối Google, dùng liên kết **Kết nối Google Drive** tại sidebar hoặc dán URL hồ sơ trực tiếp.
