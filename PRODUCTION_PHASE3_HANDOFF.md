# Giai đoạn 3 — phiếu kiểm mẫu trước chạy hàng loạt

Trạng thái: đã viết source và rà soát diff. Toàn bộ test vẫn tạm hoãn theo yêu cầu kiểm tra tập trung sau; chưa chạy kiểm tra cú pháp, test tự động, trình duyệt hoặc Google/Drive thật. Chưa build/recreate dịch vụ cho giai đoạn 3, không deploy production.

## Nguồn dữ liệu đã đối chiếu

- Đã đọc AGENTS.md và kiểm tra schema MySQL local của `production_setups`, `qc_checks`, `QC_TEMPLATES`, `production_order_assignments`; database đang ở revision 015. Migration 016 của giai đoạn 2 vẫn chưa được áp dụng.
- Dùng chính `production_setups` làm đợt chạy mẫu, lưu metadata phiên bản trong `source.sample_episode_v1`; tiếp tục dùng ID LSX hiện có.
- Dùng chính `qc_checks` lưu phiếu và `FORM_DATA.production_sample_v1` lưu trạng thái, quyết định và hai bằng chứng ký. Không thêm bảng/cột hoặc migration giai đoạn 3; không tạo hệ template, bộ đếm QC hoặc sổ NVL riêng.
- Template tiếp tục đăng ký Google Sheets từ Drive, mapping và Lưu/phê duyệt tại màn hình quản lý template QC hiện có. Chọn template theo cùng quy tắc phạm vi và ưu tiên sản phẩm; các sản phẩm ghép phải có một template chung phù hợp. Giữ quy tắc mã QC hiện có, kể cả giới hạn 99 phiếu/ngày; phiếu nháp cũng dùng dãy mã này.

## Luồng sử dụng

1. Vào **Kiểm mẫu trước chạy**, tìm LSX đã phát, chọn phân công máy hiện hành. Định hình lấy các CTĐH đang thực hiện của LSX; Cắt/Ép biên cho chọn nhiều CTĐH cùng máy và nguồn nhật ký hút đã chốt.
2. Nhập thời điểm kết thúc dự kiến đợt chạy và lý do mở/chạy lại. Đây là giới hạn của đợt, không phải mã LSX mới hay thời gian bắt buộc xếp thứ tự kế hoạch. Backend kiểm tra máy/LSX, phân công, khoảng dừng và nguồn NVL đã ký nhận; công đoạn sau kiểm tra nguồn hàng đã chốt theo cơ chế mới.
3. Chọn loại QC đầu/giữa/cuối ca và template đã đăng ký từ Drive. Phiếu liên kết đối tượng `SETUP`; các template giữa/cuối ca có thể cấu hình đối tượng SETUP bằng hệ quản lý QC hiện có, các loại HUT/CAT/EB cũ vẫn giữ nguyên.
4. Nhập tiêu chí và lưu nháp. Cho lưu tiêu chí chưa hoàn tất; trước ký phải đủ dữ liệu áp dụng theo chính validator QC dùng chung.
5. Kỹ thuật và QC mở cùng phiếu, mỗi vai trò chủ động xác nhận nội dung và ký bằng phiên Google hiện tại. Thứ tự ký tùy người thực hiện; không tự gán chữ ký hoặc danh tính của vai trò còn lại. Phiếu đã có chữ ký không sửa nội dung; sai nội dung cần hủy khi chưa dùng và lập phiếu mới.
6. Đạt + quyết định Cho chạy hàng loạt, hoặc NG + quyết định Cho chạy lọc, chỉ mở chạy khi đủ cả hai xác nhận. NG vẫn là NG; có tiêu chí Không đạt không tự chặn quyết định Cho chạy lọc hợp lệ. NG cần ghi tình trạng/phương án; quyết định Dừng chạy luôn chặn.

Quyền dùng lại ma trận hiện có: lập phiếu `QC_CREATE`, sửa/hủy `QC_EDIT`, kỹ thuật ký và mở/đóng đợt `PRODUCTION_EDIT`, QC ký `QC_CREATE` hoặc `QC_EDIT`. Không tự sửa ma trận quyền; mỗi người cần được cấp quyền phù hợp theo cấu hình hiện hành.

## Điều kiện mở chạy và lịch sử

- API điều kiện trả `allowed`, lý do chặn, và `basis` gồm mã QC, version, ID đợt chạy, máy, công đoạn, kết quả, quyết định, thời điểm đủ xác nhận, giới hạn đợt và hash nội dung.
- Chặn tại backend khi bắt đầu chạy, ghi ca có sản lượng/chạy thuần/tiêu hao và ghi công đoạn sau. Không chỉ khóa nút trên giao diện. Nhật ký lưu `setup_id` cùng bản chụp phiếu căn cứ; giao diện nhật ký cho chọn đợt tương ứng khi ghi dữ liệu của khoảng đã thực hiện.
- Đổi phân công máy, cấu hình/thành phần/số lượng kế hoạch, hết khoảng đợt hoặc có dừng máy làm mất điều kiện tiếp tục dùng phiếu. Mở setup mới qua cả API cũ cũng đóng đợt liên quan trước đó; chạy lại cần đợt mới và phiếu mới. Không tự gia hạn một phiếu cho toàn LSX.
- Lưu dừng máy qua kế hoạch thu hẹp khoảng đợt và ghi audit. Tắt dừng sau đó không tự kéo dài lại hiệu lực phiếu cũ. Dừng thực tế phải được ghi nhận hoặc đóng đợt trên ERP để hệ thống biết cần chạy mẫu lại.
- Phiếu mới nhất của đợt kiểm soát quyền chạy, kể cả đang nhập/chưa đủ ký/hủy. Hủy phiếu mới nhất không khôi phục ngầm quyền từ phiếu cũ.
- Phiếu đã liên kết nhật ký không được hủy hoặc sửa ngược. Nhật ký đã có căn cứ không được chuyển sang phiếu khác khi sửa. Chưa xây dựng quy trình điều chỉnh dây chuyền nhật ký/phát hành lại căn cứ; backend từ chối để giữ dữ liệu đã thực hiện.
- Được ghi nhật ký cho khoảng đợt đã đóng nếu toàn bộ khoảng nằm trong hiệu lực và sau thời điểm đủ ký; đóng đợt không xóa lịch sử. Các ràng buộc nhật ký/phân công hiện có vẫn áp dụng.

## Xuất phiếu

- Dùng lại worker, thư mục Drive, bản sao tạm Google Sheets, mapping và xuất PDF QC hiện có; không sửa template Drive gốc.
- QC ký tại vùng mapping đã duyệt. Cùng file PDF có thêm trang xác nhận chứa LSX chính thức, CTĐH, máy, đợt chạy, kết luận/quyết định và hai chữ ký kỹ thuật/QC với người, thời điểm, hash/nonce. Không cần tạo hệ mapping chữ ký riêng cho kỹ thuật.
- Chỉ phiếu đủ hai xác nhận mới được đưa vào hàng đợi xuất PDF. Phiếu chưa đủ ký/đã hủy không được tải như phiếu dùng chạy. Kết quả chạy worker/Google thực tế chưa được kiểm tra.

## API chính

- `POST /api/production/runs/{run_id}/sample-episodes`: mở đợt thực tế, kiểm tra nguồn và phân công.
- `GET /api/production/sample-episodes`: tra cứu/pagination theo LSX, máy, công đoạn; chỉ tải khi người dùng thao tác.
- `GET /api/production/sample-episodes/{id}/template-options`: template QC phù hợp từ kho template hiện có.
- `POST /api/production/sample-episodes/{id}/close`: đóng đợt có version và lý do.
- `GET/POST /api/production/samples`, `GET/PUT /api/production/samples/{id}`: danh sách, lưu nháp và chi tiết.
- `POST /api/production/samples/{id}/confirm-signature`, `/sign`, `/cancel`: xác nhận nội dung, ký và hủy có kiểm soát.
- `GET /api/production/runs/{run_id}/sample-eligibility`: điều kiện mở chạy và phiếu căn cứ. API ghi nhật ký luôn kiểm tra lại trong transaction.

## Tương thích và kiểm tra còn lại

- Setup, QC và nhật ký cũ không có metadata/bằng chứng mới không tự được xem là đã kiểm mẫu hoặc được phép chạy. Không backfill chữ ký, không sửa kết quả QC hay nhật ký lịch sử.
- Xem lịch sử cũ vẫn dùng luồng hiện có. Ghi sản lượng mới hoặc sửa nhật ký có tác động căn cứ phải qua kiểm soát mới; không hồi tố phiếu vừa ký cho thời gian trước đó.
- [Bộ test giai đoạn 3](backend/tests/test_production_samples.py) đã được chuẩn bị bằng fixture MySQL rollback và giả lập danh tính/xuất nền; chưa chạy. Bao gồm pending NVL, nháp/thiếu ký, NG chạy lọc/dừng, chạy lại/hết hiệu lực, giả mạo phiên/vai trò/nét ký, phiếu đã dùng và hủy không khôi phục phiếu cũ.
- Đợt test tập trung còn cần kiểm tra transaction/ghi đồng thời, đổi máy/cập nhật kế hoạch/dừng, ghép CTĐH và nguồn Cắt/Ép biên, hồi quy QC_NVL và xuất PDF thật trên Drive.
- Trước khi chạy code mới cần áp dụng migration 016 giai đoạn 2 và cập nhật backend/worker local đồng bộ. Không đưa backend mới chạy trên schema 015. Không có migration mới riêng cho giai đoạn 3.

## File chính

- [Service nghiệp vụ](backend/app/modules/production/sample_service.py), [API](backend/app/modules/production/sample_api.py), [schema đầu vào](backend/app/modules/production/sample_schemas.py).
- [Màn hình kiểm mẫu](frontend/production/samples.html), [logic giao diện](frontend/production/samples.js).
- [Trang xác nhận PDF](backend/app/modules/qc/sample_pdf.py); các hook trực tiếp nằm trong release/run/schedule service, QC runtime/service/API và luồng xuất Sheets PDF hiện có.
