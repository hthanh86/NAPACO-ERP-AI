# Hướng dẫn hiện tại

Bản giao diện đơn hàng rút gọn đã được thay bằng các màn hình và menu gốc theo yêu cầu.

Đọc [Hướng dẫn test toàn bộ giao diện gốc](Huong%20dan%20test%20toan%20bo%20giao%20dien%20goc.md).

Đọc [Hướng dẫn kết nối Google và Drive](Huong%20dan%20ket%20noi%20Google%20va%20Drive.md) để hoàn tất đăng nhập Google và tìm/tải file.

Mở ứng dụng tại http://127.0.0.1:8000/?view=index. Mật khẩu local vẫn ở `.local-admin.txt`.

## 1. Khi nào cần build hoặc rebuild?

| Thay đổi | Cách áp dụng |
| --- | --- |
| HTML, JavaScript, CSS trong `frontend/` | Tải lại trang, có thể dùng Cmd + Shift + R. Không cần build backend vì thư mục này được mount trực tiếp vào container. |
| Python hoặc JavaScript trong `backend/`, kể cả `backend/app/modules/materials/receiving/legacy/service.js` | Build lại image backend rồi tạo lại container backend theo mục 4. |
| `backend/requirements.txt` hoặc `backend/Dockerfile` | Build lại backend. Có thể cần mạng để tải image hoặc dependency đã khai báo. |
| Cấu hình container trong `compose.yaml`, `.mysql.env`, `.google.env` | Cần áp dụng lại cấu hình cho service liên quan; không chỉ tải lại trang. Không chia sẻ nội dung các file chứa thông tin đăng nhập. |
| Schema database hoặc migration | Là công việc riêng cần xem xét/phê duyệt; không chạy migration chỉ vì vừa sửa code. |

Build tạo image từ source code; rebuild là build lại sau khi sửa. Chỉ build chưa làm container đang chạy dùng code mới. `restart` container cũng không đưa source backend mới vào image cũ.

## 2. Chuẩn bị Terminal

Hướng dẫn dành cho dự án local đang dùng Docker Desktop trên macOS. Mở Docker Desktop, chờ Docker sẵn sàng. Trong Terminal chạy:

```sh
cd "/Users/hoangthanh/Documents/ChatGPT/Bế Dán - Giải Quyết Lỗi/Napaco ERP Local"
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

Các lệnh bên dưới thực hiện trong cùng cửa sổ Terminal này. Nếu mở cửa sổ mới, chạy lại phần chuẩn bị. Dùng đường dẫn Compose đầy đủ, không cần khai báo biến `NAPACO_COMPOSE`. File môi trường sử dụng giống [script quản lý local](scripts/manage.py).

Cần có `.mysql.env` của dự án và các cấu hình local đã được thiết lập. Không tạo lại hoặc ghi đè các file cấu hình đang dùng. Nếu máy chưa được thiết lập hoặc chưa có database/dữ liệu ERP, cần quy trình khởi tạo/nhập dữ liệu riêng; build không tự tạo tài khoản và nhập dữ liệu nghiệp vụ.

## 3. Build lần đầu và mở ứng dụng đã được thiết lập

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env build backend
```

Sau khi build thành công, mở [Mo ung dung.command](Mo%20ung%20dung.command), hoặc chạy:

```sh
python3 scripts/manage.py start
```

Lệnh `start` mở Docker, bật MySQL, chờ MySQL sẵn sàng, chạy `alembic upgrade head`, khởi tạo lớp tương thích nếu chưa có, rồi bật backend và mở trình duyệt. **Lệnh này có chạy migration**, nên chỉ dùng khi đã chấp thuận các migration hiện có. Nếu chỉ cập nhật code trên database đang hoạt động và không cần migration, dùng mục 4.

## 4. Rebuild sau khi sửa backend, giữ nguyên dữ liệu

Áp dụng cho môi trường local đã có dữ liệu ERP. Không cần tắt hoặc xóa MySQL.

### Bước 1: Bật MySQL và sao lưu

Nếu MySQL đang tắt:

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env up -d mysql
```

Chờ MySQL hiển thị `healthy` trong Docker Desktop. Sau đó mở [Sao luu du lieu.command](Sao%20luu%20du%20lieu.command), hoặc chạy lệnh tương đương:

```sh
python3 scripts/manage.py backup
```

Script sao lưu cần container MySQL đang chạy; nó mở Docker Desktop nhưng không tự bật service MySQL. Chỉ tiếp tục khi thông báo `Đã sao lưu` xuất hiện và lệnh kết thúc thành công.

Bản sao lưu nằm trong `backups/`, gồm file `napaco-YYYYMMDD-HHMMSS.sql.gz` và file checksum `.sql.gz.sha256`. Đây là sao lưu database, không phải sao lưu toàn bộ source code, cấu hình bí mật hoặc file trên Google Drive. Không cần chạy script khôi phục/kiểm thử backup để rebuild.

### Bước 2: Build lại backend

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env build backend
```

Nếu build thất bại, dừng tại đây và đọc lỗi; chưa thay container đang chạy. Cache build được dùng bình thường và Docker tự nhận diện source thay đổi.

### Bước 3: Tạo lại riêng container backend bằng image mới

Chỉ chạy khi bước build đã thành công:

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env up -d --no-deps --force-recreate backend
```

Lệnh này có gián đoạn backend local trong lúc tạo lại container; nên hoàn tất thao tác đang nhập/lưu trước khi thực hiện. Nó không tạo lại MySQL, không xóa volume, không nhập lại dữ liệu và không tự chạy migration. Dữ liệu MySQL tiếp tục được lưu trong volume `mysql84_data` khai báo trong [compose.yaml](compose.yaml).

### Bước 4: Xem trạng thái và mở lại trang

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env ps
```

Mở http://127.0.0.1:8000/?view=index và tải lại trang bằng Cmd + Shift + R. Trạng thái container chạy không thay thế việc kiểm tra chức năng; chỉ chạy test khi có yêu cầu.

## 5. Khi vẫn thấy code cũ hoặc có lỗi

### Lệnh build báo `permission denied`

Không thêm `sudo` hoặc thay quyền file ngay. Nếu dùng `"$NAPACO_COMPOSE"`, biến có thể chưa được khai báo trong cửa sổ Terminal hiện tại hoặc trỏ sai đường dẫn. Chạy lại phần chuẩn bị ở mục 2 và dùng lệnh đường dẫn đầy đủ ở mục 4, bước 2.

Có thể kiểm tra riêng chương trình Compose, không build hay thay đổi dữ liệu:

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --version
```

Nếu lệnh này chạy được thì chương trình Compose có quyền thực thi; không cần `chmod`. Nếu vẫn báo lỗi, giữ nguyên thông báo và đường dẫn bị từ chối để xác định nguyên nhân. Lỗi truy cập `.docker/config.json`, `.docker/buildx/.lock` hoặc Docker socket trong phiên agent bị sandbox giới hạn cần cấp quyền thực thi Docker qua hộp thoại phê duyệt của ứng dụng; không khắc phục bằng cách mở quyền rộng cho thư mục Docker. Nếu chạy Terminal thông thường, kiểm tra Docker Desktop đang hoạt động và quyền truy cập tài khoản hiện tại, không tự đổi chủ sở hữu/xóa cấu hình Docker.

### Các lỗi khác

- Đã sửa backend nhưng chỉ refresh hoặc restart: thực hiện đủ bước build và tạo lại backend ở mục 4.
- Frontend đổi nhưng backend chưa rebuild: có thể lệch phiên bản API, gây lỗi tải dữ liệu/validation. Rebuild backend trước khi kiểm tra lại.
- Xem lỗi backend khi cần:

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env logs --tail=100 backend
```

- Chỉ khi nghi cache build có vấn đề, thay lệnh build thông thường bằng:

```sh
"/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose" --env-file .mysql.env build --no-cache backend
```

Sau đó vẫn phải thực hiện bước tạo lại container backend. `--no-cache` chậm hơn và có thể cần tải dependency; không cần dùng cho mỗi lần sửa code.

## 6. Lưu ý giữ dữ liệu

- Không dùng `down -v`, xóa volume MySQL hoặc xóa dữ liệu Docker để cập nhật code.
- Không chạy lại import dữ liệu nguồn để áp dụng thay đổi giao diện/backend.
- Không chạy migration ngoài phạm vi đã được chấp thuận.
- Rebuild backend không yêu cầu thay mật khẩu, sửa schema hoặc xóa database.
