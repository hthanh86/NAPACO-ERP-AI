# QC – Một Google Sheets Template và xử lý hồ sơ nền

## Phạm vi và môi trường

Môi trường đã xác minh: Docker Compose trên **một host** theo xác nhận của người dùng; MySQL 8.4.13, schema ban đầu 008; chưa có queue hoặc staging. Hai GoogleCredential hiện có đều có encrypted refresh token (chỉ kiểm tra thống kê, không in token).

Bổ sung một service `qc-worker` dùng cùng image backend và volume `napaco-local_qc_staging`, mount vào `/var/lib/napaco/qc-staging`. Không thêm Redis, broker hay object storage. Không triển khai production. Không tạo QC_FILES; không sửa các cột QC/Template hiện có.

## Quy tắc template

- QC mới bắt buộc một Google Sheets Template ACTIVE, đã phê duyệt, source_matches hợp lệ. Backend chặn form ERP cũ cho phiếu mới.
- QC NVL dùng template chung, không giới hạn sản phẩm. Hai template chung cùng hiệu lực gây lỗi cấu hình; không chọn bản mới nhất một cách âm thầm.
- QC sản phẩm: template riêng sản phẩm ưu tiên hơn template chung; trong mỗi mức, scope OBJECT_TYPE cụ thể ưu tiên scope công đoạn chung. Hai template ngang mức bị chặn.
- Nếu một đối tượng liên quan nhiều sản phẩm và các sản phẩm phân giải ra những template khác nhau, từ chối tạo phiếu thay vì chọn tùy ý.
- Frontend tự xác định template duy nhất sau khi chọn đối tượng. Phiếu cũ vẫn mở từ FORM_DATA snapshot của chính phiên bản đã lưu; không ép đổi sang template hiện hành.

## Tiếp nhận và worker

1. Chọn file: browser truyền binary từng khối tối đa 4 MiB vào staging, có phần trăm tiến độ và retry tiếp nhận. Chưa ghi Drive.
2. Backend ghi bytes, flush/fsync trước khi commit offset; tính SHA-256 khi nhận đủ file. Tên file thiết bị chỉ là metadata, đường dẫn staging dùng UUID.
3. Nhấn Lưu: backend kiểm tra kết quả, chữ ký Google, duy nhất template và manifest staging. QC, kết quả, chữ ký và job PENDING được commit cùng giao dịch MySQL.
4. Sau phản hồi tiếp nhận thành công, giao diện chuyển sang Danh sách QC ngay, không gọi export/upload Drive trong request lưu.
5. Worker độc lập xử lý thư mục, bản sao template, mapping, PDF và bằng chứng; giữ nguyên kiểm tra QC_ROOT_FOLDER_ID trước khi ghi Drive.
6. Worker kiểm tra lại PDF (MIME, size, parent) và từng bằng chứng (key, size, không trùng) trên Drive trước khi COMPLETED. Chỉ sau đó xóa bytes staging.
7. Người dùng có thể đóng tab **sau khi nhận QC_ID**. File đang staging hoặc phiếu chưa lưu vẫn cần hoàn tất thao tác tiếp nhận trước.

Không bỏ qua xác minh quyền Drive: chuyển xác minh scope/khả năng ghi từ request tiếp nhận sang worker, trước thao tác ghi đầu tiên. Folder không hợp lệ sẽ làm job FAILED, dữ liệu QC đã tiếp nhận vẫn giữ nguyên.

## Queue và chống trùng

Migration [009_qc_jobs.py](backend/alembic/versions/009_qc_jobs.py) bổ sung QC_JOBS với ID, QC_ID nullable/unique, chủ job, status, step, attempts, error, timestamps, available_at, lease, fencing token, manifest, metrics, revision và Google subject. QC_ID nullable phục vụ tiếp nhận staging trước khi có phiếu; STAGING/ATTACHED/EXPIRED chỉ là trạng thái kỹ thuật, không hiển thị như trạng thái hồ sơ QC.

- Claim bằng SELECT ... FOR UPDATE SKIP LOCKED; MySQL lease 180 giây, heartbeat 20 giây. Mỗi job có fencing token; worker cũ không ghi đè trạng thái của worker đã nhận lại lease.
- Thêm MySQL advisory lock theo QC_ID để tránh hai tiến trình cùng chạy luồng Drive cho một phiếu.
- Tối đa 3 lần thử tự động; lỗi tạm thời chờ 10/20 giây giữa các lần thử. Lỗi quyền/tài khoản hoặc dữ liệu cần người dùng xử lý; nút Thử lại đồng bộ đưa job về PENDING.
- Khi SIGTERM, dừng tại checkpoint an toàn; nếu bị kill, job được nhận lại sau lease. Không dựa vào tab hoặc request HTTP.
- Lưu DRIVE_FOLDER_ID/PDF ID trước thao tác tạo tương ứng. Mỗi file có ID Drive cấp trước và khóa metadata ổn định; lưu tham chiếu resumable đã mã hóa để probe/tiếp tục phần còn lại.
- Không lưu OAuth access/refresh token trong manifest hoặc frontend. Worker đọc credential mã hóa hiện có của OWNER_ID; kiểm tra Google subject đã tiếp nhận. Không tự chuyển sang tài khoản Google khác.
- Chặn sửa nội dung QC khi job PENDING/PROCESSING. Khi sửa sau hoàn tất, giữ nét ký của chính tài khoản Google đã ký; thao tác Lưu tái xác nhận nội dung mới, ghi nhận người/thời điểm/hash mới và dấu vết lần ký gốc. Không bắt vẽ lại chữ ký chỉ vì sửa trường dữ liệu. Chữ ký của tài khoản khác không được tự dùng lại. Lưu revision mới và đưa job về PENDING; PDF dùng lại ID, bằng chứng đã hoàn tất được giữ lại.
- Thao tác upload/bundle cũ từ tab không được chạy đồng thời cho hồ sơ đã thuộc queue. Hồ sơ lịch sử chưa có job vẫn mở được; bổ sung bằng chứng qua staging sẽ tạo job cho hồ sơ đó.

## Staging và dọn dẹp

- Volume Docker bền vững, dùng chung API/worker, UID 10001, thư mục quyền 0700; không public qua StaticFiles.
- Mặc định tối đa 5 GiB/file, hạn mức 20 GiB/tài khoản cho dữ liệu chưa dọn. Cấu hình bằng QC_MAX_FILE_BYTES, QC_STAGING_QUOTA_BYTES và QC_STAGING_PATH trong env_file/environment dùng chung của Compose (API và worker phải cùng cấu hình; đổi path phải đổi mount tương ứng).
- STAGING bỏ dở: hết hạn sau 24 giờ không cập nhật; orphan directory không có job cũng được dọn sau 24 giờ.
- FAILED: giữ bytes 7 ngày sau cập nhật cuối để retry. Sau khi hết hạn, cần chọn lại file chưa hoàn tất.
- PENDING/PROCESSING không bị dọn theo tuổi. COMPLETED: xóa bytes sau xác minh Drive; giữ manifest kỹ thuật phục vụ đối soát.
- Worker dọn theo lô mỗi 5 phút; không xóa PDF/bằng chứng đã upload thành công trên Drive.
- Volume tồn tại qua restart/recreate container. Không dùng `down -v` hoặc volume prune nếu còn dữ liệu cần giữ. Backup MySQL và volume staging khi vận hành/di chuyển host.

## Drive dialog và danh sách

Dialog có Back/Forward/Up/Refresh/Search, breadcrumb, Grid/List, single-click chọn, double-click/Enter mở, footer Hủy/Chọn thư mục. Search lọc thư mục đã tải ở cấp hiện tại, không tìm toàn Drive. Có tải thêm phân trang.

Cache chỉ trong phiên trang, theo ERP user/quyền/root/folder; TTL 5 phút, Refresh truy vấn lại. Đăng nhập Google chuyển trang nên cache được tạo lại. Phản hồi cũ không thay đổi thư mục mới. Backend luôn là nơi xác minh scope/quyền trước ghi.

Danh sách phân biệt kết quả QC với PENDING/PROCESSING/COMPLETED/FAILED, hiển thị step/lỗi, nút retry theo quyền và link Drive theo DRIVE_FOLDER_ID. Poll 5 giây chỉ khi trang hiện tại còn job chờ/xử lý; không poll khi tab ẩn.

## Chạy và giám sát

Từ thư mục dự án:

```sh
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env build backend
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env run --rm --no-deps backend alembic upgrade head
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env up -d backend qc-worker
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env ps
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env logs --tail 100 qc-worker
```

Healthcheck worker kiểm tra heartbeat; log có QC_WORKER_STARTED, QC_WORKER_ERROR, QC_WORKER_LOOP_ERROR và QC_PERF theo trace. Nếu worker dừng, job vẫn nằm trong MySQL. Không xóa job để retry; dùng nút trong ERP sau khi sửa nguyên nhân.

Worker không cần session browser còn sống. Google OAuth phải tiếp tục có refresh token hợp lệ và quyền trên vùng QC. Thu hồi quyền/hết hạn refresh token cần chủ job kết nối lại đúng tài khoản.

## Số đo trước chuyển đổi

Các số dưới đây là log thực tế đọc trước khi thay backend, không phải benchmark giả lập:

| Công đoạn | Thời gian |
| --- | ---: |
| Request tạo lô QC | 3.918 ms |
| Service tạo QC | 3.866 ms |
| Commit MySQL | 38 ms |
| Xác minh phạm vi Drive trong request tạo | 3.712 ms |
| Tổng chuẩn bị folder/PDF, một lần thành công | 32.733 ms |
| Ba lượt xác minh scope trong bundle | 3.604 + 3.465 + 4.240 ms |
| Copy template | 3.758 ms |
| Batch mapping | 940 ms |
| Đọc lại mapping | 469 ms |
| Export Google PDF | 1.291 ms |
| Ghép chữ ký | 51 ms |
| Upload PDF 90.832 bytes | 3.578 ms |

Trace tạo: `b99c633e00344f65b4062301aa9d517d`; trace bundle thành công: `0ed995726c634440b94dd31a5e005e2d`. Trước đây đếm được ít nhất 6 request trong trace tạo và 31 trong trace bundle qua các operation đã có; chưa bao phủ đầy đủ Sheets reads/redirect, nên không coi đó là số request tuyệt đối.

Log cũ hiện còn không đủ số đo riêng lưu chữ ký, tạo folder, upload từng bằng chứng hoặc tổng end-to-end của cùng hồ sơ. Không tự cộng các request khác nhau để công bố tổng hoàn thiện một hồ sơ. Nút thắt lớn nhìn thấy: xác minh scope lặp lại theo chuỗi thư mục; chưa tối ưu chuyên sâu trong đợt này.

Sau chuyển đổi, thêm google.http_request ở từng transport Google, drive.create_qc_folder, qc.signature.validate và giữ các span mapping/export/upload. QC_JOBS.METRICS lưu các run gần nhất, số request tích lũy, số lần chạy, các span theo file_index/bytes và thời gian từ tiếp nhận đến COMPLETED. Chưa có benchmark Google trước/sau cùng điều kiện khi chưa được phép ghi hồ sơ thử lên Drive công ty; không thay số đo thực tế bằng thời gian mock.

## Kiểm thử và giới hạn

- 31/31 test backend tập trung đạt; thêm 1/1 test OAuth refresh/thu hồi quyền đạt riêng (tổng 32 test): template ưu tiên/xung đột, staging binary nhiều khối, replay offset, quyền sở hữu, giao dịch tiếp nhận, chữ ký, mapping, PDF retry, resumable, hai kết nối MySQL SKIP LOCKED, Google subject khác, dọn staging, lease fencing. Test OAuth xác nhận refresh không cần session browser, không refresh thừa khi access token còn hạn và không đổi tài khoản khi refresh bị từ chối.
- Test phục hồi tiến trình thật: tiến trình đầu checkpoint rồi os._exit(23); tiến trình mới nhận lại lease đã hết hạn và chỉ upload 19 bytes cuối của file 4 MiB + 19 bytes qua transport giả lập. Không có tab/request tồn tại trong giai đoạn xử lý.
- Test JavaScript Drive dialog đạt: single-click giữ node để nhận double-click, Back/Forward dùng cache, Refresh truy vấn mới, phản hồi cũ bị bỏ.
- Runtime local: migration 009 được xác minh; backend khởi động thành công, worker healthy trước/sau restart, log có QC_WORKER_STARTED. API ghi marker vào volume, worker đọc đúng sau restart rồi xóa marker QA; thư mục staging UID 10001, mode 0700. Không còn hàng QC có prefix QA sau kiểm thử; queue trống tại lần kiểm tra. Cú pháp các script QC đang mount đã được kiểm tra bằng Node.
- Google được giả lập trong các test ghi. Test MySQL nghiệp vụ dùng transaction rollback; test concurrency/process tạo các hàng QA bằng UUID và dọn chính các hàng đó trong finally. Staging test nằm ở thư mục tạm riêng.
- Có cảnh báo datetime/dependency deprecation và pytest cache permission; không che test fail. Kết quả nêu trên là lần chạy cuối.
- Chưa test video cỡ GiB thực tế, hết hạn/thu hồi Google thật, upload Drive thật qua worker mới hoặc UI trực quan trong trình duyệt. Công cụ điều khiển tab hiện lỗi môi trường OpenSSL/sandbox; không coi test DOM giả lập là visual QA.
- Việc xác minh file trên Drive diễn ra trước COMPLETED; nếu ai đó xóa file sau đó, trạng thái không tự đổi khi chưa có lần đối soát tiếp theo.

## Source thay đổi

- [job_models.py](backend/app/modules/qc/job_models.py), [jobs.py](backend/app/modules/qc/jobs.py), [worker.py](backend/app/modules/qc/worker.py), [009_qc_jobs.py](backend/alembic/versions/009_qc_jobs.py): queue, staging và worker.
- [compose.yaml](compose.yaml), [Dockerfile](backend/Dockerfile), [model_registry.py](backend/app/core/model_registry.py), [main.py](backend/app/main.py): service, volume, đăng ký model/router.
- [template_runtime.py](backend/app/modules/qc/template_runtime.py), [templates.py](backend/app/modules/qc/templates.py), [schemas.py](backend/app/modules/qc/schemas.py), [service.py](backend/app/modules/qc/service.py), [api.py](backend/app/modules/qc/api.py): phân giải template, giao dịch job, trạng thái/list/retry.
- [drive_bundle.py](backend/app/modules/qc/drive_bundle.py), [sheets_pdf.py](backend/app/modules/qc/sheets_pdf.py), [signing.py](backend/app/modules/qc/signing.py), [oauth.py](backend/app/integrations/google/oauth.py), [sheets.py](backend/app/integrations/google/sheets.py): tái sử dụng pipeline và bổ sung checkpoint/log transport.
- [staging.js](frontend/qc/staging.js), [drive-picker.js](frontend/qc/drive-picker.js), [forms.js](frontend/qc/forms.js), [mapped-forms.js](frontend/qc/mapped-forms.js), [qc.js](frontend/qc/qc.js), [index.html](frontend/qc/index.html), [qc.css](frontend/qc/qc.css): giao diện và tiếp nhận nền.
- [test_qc_jobs.py](backend/tests/test_qc_jobs.py), [test_qc_mapping.py](backend/tests/test_qc_mapping.py), [test_qc_completion.py](backend/tests/test_qc_completion.py), [conftest.py](backend/tests/conftest.py), [drive-picker.cjs](frontend/qc/tests/drive-picker.cjs): kiểm thử.

Tham chiếu thiết kế: [MySQL locking reads/SKIP LOCKED](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html), [Docker volume lifecycle](https://docs.docker.com/engine/storage/volumes/).

## Sửa lỗi validate revision và điều chỉnh chữ ký – 13/11/2026

Nguyên nhân đã tái hiện trên MySQL 8.4 thực tế: binary JSON làm tròn một số tọa độ dấu phẩy động khi serialize. Ví dụ số ngẫu nhiên không liên quan dữ liệu người dùng `0.09274584338014791` được đọc lại thành `0.09274584338014792`. Kiểm tra 2.000 số ngẫu nhiên gặp 206 giá trị lệch một ULP. Vì job lấy hash từ đối tượng Python trước khi đọc lại JSON đã lưu, worker báo khác phiên bản dù nội dung không bị sửa.

- Enqueue nay flush và refresh FORM_DATA trong cùng giao dịch, sau đó lấy revision từ dữ liệu MySQL. Không đổi thuật toán hash chung của template/mapping và không bỏ kiểm tra toàn vẹn ở worker.
- Với job cũ FAILED ở bước validate đúng lỗi này, nút retry đối chiếu FORM_DATA/TEMPLATE_ID với snapshot idempotency tiếp nhận ban đầu trước khi sửa revision. Không khớp thì từ chối. Có audit QC_JOB_REVISION_REPAIR; không sửa nội dung QC.
- Dry-run phiếu QC_261113_04 xác nhận snapshot khớp và staging còn đủ; rollback đã được kiểm tra, không commit job và không gọi Drive trong lần chẩn đoán.
- Giao diện không xóa nét ký khi thay đổi số lượng, ghi chú hoặc tiêu chí. Khi Lưu/đưa vào lô, tự xác nhận nội dung mới bằng phiên Google hiện tại. Phiếu đã lưu chỉ cho dùng lại đúng nét ký, đúng ERP user và đúng Google subject; giữ thời điểm ký gốc, hash nội dung trước và ghi nhận thời điểm xác nhận mới. Người khác phải ký bằng chữ ký của mình.
- 38/38 test backend tập trung đạt, gồm regression số thập phân trên MySQL thật, repair snapshot hợp lệ, từ chối nội dung đã thay đổi thật, lưu/sửa với nét ký cũ, từ chối sai user/Google subject/nét ký. Hai nhóm test Node cho giữ chữ ký và Drive dialog đều đạt. Google ghi được mock; chưa kiểm thử upload thật qua Drive trong đợt sửa này.
- Không migration hoặc dependency mới.

Các file bổ sung sửa trong đợt này: [jobs.py](backend/app/modules/qc/jobs.py), [schemas.py](backend/app/modules/qc/schemas.py), [signing.py](backend/app/modules/qc/signing.py), [template_runtime.py](backend/app/modules/qc/template_runtime.py), [mapped-forms.js](frontend/qc/mapped-forms.js), [qc.js](frontend/qc/qc.js), [test_qc_jobs.py](backend/tests/test_qc_jobs.py), [test_qc_completion.py](backend/tests/test_qc_completion.py), [signature-retention.cjs](frontend/qc/tests/signature-retention.cjs).
