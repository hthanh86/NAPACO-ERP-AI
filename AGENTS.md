
# AGENTS.md — NAPACO ERP

## 1. Mục tiêu và nguyên tắc chung

Dự án NAPACO ERP là hệ thống quản lý doanh nghiệp sử dụng MySQL làm cơ sở dữ liệu cho các module đã chuyển đổi.

Mục tiêu khi thực hiện công việc:
- Chính xác về nghiệp vụ.
- An toàn dữ liệu và bảo mật.
- Ổn định, dễ bảo trì.
- Tối ưu hiệu năng.
- Tiết kiệm token và hạn mức Codex.

Nguyên tắc:
- Chỉ thực hiện đúng yêu cầu được giao.
- Không tự ý mở rộng phạm vi công việc.
- Không refactor các chức năng không liên quan.
- Không thay đổi logic nghiệp vụ đang hoạt động ổn định.
- Chỉ cài đặt dependency mới khi thấy thực sự cần thiết để thực hiện một tính năng mới
- Không tự ý triển khai lên môi trường production.

## 2. Kiểm soát đọc source code và token

Đây là quy tắc bắt buộc đối với tất cả các tác vụ.

### 2.1. Tìm kiếm trước khi đọc

- Không tự động đọc toàn bộ repository.
- Không quét tất cả các file chỉ để tìm một lỗi nhỏ.
- Trước tiên tìm theo tên hàm, API, component, bảng database hoặc từ khóa nghiệp vụ.
- Ưu tiên tìm tên file và vị trí xuất hiện của từ khóa.
- Chỉ đọc những đoạn code cần thiết.
- Chỉ mở thêm file khi có phụ thuộc thực tế.
- Không đọc lại file chưa thay đổi nếu ngữ cảnh hiện tại đã đủ.

### 2.2. Giới hạn phạm vi

- Bắt đầu từ module trực tiếp liên quan.
- Xác định luồng gọi hàm và dependency cần thiết.
- Không tự động mở rộng sang module khác.
- Không thực hiện audit toàn hệ thống trừ khi được yêu cầu.
- Nếu cần mở rộng phạm vi đáng kể, giải thích lý do trước khi tiếp tục.

### 2.3. Các thao tác cần tránh

- Không đọc toàn bộ file lớn nếu chỉ cần một hàm.
- Không in toàn bộ source code trong câu trả lời.
- Không chạy tìm kiếm trùng lặp không cần thiết.
- Không đọc thư mục build, cache, logs hoặc dependency đã cài đặt nếu không liên quan.
- Không lặp lại những kiểm tra đã thành công khi code chưa thay đổi.

Không đánh đổi độ chính xác hoặc an toàn chỉ để giảm token.

## 3. Kiến trúc hệ thống

- MySQL là nguồn dữ liệu chính của các module đã chuyển đổi.
- Không mặc định Google Sheets là database của hệ thống hiện tại.
- Không áp dụng lại logic SpreadsheetApp, google.script.run hoặc LockService của kiến trúc cũ nếu không được yêu cầu.
- Xác định framework, ORM, cấu trúc backend và frontend theo source code thực tế.
- Tôn trọng ranh giới giữa frontend, backend và database.
- Không thực hiện truy vấn database trực tiếp từ frontend.
- Không tự ý thay đổi API contract.
- Không tạo logic nghiệp vụ trùng lặp giữa các module.
- Ưu tiên sử dụng service, repository và tiện ích dùng chung đã có.

Nếu module dùng NestJS, TypeORM hoặc Next.js, tuân thủ cấu trúc và quy ước hiện có của module đó.

## 4. Quy tắc làm việc với MySQL

### 4.1. Truy vấn dữ liệu

- Chỉ truy vấn database khi chức năng thực sự cần.
- Không tự động lấy toàn bộ dữ liệu khi mở giao diện nếu nghiệp vụ chỉ yêu cầu truy vấn sau khi lọc.
- Với màn hình sử dụng bộ lọc, chỉ thực hiện truy vấn khi người dùng xác nhận hoặc khi điều kiện kích hoạt truy vấn đã được xác định.
- Không thực hiện lại truy vấn nếu tham số và dữ liệu liên quan không thay đổi, trừ khi cần đảm bảo dữ liệu mới nhất.
- Ưu tiên SELECT đúng các cột cần sử dụng.
- Sử dụng WHERE với điều kiện phù hợp.
- Sử dụng LIMIT và pagination cho danh sách lớn.
- Không SELECT * trên bảng lớn nếu không có lý do.
- Tránh truy vấn lặp trong vòng lặp.
- Kiểm tra và xử lý vấn đề N+1 queries.
- Ưu tiên JOIN hợp lý thay vì nhiều truy vấn riêng lẻ không cần thiết.
- Chỉ thêm index khi có cơ sở từ điều kiện truy vấn và dữ liệu thực tế.
- Không tự ý thêm cache nếu chưa đánh giá vấn đề dữ liệu cũ và cơ chế invalidation.

### 4.2. Ghi dữ liệu

- Chỉ cập nhật những bản ghi và trường dữ liệu cần thiết.
- Không ghi lại toàn bộ bản ghi nếu chỉ thay đổi một số trường.
- Sử dụng transaction khi một nghiệp vụ thay đổi nhiều bảng và cần tính nguyên tử.
- Xử lý rollback khi transaction thất bại.
- Không tự ý dùng DELETE hoặc UPDATE thiếu điều kiện WHERE.
- Kiểm tra dữ liệu đầu vào tại backend.
- Không tin tưởng dữ liệu hoặc quyền do frontend gửi lên.
- Không tự ý thay đổi khóa chính, khóa ngoại hoặc quan hệ dữ liệu.
- Bảo vệ dữ liệu trước các thao tác ghi đồng thời.

### 4.3. Hiệu năng và bảo mật

- Sử dụng parameterized queries hoặc phương thức an toàn của ORM.
- Không nối trực tiếp dữ liệu người dùng vào SQL.
- Tránh truy vấn dư thừa và truyền dữ liệu không cần thiết qua API.
- Không tạo kết nối database mới cho mỗi bản ghi.
- Sử dụng cơ chế quản lý connection hiện có.
- Không ghi mật khẩu, token hoặc thông tin nhạy cảm vào log.
- Không đọc hoặc in toàn bộ file .env nếu không thực sự cần.
- Không thay đổi cấu hình production khi chưa được yêu cầu.

## 5. Database schema và nghiệp vụ ERP

- Database schema hiện tại là nguồn tham chiếu chính.
- Xác minh tên bảng, tên cột và quan hệ từ schema hoặc entity thực tế trước khi sửa.
- Không tự ý đổi tên bảng hoặc cột.
- Không tự ý thêm, xóa hoặc thay đổi kiểu dữ liệu.
- Không tự ý thay đổi ràng buộc UNIQUE, FOREIGN KEY hoặc NOT NULL.
- Không tự ý thay đổi quy tắc tạo ID hoặc mã chứng từ.
- Không giả định tên bảng MySQL giống tên sheet cũ.
- Không sử dụng số thứ tự cột cố định để xác định dữ liệu.
- Không tự ý thay đổi logic phân quyền.
- Không bỏ qua kiểm tra quyền ở backend.
- Không tự ý thay đổi trạng thái nghiệp vụ của chứng từ.

Các quy tắc nghiệp vụ quan trọng cần bảo toàn:
- Quan hệ giữa đơn hàng, chi tiết đơn hàng, đơn đặt nguyên liệu và nhập kho.
- Quy tắc sinh mã PO_NVL, DN, N_NVL và các mã nghiệp vụ khác.
- Quy trình kiểm tra và nhận nguyên vật liệu.
- Phân quyền người dùng theo thiết kế hiện tại.
- Các điều kiện xác nhận, hoàn thành và cập nhật trạng thái chứng từ.

Phải xác minh các quy tắc trên từ code và schema hiện hành, không áp đặt cấu trúc Google Sheets cũ.

## 6. Quy tắc sửa code

- Chỉ sửa những file và hàm liên quan.
- Ưu tiên thay đổi nhỏ, có mục tiêu.
- Giữ nguyên coding convention của dự án.
- Tái sử dụng các hàm và service đã có.
- Không tạo thêm hàm trùng chức năng.
- Không thay đổi API response nếu không cần thiết.
- Không tự ý thay đổi giao diện ngoài phạm vi yêu cầu.
- Không kết hợp sửa lỗi với refactor quy mô lớn.
- Không thực hiện migration database nếu chưa được yêu cầu hoặc phê duyệt.

Nếu cần thay đổi nhiều file, phải xác định rõ quan hệ phụ thuộc và tác động trước khi sửa.

## 7. Kiểm tra sau khi sửa

- Kiểm tra diff của các file đã thay đổi.
- Kiểm tra các dependency trực tiếp có liên quan.
- Ưu tiên test chức năng vừa sửa.
- Kiểm tra các trường hợp lỗi và dữ liệu đầu vào quan trọng.
- Với thay đổi ghi database, kiểm tra tính toàn vẹn dữ liệu và transaction.
- Không chạy toàn bộ test suite khi chỉ cần targeted tests, trừ khi rủi ro yêu cầu.
- Không tự động chạy audit toàn repository.
- Không chạy thao tác ghi/xóa dữ liệu production để thử nghiệm.
- Không tự ý deploy sau khi sửa.
- Không tuyên bố test thành công nếu thực tế chưa chạy.

## 8. Cách thực hiện nhiệm vụ

Đối với mỗi yêu cầu:

Bước 1: Xác định chức năng cần xử lý.

Bước 2: Tìm những file, hàm, API hoặc bảng liên quan.

Bước 3: Đọc các đoạn code cần thiết.

Bước 4: Phân tích nguyên nhân hoặc yêu cầu thay đổi.

Bước 5: Thực hiện sửa đổi tối thiểu, đúng phạm vi.

Bước 6: Kiểm tra diff và và trước khi test liên quan hãy hỏi lại xem có cần test không. Nếu bị từ chối thì thực hiện bước tiếp theo và sau cuối build lên cho người dùng tự test

Bước 7: Báo cáo kết quả ngắn gọn.

Không cần hỏi xác nhận cho các thao tác đọc và sửa thông thường nằm trong phạm vi được giao.

Chỉ yêu cầu xác nhận khi cần:
- Thay đổi database schema hoặc migration có rủi ro.
- Xóa dữ liệu.
- Thay đổi phân quyền hoặc bảo mật.
- Thao tác với môi trường production.
- Mở rộng đáng kể phạm vi công việc.
- Thay đổi logic nghiệp vụ chưa được người dùng chấp thuận.

## 9. Quy tắc báo cáo

Sau mỗi nhiệm vụ, báo cáo bằng tiếng Việt:

1. Nguyên nhân hoặc vấn đề đã xác định.
2. File và hàm đã sửa.
3. Thay đổi chính.
4. Kết quả kiểm tra thực tế.
5. Rủi ro hoặc nội dung chưa hoàn thành.

Báo cáo ngắn gọn, rõ ràng.
Không in lại toàn bộ source code nếu không được yêu cầu.

## 10. Thứ tự ưu tiên

1. An toàn dữ liệu và bảo mật.
2. Chính xác về nghiệp vụ.
3. Ổn định và khả năng bảo trì.
4. Hiệu năng ứng dụng và MySQL.
5. Tiết kiệm token và hạn mức Codex.

Khi các mục tiêu mâu thuẫn, tuân thủ thứ tự ưu tiên trên.
