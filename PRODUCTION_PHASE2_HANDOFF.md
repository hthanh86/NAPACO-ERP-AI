# Giai đoạn 2 — bàn giao source

Trạng thái ngày 15/11/2026: đã viết code, chưa xác nhận hoạt động bằng test. Người dùng yêu cầu tạm hoãn toàn bộ test để kiểm tra tập trung sau.

## Thay đổi chính

- Lập phiếu nháp → ký cấp → ký nhận trên cùng phiếu; dùng cơ chế xác minh danh tính và bằng chứng chữ ký hiện có. Người nhận lấy từ tài khoản chủ động ký nhận.
- Nháp giữ cam kết trên phân bổ, chưa ghi sổ kho. Ký cấp ghi một CẤP NVL và trừ tồn đúng một lần; ký nhận chỉ bổ sung bằng chứng bàn giao, không trừ lần nữa.
- LSX phải đã phát và còn hiệu lực. Backend kiểm soát lô, lượng, phân bổ, quyền, phiên ký, version, idempotency và transaction.
- Nguồn sản xuất theo LSX/lô chỉ nhận phiếu đã ký nhận; pending được trình bày riêng. Nhật ký dùng thời điểm nhận, lưu liên kết movement để tránh cộng lại giữa các ca.
- Chuyển NVL tái sử dụng giao dịch trả–cấp hiện có ở bước ký cấp; giữ điều kiện kho xác nhận trả.

## Điểm vào

- Giao diện `/production/handovers`, mở từ màn hình phân bổ NVL; có danh sách, ký và phiếu in chứa hai chữ ký.
- API `/api/production/materials/handovers`: lập, danh sách, chi tiết, hủy nháp, xác nhận chữ ký, ký và phiếu in.
- API `/api/production/materials/runs/{id}/balance`: nguồn đã nhận, chờ nhận, trả và lượng còn dùng được theo lô.
- Hai endpoint issue/transfer hiện có chuyển sang lập nháp để không bỏ qua bước ký.

## Dữ liệu cũ và schema

- [Migration 016](backend/alembic/versions/016_material_handovers.py) chỉ thêm bảng hồ sơ `material_handovers`; `film_movements` tiếp tục là sổ biến động duy nhất. Migration chưa được áp dụng.
- Không sửa các giao dịch cũ hoặc suy diễn chữ ký từ `receiver_id`. Các phiếu cũ được đọc là `legacy_unverified`; số dư lịch sử được trình bày riêng, không tự đưa vào nguồn đã nhận theo cơ chế mới.
- Các giao dịch trả cũ vẫn giữ tác động tồn và điều kiện kho xác nhận. Chưa có bước đối soát/chuyển tiếp số dư cũ; đây không phải phần tự động của migration.
- Chi tiết mô hình đã duyệt: [phương án giai đoạn 2](./PRODUCTION_PHASE2_PROPOSAL.md).

## Kiểm tra và môi trường

- Đã rà soát diff; chưa chạy test, kiểm tra cú pháp hoặc nghiệm thu trình duyệt giai đoạn 2. Bộ test đã được chuẩn bị, chưa có kết quả.
- Một build backend local và bản sao lưu local đã hoàn tất từ thao tác khởi động trước chỉ đạo tạm hoãn. Chưa recreate backend/worker, chưa chạy migration 016; source giai đoạn 2 chưa được đưa vào dịch vụ đang chạy.
- Không deploy production. Cần áp dụng schema và cập nhật dịch vụ local cùng nhau khi tiếp tục; không đưa backend mới chạy trên schema 015.
