# Hướng dẫn test toàn bộ Web App gốc trên MySQL local

Cập nhật ngày 11/11/2026. Tài liệu này thay thế hướng dẫn bản local đầu tiên có giao diện đơn hàng rút gọn.

## 1. Phạm vi chuyển đổi

**Menu, HTML, CSS, JavaScript giao diện và logic nghiệp vụ gốc được dùng lại.** Không gộp các màn hình vào một giao diện mới.

Đã nối với MySQL:

| Menu / màn hình | Chức năng giữ từ source cũ |
|---|---|
| Đơn Hàng → Tổng quan | Trang chọn công đoạn |
| Đơn Hàng → Tạo đơn hàng | Nhiều PO, nhiều khách hàng, danh mục mới, nhiều dòng sản phẩm, khuôn/màng/đóng gói |
| Đơn Hàng → Định Hình | PO Header, Line-Item, sửa hàng loạt, Kanban |
| Đơn Hàng → Bế | Line-Item và Kanban theo loại gia công 2 |
| Nguyên Liệu → Tạo Đơn | Quy cách, công thức tính kg, tham khảo khuôn/lịch sử, gán CTĐH |
| Nguyên Liệu → Màng Đã Đặt | Tìm/lọc, Xem/Sửa, gán/bỏ gán CTĐH, trạng thái, lịch sử nhận, sao chép quy cách |
| Nguyên Liệu → Nhận Màng | Chọn nhận, Lưu Tạm, sửa/bỏ dòng tạm, Lưu Tổng |
| Nguyên Liệu → Tồn Kho | Tồn theo lần nhận, lọc, trả chờ, xác nhận nhận trả |

**Nhật Ký Định Hình** vẫn ghi **Chờ liên kết**, vì source Web App cũ cũng chưa có đường dẫn/màn hình này. Không coi các module trong SPEC nhưng chưa có code là đã triển khai.

Các thao tác nghiệp vụ tại local không gọi Google Sheets và không sửa hệ thống Apps Script đang chạy. File PO vẫn được thiết kế lưu ở Drive, không đổi ngầm sang lưu trong MySQL hoặc ổ đĩa local.

## 2. Mở ứng dụng

1. Mở Docker Desktop, chờ Docker sẵn sàng.
2. Trong thư mục dự án, mở **`Mo ung dung.command`**.
3. Vào **http://127.0.0.1:8000/?view=index**.
4. Đăng nhập bằng tài khoản trong **`.local-admin.txt`** để test ngay các chức năng nghiệp vụ không cần Drive.

Finder thường ẩn file bắt đầu bằng dấu chấm. Nhấn **Command + Shift + .** để hiện file `.local-admin.txt`.

Trên màn hình nhỏ, nhấn **☰ Menu**. Hai nhóm **Đơn Hàng** và **Nguyên Liệu** mở/thu gọn giống bản cũ. Trên desktop, menu nằm bên trái.

Các địa chỉ trực tiếp:

```text
http://127.0.0.1:8000/?view=index
http://127.0.0.1:8000/?view=create
http://127.0.0.1:8000/?view=list
http://127.0.0.1:8000/?view=be
http://127.0.0.1:8000/?view=film-create
http://127.0.0.1:8000/?view=film
http://127.0.0.1:8000/?view=film-receive
http://127.0.0.1:8000/?view=film-stock
```

## 3. Đăng nhập Google và file Drive

Hai phần này cần cấu hình OAuth riêng, vì quyền Google của Apps Script không tự chuyển cho backend mới.

**Cần anh thực hiện:** làm theo **`Huong dan ket noi Google va Drive.md`**, tạo OAuth Client loại Web application và lưu JSON tại `data/google-oauth-client.json`. Sau đó mở **`Cau hinh Google.command`**, vào `/login` và chọn **Đăng nhập Google**.

Callback cần khai báo:

```text
http://127.0.0.1:8000/auth/google/callback
```

Backend sẽ khớp email Google đã xác minh với một nhân viên đang hoạt động trong danh mục. Không tự cấp quyền quản trị cho người mới. Quyền từng nghiệp vụ vẫn đi theo ma trận quyền cũ.

Sau khi kết nối, test đúng các nút **Chọn tệp từ máy** và **Tìm trên Google Drive** của form gốc. Tệp tải từ máy được đưa vào thư mục Drive cấu hình trong source, giữ quy tắc đặt tên theo số PO.

**Khi chưa cấu hình:** phần tìm/tải Drive báo rõ chưa có quyền; giao dịch có file đính kèm không được lưu dở. Không dùng thư mục local làm nơi thay thế Drive. Vẫn có thể test luồng đơn hàng không đính kèm file.

Hiện các kiểm thử Google dùng dịch vụ giả lập để kiểm tra trạng thái đăng nhập, mã hóa token, khớp nhân viên và rollback khi tải file lỗi. Việc đăng nhập/tìm/tải trên Drive thật còn chờ client JSON và lần chấp thuận quyền của anh.

## 4. Quy trình test Đơn hàng

### A. Tạo nhiều PO

1. Chọn **Đơn Hàng → Tạo đơn hàng**.
2. Chọn khách hàng bằng ô gợi ý như cũ. Có thể nhập khách mới theo luồng gốc.
3. Điền số PO, nhân viên kinh doanh, ghi chú.
4. Chọn sản phẩm hoặc nhập sản phẩm mới; kiểm tra Code SP, ĐVT, số lượng và giá.
5. Mở nút **⚙️** để kiểm tra khuôn/màng/đóng gói.
6. Kiểm tra ngày đặt, ngày giao từng dòng và ngày giao chung là ngày muộn nhất.
7. Nhấn **+ Thêm dòng sản phẩm** và **+ Thêm PO** để kiểm tra nhiều dòng, nhiều PO trong một lần lưu.
8. Chưa cấu hình Google thì để trống phần tệp đính kèm.
9. Nhấn **XÁC NHẬN & LƯU TẤT CẢ VÀO DATABASE**.
10. Kiểm tra thông báo và đường dẫn tới đơn vừa tạo; xem đúng phần Định Hình/Bế nếu một giao dịch có cả hai loại.

Nên dùng tiền tố số PO `LOCAL-TEST-` cho các đơn thử. Đây vẫn là giao dịch lưu thật vào MySQL local; không tự xóa sau khi test.

### B. Danh sách và sửa hàng loạt

1. Mở **Định Hình**. Mặc định là **Line-Item**, đúng source gốc.
2. Thử từ khóa, khách hàng, nhóm trạng thái, ngày đặt/ngày giao; nhấn **Lọc (DB)** khi cần lấy lại dữ liệu.
3. Chuyển sang **PO Header**, mở chi tiết của PO.
4. Chọn một hoặc nhiều dòng; dùng thanh sửa hàng loạt và modal gốc.
5. Thử từng trường như số lượng, giá, ngày, sales, trạng thái, code, màng, ĐVT, giá khuôn theo những trường giao diện cho phép.
6. Lưu, tải lại và xác nhận dữ liệu được giữ.
7. Mở **Bế**, kiểm tra chỉ còn Line-Item và Kanban như trước, không thêm PO Header vào màn hình này.

Các bộ lọc mặc định chỉ hiển thị nhóm đang thực hiện và theo công đoạn. Vì vậy số hiển thị trên một màn hình không nhất thiết bằng tổng 42 đơn/45 chi tiết đã nhập. Chọn đúng trạng thái/bộ lọc để đối chiếu.

### C. Kanban

1. Chọn **Điều Phối Xưởng (Kanban)**.
2. Kiểm tra ba vùng Đang sản xuất, Ưu tiên, Chờ sản xuất.
3. Kéo một thẻ sang vùng khác hoặc đổi thứ tự.
4. Chờ báo đã lưu, tải lại để xác nhận.
5. Thử có bộ lọc đang bật, kiểm tra các thẻ ngoài bộ lọc không bị mất vị trí.

Thư viện kéo thả đúng phiên bản cũ đã được lưu cùng ứng dụng để không phụ thuộc CDN khi test local.

## 5. Quy trình test từ đặt màng tới tồn kho

### A. Tạo đơn màng

1. Chọn **Nguyên Liệu → Tạo Đơn**.
2. Chọn ngày, nhà cung cấp, ghi chú.
3. Nhập các quy cách và số kg, đơn giá, ngày giao.
4. Thử phần tra sản phẩm, khuôn, lịch sử và tính kg theo công thức.
5. Gán một CTĐH đang đủ điều kiện vào quy cách.
6. Lưu, vào **Màng Đã Đặt** kiểm tra PO và DN vừa sinh.

### B. Sửa, sao chép và gán CTĐH

1. Từ **Màng Đã Đặt**, chọn **Xem / Sửa**.
2. Thử sửa các trường được phép. PO đã nhận hàng vẫn giữ các hạn chế gốc về nhà cung cấp, ngày, quy cách và kg.
3. Thử xem danh sách CTĐH được gán, sửa/bổ sung gán, bỏ gán, mở lại để kiểm tra.
4. Chọn quy cách ở danh sách rồi dùng **Tạo đơn từ quy cách đã chọn**.
5. Kiểm tra lịch sử phiếu nhận và trạng thái Chờ Nhận/Nhận một phần/Đóng.

### C. Nhận màng

1. Mở **Nhận Màng**, chọn **Chọn nhận** trên một DN còn được nhận.
2. Nhập ngày nhận, ngày sản xuất, số cuộn, kg, vị trí, OK/NG và ghi chú.
3. Nhấn **Lưu Tạm**. Ở bước này chưa ghi vào kho.
4. Thử **Sửa** và **Bỏ** dòng tạm; thêm một DN khác.
5. Nhấn **Lưu Tổng** để ghi các dòng vào MySQL trong một giao dịch.
6. Tải lại, đối chiếu kg đã nhận, còn lại/dư và trạng thái.

Nếu chọn NG cần ghi chú. Nếu số kg đặt/đã nhận bị thay đổi ở phiên khác, hệ thống yêu cầu tải lại; không ghi đè bằng số liệu cũ. Gửi lại cùng phiên nhập không tạo thêm phiếu nhận trùng.

### D. Tồn kho và nhận trả

1. Mở **Tồn Kho**, tìm phiếu nhận vừa lưu.
2. Thử lọc độ dày, khổ, nhà cung cấp, còn/hết tồn.
3. Tồn được tính theo **từng lần nhập**: kg nhận − kg cấp + kg trả đã được kho xác nhận.
4. Nếu có phiếu trả chờ, kiểm tra thông báo trong menu và xác nhận theo luồng gốc.
5. Xác nhận lại một phiếu đã nhận không cộng tồn thêm lần nữa.

Bản dữ liệu xuất hiện có chưa có giao dịch cấp/trả. Không tự tạo giao dịch giả để làm đầy màn hình. Luồng nhận trả đã được kiểm thử với dữ liệu thử trong giao dịch hoàn tác.

Phần đồng bộ trả tự động từ nhật ký được giữ ở backend, nhưng source Web App chưa có màn hình lưu nhật ký. Muốn test từ thao tác nhập nhật ký trên giao diện cần nối/xây màn hình đó, thay vì giả vờ phần này đã có.

## 6. Dữ liệu đã chuyển và dữ liệu chưa khớp

Các bảng mới được bổ sung từ bản Excel đã xuất, không nhập đè lại đơn hàng đã có trên local:

| Nhóm | Dữ liệu ban đầu |
|---|---:|
| Khách hàng | 184 |
| Sản phẩm | 2.140 |
| Nhân sự nguồn | 12 |
| Đơn hàng | 42 |
| Chi tiết đơn hàng | 45 |
| Nhà cung cấp | 5 |
| Quy cách vật liệu | 9 |
| PO màng | 4 |
| Dòng đặt màng | 8 |
| Phiếu nhận màng | 6 |
| Giao dịch cấp/trả trong nguồn | 0 |

Đây là số liệu baseline nhập đầu, sẽ tăng/thay đổi khi anh lưu giao dịch thử. Chỉ các nhà cung cấp phù hợp theo quy tắc cũ mới xuất hiện ở lựa chọn đặt màng.

Dữ liệu gốc có **898 sản phẩm chưa liên kết được khách hàng** và mã sản phẩm **`SP_261024_01`** chưa có trong danh mục. Mã và dữ liệu nguyên gốc vẫn được giữ, không tự đoán thay thế. Xem `reports/import-result.json` để đối chiếu.

Giao diện gốc có thể lọc hoặc hiển thị mã thô đối với bản ghi thiếu danh mục, đúng logic nguồn. Không coi việc chuyển MySQL là đã làm sạch các liên kết này. Nên xác minh danh mục trước khi kết luận số hiển thị là sai hoặc dùng dữ liệu để vận hành thực tế.

Đây là bản sao tại thời điểm xuất Excel; local chưa đồng bộ hai chiều với Sheets. Nếu hệ thống cũ phát sinh dữ liệu mới, cần có đợt đối chiếu/nhập bổ sung riêng, không chép file mới đè lên dữ liệu đang test.

## 7. Những khác biệt môi trường đã công khai

- Địa chỉ đổi từ Apps Script sang `127.0.0.1:8000`.
- Có trang đăng nhập riêng. Tài khoản local dùng để test; đăng nhập Google cần OAuth như mục 3.
- Quyền đọc/ghi Google Drive phải được cấp lại cho ứng dụng mới. Ảnh/file riêng tư còn phụ thuộc quyền Google của người xem.
- Giữ kiểm tra sửa đồng thời theo quy tắc gốc của từng nghiệp vụ: phiên bản PO màng, danh sách CTĐH gán và số kg đã nhận. Không bắt tất cả tab tải lại chỉ vì có thay đổi ở một đơn khác.
- Các hàm thao tác bên trong Google Sheets như `onEdit`, đồng bộ cache vào Sheets hoặc modal mở từ sheet `TAO DON` không phải màn hình Web App local. Muốn tiếp tục chạy chúng từ Google cần đường kết nối tới backend sau khi triển khai; Google không truy cập được `127.0.0.1` trên máy Mac của anh.

**Không có hạn chế của MySQL/FastAPI buộc phải đổi menu hoặc thao tác các màn hình Web App đang có.** Các phần trên là cấu hình quyền hoặc khác biệt nơi chạy, không được thay âm thầm bằng giao diện khác.

## 8. Sao lưu, dừng và mở lại

- Mở **`Sao luu du lieu.command`** để tạo bản sao lưu trong `backups`.
- Mở **`Dung ung dung.command`** để dừng riêng ứng dụng và MySQL mới.
- Mở lại bằng **`Mo ung dung.command`**.
- Chạy `python3 scripts/verify_backup.py` trong thư mục dự án để thử khôi phục bản sao lưu mới nhất vào database tạm. Công cụ không ghi đè database đang dùng.

MySQL 8.4 chạy ở `127.0.0.1:3307`, database `napaco_erp_local`. Bản MySQL cũ ở 3306 không thay đổi. Tài khoản database trong `.env`, cấu hình Docker trong `.mysql.env`; các mật khẩu này khác tài khoản đăng nhập website.

Dữ liệu được giữ trong volume Docker `napaco-local_mysql84_data`. Không xóa volume hoặc chọn xóa toàn bộ dữ liệu Docker. Sao lưu thủ công hiện tại cần được tự động hóa trước khi dùng chính thức.

## 9. Cấu trúc triển khai để bảo trì

```text
HTML/CSS/JS màn hình gốc
        ↓ cầu nối gọi API
FastAPI: đăng nhập, quyền, giao dịch, kiểm soát phiên bản
        ↓
Logic JavaScript gốc chạy bằng Node local
        ↓ ánh xạ dữ liệu
MySQL: khách hàng, sản phẩm, đơn, màng, nhận, cấp/trả…
```

Đây là một backend đóng gói chung; Node dùng để giữ logic JavaScript gốc khi chuyển đổi, không gọi Apps Script để chạy nghiệp vụ. Các cấu trúc giống bảng tính chỉ được dựng trong bộ nhớ từng yêu cầu; dữ liệu nghiệp vụ được đọc/ghi vào các bảng MySQL riêng. Sau khi đối chiếu xong có thể chuyển dần logic sang Python mà không đổi giao diện.

**Source đã được tổ chức theo module.** Xem [Cấu trúc source và quy tắc bảo trì](Cau%20truc%20source%20va%20quy%20tac%20maintain.md) để biết đầy đủ cây thư mục và nơi cần sửa.

- Backend Đơn hàng: `backend/app/modules/orders/`.
- Backend Nguyên liệu: `backend/app/modules/materials/`, chia `purchasing`, `receiving`, `inventory`.
- Giao diện tương ứng: `frontend/orders/` và `frontend/materials/`; menu tại `frontend/shared/menu.html`.
- Đăng nhập ở `backend/app/auth/`; Google/Drive ở `backend/app/integrations/google/`.
- Cầu nối code cũ nằm riêng tại `backend/app/compatibility/`.

`source-appscript/` là bản gốc để đối chiếu, không còn là thư mục được đọc trực tiếp để chạy màn hình local. Tám template đang chạy trong `frontend` giữ nguyên nội dung gốc; bộ dựng trang chỉ thay đường gọi `google.script.run` bằng API local và dùng thư viện kéo thả lưu tại máy.

Quy tắc bảo trì: đặt nghiệp vụ vào module sở hữu; tách API, kiểm tra đầu vào, xử lý nghiệp vụ và model; không dồn nghiệp vụ mới vào `core` hoặc `compatibility`. Khi cần chuyển logic JavaScript sang Python, thực hiện trong chính module đó và giữ các hợp đồng giao diện hiện có.

Mã nguồn được lưu bằng Git, bí mật và dữ liệu được loại khỏi Git. Không đưa `.mysql.env`, `.google.env`, `.env`, `.local-admin.txt`, client JSON, Excel nguồn hoặc backup lên kho mã công khai.

## 10. Trạng thái kiểm tra và xử lý lỗi

Kiểm tra sức khỏe tại **http://127.0.0.1:8000/api/health**. MySQL cần là 8.4.13, migration hiện tại `003`.

Chạy kiểm thử bằng Terminal tại thư mục dự án:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env run --rm --no-deps backend python -m pytest -q -p no:cacheprovider
```

Bộ kiểm thử dùng giao dịch ngoài cùng để hoàn tác toàn bộ dữ liệu thử. Không để lại các PO thử do công cụ tạo. Kết quả mới nhất và kiểm tra khôi phục được lưu trong `reports`.

| Vấn đề | Cách xử lý |
|---|---|
| Vẫn thấy giao diện rút gọn cũ | Mở đúng địa chỉ `/?view=index`, tải lại trang; không mở file HTML cũ bằng Finder |
| Màn hình nhỏ không thấy menu | Nhấn ☰ Menu |
| Không thấy đủ đơn | Kiểm tra công đoạn, nhóm trạng thái và bộ lọc trước |
| Báo dữ liệu đã thay đổi | Nhấn Tải lại hoặc Lọc (DB), đối chiếu rồi sửa lại |
| Tìm/tải Drive báo chưa cấu hình | Làm hướng dẫn Google, nhập client JSON, đăng nhập Google |
| `redirect_uri_mismatch` | Kiểm tra redirect URI đúng `127.0.0.1:8000/auth/google/callback` |
| Google báo không có quyền file/thư mục | Kiểm tra tài khoản và quyền Drive; không mở công khai file để né quyền |
| Không mở website | Mở Docker, chạy lại Mo ung dung.command |
| Nhật ký vẫn Chờ liên kết | Source cũ chưa có màn hình này; không phải lỗi chuyển MySQL |
