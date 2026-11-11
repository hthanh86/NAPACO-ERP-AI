# MySQL local cho Napaco

MySQL 8.4.13 LTS chạy riêng bằng Docker Desktop tại `127.0.0.1:3307`, database `napaco_erp_local`. MySQL 8.0 cũ vẫn dùng cổng 3306.

Để sử dụng ứng dụng, mở `Mo ung dung.command`, vào http://127.0.0.1:8000 và đăng nhập bằng tài khoản trong `.local-admin.txt`.

Thông tin kết nối database nằm trong `.env`; cấu hình Docker nằm trong `.mysql.env`. Không chia sẻ các file này. Tài khoản đăng nhập website khác tài khoản MySQL.

Đọc `Huong dan chay va chuyen doi local.md` để biết đầy đủ cách dùng, sao lưu, nhập dữ liệu và xử lý lỗi.
