# Bàn giao QC và các bảng sản xuất liên quan

## Cập nhật IQC NVL — migration 005

Đã áp dụng trên local, ngày 12/11/2026:

- Tìm NVL chỉ trả phiếu nhập còn tồn, chưa có OBJECT_ID trong bảng QC và ngày nhập từ hôm nay trừ 14 ngày đến hết hôm nay (15 ngày lịch, theo giờ Việt Nam). Chỉ truy vấn khi nhấn tìm kiếm; cho phép để trống từ khóa để xem những phiếu phù hợp, phân trang server.
- Hiển thị mã N_NVL, các tên sản phẩm được gắn qua đơn hàng, nhựa/quy cách và nhà cung cấp. Có thể tìm theo mã, sản phẩm, nhựa và nhà cung cấp. Tồn kho tính đúng quy tắc đang có: đã nhận − cấp + trả được xác nhận; trả chưa xác nhận không được cộng tồn.
- **Tạo phiếu tiếp theo** đưa phiếu vào danh sách tạm rồi mở form trắng. **Tạo Phiếu** gửi toàn bộ danh sách cùng phiếu đang nhập trong một transaction, tối đa 10 phiếu. Nếu form hiện tại trống thì chỉ gửi các phiếu đã đưa vào danh sách tạm. Một phiếu nhập không được lặp trong lô. Phiếu tạm chưa được ghi MySQL; rời trang sẽ được nhắc nếu còn danh sách tạm.
- Backend kiểm tra lại điều kiện NVL khi tạo, khóa các phiếu nhập theo thứ tự cố định để chống hai yêu cầu cùng IQC một phiếu nhập; dùng idempotency để retry không tạo lặp. Nếu một phiếu lỗi hoặc lỗi giữa lúc ghi thì rollback toàn bộ lô. Sửa QC đã có vẫn được phép khi NVL đã quá 15 ngày/hết tồn, miễn giữ nguyên đối tượng. Nếu đổi sang đối tượng khác, đối tượng mới phải đủ điều kiện.
- Nhập/sửa số lượng kiểm tra yêu cầu **số nguyên dương**. Danh sách và form chi tiết hiển thị số nguyên; không sửa kiểu cột DECIMAL hoặc tự chuyển đổi dữ liệu lịch sử trong database.
- Danh sách: từ ngày/đến ngày cùng hàng; tạm ẩn bộ lọc OBJECT_ID và mã OBJECT_ID trong cột đối tượng, giữ hỗ trợ trong API; người QC hiển thị tên user. Cột **Tiêu Chuẩn** dùng `Tieu_Chuan_STD`; cột **Bằng Chứng** dùng `evidence`.
- [Migration 005](./backend/alembic/versions/005_qc_evidence.py) đổi tên cột `qc_checks.Hinh_Anh` thành `evidence`, không sao chép/xóa dữ liệu. Thuộc tính Python/API `image_url` giữ tương thích; API danh sách/chi tiết có thêm `evidence` và `staff_name`.
- Form chi tiết có nút lưu/đóng ở cả đầu và cuối. Tìm đối tượng mặc định thu gọn, có thể mở để tìm và gán lại.
- API mới: `POST /api/qc/batch`, body `{items: [...]}`, header UUID `Idempotency-Key`. Chỉ áp dụng cho IQC NVL; quyền vẫn là `QC_CREATE` hiện có.

File chỉnh sửa: [service QC](./backend/app/modules/qc/service.py), [schema đầu vào](./backend/app/modules/qc/schemas.py), [API QC](./backend/app/modules/qc/api.py), [model QC](./backend/app/modules/qc/models.py), [bộ nhập nguồn](./backend/app/migrations/import_qc_production.py), [HTML](./frontend/qc/index.html), [JavaScript](./frontend/qc/qc.js), [CSS](./frontend/qc/qc.css), [test QC](./backend/tests/test_qc.py). File mới: [truy vấn NVL cho IQC](./backend/app/modules/qc/materials.py), [migration 005](./backend/alembic/versions/005_qc_evidence.py), [test IQC](./backend/tests/test_iqc.py).

Kiểm tra thực tế:

- **11 test QC và 3 test IQC đạt** trong MySQL local bằng fixture rollback. Bao gồm mốc 15 ngày, tồn/phiếu trả chưa xác nhận, tìm tên sản phẩm/NCC, phân trang, chống IQC trùng, số nguyên dương, lô 10 phiếu, từ chối 11 phiếu, quyền, idempotency và rollback cả sau khi phiếu đầu đã flush.
- Kiểm tra cú pháp JavaScript đạt; kiểm tra lỗi VS Code không phát hiện lỗi ở các file đã kiểm tra.
- Kiểm tra trình duyệt bằng đăng nhập local: tên/quy cách/NCC thực tế; ngày lọc cùng hàng; OBJECT_ID ẩn; tên người QC; link tiêu chuẩn/bằng chứng; form chi tiết thu gọn và đủ hai cặp nút lưu/đóng.
- Kiểm tra danh sách tạm và gửi đúng lô 10 phiếu trên trình duyệt bằng API phản hồi giả lập; không ghi các phiếu thử đó vào database. Test backend tạo lô dùng MySQL thật nhưng rollback sau test.
- Migration đối chiếu SHA-256 của cặp mã QC/liên kết bằng chứng trước và sau: khớp, giữ nguyên 1 phiếu thật. Sau kiểm thử vẫn chỉ có 1 QC, không còn user/QC/audit/request thử nghiệm.
- Sao lưu trước migration: [napaco-before-iqc-005.sql](./reports/napaco-before-iqc-005.sql), quyền file 600, nằm trong thư mục được Git ignore. [Đối soát migration](./reports/iqc-migration-005.json), [đối soát sau test](./reports/iqc-validation-005.json).
- Đã build lại image và nạp thay đổi backend local. Không thêm dependency, không tác động production. Chưa kiểm thử tải đồng thời nhiều kết nối hoặc Drive OAuth thật trong lần cập nhật này.

## Nội dung bàn giao ban đầu — migration 004

### Trạng thái ban đầu

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
# Biểu mẫu ERP và thư mục hồ sơ QC — migration 006

- `system_settings`: khóa `QC_ROOT_FOLDER_ID`, giá trị `1N_sNZGMv2LyPE1mowNGRTa9KW6A2kmnz`. Không dùng lại thư mục upload của module đơn hàng.
- `qc_checks`: thêm `DRIVE_FOLDER_ID VARCHAR(255) NULL`, `FORM_DATA JSON NULL`. Giữ nguyên `Tieu_Chuan_STD TEXT`, `evidence` và toàn bộ dữ liệu cũ. Không tạo `QC_FILES`, `DRIVE_PARENT_FOLDER_ID`, `DRIVE_FOLDER_URL`.
- `QC_NVL_V1` định nghĩa trong code gồm 7 hạng mục từ ảnh người dùng cung cấp. Không tự bổ sung dung sai hoặc suy ra quy tắc theo PET/PP/PS/PVC. Tiêu chí Không áp dụng cần lý do; kết luận phải khớp đánh giá. PASS ánh xạ sang kết quả phiếu OK, FAIL sang NG.
- `FORM_DATA` lưu bản chụp định nghĩa/phiên bản, đầu vào, kết quả, nét ký chuẩn hóa, người dùng và thời điểm ký do backend ghi nhận. PDF và dialog phiếu cũ dùng bản chụp này. Thay cấu trúc đã sử dụng phải tạo mã phiên bản mới.
- Phiếu IQC mới bắt buộc có biểu mẫu đã ký và thư mục cha hợp lệ. Phiếu lịch sử vẫn xem/sửa theo cấu trúc cũ; khi bổ sung form ERP sẽ áp dụng luồng mới.
- Backend duyệt và kiểm tra chuỗi thư mục cha tới thư mục gốc bằng OAuth của người dùng. Chặn file/shortcut và thư mục ngoài phạm vi; kiểm tra lại lúc lưu, tạo hồ sơ và upload.
- Lưu QC trong transaction trước xử lý Drive. Cấp trước và lưu ID thư mục trước tạo; thử lại dùng cùng ID. Không đổi tên/move bằng chứng cũ trong luồng form mới. Trạng thái tạo thư mục/PDF nằm trong JSON `source`, không có bảng danh mục file.
- Upload bằng chứng sau lưu, theo khối 4 MiB qua backend; token OAuth không đưa ra trình duyệt. Ticket upload mã hóa gắn với user/QC/folder, hỗ trợ thăm dò offset và tiếp tục. Dữ liệu file giữ tại trình duyệt tới khi gửi; đóng trang cần chọn lại file chưa hoàn tất. Drive appProperties dùng nhận diện file đã gửi để tránh gửi lại bản hoàn tất.
- Đã chạy 19 test QC/IQC/form/phạm vi Drive/retry trên image mới, gồm xuất PDF thật với font Unicode và ghi chú dài; test nghiệp vụ dùng rollback MySQL. Browser đã thử nhập đủ 7 tiêu chí, ký bằng pointer, chọn thư mục, gửi khối bằng chứng và điều hướng về danh sách; POST tạo/upload của bài thử browser được giả lập, không thêm phiếu thật.
- Migration 006 đã chạy local. Đối chiếu 6 phiếu lịch sử không thay đổi; bản sao trước migration: `reports/qc-before-006.json` (quyền 600). Một trong hai kết nối OAuth có quyền ghi thư mục gốc `05_HỒ_SƠ_RECORDS`; kết nối còn lại bị Google từ chối HTTP 403.
- Đã bổ sung `reportlab==5.1.0` trong `backend/requirements.txt` và font `fonts-dejavu-core` trong `backend/Dockerfile`, build image `napaco-local-backend:latest` (`b206efcc3acb`) và recreate riêng backend local. Backend đang chạy image mới; MySQL không bị recreate hoặc xóa volume.
- Đã xuất PDF thật, render và xem trực tiếp: mẫu 7 tiêu chí, tiếng Việt, kết luận và chữ ký nằm đủ trên một trang A4 ngang. Trường hợp ghi chú dài được kiểm tra xuất nhiều trang không phát sinh lỗi bố cục.
- Đã kiểm tra Drive thật bằng OAuth có quyền trên thư mục gốc: tạo thư mục QC/PDF trong thư mục test riêng, thử lại dùng cùng ID thư mục/PDF, upload 9.200.000 byte theo khối, thăm dò và tiếp tục từ offset 4.194.304, đối chiếu checksum và bỏ qua file đã hoàn tất khi gửi lại. Có đúng hai file trong thư mục con: PDF và bằng chứng thử nghiệm. Thư mục test đã đưa vào thùng rác; transaction QC test rollback, số phiếu trước/sau đều là 6, revision MySQL vẫn `006`. Kết quả kỹ thuật lưu trong `reports/qc-deploy-verification.json`.
- Tài khoản `local-admin` của tab trình duyệt hiện chưa nối Google. Để thử toàn bộ quy trình, đăng nhập tài khoản ERP đã nối Google có quyền ghi thư mục QC, hoặc dùng **Kết nối Google Drive** với tài khoản Google có quyền tương ứng. Chưa thử video kích thước hàng GB; cơ chế truyền từng khối đã được kiểm tra thực tế với file 9,2 MB.

### Các file chính của phần biểu mẫu và Drive

- `backend/app/modules/qc/forms.py`, `schemas.py`, `service.py`, `api.py`, `models.py`: định nghĩa/kiểm tra biểu mẫu, lưu snapshot và tích hợp luồng QC hiện có.
- `backend/app/modules/qc/pdf.py`, `drive_bundle.py`: xuất PDF, kiểm tra phạm vi thư mục và upload có tiếp tục.
- `backend/app/core/settings.py`, `model_registry.py`, `backend/alembic/versions/006_qc_forms.py`: cấu hình chung và migration bổ sung an toàn.
- `backend/app/integrations/google/oauth.py`: tái sử dụng OAuth, bổ sung xử lý Drive 404 cho thử lại theo ID đã cấp.
- `frontend/qc/index.html`, `forms.js`, `qc.js`, `qc.css`: dialog biểu mẫu/chữ ký, chọn thư mục, giữ file trước lưu và tiến trình upload.
- `backend/tests/conftest.py`, `test_qc.py`, `test_iqc.py`, `test_qc_forms.py`: kiểm thử tập trung có rollback; `backend/requirements.txt`, `backend/Dockerfile`: dependency PDF/font.

## Điều chỉnh template, phiếu PQC và thư mục mặc định — 12/11/2026

- Tài liệu mô tả dữ liệu hiện hành: [QC — dữ liệu và biểu mẫu](./QC-du-lieu-va-bieu-mau.md). Phần này thay thế hướng dẫn chọn thư mục thủ công và mã template trong mô tả triển khai trước ở trên.
- Template NVL đang ban hành là `QC_NVL_261101_V1`. Mã cũ giữ cho lịch sử; ánh xạ `RELEASED` chỉ cho phép một template đang ban hành mỗi nghiệp vụ. Chưa có template sản phẩm thực tế, nên giao diện báo chưa ban hành và không cung cấp mẫu NVL cho QC sản phẩm.
- Dung sai/Ghi chú dùng placeholder, ẩn khi focus; giá trị gợi ý không được lưu như ghi chú người dùng. Không áp dụng khóa/bôi xám kết quả thực tế, không bắt nhập ghi chú; backend chuẩn hóa actual về rỗng.
- Bản ghi QC giữ mã `QC_yymmdd_xx`; hồ sơ điền và ký có mã `PQC_yymmdd_xx` cùng phần ngày/số, lưu tại `FORM_DATA.document_id`. PDF mới tên PQC, thư mục vẫn tên QC. Không có bộ đếm PQC hoặc bảng PQC riêng.
- Hồ sơ mới dùng trực tiếp root tại `system_settings.QC_ROOT_FOLDER_ID`, không mở hộp duyệt thư mục. Backend lấy lại root từ MySQL lúc lưu và giữ kiểm tra quyền/phạm vi Drive.
- Đã build và recreate backend local với image `7cff407f10dc`. Bộ kiểm thử QC tập trung đạt 23 test, bao gồm chọn template đúng nghiệp vụ, chặn bản đã ngừng ban hành cho phiếu mới, giữ snapshot đã lưu và mã PQC. Đã kiểm tra giao diện placeholder/NA/root tự động; không thêm hoặc sửa phiếu nghiệp vụ thật. Không migration mới; 6 QC lịch sử giữ nguyên, revision `006`.

### Làm rõ chọn thư mục cha

- Đã khôi phục **Mở Drive · Chọn thư mục cha**. Hộp chọn mở tại root hiện hành từ `system_settings`, cho duyệt/chọn thư mục bên trong; backend dùng thư mục cha đã chọn để tạo thư mục QC, tiếp tục kiểm tra phạm vi và quyền ghi.
- Chọn thư mục không ghi hoặc thay đổi cấu hình chung. Phiếu đã có thư mục bằng chứng giữ nguyên thư mục đó.
- Không chạy test cho điều chỉnh này theo yêu cầu người dùng; kết quả 23 test nêu trên thuộc bản trước điều chỉnh.

