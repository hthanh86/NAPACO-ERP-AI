# Kết nối Google và Drive cho bản Napaco local

Các màn hình nghiệp vụ local giữ nguyên HTML và thao tác của ứng dụng cũ. Tuy nhiên, quyền Google mà Apps Script đang có không tự chuyển sang backend chạy trên máy Mac. Cần tạo OAuth Client riêng để đăng nhập Google và tìm/tải file Drive đúng tài khoản người dùng.

## 1. Tạo dự án Google Cloud

1. Mở https://console.cloud.google.com/ bằng tài khoản công ty sẽ quản lý ứng dụng.
2. Chọn một dự án của công ty nếu có quyền quản trị phù hợp, hoặc chọn **New project** để tạo dự án `Napaco ERP Local`.
3. Chọn đúng dự án này ở thanh trên cùng.
4. Vào **APIs & Services → Library**, tìm **Google Drive API**, chọn **Enable**. Chưa cần bật Google Sheets API để chạy MySQL local.

## 2. Khai báo ứng dụng

1. Mở **Google Auth Platform**. Nếu chưa cấu hình, chọn **Get started**.
2. Trong **Branding**, đặt tên ứng dụng `Napaco ERP Local`, chọn email hỗ trợ và email liên hệ của anh.
3. Trong **Audience**:
   - Chọn **Internal** nếu dự án thuộc tổ chức Google Workspace và chỉ nhân viên tổ chức đó sử dụng.
   - Nếu không có lựa chọn Internal hoặc đang dùng Gmail cá nhân, chọn **External**, giữ chế độ **Testing**, thêm tài khoản Google anh sẽ dùng vào **Test users**.
4. Trong **Data Access**, thêm các phạm vi:

```text
openid
https://www.googleapis.com/auth/userinfo.email
https://www.googleapis.com/auth/userinfo.profile
https://www.googleapis.com/auth/drive
```

Phạm vi Drive đầy đủ cần để giữ cách tìm mọi file mà người dùng được xem và tạo file trong thư mục Drive hiện có như ứng dụng cũ. Đây là quyền rộng; backend chỉ triển khai thao tác đọc/tìm và tạo file phục vụ PO, không có chức năng xóa tùy ý dữ liệu Drive. Nếu muốn giảm phạm vi xuống những file được chọn riêng, cần đổi sang Google Picker và cách thao tác sẽ khác ứng dụng cũ.

Ứng dụng External ở chế độ Testing có thể yêu cầu kết nối lại sau khi refresh token hết hạn; đây là cấu hình phù hợp để test, chưa phải cấu hình triển khai chính thức.

## 3. Tạo OAuth Client

1. Vào **Clients → Create client**.
2. Chọn loại **Web application**. Không chọn Desktop app hoặc Service account.
3. Đặt tên `Napaco Local Web`.
4. Thêm **Authorized JavaScript origins**:

```text
http://127.0.0.1:8000
```

5. Thêm **Authorized redirect URIs** chính xác:

```text
http://127.0.0.1:8000/auth/google/callback
```

6. Chọn **Create**, sau đó tải file JSON của client.
7. Đổi tên file thành **`google-oauth-client.json`** và lưu vào:

```text
Napaco ERP Local/data/google-oauth-client.json
```

Không gửi nội dung client secret vào chat. File này là thông tin riêng của dự án và đã được loại khỏi Git qua thư mục `data`.

## 4. Sau khi lưu file

Báo đã lưu file để hoàn tất cấu hình và kiểm tra trên máy. Khi backend đã nhận cấu hình:

1. Mở http://127.0.0.1:8000/login.
2. Chọn **Đăng nhập Google**.
3. Chọn đúng tài khoản và xem kỹ quyền được yêu cầu trước khi đồng ý.
4. Tài khoản phải khớp một nhân viên đang hoạt động trong danh mục đã nhập. Không tự cấp quyền quản trị cho tài khoản lạ.
5. Thử tìm file Drive và lưu PO có đính kèm bằng màn hình gốc.

Nếu báo `redirect_uri_mismatch`, kiểm tra từng ký tự của redirect URI trên. `localhost` và `127.0.0.1` là hai địa chỉ khác nhau khi cấu hình OAuth; bản local này dùng `127.0.0.1`.

Nếu Google Workspace chặn ứng dụng hoặc phạm vi Drive, cần quản trị viên Workspace cho phép ứng dụng. Đây là quyền của tổ chức, không phải giới hạn của MySQL.

## Tham khảo chính thức

- https://developers.google.com/workspace/guides/configure-oauth-consent
- https://developers.google.com/workspace/guides/create-credentials
- https://developers.google.com/identity/protocols/oauth2/web-server
