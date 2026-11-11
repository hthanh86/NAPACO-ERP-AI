# Cấu trúc source và quy tắc bảo trì

Cập nhật ngày 11/11/2026. Cấu trúc này đã được áp dụng vào code đang chạy, không chỉ là đề xuất.

## 1. Nguyên tắc tổ chức

Code được chia theo nghiệp vụ để sửa Đơn hàng thì tìm trong `orders`, sửa nhận màng thì tìm trong `materials/receiving`. Các phần dùng chung và tích hợp bên ngoài có thư mục riêng.

Ứng dụng vẫn là một backend chia module, chưa tách microservices. Lần sắp xếp này không đổi tên bảng, không nhập lại dữ liệu, không thay đổi menu hoặc quy trình thao tác.

```text
backend/
├── app/
│   ├── main.py                      # Ghép ứng dụng và đăng ký các router
│   ├── core/
│   │   ├── database.py              # Kết nối, session và Base của SQLAlchemy
│   │   ├── config.py                # Đọc cấu hình dùng chung
│   │   ├── legacy_schema.json       # Cấu hình bảng/cột và quy tắc từ hệ thống cũ
│   │   ├── paths.py                 # Đường dẫn chung
│   │   ├── http.py                  # Xử lý lỗi và bảo vệ HTTP dùng chung
│   │   ├── models.py                # Lịch sử thao tác, bộ đếm mã dùng chung
│   │   └── model_registry.py        # Đăng ký model của các module
│   ├── auth/
│   │   ├── api.py                   # Đăng nhập, đăng xuất, thông tin phiên
│   │   ├── schemas.py               # Dữ liệu đầu vào đăng nhập
│   │   ├── security.py              # Mật khẩu, phiên và kiểm tra quyền
│   │   ├── models.py                # Người dùng, vai trò, phiên
│   │   ├── bootstrap.py             # Công cụ tạo quản trị local
│   │   ├── legacy_adapter.py        # Ánh xạ nhân sự nguồn
│   │   └── legacy/                  # Phần kiểm tra quyền JavaScript giữ lại
│   ├── integrations/google/
│   │   ├── oauth.py                 # Đăng nhập và token Google
│   │   ├── drive.py                 # Tìm/tải file Drive
│   │   └── models.py                # Cấu trúc lưu kết nối Google
│   ├── modules/
│   │   ├── customers/
│   │   │   ├── models.py
│   │   │   └── legacy_adapter.py
│   │   ├── products/
│   │   │   ├── api.py
│   │   │   ├── models.py
│   │   │   └── legacy_adapter.py
│   │   ├── orders/
│   │   │   ├── api.py               # API đơn hàng
│   │   │   ├── schemas.py           # Kiểm tra dữ liệu đầu vào
│   │   │   ├── service.py           # Xử lý đơn hàng bằng Python
│   │   │   ├── models.py            # Đầu đơn, chi tiết và mã chống lưu trùng
│   │   │   ├── legacy_adapter.py    # Ánh xạ trường dữ liệu đơn hàng
│   │   │   └── legacy/
│   │   │       ├── controller.js    # Bộ điều phối giữ từ source cũ
│   │   │       └── service.js       # Nghiệp vụ JavaScript giữ từ source cũ
│   │   └── materials/
│   │       ├── models.py            # Nhà cung cấp, quy cách dùng chung
│   │       ├── legacy_adapter.py
│   │       ├── purchasing/          # Đặt màng
│   │       │   ├── models.py
│   │       │   ├── legacy_adapter.py
│   │       │   └── legacy/service.js
│   │       ├── receiving/           # Nhận màng
│   │       │   ├── models.py
│   │       │   ├── legacy_adapter.py
│   │       │   └── legacy/service.js
│   │       └── inventory/           # Tồn, cấp/trả và xác nhận trả
│   │           ├── models.py
│   │           ├── legacy_adapter.py
│   │           └── legacy/
│   │               ├── stock.js
│   │               └── returns.js
│   ├── compatibility/
│   │   ├── api.py                   # Cầu nối các lời gọi từ màn hình cũ
│   │   ├── store.py                 # Chuyển đổi dữ liệu trong giao dịch MySQL
│   │   ├── registry.py              # Ghép các ánh xạ do module sở hữu
│   │   ├── models.py               # Metadata tương thích và chống gửi trùng
│   │   ├── runtime.cjs              # Chạy JavaScript cũ bằng Node local
│   │   └── legacy/                  # Các hàm đọc bảng/cấu hình dùng chung
│   ├── migrations/
│   │   ├── import_data.py           # Nhập Excel nguồn
│   │   ├── report.py                # Báo cáo dữ liệu sau chuyển đổi
│   │   ├── models.py                # Lần nhập và dòng dữ liệu nguồn
│   │   └── snapshots/               # Schema lịch sử đã chụp, không sửa tùy ý
│   └── system/api.py                # Trang vào ứng dụng, health và trạng thái nhập
├── alembic/                         # Các phiên bản thay đổi database
└── tests/                           # Kiểm thử tích hợp

frontend/
├── auth/                            # Trang đăng nhập và tài nguyên của nó
├── shared/
│   ├── menu.html                    # Menu dùng chung, giữ giao diện cũ
│   └── bridge.js                    # Cầu nối giao diện với API local
├── orders/
│   ├── index.html                   # Tổng quan đơn hàng
│   ├── create.html                  # Form tạo nhiều PO
│   ├── list.html                    # Định Hình/Bế, Line-Item, Header, Kanban
│   └── be.html                      # Mẫu phụ cho phần Bế
├── materials/
│   ├── purchasing.html              # Tạo/sửa và danh sách đặt màng
│   ├── receiving.html               # Nhận màng, lưu tạm và lưu tổng
│   └── inventory.html               # Tồn kho và nhận trả
└── vendor/                          # Thư viện bên ngoài đã cố định phiên bản
```

## 2. Khi cần sửa, tìm ở đâu?

| Nhu cầu | Nơi sửa chính |
|---|---|
| Menu, nhóm Đơn Hàng/Nguyên Liệu | `frontend/shared/menu.html` |
| Giao diện tạo PO, thêm PO/thêm dòng | `frontend/orders/create.html` |
| Giao diện Header/Line-Item/Kanban | `frontend/orders/list.html` |
| Quy tắc cũ về lưu nhiều PO, sửa hàng loạt, Kanban | `backend/app/modules/orders/legacy/` |
| API đơn hàng viết bằng Python | `backend/app/modules/orders/api.py`, `schemas.py`, `service.py` |
| Quy tắc đặt màng | `backend/app/modules/materials/purchasing/legacy/service.js` |
| Quy tắc nhận màng | `backend/app/modules/materials/receiving/legacy/service.js` |
| Tính tồn, trả chờ, xác nhận trả | `backend/app/modules/materials/inventory/legacy/` |
| Tên trường MySQL tương ứng với dữ liệu cũ | `legacy_adapter.py` của module đó |
| Đăng nhập hoặc quyền | `backend/app/auth/` |
| Google OAuth hoặc Drive | `backend/app/integrations/google/` |
| Kết nối MySQL, đường dẫn và lỗi HTTP chung | `backend/app/core/` |

File `list.html` dùng chung cho Định Hình và Bế vì hai màn hình có cùng cấu trúc; tham số loại sản phẩm quyết định nội dung và các tab. Không cần nhân đôi toàn bộ code chỉ để hai menu có hai đường dẫn riêng.

## 3. Quy tắc thêm hoặc sửa chức năng

1. **Đặt code vào module sở hữu nghiệp vụ.** Không đưa nghiệp vụ Đơn hàng vào `core`, hoặc nghiệp vụ nhận màng vào `orders` chỉ vì đang có một file thuận tiện để thêm.
2. **`api.py` nhận yêu cầu và trả kết quả; `schemas.py` kiểm tra đầu vào; `service.py` xử lý nghiệp vụ; `models.py` khai báo bảng.** Không cần tạo file rỗng ở module chưa có phần triển khai tương ứng.
3. **Đơn hàng sở hữu đơn và chi tiết; Nguyên liệu sở hữu đặt/nhận/cấp/trả.** Phần gán CTĐH vào màng cần đi qua thao tác có kiểm tra quyền và giao dịch, tránh sửa dữ liệu rải rác từ giao diện.
4. **`compatibility` chỉ phục vụ chuyển đổi.** Không tiếp tục dồn các nghiệp vụ mới vào cầu nối chung. Ánh xạ bảng/trường nằm trong module; registry chỉ ghép chúng lại.
5. **Cấu hình bảng/cột cũ tập trung trong `core/legacy_schema.json`.** Python và JavaScript local đọc chung cấu hình này. Thông tin bí mật vẫn ở các file môi trường riêng, không đưa vào JSON cấu hình source.
6. **Thay đổi database phải thêm migration Alembic mới.** Di chuyển file Python không phải lý do đổi bảng hoặc nhập lại dữ liệu. Không sửa nội dung các schema snapshot lịch sử để phản ánh model mới.
7. **Giữ hợp đồng giao diện khi sửa backend.** Tên thao tác, payload và kết quả mà màn hình cũ đang dùng phải tiếp tục đúng; chạy lại kiểm thử nghiệp vụ liên quan.

## 4. Phân biệt code đang chạy và bản nguồn đối chiếu

- **Code đang chạy:** `frontend/` và `backend/app/` theo cây trên.
- **Bản Apps Script tham chiếu:** `source-appscript/`. Giữ nguyên để đối chiếu và truy vết quá trình chuyển đổi; không sửa giao diện ở đây rồi kỳ vọng local tự thay đổi.
- **Dữ liệu/backup/bí mật:** `data/`, `backups/`, các file `.env`; không phải source của module và không đưa vào Git.

Nếu lấy thêm bản Apps Script mới, cần so sánh và đưa thay đổi có chọn lọc vào module đang chạy. Không chép đè toàn bộ bản tham chiếu lên các module vì có thể mất những chỉnh sửa đã thực hiện trên local.

Tám template nghiệp vụ được chuyển sang `frontend` giữ nguyên nội dung gốc. Các hàm JavaScript nghiệp vụ được chuyển vào module tương ứng. Những hàm đọc dữ liệu và quyền dùng chung được tách vào lớp tương thích và module đăng nhập.

## 5. Trạng thái kỹ thuật hiện tại

Việc chia module **không đồng nghĩa toàn bộ logic đã được viết lại bằng Python**. Một phần nghiệp vụ vẫn là JavaScript trong thư mục `legacy`, được chạy bằng Node local để giữ đúng thao tác cũ. FastAPI quản lý API, đăng nhập và giao dịch MySQL.

Sau khi đối chiếu ổn định, chuyển lần lượt các nghiệp vụ từ `legacy/service.js` sang `service.py` trong chính module đó, giữ giao diện và kiểm thử làm căn cứ. Không cần viết lại toàn bộ hệ thống trong một lần.

## 6. Kiểm tra và chạy lại sau khi sửa

Tại thư mục dự án, chạy kiểm thử như hướng dẫn test. Khi sửa code backend Python hoặc JavaScript trong backend, cần build lại image trước khi mở bản chạy thông thường:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env build backend
python3 scripts/manage.py start
```

Các template giao diện được gắn trực tiếp từ thư mục `frontend`, nên sửa giao diện rồi tải lại trang sẽ đọc bản mới. Đây là template có bước dựng phía server; không mở trực tiếp file HTML bằng Finder để test.

Các công cụ vẫn được gọi qua `scripts/manage.py` để không phải nhớ đường dẫn module nội bộ:

```bash
python3 scripts/manage.py start
python3 scripts/manage.py status
python3 scripts/manage.py preview
python3 scripts/manage.py backup
```

Lần tổ chức lại này được đối chiếu bằng bộ kiểm thử nghiệp vụ, cấu trúc ORM, các đường dẫn HTTP và nội dung tám template gốc. Không tạo migration hoặc nhập lại dữ liệu chỉ để chuyển thư mục.
