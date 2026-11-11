# Hướng dẫn chạy và chuyển đổi NAPACO ERP trên máy local

Cập nhật ngày 11/11/2026. Tài liệu dành cho bản chạy thử đầu tiên: Đơn hàng.

## 1. Kết quả hiện có

Ứng dụng đã chạy tại **http://127.0.0.1:8000** trên máy Mac này, kết nối MySQL **8.4.13 LTS** tại cổng **3307**.

Đã thực hiện:

1. Tải 19 file source mới nhất trực tiếp từ Apps Script vào `source-appscript/src`.
2. Cài MySQL 8.4 riêng bằng Docker, dùng vùng dữ liệu riêng, không thay đổi MySQL 8.0 tại cổng 3306.
3. Xây backend FastAPI, SQLAlchemy và quản lý cấu trúc bảng bằng Alembic.
4. Đọc hai file Excel anh đã xuất từ MASTER và OPERATION.
5. Kiểm tra mã trùng, ngày, số, liên kết; nhập vào MySQL trong một giao dịch.
6. Tạo giao diện local cho xem, tìm kiếm, phân trang, tạo và sửa đơn hàng.
7. Tạo đăng nhập local, kiểm tra quyền ghi, lưu lịch sử thao tác, chống lưu trùng và sửa đè.
8. Kiểm thử và sao lưu; thử khôi phục thành công vào một database tạm riêng.

Đây là **luồng Đơn hàng đầu tiên để dùng thử**, chưa thay thế toàn bộ ứng dụng Apps Script. Google Sheets và source trên Google không bị sửa. Dữ liệu tạo/sửa tại local không tự đồng bộ ngược lên Sheets.

## 2. Cách mở ứng dụng mỗi ngày

1. Mở **Docker Desktop** và đợi Docker hoạt động.
2. Mở thư mục `Napaco ERP Local`.
3. Mở file **`Mo ung dung.command`**. File sẽ bật database, kiểm tra phiên bản cấu trúc bảng, bật backend và mở trình duyệt.
4. Nếu trình duyệt chưa mở, vào **http://127.0.0.1:8000**.
5. Đăng nhập bằng tài khoản trong file **`.local-admin.txt`** ở thư mục dự án.

Tên đăng nhập là `local-admin`. Mật khẩu được sinh riêng trên máy và không ghi trong tài liệu này.

File bắt đầu bằng dấu chấm thường bị Finder ẩn. Trong Finder, nhấn **Command + Shift + .** để hiện/ẩn các file này. Có thể mở `.local-admin.txt` bằng TextEdit.

Nếu macOS không mở file `.command`, mở Terminal, nhập `python3`, thêm một dấu cách, kéo file `scripts/manage.py` vào cửa sổ Terminal, thêm ` start`, rồi nhấn Enter.

Phiên đăng nhập có hạn 8 giờ. Khi hết hạn, đăng nhập lại. Đây là tài khoản quản trị cho môi trường phát triển local, chưa phải cơ chế đăng nhập Google dành cho nhân viên.

## 3. Tìm và xem đơn hàng

1. Nhập từ khóa: mã đơn, số PO, tên khách hàng, mã hoặc tên sản phẩm.
2. Chọn thêm khách hàng, công đoạn Định hình/Bế, trạng thái nếu cần.
3. Có thể lọc từ ngày đặt và đến ngày hẹn giao.
4. Nhấn **Tìm kiếm**. Mỗi trang hiển thị tối đa 25 đơn.
5. Chọn **Xem / Sửa** trên dòng đơn để mở chi tiết.
6. Nhấn **Đặt lại** để bỏ bộ lọc; dùng **Trước / Sau** để chuyển trang.

Bộ lọc công đoạn/trạng thái chọn các đơn có dòng phù hợp; khi mở một đơn, màn hình vẫn hiển thị toàn bộ dòng của đơn đó để không làm mất ngữ cảnh. Tổng giá trị một đơn được tính từ toàn bộ chi tiết của đơn.

Ngày giao trên đầu đơn là ngày giao dự kiến của đầu đơn đã nhập. Khi lưu sửa, ngày này được tính lại bằng ngày giao muộn nhất của các dòng chi tiết.

## 4. Tạo một đơn hàng thử

1. Nhấn **Tạo đơn hàng**.
2. Chọn khách hàng có trong danh mục.
3. Điền số PO. Nên đặt tiền tố `LOCAL-TEST-` cho các đơn thử để nhận diện.
4. Kiểm tra ngày đặt. Ngày giao từng dòng mặc định là ngày hiện tại cộng 10 ngày.
5. Chọn sản phẩm thuộc khách hàng; đơn vị và giá được điền từ danh mục, có thể sửa.
6. Điền số lượng, đơn giá, ngày giao, nhân viên phụ trách, trạng thái và ghi chú.
7. Nhấn **Thêm dòng** để thêm sản phẩm khác. Dòng mới chưa lưu có thể xóa bằng nút ✕.
8. Nếu thiếu sản phẩm trong danh sách, gõ tên hoặc mã ở ô tìm sản phẩm, nhấn **Tìm sản phẩm**, rồi chọn lại ở dòng.
9. Có thể dán liên kết HTTPS tới file PO đã có trên Drive. Bản đầu chưa tải file mới lên Drive.
10. Nhấn **Lưu đơn hàng**. Khi thành công sẽ có thông báo mã đơn vừa lưu.
11. Đóng/mở lại đơn để xác nhận dữ liệu đã được đọc lại từ MySQL.

Số lượng phải lớn hơn 0, đơn giá không âm, tối đa 4 chữ số thập phân. Ngày giao không trước ngày đặt. Backend tự kiểm tra sản phẩm có thuộc khách hàng hay không, không chỉ dựa vào giao diện.

Mã mới giữ kiểu `DH_yymmdd_xx` và `CT_yymmdd_xx`, dùng ngày Việt Nam và bộ đếm có khóa trong MySQL. Bộ đếm được tiếp nối từ mã đã nhập để tránh trùng.

Hiện chưa tạo khách hàng hoặc sản phẩm mới từ form. Danh mục thiếu cần được rà soát và bổ sung ở bước tiếp theo.

## 5. Sửa một đơn đã có

1. Mở **Xem / Sửa**.
2. Sửa số PO, ngày đặt, liên kết file và các trường chi tiết được mở.
3. Có thể thêm dòng mới vào đơn.
4. Nhấn **Lưu đơn hàng** và mở lại để kiểm tra.

Bản đầu giữ nguyên khách hàng của đơn, mã dòng và sản phẩm của dòng đã lưu. Chưa hỗ trợ xóa dòng đã lưu hoặc chuyển dòng sang đơn khác. Các số liệu đã sản xuất/đã giao, liên kết màng và vị trí ưu tiên được giữ lại.

Nếu phiên khác đã sửa đơn, hệ thống từ chối phiên bản cũ. Hãy ghi lại phần đang sửa, đóng form, mở lại và cập nhật trên dữ liệu mới; không bấm lưu lặp liên tục.

Đầu đơn và toàn bộ chi tiết được lưu trong cùng giao dịch. Nếu một dòng lỗi, toàn bộ lần ghi bị hủy. Việc tạo đơn có mã yêu cầu riêng để một lần gửi lại không tạo thêm đơn trùng.

## 6. Dữ liệu đã chuyển và điểm cần đối chiếu

Kết quả của lần nhập đầu:

| Nội dung | Số lượng |
|---|---:|
| Khách hàng | 184 |
| Sản phẩm | 2.140 |
| Nhân sự từ Sheets | 12 |
| Tài khoản quản trị local bổ sung | 1 |
| Đơn hàng | 42 |
| Chi tiết đơn hàng | 45 |
| Ô quyền theo vai trò đã chuyển | 70 |
| Dòng nguồn có dữ liệu được lưu để đối chiếu | 2.524 |
| Tổng số lượng đặt | 276.648 |
| Tổng số lượng đã giao trong nguồn | 0 |
| Tổng giá trị chi tiết, số lượng × đơn giá | 607.091.950 đồng |

Các số lượng và tổng giá trị đã đối chiếu trực tiếp với MySQL trong giao dịch nhập. Tổng giá trị là phép cộng chi tiết; chưa phải số liệu kế toán, doanh thu đã ghi nhận, VAT hoặc giá trị đã giao.

**Dữ liệu nguồn có vấn đề cần xử lý:**

- **898 sản phẩm** không liên kết được với khách hàng trong bản MASTER: có mã khách hàng trống hoặc tham chiếu mã không có trong danh mục khách hàng. Không tự gán các sản phẩm này cho khách khác. Mã gốc được giữ ở `source_customer_id` và dữ liệu nguồn; khóa liên kết để trống. Những sản phẩm này chưa xuất hiện trong lựa chọn sản phẩm theo khách hàng.
- **1 dòng đơn hàng** dùng sản phẩm **`SP_261024_01`**, chưa có trong danh mục sản phẩm. Đơn liên quan là **`DH_261024_02`**. Dòng vẫn được nhập đủ số lượng, giá và mã gốc; đơn này chỉ xem trên giao diện cho đến khi danh mục được xác minh.

Chi tiết đầy đủ ở **`reports/import-result.json`**, gồm cảnh báo, số dòng và kết quả `reconciliation: PASS`.

Không suy đoán tên hoặc khách hàng của mã thiếu. Cần kiểm tra nguồn nghiệp vụ, xác nhận ánh xạ rồi mới bổ sung. Chưa có công cụ tự sửa các ánh xạ này ở bản đầu.

Số lượng còn lại trên màn hình = số lượng đặt − số lượng đã giao. Giá trị `SL_Con_Lai` gốc vẫn được lưu riêng để đối chiếu. Các công thức Excel không trở thành công thức chạy trong MySQL; bản Excel gốc vẫn được giữ nguyên.

## 7. Nhập dữ liệu: quy trình đã dùng

### Bước 1 — Lấy đúng source

Source được tải từ dự án Apps Script hiện tại vào `source-appscript/src`. File `source-appscript/schema.json` là bản ánh xạ tên bảng/cột từ `Config.js`. Nếu source đổi, phải rà soát ánh xạ trước khi nhập lại.

### Bước 2 — Xuất dữ liệu từ Google Sheets

Trong mỗi file MASTER và OPERATION, chọn **Tệp → Tải xuống → Microsoft Excel (.xlsx)**.

Lưu vào:

```text
Napaco ERP Local/data/source-master.xlsx
Napaco ERP Local/data/source-operation.xlsx
```

Phiên đăng nhập clasp hiện dùng để đọc source chưa có quyền xuất hai file dữ liệu, và Sheets API của dự án OAuth đó chưa bật. Vì vậy lần chuyển này dùng hai file Excel anh đã xuất, không phụ thuộc việc sửa cấu hình Google Cloud.

Hai file được xuất riêng, không phải một snapshot nguyên tử giữa hai workbook. Trước lần chuyển chính thức cần dừng nhập liệu trong thời gian xuất để tránh dữ liệu thay đổi giữa hai bản.

### Bước 3 — Sao lưu trước khi thay đổi

Mở `Sao luu du lieu.command`. Chờ thông báo tạo file `.sql.gz` trong `backups`.

### Bước 4 — Kiểm tra trước khi nhập

Mở `Kiem tra du lieu nhap.command`, hoặc trong Terminal tại thư mục dự án:

```bash
python3 scripts/manage.py preview
```

Kết quả lưu vào `reports/import-preview.json`. Bước này đọc Excel và kiểm tra, chưa ghi dữ liệu nghiệp vụ.

### Bước 5 — Nhập vào database mới

Chỉ dùng với database mới chưa có dữ liệu nghiệp vụ:

```bash
python3 scripts/manage.py import
```

Lần đầu đã thực hiện, **không cần chạy lại để sử dụng ứng dụng**. Import nhận diện cùng snapshot bằng checksum, sẽ bỏ qua nếu đã nhập. Nếu đổi file nguồn trong khi database đã có dữ liệu, công cụ từ chối ghi đè; cần quy trình đồng bộ riêng để không làm mất sửa đổi local.

### Bước 6 — Đối chiếu

Kiểm tra số khách hàng, sản phẩm, đơn, chi tiết và tổng số lượng/giá trị trong báo cáo. Mở vài đơn thực tế để so tên khách, PO, sản phẩm, ngày, đơn giá, trạng thái và ghi chú.

## 8. Sao lưu và thử khôi phục

### Tạo bản sao lưu

Mở **`Sao luu du lieu.command`** hoặc chạy:

```bash
python3 scripts/manage.py backup
```

File được lưu dạng `backups/napaco-YYYYMMDD-HHMMSS.sql.gz`, kèm file checksum `.sha256`. Bản sao lưu chứa dữ liệu nghiệp vụ và thông tin đăng nhập đã băm; cần bảo vệ như dữ liệu nội bộ.

### Thử khôi phục an toàn

Chạy tại thư mục dự án:

```bash
python3 scripts/verify_backup.py
```

Công cụ lấy bản sao lưu mới nhất, kiểm tra checksum, tạo một database tạm tên `napaco_restorecheck_...`, nhập dữ liệu, đếm bảng và đọc tổng số lượng/giá trị. Sau đó xóa database tạm do chính công cụ tạo. Database đang dùng không bị ghi đè.

Kết quả ở `reports/backup-verification.json`. Lần kiểm tra đầu đã thành công và đọc lại đúng 42 đơn, 45 chi tiết, tổng số lượng 276.648, giá trị 607.091.950 đồng.

Việc thử khôi phục này không tự chuyển ứng dụng về dữ liệu cũ. Khi cần phục hồi để sử dụng thật, cần dừng ghi dữ liệu, sao lưu hiện trạng, phục hồi vào một database riêng, đối chiếu rồi mới đổi kết nối. Không nhập một bản dump cũ trực tiếp đè vào database đang sử dụng.

Hiện sao lưu được chạy thủ công. Nên sao lưu trước mỗi đợt dùng thử hoặc nâng cấp và giữ thêm bản sao ở ổ khác; volume Docker không phải bản sao lưu độc lập.

## 9. Dừng ứng dụng và bảo quản dữ liệu

- Mở **`Dung ung dung.command`** để dừng riêng backend và MySQL của Napaco.
- Mở lại bằng **`Mo ung dung.command`**.
- Dữ liệu nằm trong Docker volume **`napaco-local_mysql84_data`**, được giữ khi dừng hoặc tạo lại container.
- Không xóa volume, không chọn xóa toàn bộ dữ liệu Docker và không dùng `down -v` khi còn cần dữ liệu.
- MySQL cũ tại 3306 và các kết nối host đã có không bị sửa.

## 10. Kết nối bằng Workbench hoặc DBeaver

Tạo kết nối TCP/IP mới:

| Trường | Giá trị |
|---|---|
| Tên gợi ý | Napaco Local 8.4 |
| Host | 127.0.0.1 |
| Port | 3307 |
| Database | napaco_erp_local |
| User / Password ứng dụng | Lấy trong `.env` |

Tài khoản quản trị MySQL có mật khẩu trong `.mysql.env`, trường `MYSQL_ROOT_PASSWORD`; đây là tài khoản khác với `local-admin` đăng nhập website. Không cần dùng tài khoản quản trị để thao tác đơn hàng hằng ngày.

Kết nối trong container dùng hostname `mysql`, cổng 3306; kết nối từ máy Mac dùng 127.0.0.1, cổng 3307. Đây là hai phía của cùng dịch vụ, không phải hai database mới khác nhau.

## 11. Các file và cấu trúc quan trọng

| Đường dẫn | Công dụng |
|---|---|
| `compose.yaml` | Chạy MySQL và backend; chỉ mở cổng trên localhost |
| `backend/app` | Backend nghiệp vụ và nhập dữ liệu |
| `backend/alembic` | Lịch sử thay đổi cấu trúc bảng |
| `backend/tests` | Kiểm thử tích hợp trên MySQL |
| `frontend` | Giao diện HTML/CSS/JavaScript local |
| `source-appscript/src` | Bản source Apps Script đã tải về |
| `data` | Hai file Excel nguồn |
| `reports/import-result.json` | Kết quả nhập và cảnh báo dữ liệu |
| `reports/verification.json` | Kiểm thử và đo API local |
| `reports/backup-verification.json` | Kết quả thử khôi phục |
| `backups` | Các bản sao lưu database |
| `.env` | Tài khoản database cho kết nối từ máy Mac |
| `.mysql.env` | Tài khoản database dùng khi chạy Docker |
| `.local-admin.txt` | Tài khoản đăng nhập website local |

Ba file cấu hình tài khoản, dữ liệu nguồn và bản sao lưu được loại khỏi Git. Không gửi chúng vào chat hoặc đưa lên kho mã công khai. Nếu chuyển máy, cần chuyển cấu hình bí mật riêng bằng kênh phù hợp; chỉ sao chép mã nguồn sẽ không có dữ liệu trong Docker volume.

Các bảng chính: `customers`, `products`, `users`, `role_permissions`, `orders`, `order_lines`, `audit_log`, `sequences`, `request_keys`, `login_sessions`, `import_runs`, `source_rows`.

`source_rows` lưu các dòng có dữ liệu từ cả hai workbook để đối chiếu các module chưa chuyển; việc có dữ liệu thô ở đây không có nghĩa các module kho/sản xuất đã hoạt động trên local.

## 12. Kiểm thử và kiểm tra sức khỏe

Mở **http://127.0.0.1:8000/api/health**. Kết quả cần có `status: ok`, `MySQL 8.4.13`, migration `001`.

Tại thư mục dự án, chạy kiểm thử bằng:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env run --rm --no-deps backend python -m pytest -q -p no:cacheprovider
```

Đã đạt 6 kiểm thử tích hợp: đăng nhập/quyền, lưu trùng và số thập phân, danh sách/tìm kiếm/phân trang, hủy toàn giao dịch khi dòng sau lỗi, từ chối phiên bản sửa cũ, kiểm tra dữ liệu và từ chối yêu cầu từ website khác. Dữ liệu kiểm thử được hoàn tác bằng giao dịch, không giữ lại đơn thử trong 42 đơn đã nhập.

Đã kiểm tra trên trình duyệt: đăng nhập, danh sách 42 đơn, mở chi tiết, mở form tạo đơn và nạp sản phẩm theo khách hàng; kiểm tra bố cục màn hình hẹp và desktop. Luồng ghi được xác minh trong kiểm thử API, không sửa đơn nguồn bằng thao tác thử trên giao diện.

10 lần gọi API danh sách trang đầu 25 đơn trên local có trung vị khoảng **25 ms**, lớn nhất khoảng **37 ms**. Đây là phép đo nhỏ khi backend đã chạy và pool kết nối sẵn có; không phải thời gian mở toàn màn hình, benchmark tải đồng thời hoặc cam kết tốc độ triển khai thực tế.

## 13. Khi gặp lỗi

| Hiện tượng | Cách kiểm tra |
|---|---|
| Không mở được website | Mở Docker Desktop, chạy lại `Mo ung dung.command` |
| Docker chưa sẵn sàng | Đợi Docker khởi động hoàn tất rồi chạy lại |
| Đăng nhập không được | Dùng tài khoản website trong `.local-admin.txt`, không dùng mật khẩu MySQL |
| Danh sách trống | Nhấn Đặt lại, kiểm tra trang và bộ lọc |
| Không thấy sản phẩm | Chọn đúng khách hàng; tìm thêm theo mã/tên; kiểm tra cảnh báo danh mục |
| Đơn không có nút Lưu | Kiểm tra quyền hoặc đơn thiếu danh mục sản phẩm |
| Báo phiên bản đã thay đổi | Đóng form, mở lại và thực hiện sửa trên phiên bản mới |
| Không mở được database | Kiểm tra cổng 3307; tránh chọn Local instance 3306 cũ |
| Nhập Excel bị từ chối | Xem báo lỗi; không xóa bảng để ép nhập lại |

Xem trạng thái: `python3 scripts/manage.py status`. Có thể xem log container `napaco-backend` trong Docker Desktop. Không đưa nội dung mật khẩu hoặc toàn bộ dữ liệu khách hàng vào ảnh/log chia sẻ.

## 14. Phạm vi còn lại trước khi thay thế Apps Script

Bản đầu chưa chuyển đầy đủ giao diện và nghiệp vụ gốc. Cần làm tiếp theo thứ tự:

1. Anh đối chiếu các đơn hiện có, tạo/sửa một số đơn thử để chốt hành vi mong muốn.
2. Làm sạch hoặc xác nhận các mã khách hàng/sản phẩm thiếu trong nguồn.
3. Hoàn thiện danh mục mới, nhiều PO trong một lần tạo, tải file Drive, các chế độ line-item/Kanban, khuôn và chỉnh sửa hàng loạt theo source gốc.
4. Chuyển Đặt màng, Nhận màng, Tồn kho và Hoàn màng, gồm kiểm thử liên kết số lượng.
5. Thiết lập đăng nhập Google, quy trình cấp tài khoản nhân viên và phân quyền đọc/ghi đầy đủ. Nhân sự nhập từ Sheets hiện chưa được cấp mật khẩu local; chỉ quản trị local dùng thử.
6. Thêm chức năng AI nhỏ có người xác nhận, sau đó mới xử lý file và tri thức.
7. Đo toàn màn hình và tải đồng thời, tự động hóa sao lưu, thử quy trình phục hồi, chốt nơi triển khai thực tế.

Hiện cả website và MySQL mới đều chỉ lắng nghe trên máy Mac. Chưa đưa lên host, mạng nội bộ công ty hoặc Internet.
