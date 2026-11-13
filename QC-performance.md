# Rà soát hiệu năng QC / Drive / PDF — bản ghi thời gian trước tối ưu

## Phạm vi bản cập nhật

Theo chỉ dẫn tiếp theo của người dùng, ưu tiên đưa logging chi tiết lên local trước, thao tác thực tế rồi đọc log để quyết định tối ưu. Bản này bỏ cột **Tiêu chuẩn** ở danh sách QC và bổ sung đo thời gian. Chưa thay cơ chế cache, HTTP connection pooling, upload, xử lý nền hay cấu trúc MySQL; không khẳng định đã tăng tốc khi chưa có số liệu.

Không chạy benchmark, test tự động, tạo phiếu thử, upload hoặc xóa dữ liệu Drive. Không sửa template, hồ sơ QC hay phân quyền hiện tại.

## Những điểm đã xác minh từ source

| Công đoạn | Hiện trạng thực tế |
| --- | --- |
| OAuth | Token đã mã hóa theo user; chỉ refresh khi còn không quá 60 giây. Chưa có bằng chứng refresh xảy ra mỗi lần click. |
| Liệt kê thư mục | Đã dùng files.list với parents, mimeType folder, trashed=false, pageSize=50 và metadata tối thiểu id/name; không quét toàn bộ Drive hoặc duyệt đệ quy danh sách. |
| Kiểm tra phạm vi | in_scope đọc root, folder được chọn rồi lần lượt đọc tổ tiên. Root bị đọc lại khi chính root được chọn hoặc khi duyệt tới tổ tiên cuối. Việc xác minh lặp ở browse, lưu phiếu, chuẩn bị PDF, mở phiên upload và mỗi chunk. |
| Số request browse | Với token còn hạn: mở root có 2 metadata GET + 1 files.list; thư mục con trực tiếp có 3 metadata GET + 1 files.list. Chưa tính độ trễ mạng, chưa coi số request là số liệu thời gian. |
| Điều hướng UI | Chưa có cache danh sách thư mục. Đã có epoch bỏ kết quả request cũ. Mở lại thư mục vẫn gọi backend. |
| Lưu QC | MySQL commit trước nhưng endpoint tiếp tục gọi finish_evidence → prepare/process trước khi trả phản hồi. Lô QC xử lý Drive lần lượt. Chưa có worker chạy độc lập. |
| PDF đang hoạt động | ReportLab render từ snapshot biểu mẫu ERP đã ký; chữ ký là vector nội bộ. Không copy Sheets, ghi mapping lên Sheets, chèn chữ ký lên Sheets hay export PDF từ Google trong nhánh này. Không có sleep/polling cố định trong luồng PDF. Layout PDF chưa thay đổi ở bản logging. |
| QC_NVL_V1 mapping | Nhánh Google-template đang chỉ lưu MySQL và snapshot; PDF/Drive/upload cho phiếu có TEMPLATE_ID vẫn bị chặn theo phạm vi Bước 2. Không có bước export QC_NVL_V1 để đo trong source hiện tại. |
| Upload PDF | Tạo file metadata rồi PATCH binary PDF. ID folder/PDF được lưu trước để retry; pdf_revision tránh render/upload lại khi nội dung không đổi. |
| Bằng chứng thiết bị | Binary qua backend, không Base64. Mọi kích thước dùng resumable; chunk 4 MiB. Client upload tuần tự. Metadata scope được đọc lại trên từng chunk. |
| Retry | File hoàn tất được đánh dấu ở tab; khi mở upload lại có truy vấn appProperties qc_upload để tránh tải lại file đã có. Trạng thái task/folder/PDF nằm trong source JSON/DRIVE_FOLDER_ID, không có QC_FILES. File chưa tải xong vẫn cần tab hoặc chọn lại file; không có worker nhận dữ liệu file sau khi tab đóng. |
| Network | google_json dùng urllib.request và upload dùng httpx.request cho từng request. Chưa đo phần kết nối/TLS và truyền dữ liệu nên chưa kết luận đây là nút thắt lớn nhất. |

Schema MySQL đọc lại trong lần rà soát có FORM_DATA, DRIVE_FOLDER_ID, source JSON và TEMPLATE_ID; không cần migration cho logging. Không tự thêm trạng thái hay bảng file.

## Log bổ sung

Backend ghi từng dòng `QC_PERF` dạng JSON với trace ngẫu nhiên, operation, ms, ok và các số đếm/kích thước. `perf_counter` là đồng hồ đơn điệu; duration tính bằng ms. Không ghi URL, request/response body, tên file, nội dung ô, token, email hay SQL/bound parameters.

Mỗi API QC có `X-QC-Trace` trong response header để đối chiếu. Cùng trace xuất hiện ở các công đoạn bên dưới. `Server-Timing` hiện hữu vẫn phản ánh thời gian backend; không bao gồm toàn bộ đường truyền browser.

| Operation | Ý nghĩa |
| --- | --- |
| qc.request, qc.endpoint.<tên hàm> | Tổng thời gian backend đến khi tạo response, HTTP status của endpoint |
| oauth.access_token | Đọc/giải mã hoặc refresh token; gồm thời gian DB và refresh nếu cần |
| oauth.refresh_token | Chỉ xuất hiện khi thực sự refresh token |
| google.json | Mỗi lần gọi Google JSON, gồm mở kết nối, chờ và đọc/parse response |
| drive.browse | Tổng thời gian xử lý browse |
| drive.verify_scope, drive.folder_metadata | Kiểm tra phạm vi và từng metadata GET trên chuỗi tổ tiên |
| drive.files_list, drive.files_metadata, drive.files_create | Thời gian liệt kê, đọc metadata và tạo folder/file metadata |
| drive.generate_id | Lấy ID tạo trước để retry an toàn |
| qc.create_total, qc.update_total | Tổng luồng tạo/sửa QC, bao gồm phần Drive đồng bộ đang có |
| mysql.SELECT/INSERT/UPDATE..., mysql.execute_error | Thời gian SQL trong request QC, chỉ ghi loại lệnh; lỗi không ghi câu SQL/giá trị |
| qc.mysql_commit | Thời gian commit phiếu QC |
| qc.finish_drive_after_commit | Phần endpoint vẫn chờ sau khi đã commit MySQL |
| drive.prepare_bundle, drive.bundle_result | Tổng chuẩn bị folder/PDF và kết quả pending; lỗi bị xử lý nội bộ vẫn có result ok=false |
| pdf.render_reportlab, pdf.output | Render PDF nội bộ và số byte đầu ra; gồm chữ ký vector sẵn có |
| drive.upload_pdf, drive.upload_http, drive.upload_transport | Upload PDF/request binary. Transport ghi method và số byte gửi, không ghi URL |
| drive.start_upload, drive.upload_chunk | Mở phiên và xử lý từng chunk/probe |
| drive.upload_chunk_info, drive.upload_response | Số byte chunk/tổng, offset/probe và HTTP status Google |
| drive.process_legacy_evidence | Xử lý liên kết bằng chứng lịch sử |

Browser Console có `QC_PERF_UI` cho duyệt folder, bundle và upload: operation, ms đến khi đọc JSON, HTTP status và trace. Không ghi tên file/URL. Nếu fetch lỗi mạng trước khi có response, xem Network của browser và trace backend đã ghi nếu request tới máy chủ.

**Không cộng các thời gian lồng nhau:** drive.verify_scope đã chứa các folder_metadata; google.json nằm trong các bước Drive; qc.request chứa cả DB và Google. Đếm số lần gọi và so sánh phần tổng/chi tiết để tìm bước chiếm thời gian.

## Cách lấy số liệu thao tác thực tế

Sau khi backend mới chạy, tải lại trang bằng Cmd + Shift + R:

1. Mở Drive, vào thư mục cha, vào một thư mục con rồi quay lại cha. Ghi lại thứ tự thao tác và khoảng thời gian thực hiện để đối chiếu trace.
2. Với phiếu dùng **biểu mẫu ERP đã ký** và bằng chứng hiện hữu, thực hiện thao tác bình thường. Không tạo phiếu giả hoặc gán chữ ký giả để đo. Nhánh QC_NVL_V1 mapping chưa có PDF/Drive.
3. Khi có nhu cầu thực tế, upload một ảnh, nhiều ảnh, video; ghi kích thước và số lượng file. Các số byte/chunk trong log giúp kiểm tra phần scope so với truyền dữ liệu.
4. Nếu thất bại, retry trên cùng phiếu. Đối chiếu log để xem PDF có bị xuất lại và các file đã thành công có được bỏ qua không.
5. Đọc log theo lệnh sau; không chia sẻ file chứa dữ liệu OAuth hoặc .env:

```sh
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env logs --since 30m backend
```

Chỉ thực hiện thao tác kiểm thử ghi/upload riêng khi đã được người dùng đồng ý; hướng dẫn trên không thay thế xác nhận. Dữ liệu benchmark trước/sau phải cùng tài khoản, folder, file, kích thước/chunk và điều kiện mạng; ghi rõ cold/warm token/cache.

## Bảng số đo

| Thao tác | Trước tối ưu | Sau tối ưu | Trạng thái |
| --- | --- | --- | --- |
| Mở thư mục cha | Chưa thu log | Chưa tối ưu | Đã có instrumentation |
| Mở thư mục con | Chưa thu log | Chưa tối ưu | Đã có instrumentation |
| Quay lại thư mục | Chưa thu log | Chưa có cache | Đã có instrumentation |
| Render PDF biểu mẫu ERP đã ký | Chưa thu log | Chưa tối ưu | Đã có instrumentation |
| PDF từ Sheets QC_NVL_V1 | Không có luồng này | Không áp dụng | Chưa triển khai trong Bước 2 |
| Upload 1 ảnh / nhiều ảnh / video | Chưa thu log | Chưa tối ưu | Đã có instrumentation byte/chunk/request |
| Tổng hoàn thiện hồ sơ | Chưa thu log | Chưa tối ưu | Chờ thao tác thực tế |

Chưa có số liệu ms thực tế thì không thay bằng số ước lượng hoặc kết luận đã tăng tốc. Sau lượt thao tác của người dùng sẽ cập nhật bảng và ưu tiên tối ưu theo trace có độ trễ lớn nhất. Các phương án cache, giảm lặp scope, giữ kết nối HTTP, upload file nhỏ và tách xử lý Drive sẽ được quyết định từ số đo; mọi thao tác ghi vẫn phải xác minh phạm vi QC_ROOT_FOLDER_ID.

## File thay đổi

- [performance.py](backend/app/core/performance.py), [http.py](backend/app/core/http.py), [database.py](backend/app/core/database.py): trace, thời gian request/SQL, header đối chiếu.
- [oauth.py](backend/app/integrations/google/oauth.py): thời gian lấy/refresh token và Google JSON, không thay scope/credential.
- [drive_bundle.py](backend/app/modules/qc/drive_bundle.py), [evidence.py](backend/app/modules/qc/evidence.py), [pdf.py](backend/app/modules/qc/pdf.py), [service.py](backend/app/modules/qc/service.py): đo các công đoạn thực tế.
- [forms.js](frontend/qc/forms.js): thời gian browser gọi các API folder/PDF/upload.
- [index.html](frontend/qc/index.html), [qc.js](frontend/qc/qc.js): bỏ duy nhất cột Tiêu chuẩn khỏi danh sách; dữ liệu tiêu chuẩn của hồ sơ/form không bị xóa.

Không thay API contract nghiệp vụ, schema, trạng thái chứng từ, layout PDF, folder ID hoặc cơ chế retry trong bản này.

## Trạng thái bàn giao

Đã rà soát diff và chẩn đoán editor; không ghi nhận lỗi tại các file instrumentation đã kiểm tra. Build image backend thành công, tạo lại riêng backend local và xác nhận container Up; MySQL vẫn healthy. Chưa chạy test/benchmark hoặc upload dữ liệu thử. Backend mới sẵn sàng ghi log các thao tác QC tiếp theo của người dùng.
