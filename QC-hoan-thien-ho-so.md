# Hoàn thiện hồ sơ QC — Bước 3–5

## Phạm vi và cấu trúc tái sử dụng

Đã đọc AGENTS.md và schema MySQL local thực tế: revision 008; qc_checks đã có FORM_DATA JSON, source JSON, DRIVE_FOLDER_ID, TEMPLATE_ID. QC_TEMPLATES đã có FIELD_MAPPING và bản chụp/phê duyệt. Không tạo migration, QC_FILES, DRIVE_PARENT_FOLDER_ID, DRIVE_FOLDER_URL hoặc cột binary. Không cập nhật đè dữ liệu cũ bằng thao tác SQL.

Tái sử dụng: session/Role × Permission, OAuth theo user, ma trận quyền QC_CREATE/QC_EDIT/QC_VIEW/QC_TEMPLATE_MANAGE, mapping và preview tab đầu, snapshot trên phiếu, sequence/idempotency/lô 10 phiếu, xác minh root, folder/PDF ID tạo trước, resumable binary 4 MiB, appProperties chống upload lại, ReportLab của luồng biểu mẫu cũ và QC_PERF hiện có.

## Ký xác nhận

- Dialog template có canvas chuột/trackpad/cảm ứng, xóa/ký lại, xem chữ ký và người/thời điểm ký khi mở lại.
- Backend xác minh current_user và quyền. Callback Google cấp cookie HttpOnly mã hóa ràng buộc với hash session, user và Google subject. Đăng nhập local/logout xóa bằng chứng phiên Google. Phiên Google đang mở trước cập nhật cần kết nối Google lại một lần; có credential lưu từ trước chưa đủ để ký.
- Khi áp dụng chữ ký, endpoint `/api/qc/signatures/confirm` cấp xác nhận mã hóa gắn với nội dung QC, nét ký, tài khoản Google, context NVL/PO, timestamp UTC và nonce. Khi lưu, backend kiểm tra lại phiên và hash. Thay nội dung hoặc phiên mà gửi lại xác nhận cũ bị từ chối.
- FORM_DATA lưu nét ký chuẩn hóa, signer, email/subject, signed_at, method, nonce, content_hash và context_hash. Cookie/confirmation token không lưu vào hồ sơ; session fingerprint không được sao chép vào signer trong MySQL. Audit ghi hash xác nhận trước/sau khi sửa, không ghi nét ký thô.
- Sửa phiếu dùng TEMPLATE_ID giữ nguyên đối tượng/loại QC/phiên bản. Thông số PO/NVL trong snapshot cũ được bảo toàn. Nhấn **Sửa nội dung và ký lại**; mọi thay đổi kết quả/kết luận/ghi chú hoặc thông tin phiếu hủy xác nhận trên frontend, backend vẫn kiểm tra token độc lập.
- Đây là xác nhận nội bộ, không phải chữ ký số chứng thư số.

## Vị trí chữ ký trên mapping

Trong Quản lý Template QC có ô đầu và ô cuối vùng ký; có thể nhấn chọn trực tiếp trên preview. Chọn vùng trống đủ chỗ cho nét ký và họ tên, không đè dữ liệu/tiêu chuẩn/đánh giá hoặc cắt ngang ô gộp.

Mẫu mới lưu mapping có thể kèm signature_cell/signature_end_cell. Mẫu đã phê duyệt nhưng thiếu vị trí ký có thao tác **Phê duyệt bổ sung vùng chữ ký** một lần, dùng QC_TEMPLATE_MANAGE, đọc/xác minh nguồn lại. Thao tác chỉ bổ sung vùng ký và thông tin phê duyệt, không thay các fields đã duyệt. Đổi vị trí đã duyệt cần phiên bản mới.

Phiếu Bước 2 chưa ký có thể nhận phần mở rộng này khi người có QC_EDIT chủ động ký/lưu lại, chỉ khi source hash và toàn bộ mapping fields vẫn giống bản lưu trên phiếu. Hồ sơ cũ không tự bị sửa khi xem. Nếu không khớp, backend không đoán vị trí ký.

## PDF theo Google Sheets

1. Đọc dữ liệu, chữ ký và template/mapping snapshot từ phiếu trong MySQL.
2. Kiểm tra nguồn Google còn khớp source_hash/tab đã lưu. Nếu template gốc thay đổi thì dừng; không âm thầm dùng nội dung mới cho phiếu cũ.
3. Tìm/tạo bản sao tạm trong folder QC_ID, có appProperties riêng. Lưu copy ID/key/revision vào source JSON để retry. Không ghi vào spreadsheet ID gốc; mọi endpoint batchUpdate chỉ dùng copy ID và có guard từ chối ID gốc.
4. Một spreadsheets.batchUpdate ghi tất cả ô ERP, tiêu chuẩn, kết quả và đánh giá. Dùng stringValue, không thực thi công thức lấy từ câu trả lời QC. Giá trị cố định/định dạng/logo/tiếng Việt/ô gộp của bản sao được giữ ngoài vùng mapping đã chọn.
5. Đọc lại các range vừa ghi bằng values.batchGet, đối chiếu giá trị; sai/thiếu thì chưa upload PDF.
6. Xuất riêng tab đầu theo toàn bộ vùng grid đã duyệt (kể cả vùng logo/hình nằm ngoài ô có chữ), A4 portrait, fit-to-page, margin 0.25 inch. Không có sleep hoặc retry chờ cố định.
7. Chữ ký riêng tư không dùng IMAGE với URL công khai. Sheets API hiện không có thao tác tạo ảnh chữ ký trực tiếp tương đương insertImage bằng OAuth. Vì vậy PDF giữ nguyên bản Google export và ghép nét ký vector cùng họ tên vào đúng vùng đã duyệt. Vùng này được định vị bằng màu tạm trong bản sao, đọc từ hình học thực tế của PDF, không dựa vào tọa độ ước lượng. Không tìm thấy, bị chia/trùng, quá nhỏ hoặc không xác minh được → báo lỗi, không lưu PDF sai vị trí.
8. Kiểm tra PDF header/kích thước/pages/nội dung, ghép bằng ReportLab+pypdf, giữ nội dung gốc của Google. Metadata có QC_ID, tên người ký, content hash và thời điểm xác nhận. Không có file chữ ký/public sharing phát sinh.
9. Upload với tên `QC_ID_Bien_Ban_Kiem_Tra.pdf` vào PDF ID đã giữ trước. Chỉ khi upload xong và pdf_revision được ghi MySQL mới dọn bản sao tạm bằng chuyển vào thùng rác; kiểm tra parent và appProperties để không dọn nhầm file/template.

Nếu nguồn Google không còn phiên bản cũ, ERP không thể khôi phục đầy đủ logo/hình/print layout từ grid JSON để giả lập bản gốc. Trường hợp này cần khôi phục file template đúng phiên bản, rồi retry. Không fallback sang PDF ReportLab khác layout cho phiếu template mới.

## Lưu và retry Drive

- Lưu QC/signature vào MySQL trước và trả QC_ID. Nhánh template trả trạng thái pending; frontend tiếp tục gọi `/bundle`, không giữ kết quả lưu MySQL chờ export trong cùng endpoint.
- Thư mục cha chỉ chọn trong trình duyệt Drive hiện có, có breadcrumb/root/cha/con. Backend vẫn xác minh nằm dưới QC_ROOT_FOLDER_ID khi tạo và upload. Không dùng Google Picker và không mở rộng OAuth scope.
- Nếu có DRIVE_FOLDER_ID, dùng lại. Nếu chưa có, tạo ID trước rồi lưu MySQL trước files.create, thư mục mang đúng QC_ID. Retry không đổi ID. PDF cũng dùng lại ID và revision.
- File từ thiết bị giữ binary, không Base64; resumable/chunk 4 MiB và probe/retry như cơ chế cũ. Không đổi kiến trúc hay thêm upload song song nhằm tối ưu trong bản này.
- source.qc_bundle lưu pending/step/error, folder parent nội bộ của tác vụ khi cần, PDF/copy IDs/revision và danh sách **hash yêu cầu upload**/hash đã hoàn tất. Đây là trạng thái tối thiểu để đếm file còn thiếu, không có tên/mime/binary hoặc danh mục file trong MySQL. Không tạo bảng file và không thêm cột parent URL vào qc_checks.
- Khi các file được chọn trước lúc lưu, backend ghi các hash dự kiến trong cùng transaction QC. Hoàn tất upload hoặc tìm thấy file đã có qua appProperties thì đánh dấu hash hoàn tất idempotent. PDF xong nhưng còn bằng chứng → vẫn chưa báo hồ sơ hoàn tất.
- Lỗi giữ nguyên QC đã lưu; UI hiện bước/error và có thử lại. File thành công không tải lại. Không có worker nền trong bản này: task/retry state bền vững trong MySQL, nhưng file bytes còn trong thiết bị. Nếu đóng tab khi chưa xong, mở phiếu và chọn lại các file còn thiếu, rồi **Lưu bằng chứng bổ sung / thử lại hồ sơ**. Không khẳng định server còn giữ bytes sau khi tab đóng.
- Chi tiết QC có chữ ký, trạng thái hồ sơ, mở PDF qua API có QC_VIEW và kiểm tra quyền Drive, mở folder từ DRIVE_FOLDER_ID trong tab mới. Bổ sung bằng chứng yêu cầu QC_EDIT hoặc chủ phiếu có QC_CREATE như writable_record hiện hữu.
- Phiếu lịch sử không có FORM_DATA vẫn có thể bổ sung file: dùng DRIVE_FOLDER_ID đã có, nhận lại link folder cũ nếu nó thuộc root, hoặc chọn parent trong root để tạo folder. Không tạo PDF giả cho phiếu lịch sử không có biểu mẫu; luồng PDF biểu mẫu ERP cũ vẫn dùng ReportLab như trước.

## Cấu hình và triển khai local

- Không migration, không đổi system_settings/QC_ROOT_FOLDER_ID, không production.
- Cần Google Drive API và Google Sheets API trong dự án OAuth hiện có. Dùng scope Drive đã có; tài khoản cần quyền đọc/copy template và quyền tạo/sửa file trong folder QC công ty.
- Cần đăng nhập Google lại sau bản cập nhật để nhận bằng chứng phiên ký HttpOnly. Không dùng đăng nhập local để giả làm phiên Google đã xác thực.
- Thêm duy nhất dependency cần thiết `pypdf==7.0.1`; ReportLab và font DejaVu đã có. Đã build thành công image backend và tạo lại riêng container backend local; container ở trạng thái Up, log xác nhận `Application startup complete`, không có lỗi khởi động trong phần log đã kiểm tra. Frontend mount trực tiếp. Đây là kiểm tra khởi động, chưa xác nhận nghiệp vụ.

Tham khảo API: [Google batchUpdate](https://developers.google.com/workspace/sheets/api/guides/batch), [mẫu Google export PDF qua HTTP](https://developers.google.com/apps-script/samples/automations/generate-pdfs), [pypdf visitor và PDF](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [pypdf trên PyPI](https://pypi.org/project/pypdf/).

## Logging và thời gian

Giữ QC_PERF và X-QC-Trace, bổ sung `sheets.copy_template`, `sheets.batch_mapping`, `sheets.verify_values`, `sheets.export_pdf`, `pdf.signature_overlay`, `sheets.cleanup_temp`, `drive.download_pdf`. Tạo folder, upload PDF/chunk, MySQL và OAuth vẫn có log hiện hữu. Không ghi token, nét ký thô, payload/file content vào log.

| Công đoạn | Thời gian thực tế |
| --- | --- |
| Tạo folder | Chưa chạy phép thử thực tế Bước 3–5 |
| Copy template | Chưa chạy phép thử thực tế |
| Batch mapping / đọc lại | Chưa chạy phép thử thực tế |
| Export PDF / ghép chữ ký | Chưa chạy phép thử thực tế |
| Upload PDF / ảnh / video | Chưa chạy phép thử thực tế |
| Tổng hoàn thiện | Chưa chạy phép thử thực tế |

Không dùng thời gian test giả lập thay cho độ trễ Google thật. Chỉ cập nhật số đo sau khi có phép thử được cho phép và log tương ứng.

## Kiểm tra và giới hạn bàn giao

Đã đọc schema, rà soát diff và chạy chẩn đoán editor ở các file mới; editor chưa báo lỗi. Đã chuẩn bị test tập trung cho proof phiên Google, nội dung bị đổi sau ký, lưu/xem/sửa chữ ký, hash upload idempotent, vùng ký chồng dữ liệu, PDF overlay và một batch write chỉ trên copy.

Đã gửi câu hỏi xác nhận kiểm thử theo AGENTS.md mục 8. Khi chưa có trả lời, chưa chạy pytest, tạo PDF mẫu, render kiểm tra hình ảnh hoặc ghi file thử lên Drive. Do đó vị trí chữ ký/layout PDF Google thật, ảnh/video lớn, lỗi mạng thực tế và thời gian end-to-end **chưa được xác minh**. Không gọi build thành công là kiểm thử thành công.

## Source tạo/sửa

- [signing.py](backend/app/modules/qc/signing.py): xác nhận ký, cookie/session binding, content/context hash.
- [oauth.py](backend/app/integrations/google/oauth.py), [auth/api.py](backend/app/auth/api.py): cấp/xóa proof phiên Google; không đổi cơ chế OAuth/token cũ.
- [sheets_pdf.py](backend/app/modules/qc/sheets_pdf.py), [pdf_signature.py](backend/app/modules/qc/pdf_signature.py): copy/batch/readback/export/ghép chữ ký/dọn copy có guard.
- [mapping.py](backend/app/modules/qc/mapping.py), [templates.py](backend/app/modules/qc/templates.py): vùng ký và phê duyệt bổ sung.
- [template_runtime.py](backend/app/modules/qc/template_runtime.py), [schemas.py](backend/app/modules/qc/schemas.py): kết quả/chữ ký/signer và chỉnh sửa đúng snapshot.
- [service.py](backend/app/modules/qc/service.py), [api.py](backend/app/modules/qc/api.py), [drive_bundle.py](backend/app/modules/qc/drive_bundle.py), [main.py](backend/app/main.py): lưu trạng thái, API QC, PDF/Drive và retry.
- [forms.js](frontend/qc/forms.js), [mapped-forms.js](frontend/qc/mapped-forms.js), [qc.js](frontend/qc/qc.js), [index.html](frontend/qc/index.html): canvas, xác nhận ký, bằng chứng, breadcrumb, xem lại/bổ sung.
- [template-mapping.js](frontend/qc/template-mapping.js), [templates.html](frontend/qc/templates.html): chọn/duyệt vùng ký.
- [requirements.txt](backend/requirements.txt): pypdf.
- [test_qc_completion.py](backend/tests/test_qc_completion.py), [test_qc_mapping.py](backend/tests/test_qc_mapping.py): kiểm thử đã chuẩn bị; kết quả thực thi ghi riêng sau khi được đồng ý.

## Cập nhật xử lý lỗi export ngày 13/11/2026

- Tái hiện trên PDF lấy từ bản sao hiện có của phiếu QC_261113_02: pypdf 7 phát sinh DeprecationError khi merge_page trên trang chưa gắn vào writer. Đã clone tài liệu vào PdfWriter trước khi ghép chữ ký; không hạ phiên bản dependency.
- Phát hiện qua test retry: job JSON dùng chung tham chiếu với giá trị ORM khiến pdf_revision/pending có thể không được ghi xuống MySQL. Đã tách bản sao dict trước các checkpoint PDF; test expire/reload xác nhận trạng thái bền vững và không upload lại PDF hoàn tất.
- File sửa: [pdf_signature.py](backend/app/modules/qc/pdf_signature.py), [drive_bundle.py](backend/app/modules/qc/drive_bundle.py), [forms.js](frontend/qc/forms.js), [test_qc_forms.py](backend/tests/test_qc_forms.py).
- Log QC_BUNDLE_ERROR bổ sung trace, loại exception và vị trí stack, không ghi exception text/token/nội dung chữ ký. UI nói rõ bằng chứng chưa upload khi PDF chưa hoàn tất.
- 20/20 test tập trung đạt (completion, mapping, PDF retry, resumable chunk), Google được mock, transaction MySQL rollback. Có cảnh báo deprecation từ dependency/datetime và quyền ghi pytest cache; không có test fail ở lần chạy cuối.
- PDF thật đã ghép và render kiểm tra local: 1 trang, 48.152 bytes trước ghép, 90.442 bytes sau ghép; tên người ký có trong text, chữ ký hiện tại vùng đã mapping, màu định vị đỏ không còn trong bản PDF sau ghép. Mapping vùng ký hiện tại rộng qua hai cột ký; chưa tự sửa mapping đã duyệt. Template hiện tại không mapping trường QC_ID nên không dùng kiểm tra text QC_ID làm điều kiện xác minh.
- Số đo log lần lỗi: copy template 4,444 giây; batch mapping 0,541 giây; đọc lại 0,476 giây; export Google 1,263 giây; ghép chữ ký lỗi sau 0,036 giây; tổng bundle 27,121 giây. Đây là số đo trước sửa, không phải kết quả tốc độ sau sửa. Chưa đo tổng upload thật sau sửa.
- Đã build và cập nhật backend local, không migration. Không tạo/sửa/xóa file thử trên Drive trong lần chẩn đoán; chỉ export đọc từ bản sao đã tồn tại. Giữ tab còn file và dùng Thử lại upload để tiếp tục hồ sơ hiện có.
