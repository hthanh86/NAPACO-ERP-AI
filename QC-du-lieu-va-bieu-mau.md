# QC — biểu mẫu, hồ sơ và dữ liệu lưu trữ

Tài liệu mô tả chức năng hiện tại tại ngày 12/11/2026. MySQL lưu dữ liệu nghiệp vụ và chữ ký; Google Drive lưu PDF cùng file bằng chứng. Điều chỉnh lần này dùng cấu trúc đã có ở migration `006`, không thêm bảng, cột hoặc chạy migration mới.

## 1. Phân biệt template, bản ghi QC và phiếu PQC

| Thành phần | Ví dụ | Nơi lưu và ý nghĩa |
| --- | --- | --- |
| Template đang ban hành cho NVL | `QC_NVL_261101_V1` | Định nghĩa bằng code trong [forms.py](backend/app/modules/qc/forms.py). Ngày ban hành 01/11/2026, phiên bản 1. Chọn nhiều lần vẫn dùng mã này cho tới khi thay template đang ban hành. |
| Bản ghi nghiệp vụ QC | `QC_261112_01` | Một dòng trong `qc_checks`, khóa chính `QC_ID`. Giữ nguyên cơ chế cấp mã QC hiện có. |
| Phiếu kiểm tra đã điền và ký | `PQC_261112_01` | Lưu toàn bộ trong `qc_checks.FORM_DATA`; mã nằm tại `document_id`. PQC dùng đúng phần ngày và số thứ tự của QC, không cấp số độc lập, không tạo thêm một dòng/bảng phiếu PQC. |
| PDF hồ sơ | `PQC_261112_01.pdf` | Sinh từ snapshot đã lưu trong MySQL, upload vào thư mục Drive của QC. Có thể tải lại từ chi tiết QC. File PDF không lưu binary trong MySQL. |
| Thư mục hồ sơ trên Drive | `QC_261112_01` | Tạo trong thư mục cha người dùng chọn, thuộc phạm vi `QC_ROOT_FOLDER_ID`. ID thư mục con lưu trong `qc_checks.DRIVE_FOLDER_ID`. |

Ví dụ cấu trúc Drive:

```text
QC_ROOT_FOLDER_ID
└── QC_261112_01/
    ├── PQC_261112_01.pdf
    ├── anh-kiem-tra.jpg
    └── video-kiem-tra.mp4
```

## 2. Quy tắc chọn phiên bản và nhập biểu mẫu

- `REGISTRY` giữ các định nghĩa có thể cần để đọc hồ sơ cũ. `RELEASED` ánh xạ mỗi nghiệp vụ sang tối đa một template đang ban hành; không chọn tùy ý phiên bản cũ cho phiếu mới.
- Nghiệp vụ `NVL` dùng `QC_NVL_261101_V1`. Nghiệp vụ `PRODUCT` tương ứng các loại QC đầu ca/giữa ca/cuối ca, hiện chưa có template ban hành vì chưa có tiêu chuẩn sản phẩm được cung cấp. Nút biểu mẫu bị vô hiệu hóa và thông báo rõ; các chức năng QC lịch sử vẫn giữ nguyên.
- Khi có template sản phẩm hoặc phiên bản bổ sung tiêu chí, thêm định nghĩa vào code và cập nhật đúng một mã trong `RELEASED` cho nghiệp vụ đó. Backend kiểm tra mã gửi lên thuộc bản đang ban hành, không chỉ lọc ở giao diện.
- Phiếu đã lưu dùng snapshot `FORM_DATA.definition` của chính phiếu đó khi xem, sửa và xuất PDF. Ban hành template mới không tự chuyển đổi phiếu cũ. Mã cũ `QC_NVL_V1` được giữ cho lịch sử, không đưa vào lựa chọn tạo mới.
- Với template mới, các nội dung có sẵn ở cột Dung sai/Ghi chú là placeholder gợi ý, ẩn khi focus vào ô; không tự coi là kết quả người dùng nhập. MySQL vẫn lưu chúng trong định nghĩa template để tái hiện gợi ý; `input.answers[].note` chỉ lưu nội dung người dùng thực nhập. PDF in ghi chú đã nhập, không tự in placeholder thành ghi chú.
- Chọn **Không áp dụng** (`NA`) làm ô Kết quả thực tế bị khóa và bôi xám. Backend chuẩn hóa kết quả thực tế về rỗng; ghi chú không bắt buộc. Tiêu chí áp dụng phải có kết quả; vẫn cần ít nhất một tiêu chí áp dụng. Nếu có FAIL, kết luận phải là FAIL; các tiêu chí áp dụng đều PASS thì kết luận PASS. PASS ánh xạ `Ket_Qua=OK`, FAIL ánh xạ `Ket_Qua=NG`.
- Người dùng ký bằng chuột/trackpad/cảm ứng. Đổi kết quả hoặc dữ liệu liên quan làm mất chữ ký đang nhập để yêu cầu ký lại. Backend ghi nhận tài khoản và thời điểm ký; đây là xác nhận nội bộ ERP.

## 3. Bảng lưu trực tiếp hồ sơ QC

### `qc_checks` — nguồn chính của từng phiếu

| Cột MySQL | Dữ liệu và mục đích |
| --- | --- |
| `QC_ID` | Khóa chính, mã `QC_yymmdd_xx`. |
| `Ngay_Gio` | Ngày giờ kiểm tra. |
| `CHECK_TYPE`, `OBJECT_TYPE`, `OBJECT_ID` | Loại QC, loại đối tượng và mã bản ghi nhập NVL/setup/sản xuất được kiểm tra. |
| `LSX_ID` | Liên kết lệnh sản xuất nếu nguồn có liên quan. |
| `Tieu_Chuan_STD` | Giữ nguyên cột TEXT cũ. Với biểu mẫu ERP lưu mã template, ví dụ `QC_NVL_261101_V1`; phiếu lịch sử vẫn có thể chứa URL tiêu chuẩn cũ. Không phải nơi lưu bản PDF đã điền. |
| `So_Luong` | Số lượng kiểm tra. Kiểu cột cũ vẫn là DECIMAL; backend yêu cầu số nguyên dương. |
| `Ket_Qua`, `Nguoi_QC` | Kết quả chung và mã người QC; tên hiển thị lấy từ `users`. |
| `NCR_ID`, `Ghi_Chu` | Tham chiếu NCR hiện có và ghi chú nghiệp vụ. Thay đổi này không bổ sung quy trình NCR/CAPA. |
| `evidence` | Liên kết bằng chứng lịch sử, giữ nguyên. Hồ sơ mới dùng `DRIVE_FOLDER_ID` để tạo link thư mục, không cần ghi URL mới vào đây. |
| `DRIVE_FOLDER_ID` | ID thư mục Drive con mang tên QC. Không phải ID thư mục gốc của công ty. |
| `FORM_DATA` | JSON chứa phiếu PQC đã điền, snapshot template, kết quả từng tiêu chí và chữ ký. |
| `source` | JSON dữ liệu nguồn lịch sử và trạng thái xử lý Drive. `qc_bundle` lưu trạng thái chờ/lỗi, ID PDF, hash phiên bản PDF và người thực hiện; ID cha chỉ được giữ tạm trước khi thư mục con hoàn tất. Không phải danh mục file bằng chứng. |

Cấu trúc chính của `FORM_DATA`:

```text
document_id: PQC_261112_01
definition: code, version, business, issued_on, name, resins, criteria, tolerance_as_hint
input: code, resin, answers[{id, actual, assessment, note}], conclusion, note, signature
context: checked_at, check_type, object_type, object_id, quantity, result, note
signer: user_id, name, signed_at, method
```

`signature` là danh sách nét vẽ gồm các tọa độ chuẩn hóa từ 0 đến 1. `signer` do backend ghi từ tài khoản xác thực; không nhận tên người ký hoặc thời điểm ký tùy ý từ frontend. Phiếu lịch sử chưa có `document_id` vẫn suy ra mã PQC từ QC_ID khi hiển thị/xuất, không cần cập nhật hàng loạt dữ liệu cũ.

### `system_settings` — cấu hình dùng chung

| Khóa | Giá trị hiện tại | Mục đích |
| --- | --- | --- |
| `QC_ROOT_FOLDER_ID` | `1N_sNZGMv2LyPE1mowNGRTa9KW6A2kmnz` | Thư mục Drive gốc của hồ sơ QC công ty. Các cột của bảng là `key` và `value`. |

Giao diện lấy cấu hình khi tải danh mục biểu mẫu. Nhấn **Mở Drive · Chọn thư mục cha** mở trình duyệt thư mục ngay tại root hiện hành trong `system_settings`; người dùng có thể đi vào thư mục con rồi chọn thư mục cha mong muốn. `parent_folder_id` gửi lên quyết định nơi tạo thư mục QC; backend kiểm tra thư mục đã chọn thuộc root và tài khoản OAuth có quyền ghi. Chọn thư mục chỉ cập nhật phiếu đang nhập, không thay đổi `system_settings`. Các thư mục đã gắn với phiếu vẫn được giữ; nếu đổi root, cần bảo đảm hồ sơ cũ còn thuộc phạm vi được phép trước khi sửa/upload tiếp.

### Các bảng hỗ trợ ghi nhận QC

| Bảng | Dữ liệu lưu và cách QC sử dụng |
| --- | --- |
| `sequences` | Bộ đếm cấp mã theo ngày. QC dùng khóa `QC_yymmdd`, khóa dòng khi cấp số để tránh trùng; giới hạn 99 phiếu/ngày. PQC không có bộ đếm riêng. |
| `legacy_requests` | Khóa idempotency của yêu cầu tạo đơn/lô QC (`qc:`/`qcb:`), người gửi, hash payload và kết quả trả ban đầu. Thử lại cùng yêu cầu không tạo thêm QC. Đây là dữ liệu kỹ thuật, không thay thế dòng hiện hành trong `qc_checks`. |
| `audit_log` | Ai tạo/sửa QC, hành động `QC_CREATE`/`QC_EDIT`, mã phiếu và tham chiếu đối tượng. Không phải bảng chi tiết kết quả tiêu chí. |

Không tạo bảng template động, bảng PQC riêng hoặc `QC_FILES`. Không thêm các cột `DRIVE_PARENT_FOLDER_ID` và `DRIVE_FOLDER_URL`. Metadata file bằng chứng nằm ở Drive; `appProperties.qc_upload` dùng nhận diện file đã hoàn tất khi thử gửi lại.

## 4. Các bảng nguồn QC đọc để tra cứu và đối chiếu

| Bảng | Vai trò trong QC |
| --- | --- |
| `film_receipts` | Nguồn mã nhập `N_NVL_...`, ngày nhập và số lượng. IQC mới chỉ chọn lô nhập trong 15 ngày lịch gồm hôm nay, còn tồn và chưa có QC. |
| `film_movements` | Xuất cấp/trả NVL để tính tồn còn lại của từng phiếu nhập. QC không tự tạo giao dịch kho. |
| `film_order_lines`, `film_purchase_orders` | Chi tiết mua NVL, nhựa và liên kết nhà cung cấp/đơn mua. |
| `film_materials`, `film_suppliers` | Quy cách NVL và tên nhà cung cấp hiển thị khi tra cứu. |
| `order_lines`, `products` | Tìm tên sản phẩm liên kết với dòng đặt NVL nếu có gắn đơn. |
| `production_orders` | Đối chiếu mã LSX liên quan. |
| `production_setups` | Nguồn đối tượng QC đầu ca (`SETUP`), đồng thời giúp truy ra LSX của công đoạn. |
| `forming_logs`, `cutting_logs`, `eb_logs` | Nguồn đối tượng QC giữa/cuối ca cho HUT/CAT/EB. |

QC đọc/khóa các dòng nguồn cần thiết để kiểm tra tồn tại và hợp lệ; việc lưu QC không tự đổi trạng thái nhập kho, sản xuất hoặc tồn kho.

## 5. Tài khoản, phân quyền và OAuth dùng lại

| Bảng | Mục đích |
| --- | --- |
| `users` | Người dùng ERP, tên hiển thị và người xác nhận biểu mẫu. |
| `role_permissions` | Quyền hiện có như QC_VIEW/QC_CREATE/QC_EDIT. Backend kiểm tra quyền cho từng API. |
| `login_sessions` | Phiên đăng nhập ERP; không phải dữ liệu phiếu. |
| `google_credentials` | Thông tin OAuth Google đã mã hóa gắn với người dùng, dùng truy cập Drive theo quyền tài khoản đó. Token không trả về frontend. |
| `google_oauth_states` | Trạng thái bảo vệ quá trình kết nối OAuth, không lưu kết quả kiểm tra QC. |

## 6. Luồng lưu và xử lý lỗi

1. Chọn đối tượng, nhập số lượng/ngày giờ, mở template đang ban hành của nghiệp vụ, nhập kết quả và ký.
2. Mở Drive từ root QC cấu hình chung, duyệt và chọn thư mục cha. Chọn file bằng chứng từ thiết bị; file còn ở trình duyệt, chưa gửi lên Drive.
3. Backend kiểm tra quyền, dữ liệu, chữ ký, phạm vi và quyền ghi thư mục cha đã chọn; cấp QC_ID và lưu QC cùng FORM_DATA trong transaction MySQL.
4. Sau commit, tạo thư mục tên QC_ID. ID được cấp và lưu trước thao tác tạo thực tế để thử lại bằng cùng ID, tránh trùng thư mục.
5. Sinh PDF tên PQC từ snapshot MySQL, upload vào thư mục QC, rồi gửi bằng chứng theo khối 4 MiB. Giữ nguyên giới hạn upload lớn hiện có; file không được nạp toàn bộ vào bộ nhớ backend trong một request.
6. Lỗi tạo thư mục/xuất PDF/upload sau commit không xóa QC. Trạng thái lỗi nằm trong `source.qc_bundle`; thử lại trên phiếu đã lưu. Upload file hỗ trợ thăm dò offset và tiếp tục; đóng trình duyệt cần chọn lại file chưa hoàn tất.
7. Hoàn tất thì điều hướng về danh sách với bộ tìm kiếm `QC_yymmdd`; khi vào danh sách trực tiếp, mặc định một tháng trước tới hôm nay và tra cứu luôn.

Backend tiếp tục kiểm tra thư mục thuộc root khi xử lý và upload, kể cả thư mục đã lưu. Không tự chia sẻ công khai. Nút **Mở thư mục bằng chứng** tạo URL từ `DRIVE_FOLDER_ID` và mở tab mới.

## 7. Vị trí code và xác minh

- [forms.py](backend/app/modules/qc/forms.py): định nghĩa, ánh xạ bản đang ban hành, kiểm tra kết quả/chữ ký và mã PQC.
- [service.py](backend/app/modules/qc/service.py), [schemas.py](backend/app/modules/qc/schemas.py), [api.py](backend/app/modules/qc/api.py): kiểm tra đầu vào, transaction, lưu snapshot và API QC.
- [settings.py](backend/app/core/settings.py): đọc cấu hình chung từ MySQL.
- [drive_bundle.py](backend/app/modules/qc/drive_bundle.py), [pdf.py](backend/app/modules/qc/pdf.py): Drive, thử lại/upload và xuất PDF.
- [forms.js](frontend/qc/forms.js), [qc.js](frontend/qc/qc.js), [index.html](frontend/qc/index.html), [qc.css](frontend/qc/qc.css): giao diện QC và biểu mẫu.
- [test_qc_forms.py](backend/tests/test_qc_forms.py): kiểm tra phạm vi Drive, template đang ban hành, giữ snapshot cũ, PQC, NA và PDF; các test nghiệp vụ chạy cùng [test_qc.py](backend/tests/test_qc.py), [test_iqc.py](backend/tests/test_iqc.py).

Đã đối chiếu các tên bảng/cột nêu trên với MySQL local. Sau kiểm thử rollback, database vẫn có 6 QC lịch sử, chưa có dòng FORM_DATA nghiệp vụ thật, revision `006`. Bộ kiểm thử tập trung đạt 23 test trên image backend mới. Tài liệu này không chứa token OAuth hoặc thông tin đăng nhập.

Điều chỉnh sau đó: khôi phục chọn thư mục cha từ root cấu hình chung; không chạy lại kiểm thử theo yêu cầu người dùng. Kết quả 23 test ở trên thuộc lần kiểm tra trước điều chỉnh này.
