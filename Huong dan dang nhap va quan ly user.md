# Đăng nhập và quản lý người dùng Napaco local

## Đăng nhập

Mở http://127.0.0.1:8000/login. Ưu tiên **Đăng nhập bằng Google** để sử dụng Drive.

Tất cả trang nghiệp vụ, file giao diện trực tiếp, API và tài liệu API yêu cầu phiên hợp lệ. Trang đăng nhập, tài nguyên CSS/JS của trang đăng nhập và luồng xác thực Google được phép mở trước khi đăng nhập. Khi chưa đăng nhập hoặc phiên hết hạn, mở trang nghiệp vụ sẽ chuyển về login và nhớ trang cần quay lại. API trả 401.

Phiên có hiệu lực 8 giờ. Không cần đăng nhập lại khi chuyển trang trong phiên đó. Thanh menu hiển thị tên, email, trạng thái kết nối Drive và nút **Đăng xuất**. Đăng xuất thu hồi phiên hiện tại. Những tab khác sẽ được chuyển về login khi tải trang hoặc gọi API tiếp theo.

Google và tài khoản local dùng cùng cơ chế phiên, nhưng tài khoản local không tự có quyền Drive của nhân viên khác. Tài khoản local quản trị dùng thông tin trong `.local-admin.txt`; không chia sẻ cho nhân viên.

## User Google nào hợp lệ?

Một user cần đáp ứng đủ:

1. Đăng nhập Google thành công và Google xác minh email.
2. Email trùng đúng một nhân viên trong MySQL local. Email lưu dạng chữ thường.
3. Nhân viên có trạng thái hoạt động (`active = true`).
4. Vai trò thuộc danh sách quyền hiện có. Đăng nhập thành công không đồng nghĩa có quyền mọi nghiệp vụ.
5. Khi OAuth còn External / Testing: email phải có trong **Google Cloud → đúng dự án Napaco → Google Auth Platform → Audience → Test users**.
6. Để dùng Drive, người dùng đồng ý quyền Drive và chính tài khoản đó được quyền xem file/thư mục cần thao tác.

Test users trên Google và nhân viên trong ERP là hai danh sách độc lập. Thêm một nơi chưa đủ. ERP không tự tạo user mới khi có tài khoản Google lạ đăng nhập.

## Xem user và vai trò

Mở Terminal tại thư mục dự án, bảo đảm Docker và backend đang chạy:

```sh
python3 scripts/users.py list
python3 scripts/users.py roles
```

`list` hiển thị mã, tên, email, vai trò, trạng thái hoạt động và đã kết nối Google hay chưa; không hiển thị mật khẩu/token. `roles` hiển thị các vai trò và quyền được cấp. Dùng đúng tên vai trò từ kết quả, không tự đặt tên mới.

## Thêm user

Ví dụ sau dùng mã và email minh họa; thay bằng thông tin thực tế và chọn vai trò có trong kết quả `roles`:

```sh
python3 scripts/users.py add NV0099 --name 'Nguyễn Văn A' --email 'nhanvien@congty.com' --role KINH_DOANH
```

Sau đó thêm email này vào Test users nếu ứng dụng còn Testing. Nhân viên mở login và đăng nhập Google. Công cụ không tạo mật khẩu local cho nhân viên.

## Sửa user

```sh
python3 scripts/users.py update NV0099 --name 'Nguyễn Văn A' --email 'emailmoi@congty.com' --role KINH_DOANH
```

Cần truyền đủ tên, email, vai trò. Sửa user sẽ thu hồi toàn bộ phiên của user đó. Đổi email cũng xóa kết nối Google và mật khẩu local cũ để người mới không kế thừa thông tin xác thực; cần đăng nhập và cấp quyền Google lại. Cập nhật không tự mở khóa nhân viên đang bị khóa.

## Bớt user / khóa quyền truy cập

```sh
python3 scripts/users.py disable NV0099
```

Khóa nhân viên, thu hồi tất cả phiên và xóa token Google đã lưu trong ERP. Giữ hồ sơ để bảo toàn tham chiếu nhân viên trên đơn hàng và lịch sử. Không xóa cứng nhân viên đã có giao dịch. Có thể gỡ email khỏi Google Test users nữa, nhưng chỉ gỡ Test users không thay thế việc khóa user trong ERP.

Mở lại:

```sh
python3 scripts/users.py enable NV0099
```

Nhân viên cần đăng nhập Google và cấp quyền lại. Công cụ không sửa/khóa tài khoản quản trị `LOCAL_ADMIN`.

Các thao tác này chỉ sửa MySQL local, không sửa danh mục trong Google Sheets/Apps Script. Không chạy nhập lại toàn bộ dữ liệu để thêm hoặc sửa user.

## Kiểm tra nhanh

- Cửa sổ riêng tư → mở `/?view=create` hoặc `/?view=film-stock`: phải về login.
- Đăng nhập Google: quay về trang đã yêu cầu; menu hiển thị đúng email và Drive đã kết nối.
- Tìm một file Drive có quyền xem.
- Đăng xuất → dán lại link nghiệp vụ: phải về login.
- Khóa một nhân viên thử bằng công cụ → phiên đang dùng phải bị chặn ở lần gọi API/tải trang tiếp theo.

## Quản lý trực tiếp trên giao diện

Mở **Quản lý người dùng** trong menu tài khoản hoặc vào http://127.0.0.1:8000/users.

- Admin local mặc định được truy cập. Admin có thể bật **Quản lý người dùng** tại mục **Vai trò và quyền** để cấp quyền `USER_MANAGE` cho một vai trò hiện có. Thay đổi này áp dụng cho tất cả nhân viên có vai trò đó và thu hồi phiên của họ.
- Tìm kiếm theo mã, tên, email; lọc tài khoản hoạt động/đã khóa.
- **Thêm người dùng**, **Sửa / Phân quyền**: chọn vai trò hiện có. Tài khoản mới có thể đăng nhập Google; muốn đăng nhập ERP bằng mật khẩu thì dùng Reset mật khẩu.
- **Khóa / Mở khóa**: giữ hồ sơ giao dịch. Khóa sẽ thu hồi phiên và xóa kết nối Google.
- **Reset mật khẩu**: đặt mật khẩu ERP local từ 12 đến 128 ký tự, nhập lại để xác nhận, rồi gửi riêng cho nhân viên. Không đổi mật khẩu Google. Mật khẩu được băm, không trả về API hoặc ghi vào nhật ký.
- Sửa tài khoản hoặc reset mật khẩu thu hồi các phiên đăng nhập. Đổi email xóa mật khẩu local và kết nối Google trước đó.
- Không sửa, khóa hay reset tài khoản `LOCAL_ADMIN` hoặc chính tài khoản đang đăng nhập trên màn hình này. Chỉ admin local được cấp/thu hồi quyền quản lý user cho vai trò; người được ủy quyền có thể quản lý tài khoản và chọn vai trò hiện có.
- Các thay đổi được ghi vào nhật ký hệ thống. Không xóa cứng người dùng.

## Menu Dữ Liệu Master và ma trận quyền

**Dữ Liệu Master** nằm đầu menu trên các màn hình nghiệp vụ, bao gồm cả màn hình User và các danh mục mới:

- **User**: chỉ hiển thị và truy cập được với admin local hoặc vai trò có `USER_MANAGE`.
- **Khách Hàng**: `/master/customers`.
- **Sản Phẩm**: `/master/products`.
- **Nhà Cung Cấp**: `/master/suppliers`.

Danh mục chỉ truy vấn khi nhấn **Tìm kiếm**, có phân trang 25 bản ghi. Nhân viên đã đăng nhập có thể xem như các API danh mục hiện tại. Quyền thêm/sửa tương ứng là `CUSTOMER_MANAGE`, `PRODUCT_MANAGE`, `SUPPLIER_MANAGE`; mặc định chưa cấp cho nhân viên. Không có thao tác xóa dữ liệu. Mã danh mục sinh theo quy tắc đang dùng, không đổi mã khi sửa. Nhà cung cấp dùng các trường hiện có: mã, tên, loại; dải mã hiện tại là NCC01–NCC99. Sản phẩm không được chuyển khách hàng qua màn hình này để bảo toàn liên kết giao dịch.

Trong **User → Vai trò và quyền**, mỗi cột là một Role, mỗi dòng là một quyền. Admin local tích/bỏ tích rồi nhấn **Lưu ma trận quyền**. Nút **Hủy thay đổi** bỏ các ô chưa lưu. Người có `USER_MANAGE` được xem ma trận và quản lý tài khoản; chỉ admin local được sửa ma trận. Cột `LOCAL_ADMIN` luôn có toàn quyền và bị khóa chỉnh sửa. Chỉ các ô thay đổi được ghi trong một transaction, kèm nhật ký và thu hồi phiên của các vai trò bị ảnh hưởng. Nếu người khác sửa cùng ô trước đó, hệ thống yêu cầu tải lại.

Dữ liệu quyền lưu tại bảng `role_permissions(role, permission, allowed)` hiện có, không cần thêm cột hay migration. Phần xử lý nghiệp vụ hiện tại cũng đọc ma trận từ MySQL này.
