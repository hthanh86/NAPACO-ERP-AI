# Giai đoạn 1 — kế hoạch, phát LSX và phân công máy

## Cách sử dụng

1. Mở **Kế hoạch · Định hình**, chọn CTĐH, định mức, máy và phần giữ NVL. Có thể ghép nhiều CTĐH theo xác nhận ghép hiện có.
2. **Tính thử → Lưu kế hoạch** tạo LSX nội bộ, chưa phát hành và chưa dùng để cấp NVL/chạy mẫu/ghi sản xuất.
3. Mở LSX trên kế hoạch, chọn **Phát lệnh**. Hệ thống cấp mã `LSX_YYMMDD_NNN` theo ngày phát tại Việt Nam; lưu người, thời điểm, nội dung đã phát và phân công hiện hành.
4. Dùng **Phiếu đã phát** để in nội dung tại thời điểm phát. Phiếu giữ nguyên khi kế hoạch tiếp tục thay đổi.
5. Sau phát hành, thay máy/số lượng/thành phần ghép qua **Cập nhật kế hoạch → Tính thử → Lưu**. Giữ cùng ID và mã LSX, không bắt buộc kết thúc LSX để chuyển máy.
6. Nhật ký mới phải thuộc phân công hiện hành và sau thời điểm phân công. Chốt phần thực tế trước khi đổi phân công; nhật ký không được đi xuyên ranh giới chuyển máy/phiên bản cấu hình.
7. Màn hình **Lần chạy / nhật ký ca** có **Lịch sử phân công**, thao tác bắt đầu/kết thúc và phiếu phát hành. Thay nguồn của LSX đã phát hành cũng đi qua kế hoạch; luồng chuyển NVL đối ứng hiện có tiếp tục được bảo vệ bởi điều kiện LSX đích đã phát.

## API nền

Các API ghi dưới đây dùng quyền PRODUCTION_EDIT hiện có và `Idempotency-Key` như các API production trước đó.

| API | Nội dung |
| --- | --- |
| POST `/api/production/schedule/preview` và `/save` | Lưu kế hoạch/cập nhật cùng LSX; lưu snapshot và audit |
| POST `/api/production/runs/{id}/release` | Body `{version, note}`; chỉ phát từ kế hoạch đã lưu khớp phiên bản LSX |
| GET `/api/production/runs/{id}/release-sheet` | Phiếu HTML có thể in, từ snapshot phát hành bất biến |
| GET `/api/production/runs/{id}/assignments?page=1&size=25` | Lịch sử máy/công đoạn/CTĐH, khoảng hiệu lực, người cập nhật, kế hoạch nguồn và snapshot |
| GET `/api/production/machines/{machine_id}/work?stage=forming&page=1&size=25` | CTĐH được thực hiện trên máy; stage cũng nhận cutting/edge |
| POST `/api/production/runs/{id}/setups` | Body `{run_version, machine_id, stage, order_line_id?, tool_id?, note}`; tạo nguồn chạy mẫu cho QC đầu ca |
| GET `/api/production/materials/production-orders?order_line_id=...` | Bộ chọn cấp NVL chỉ lấy LSX đã phát và CTĐH còn lượng được thực hiện |

Danh sách theo máy không lọc giờ dự kiến và không ép thứ tự kế hoạch. Công đoạn sau chỉ xuất hiện khi có lượng tốt thực tế ở công đoạn trước chưa dùng hết. Khi ghi, backend kiểm tra lại phân công, phiên bản, khoảng thời gian và sản lượng nguồn.

## Dữ liệu cũ

- Không thay ID, mã cũ, ngày cũ, trạng thái vận hành, số lượng, cấp/trả hoặc nhật ký lịch sử.
- Migration đánh dấu 12 LSX đang có là `legacy`; không tự coi là đã phát hành, không gán số hay người phát, không tạo phân công lịch sử.
- LSX cũ chưa kết thúc: cần cập nhật/lưu kế hoạch và chủ động Phát lệnh cho phần tiếp tục. Ngày phát mới là ngày xác nhận, không hồi tố.
- LSX đã kết thúc giữ nguyên để đọc. Dữ liệu nhập cũ thiếu run_snapshot cần đối soát cấu hình trước; không tự chuyển sang mô hình mới.
- Nhật ký cũ đọc máy từ snapshot có chứng cứ; thiếu chứng cứ hiển thị chưa xác định, không lấy máy hiện tại để thay thế.
- Cho phép đọc lịch sử và xử lý trả/đối soát NVL cũ; chặn cấp mới/chạy mẫu mới/sản xuất mới khi chưa xác nhận phát hành.

## Vận hành local và kiểm tra

- Migration: 015, chỉ bổ sung schema; không tự backfill lịch sử.
- Backup: `backups/napaco-pre-phase1-release-20261115.sql.gz`, quyền 0600.
- Đã build image/recreate local; không deploy production.
- Đã rà soát diff và diagnostics editor. Bộ kiểm tra chuẩn bị tại [test_production_release.py](backend/tests/test_production_release.py), chưa chạy khi chưa được xác nhận.
