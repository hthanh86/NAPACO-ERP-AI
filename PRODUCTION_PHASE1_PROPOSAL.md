# Giai đoạn 1: kế hoạch → phát LSX → phân công máy

Trạng thái: người dùng đã duyệt schema, quy tắc mã và cách xử lý dữ liệu cũ; đã triển khai source và áp dụng migration 015 trên local. Test nghiệp vụ đang chờ xác nhận riêng theo AGENTS.md.

## Kết quả kiểm tra ngày 15/11/2026

- Đã đọc AGENTS.md, model, migration và các luồng save_run, schedule save, cấp NVL, QC, nhật ký và hiển thị thực tế liên quan.
- Đã đọc schema MySQL local qua kết nối của backend; Alembic hiện tại là 014.
- production_orders dùng khóa ID_Lenh_SX; chưa có cột mã chính thức, người phát và bản chụp phát hành. Ngay_Ra_Lenh hiện bị ghi khi lưu cấu hình, kể cả khi sửa.
- production_order_items có khóa ghép (run_id, order_line_id), không UNIQUE riêng order_line_id: giữ nguyên quan hệ nhiều–nhiều.
- production_schedule_plans đã lưu request/result/context bất biến, version và người lập. production_schedule_days trỏ bản đầu ngày/bản cập nhật. Tái sử dụng các bảng này.
- save_run hiện xóa/tạo lại items và bindings khi sửa, đặt lại sản lượng; chặn sửa khi đã chạy hoặc đã có cấp/trả. Không thể dùng nguyên cách này cho cập nhật LSX đã thực hiện.
- forming_logs có shift_snapshot nhưng chưa có trường máy thực tế riêng; schedule_actual và kiểm tra chồng máy đang dùng máy hiện tại của production_orders.
- before_issue và QC resolve_object chưa có điều kiện phát hành riêng.
- Truy vấn tối đa 20 LSX trả về 12 bản ghi, đều mang mã DEMO7; không dùng mã demo làm quy tắc nghiệp vụ. Trong phạm vi source đã kiểm tra, mã LSX do người dùng nhập. QC và đơn hàng đã có cơ chế sequences theo ngày.

## Quy tắc mã đề nghị xác nhận

Mã hiển thị: LSX_YYMMDD_NNN, ví dụ LSX_261115_001.

- Ngày lấy từ thời điểm Phát lệnh tại Asia/Ho_Chi_Minh, không lấy ngày kế hoạch/ngày chạy.
- Số thứ tự tăng trong ngày, tối thiểu ba chữ số; vượt 999 tiếp tục 1000, không quay vòng.
- Dùng bảng sequences hiện có, khóa hàng và transaction; thêm UNIQUE mã LSX để bảo vệ đồng thời. Retry không phát thêm mã.
- Mã không đổi khi cập nhật kế hoạch/chuyển máy. ID_Lenh_SX vẫn giữ nguyên; bản mới sinh ID nội bộ tự động và ẩn khỏi giao diện thông thường.
- Bản nháp hiển thị “Chưa phát hành” và thông tin nhóm/CTĐH. Phiếu chính thức chỉ dùng được sau phát hành.

## Migration 015 đề nghị xác nhận

Chỉ bổ sung vào mô hình hiện có, không thêm bảng đầu LSX thay thế.

| Bảng | Thay đổi đề nghị | Mục đích |
| --- | --- | --- |
| production_orders | official_code VARCHAR(100) NULL, UNIQUE | Mã chính thức, chỉ cấp lúc phát |
| production_orders | released_at DATETIME NULL; released_by VARCHAR(100) NULL, FK users.id | Thời điểm/người phát thực sự, tách khỏi Ngay_Ra_Lenh cũ |
| production_orders | release_snapshot JSON NULL | Nội dung đã phát bất biến: cấu hình, CTĐH, số lượng, nguồn, phân công và phiên bản kế hoạch |
| production_orders | release_state VARCHAR(20) NOT NULL DEFAULT 'legacy' | Phân biệt legacy/draft/released; bản mới được ứng dụng ghi draft rõ ràng |
| production_order_items | enabled BOOLEAN NOT NULL DEFAULT TRUE | Ngừng thực hiện thành phần ghép mà vẫn giữ số lượng đã làm và liên kết cũ |
| production_order_assignments (mới) | id, run_id FK, stage, machine_id FK, order_line_id NULL FK, started_at, ended_at NULL, plan_id FK, created_by FK, snapshot JSON | Lịch sử phân công; mỗi lần chuyển đóng phân công trước và thêm phân công mới |
| forming_logs | actual_machine_id VARCHAR(100) NULL; assignment_id NULL FK production_order_assignments.id | Máy thực tế/phân công của nhật ký mới, không phụ thuộc máy hiện tại của LSX |

Kiểu khóa ngoại theo đúng khóa bảng đích. Không thay PK/FK hiện hữu, không đổi UNIQUE của quan hệ LSX–CTĐH. Index phân công phục vụ tìm theo máy/công đoạn/phân công chưa đóng và lịch sử LSX; chốt index cụ thể trong migration theo truy vấn triển khai.

Migration chỉ thêm schema; không suy diễn mã, người phát, ngày phát, máy thực tế hay phân công lịch sử. Giá trị legacy chỉ đánh dấu nguồn cũ chưa xác nhận, không đồng nghĩa đã phát hành. Không ghi đè Ngay_Ra_Lenh hiện có.

## Luồng triển khai sau xác nhận

1. Lưu kế hoạch tạo/cập nhật LSX draft; chưa cấp mã chính thức. Backend chặn draft ở cấp/chuyển NVL vào LSX, chạy mẫu/setup/QC liên quan và ghi sản xuất, kể cả qua đường ghi tương thích cũ nếu có.
2. Phát lệnh từ bản kế hoạch đã lưu, kiểm tra version và quyền hiện có. Trong một transaction: khóa LSX, kiểm tra dữ liệu, cấp mã, ghi người/thời điểm/bản chụp và tạo phân công hiệu lực. Phát lại không đổi mã/nội dung đã phát.
3. Sau phát hành, thay đổi máy/số lượng/thành phần ghép chỉ qua tính thử/lưu cập nhật kế hoạch. Giữ release_snapshot ban đầu; bản kế hoạch mới lưu nội dung sau thay đổi, audit lưu người/lý do và tham chiếu bản trước/sau.
4. Không reset completed_qty, issued_kg, số dư nguồn, tổng nhật ký. Không giảm mục tiêu dưới phần đã làm; không xóa thành phần có truy vết. Thành phần bị rút khỏi phần còn lại chuyển enabled=false và vẫn xem được lịch sử. Không thay cấu hình của nhật ký đã chốt.
5. Giữ cùng LSX qua nhiều ngày và DH01 → DH02. Chỉ cho một phân công định hình hiệu lực của LSX; việc chuyển đóng máy cũ/mở máy mới là nguyên tử dưới khóa ERP và khóa LSX. Kiểm tra nhật ký chồng lấn theo máy thực tế đã ghi. Chặn nhật ký vượt ranh giới chuyển máy; cần chốt phần máy cũ trước chuyển.
6. Phân công định hình và cắt độc lập; cho phép song song khi có nguồn nhật ký/WIP hợp lệ và còn lượng. Không bỏ kiểm tra giới hạn tiêu thụ nguồn.
7. API danh sách theo máy/công đoạn trả mã LSX, CTĐH, phân công/version và lượng còn được thực hiện. Chỉ lấy released, phân công hiện hành đúng máy, thành phần còn hiệu lực/còn lượng; công đoạn sau kiểm tra nguồn còn hợp lệ. Có pagination; không lọc theo giờ dự kiến và không ép thứ tự kế hoạch. Backend kiểm tra lại khi ghi.
8. UI kế hoạch/LSX bổ sung trạng thái phát hành, nút Phát lệnh, mã chính thức, lịch sử cập nhật/phân công; ID nội bộ chỉ dùng trong request và liên kết kỹ thuật. Cập nhật bộ chọn cấp NVL/QC và phiếu trong phạm vi liên quan.

## Ảnh hưởng dữ liệu cũ cần duyệt

- Giữ nguyên 12 LSX hiện có, ID, trạng thái vận hành, kế hoạch, cấp/trả và nhật ký; không tự phát hành hay gán mã mới.
- Hiển thị dữ liệu cũ là “LSX cũ — chưa xác nhận phát hành”. Cho đọc lịch sử và xử lý nghĩa vụ trả/đối soát đã có; chặn cấp mới, chạy mẫu mới, bắt đầu/ghi sản xuất mới cho đến khi có xác nhận tiếp tục rõ ràng.
- Nếu tiếp tục LSX cũ, người có quyền phải chủ động phát hành cho phần tiếp tục từ kế hoạch hiện tại; ngày phát và snapshot là tại thời điểm xác nhận, không hồi tố. LSX đã kết thúc chỉ đọc, không tự mở lại.
- Nhật ký cũ có máy trong snapshot sẽ đọc từ snapshot đó. Nếu thiếu chứng cứ thì hiển thị chưa xác định máy thực tế; không gán máy hiện tại của LSX làm lịch sử.
- Không sửa số lượng/tồn hay tái tạo nhật ký cũ trong migration.

## Kiểm tra và triển khai

- Sau khi sửa: kiểm tra diff và dependency trực tiếp; hỏi người dùng trước khi chạy test theo AGENTS.md.
- Bộ kiểm tra dự kiến: draft bị chặn, phát lệnh đồng thời/retry, ghép nhiều–nhiều, cập nhật sau cấp NVL, chuyển máy giữ nhật ký cũ, một LSX không định hình hai máy, cắt song song có nguồn, danh sách máy và LSX legacy.
- Không chạy test, build/recreate hoặc áp dụng migration ở bước khảo sát này. Không deploy production.
- Git hệ thống hiện lỗi xcrun do thiếu CommandLineTools; đã dùng Git có sẵn trong Sourcetree để kiểm tra diff, không cài công cụ hệ thống.

## Kết quả triển khai local

- Đã bổ sung migration 015, release_service, luồng cập nhật LSX không xóa lịch sử, API phân công/danh sách máy/chạy mẫu/phiếu phát hành và giao diện liên quan.
- MySQL xác nhận revision 015; 12 LSX cũ đều là legacy, không có official_code/released_at và chưa có phân công suy diễn.
- Backup trước migration: backups/napaco-pre-phase1-release-20261115.sql.gz, quyền 0600, gzip báo dung lượng giải nén 4.668.452 byte.
- Đã build và recreate dịch vụ local. Không deploy production.
- Diff không có lỗi khoảng trắng; editor không báo lỗi trên các file chính đã kiểm tra. Đã viết test_production_release.py nhưng chưa chạy khi chưa có xác nhận test.
