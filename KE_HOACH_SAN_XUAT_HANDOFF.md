# Kế hoạch sản xuất — bàn giao giai đoạn 1–7

**Trạng thái mới nhất — giai đoạn 7, 14/11/2026:** đã triển khai source gợi ý nhật ký, duyệt định mức chủ động và sửa lỗi tích hợp. MySQL local đã áp dụng **012–014**, có dữ liệu DEMO7 được giữ lại để kiểm tra. Backend/worker local đã được recreate; bằng chứng image/kiểm thử cuối ở mục giai đoạn 7 bên dưới. Không triển khai production. Các đoạn trạng thái 011/chưa test/chờ migration phía dưới là lịch sử bàn giao từng giai đoạn, không phải trạng thái cuối.

Hướng dẫn sử dụng: [KE_HOACH_SAN_XUAT_VAN_HANH.md](./KE_HOACH_SAN_XUAT_VAN_HANH.md). Báo cáo từng checkpoint và dữ liệu thật đã tạo: [production-phase7-demo.json](./reports/production-phase7-demo.json).

Ngày cập nhật: 14/11/2026. **Đã triển khai source giai đoạn 1+2 trên local; migration hiện tại 011 (đã áp dụng 010 và 011). Backend đã build/recreate và khởi động thành công. Chưa chạy test nghiệp vụ theo yêu cầu người dùng. Không có Gantt.**

**Giai đoạn 3:** source đã bổ sung ở phần cuối tài liệu; migration 012 đang chờ duyệt, chưa cập nhật backend giai đoạn 3 vào local. Không coi phần này đã vận hành.

**Giai đoạn 4:** đã bổ sung bộ tính/API/snapshot trong source và build image local. Migration 013 nối 012, cả hai chưa áp dụng; chưa chạy test hoặc cập nhật backend đang phục vụ cho giai đoạn 3–4. Chi tiết contract và giới hạn ở phần cuối.

**Giai đoạn 5:** đã bổ sung source Gantt và luồng nháp/tính thử/xác nhận/lưu, không thêm migration hoặc thư viện. Vẫn chờ 012/013 trước khi cập nhật backend phục vụ và nghiệm thu; chưa chạy test nghiệp vụ/browser.

**Giai đoạn 6:** đã bổ sung source bản cập nhật/chốt theo ngày, snapshot đầy đủ và so sánh nhật ký trực tiếp; thiết lập chung T2–CN nhập một lần. Chuẩn bị migration 014 nối 013, chưa áp dụng; local vẫn 011, chưa nghiệm thu API/browser.

## 1. Đối chiếu schema và migration

Đã đọc `AGENTS.md`, `Cau truc source va quy tac maintain.md`, `MYSQL-LOCAL.md`, `QC-ban-giao.md` và source/model liên quan. Đã truy vấn chỉ đọc MySQL local: revision **009**; có `products`, `film_materials`, `production_orders`, `production_setups`, `forming_logs`, `production_wip`, `cutting_logs`, `eb_logs`. Không có bảng quản lý máy/định mức/lịch tương đương.

Máy hiện nằm ở `source_rows` / master / `06.DM_May` (5 máy và tiêu đề); khuôn ở `05.Cong_Cu` với khóa nguồn `MaCC`, mã khuôn `Ma_Khuon`, liên kết sản phẩm `MaSP`. Đọc theo tên tiêu đề; không sửa baseline `source_rows`, không tạo bảng khuôn/vật liệu/sản phẩm mới. Công thức bìa nằm trong giao diện đặt nhựa, không nằm trong model vật liệu.

Migration cụ thể: [010_production_planning.py](backend/alembic/versions/010_production_planning.py), nối `009`, tạo **4 bảng**:

- `production_machines`: giữ mã máy; tên, loại `automatic/semi_automatic/cutting/edge/unclassified`, trạng thái `ready/running/maintenance/fault/inactive`, khổ màng/bước kéo tối đa (mm), ghi chú, lịch tuần JSON, version chống ghi đè.
- `production_standards`: ID UUID, code + revision UNIQUE; FK máy, vật liệu, người tạo; MaCC của khuôn nguồn; thông số JSON, snapshot JSON, ngày tạo, cờ áp dụng. Không cập nhật/xóa bản đã lưu.
- `production_standard_items`: PK ghép standard_id + product_id, FK định mức/sản phẩm, cavity riêng, ép biên, snapshot sản phẩm và tuyến công đoạn.
- `production_calendar_exceptions`: PK máy + ngày, FK máy, các khoảng được chạy và ghi chú.

Migration nhập đúng 5 máy nguồn, không tự tạo mã mới. Hai máy “Bế cắt” → cutting; ba máy “Định hình” → **unclassified**, phải phân loại bằng giao diện trước khi lập định mức. Giữ trạng thái nguồn tương ứng. Không tự đặt giờ làm, không tự tạo máy ép biên chưa có trong nguồn. Không thay đổi LSX/nhật ký/kho/quyền/bảng cũ. MySQL DDL không đảm bảo rollback nguyên khối; nếu migration bị ngắt phải kiểm tra bảng và revision trước khi xử lý tiếp. Downgrade tự động bị chặn để tránh xóa lịch sử.

**Đã áp dụng local ngày 14/11/2026**, sau khi người dùng yêu cầu build/triển khai để xem và đã sao lưu. Lệnh tham khảo cho môi trường còn ở 009 (không chạy lại hoặc dùng production tùy tiện):

```sh
# Không chạy trước khi được duyệt; không dùng production.
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env run --rm --no-deps backend alembic upgrade 010
```

Local hiện đã lên 011; không cần chạy lại riêng 010.

## 2. API/service và nghiệp vụ đã viết

Tất cả API dữ liệu kế hoạch và trang quản lý đều kiểm tra quyền hiện hữu `PRODUCTION_EDIT` tại backend; không thêm quyền, không cấp quyền cho vai trò. File công thức thuần toán chỉ yêu cầu đăng nhập để màn hình đặt nhựa tiếp tục dùng được.

| Method/path | Chức năng |
|---|---|
| GET `/api/production/machines?q=&kind=&status=&page=1&size=25` | Tìm máy, phân trang tối đa 100 |
| POST `/api/production/machines` | Tạo máy; mã do người dùng nhập, không đổi quy tắc mã cũ |
| PUT `/api/production/machines/{id}` | Sửa máy, bắt buộc version hiện tại, không đổi ID |
| GET `/api/production/references/{products,materials,molds}` | Chọn dữ liệu hiện có; q/page/size |
| GET `/api/production/standards` | q/machine_id/product_id/page/size; mặc định bản mới nhất mỗi code; history=true lấy cả lịch sử |
| GET `/api/production/standards/{id}` | Chi tiết phiên bản cùng sản phẩm/snapshot |
| POST `/api/production/standards` | Tạo code mới, revision 1 |
| POST `/api/production/standards/{id}/revisions` | Tạo bản kế tiếp từ phiên bản mới nhất, giữ nguyên code |
| GET `/api/production/standards/{id}/route` | Tuyến từng sản phẩm + cavity + đơn vị |
| GET `/api/production/calendars/{machine_id}?start=YYYY-MM-DD&end=YYYY-MM-DD` | Lịch tuần, ngoại lệ trong khoảng, version |
| PUT `/api/production/calendars` | Áp dụng lịch tuần/ngoại lệ cho nhiều máy nguyên tử |
| GET `/api/production/availability?machine_id=DH-01&machine_id=BC-01&start=2026-11-14&end=2026-11-20` | Khoảng được chạy, nhiều máy, tối đa 93 ngày |

Service tái sử dụng: [planning_service.py](backend/app/modules/production/planning_service.py): `save_machine`, `save_standard`, `route_for_standard`, `save_calendars`, `available_windows`, `calculate_sheet_weight`. Caller của service chịu trách nhiệm authorization và commit/rollback; API đã thực hiện. Read không commit. Ghi nhiều bảng cùng transaction; lỗi rollback; audit dùng `audit_log` hiện có. Khóa máy FOR UPDATE; áp dụng nhiều máy khóa theo mã tăng dần. Cập nhật máy/lịch cần version, sai trả 409. Tạo revision khóa bản nguồn, từ chối nếu có bản mới hơn; UNIQUE(code,revision) bảo vệ cạnh tranh.

### Định mức và đơn vị

- Một phiên bản là cấu hình **định hình** trên một máy automatic/semi_automatic, một vật liệu, một khuôn nguồn và nhiều sản phẩm. Máy cắt/ép biên được quản lý để giai đoạn sau phân công theo tuyến; chưa đặt định mức tốc độ riêng cho hai công đoạn đó.
- 1 chu kỳ = 1 bìa. Sản lượng mỗi sản phẩm = số chu kỳ × cavity của chính sản phẩm đó; **không cộng cavity các sản phẩm để chia nhu cầu của từng sản phẩm**. Số chu kỳ đáp ứng nhiều nhu cầu = max(ceil(nhu cầu_i / cavity_i)); có thể sinh dư sản phẩm ghép. Đây là quy ước đầu vào cho giai đoạn sau, chưa tạo lệnh hay tính phân bổ nhu cầu.
- Bán tự động: forming → cutting → edge nếu sản phẩm có ép biên. Tự động: forming_cutting → edge nếu có. Route được snapshot theo từng sản phẩm trong phiên bản.
- Bước kéo, chiều rộng và độ dày: mm. Giây/chu kỳ, setup phút, hao hụt phần trăm 0–100. Tỷ trọng g/cm³; trọng lượng bìa lưu kg/bìa. Hao hụt là mức dự kiến, chưa phát sinh xuất kho hay điều chỉnh tồn.
- Tái sử dụng **nguyên hàm** `filmCalculation` của đặt nhựa tại [calculation.js](backend/app/modules/materials/purchasing/calculation.js). Trang đặt nhựa tải cùng file qua API; backend gọi Node có sẵn, truyền JSON, timeout 5 giây. Không có công thức trọng lượng bìa thứ hai ở module mới. Giữ nguyên làm tròn lượng đặt bội 10 kg và tính ceil số bìa của đặt nhựa. Định mức lấy weight chưa làm tròn.
- Backend kiểm tra máy đã phân loại; active chỉ khi máy ready/running; vật liệu/sản phẩm/khuôn tồn tại, khuôn đúng loại; cavity nguyên dương, sản phẩm không lặp, khổ/bước kéo không vượt máy và không nhỏ hơn khuôn. Giới hạn máy để trống nghĩa là chưa khai báo, không khẳng định tương thích đã được xác minh. Không tự suy cavity từ khuôn cho cấu hình nhiều sản phẩm; người quản lý nhập cavity riêng và chịu trách nhiệm bố trí thực tế. `MaSP` nguồn là thông tin tham chiếu, không coi là khóa giới hạn một khuôn chỉ chạy một sản phẩm.
- Mỗi lần sửa tạo ID/revision mới; mọi thông số, trọng lượng, máy/khuôn/vật liệu/sản phẩm và route được snapshot. Giai đoạn sau **phải tham chiếu ID phiên bản cụ thể hoặc chụp snapshot khi tạo lần chạy**, không chỉ lưu code rồi tra bản mới nhất. Giai đoạn này không sửa lịch sử LSX hiện có.
- Muốn ngừng cấu hình: tạo phiên bản mới active=false. Bản cũ vẫn truy xuất được. Danh sách mặc định lấy bản mới nhất kể cả khi inactive, tránh làm bản cũ hoạt động lại.

### Lịch máy

- `calendar` là map weekday `'0'` (Thứ Hai) đến `'6'` (Chủ Nhật), mỗi ngày `{shifts:[{start:480,end:1020}],breaks:[{start:720,end:780}]}`. Số phút từ 00:00, end tối đa 1440, khoảng nửa mở [start,end). Ngày thiếu/ca rỗng = không chạy; giờ nghỉ phải nằm trong ca; không cho khoảng chồng lấn.
- Lịch mặc định chưa khai báo = không có giờ chạy. Ca qua đêm chia tại 00:00 thành hai ngày; không suy ca sang hôm sau.
- Ngoại lệ **thay toàn bộ** khoảng chạy của ngày; nhập `[480,1020]` sẽ cho chạy xuyên nghỉ trưa; `[]` = nghỉ cả ngày. Xóa ngoại lệ quay về lịch tuần. Không có lệnh xóa máy/định mức.
- PUT calendars payload có `versions:{"DH-01":1,"DH-02":1}`, tùy chọn `weekly`, `exceptions:[{day:"2026-11-14",windows:[{start:480,end:1020}],note:"..."}]`, `remove_exceptions:["2026-11-15"]`. Nếu bỏ weekly thì giữ lịch tuần, nếu weekly={} thì xóa giờ tuần cho các máy được chọn. Một máy sai version khiến cả batch rollback.
- Availability nhận ngày đầu/cuối inclusive theo Asia/Ho_Chi_Minh, trả ISO +07:00. Máy maintenance/fault/inactive trả windows rỗng, ngoại lệ không mở khóa trạng thái máy. Đây là **khả năng làm việc theo lịch và trạng thái hiện tại**, chưa trừ các lần chạy/đặt chỗ và chưa biểu diễn trạng thái máy theo lịch sử.

## 3. File chính và sử dụng

- Model/migration: [planning_models.py](backend/app/modules/production/planning_models.py), [010_production_planning.py](backend/alembic/versions/010_production_planning.py).
- Backend: [planning_api.py](backend/app/modules/production/planning_api.py), [planning_schemas.py](backend/app/modules/production/planning_schemas.py), [planning_service.py](backend/app/modules/production/planning_service.py). Đã đăng ký router/model trong assembly hiện có.
- UI: [planning.html](frontend/production/planning.html), [planning.js](frontend/production/planning.js), [planning.css](frontend/production/planning.css). Menu “Kế hoạch sản xuất → Dữ liệu nền”, URL `/production/planning`; dùng navigation/CSS hiện có, không tải danh mục khi vừa mở.
- Chọn Máy → Tìm kiếm → sửa phân loại máy nguồn / thêm máy; chọn Bộ định mức → Thêm mới → tìm và chọn máy, vật liệu, MaCC, sản phẩm; nhập cavity riêng và các thông số → lưu. Mở lại để xem trọng lượng/tuyến và lưu phiên bản tiếp theo.
- Lịch: tìm danh sách máy, tick các máy, Nạp lịch máy đầu tiên, chỉnh ca/nghỉ, Áp dụng lịch tuần. Ngoại lệ áp dụng cùng ngày cho tất cả máy đã tick. Chọn khoảng ngày và Lấy các khoảng được phép chạy.

## 4. Kiểm tra thực tế

- Đã đọc trực tiếp schema/table list, revision 009, cột film_materials, tiêu đề công cụ, danh mục máy và số dòng danh mục từ MySQL local; chỉ SELECT, không sửa dữ liệu.
- Đã rà soát diff các file có sẵn và đọc các file mới/phụ thuộc trực tiếp. Git hệ thống thiếu Command Line Tools, đã dùng Git của Sourcetree để xem diff.
- Đã chuẩn bị [test_production_planning.py](backend/tests/test_production_planning.py): API/quyền, xung đột version, định mức ghép và lịch sử tuyến, công thức dùng chung, trừ giờ nghỉ/ngoại lệ, batch lịch nguyên tử, tham chiếu danh mục. Test dùng SQLite trong RAM; không gọi database ERP. Chưa chạy.
- **Chưa chạy test hoặc kiểm tra chức năng API/browser**, theo yêu cầu “không test vội”. Đã build/recreate backend và áp dụng 010+011 vào local; đã xác nhận log Application startup complete, schema revision 011 và đủ sáu bảng mới. Các thao tác này chỉ xác nhận triển khai/khởi động, không thay thế nghiệm thu nghiệp vụ.

## 5. Chưa hoàn thành và đầu vào giai đoạn sau

- Migration 010 đã áp dụng cùng 011 trên local; backend đã cập nhật. Còn kiểm thử nghiệp vụ khi người dùng cho phép. Không deploy production.
- Cần dữ liệu thực: loại tự động/bán tự động của 3 máy DH, máy ép biên, giới hạn máy, lịch ca/nghỉ, cấu hình ghép/cavity, tỷ trọng, tốc độ/setup/hao hụt. Không tự tạo giá trị nghiệp vụ giả trong danh mục thật.
- Chưa có Gantt, thuật toán xếp lịch, phân máy cắt/ép biên, tốc độ/setup công đoạn sau, liên kết phiên bản vào lần chạy mới, đặt chỗ máy, năng lực theo ngày lịch sử. Không coi các nội dung này đã triển khai.
- Test SQLite nếu được chạy chỉ xác minh logic/API cô lập; không chứng minh FOR UPDATE, ràng buộc MySQL và DDL thực tế. Muốn nghiệm thu phải kiểm tra MySQL local sau migration và kiểm tra giao diện/đặt nhựa dùng hàm chung.

# Giai đoạn 2 — chuẩn bị và phân bổ nhựa

Cập nhật 14/11/2026. **Đầu giai đoạn MySQL là 009; sau khi người dùng yêu cầu build/triển khai, đã sao lưu và áp dụng 010+011 vào local. Backend mới đã khởi động thành công. Chưa nghiệm thu API/giao diện vì người dùng yêu cầu chưa test.** Không coi việc khởi động thành công là đã nghiệm thu nghiệp vụ.

## 1. Schema và migration giai đoạn 2

Đã kiểm tra lại trực tiếp MySQL: có `film_receipts`, `film_movements`, `film_order_lines`, `film_purchase_orders`, `order_lines`, LSX và nhật ký; chưa có bảng allocation hay máy/định mức. Receipt hiện có trạng thái `OK` / `NG`, chưa có dòng cấp/trả tại thời điểm khảo sát. Không dựa số lượng bản ghi này để giới hạn luồng cấp/trả tương lai.

Migration [011_material_allocations.py](backend/alembic/versions/011_material_allocations.py), phụ thuộc 010, tạo **2 bảng**, không ALTER bảng nghiệp vụ cũ:

- `material_allocations`: UUID; FK N_NVL_ID → film_receipts.id, CTĐH → order_lines.id, phiên bản định mức → production_standards.id, người tạo → users.id; `held_kg DECIMAL(24,8)` CHECK >= 0; version, ghi chú, thời gian tạo. Index nguồn nhập và CTĐH phục vụ SUM giữ/tìm CTĐH. Không đặt UNIQUE receipt + CTĐH vì một CTĐH có thể giữ nhiều lần/phiên bản; mỗi row là một khoản giữ có lịch sử riêng.
- `material_allocation_movements`: PK/FK movement_id → film_movements.id; FK allocation_id, issue_id → lần cấp gốc; mode, transfer_id và snapshot nguồn/LSX/số kg. Index allocation, issue, nhóm chuyển. Một giao dịch vật lý thuộc một phân bổ; cấp tách phần tạo giao dịch riêng.

Không tạo sổ tồn mới; không tạo lại bảng cấp/trả. Tái sử dụng `legacy_requests` cho Idempotency-Key, `audit_log` cho audit và `legacy_state` cho khóa tương thích. Không suy đoán/backfill liên kết phân bổ cho lịch sử chưa đủ chứng cứ; các giao dịch lịch sử chưa liên kết vẫn được nhận diện riêng.

**Đã thực hiện theo yêu cầu triển khai local của người dùng**: sao lưu local, build image source mới và chạy `alembic upgrade 011` từ 009. Tổng 6 bảng mới của hai giai đoạn; 010 đã nhập 5 mã máy nguồn như phần trên. Đã xác nhận schema thực tế ở 011 và sáu bảng tồn tại. Không deploy production, không có downgrade tự xóa dữ liệu.

## 2. Backend và nghiệp vụ giai đoạn 2 đã viết

File chính:

- [allocation_models.py](backend/app/modules/materials/inventory/allocation_models.py), [allocation_schemas.py](backend/app/modules/materials/inventory/allocation_schemas.py).
- [allocation_service.py](backend/app/modules/materials/inventory/allocation_service.py): reserve/edit/issue/request_return/confirm_return/sync_return/transfer; `ensure_available` để giai đoạn 3 dùng khi lưu kế hoạch.
- [allocation_api.py](backend/app/modules/materials/inventory/allocation_api.py): API, transaction, quyền và idempotency.
- [readiness_service.py](backend/app/modules/production/readiness_service.py): danh sách CTĐH chuẩn bị lập kế hoạch.
- [stock.py](backend/app/modules/materials/inventory/stock.py): chuyển nguyên `stock_expression` hiện có từ QC sang module tồn kho sở hữu nghiệp vụ; QC import lại cùng hàm, giữ tên/hành vi cũ. Không duy trì thêm công thức SQL tính tồn thứ hai.
- [compatibility/api.py](backend/app/compatibility/api.py): dispatch xác nhận/đồng bộ trả có liên kết về service native; guard sau ghi legacy, trước commit. Luồng cũ chưa có liên kết giữ nguyên.

### Phân bổ và khả dụng

- Giữ ngay khi lưu: `khả dụng = thực nhận − cấp + trả đã được kho nhận − SUM(held_kg)` theo từng phiếu nhập, không theo tổng PO. `held_kg` chỉ là phần **chưa cấp**.
- Nguồn sử dụng phải có phiếu nhận với trạng thái `OK`, vật liệu khớp phiên bản định mức đã chọn. `NG`, vật liệu thiếu/không khớp hoặc phần chưa nhận không được giữ. Không tự đặt thêm workflow phê duyệt IQC; điều kiện trạng thái sử dụng theo chất lượng nhận `OK/NG` hiện hành. QC vẫn không tự sửa kho/trạng thái nhập như thiết kế cũ.
- Mã DN gán vào CTĐH hiện hữu chỉ tạo thông tin nguồn dự kiến. Kg dự kiến = max(kg đặt − tổng đã nhận,0), PO/dòng hủy không được hiển thị. Nhận NG đã là lượng nhận thực tế, không được tính lại thành phần chưa nhận.
- Giữ yêu cầu phiên bản định mức mới nhất active, sản phẩm nằm trong cấu hình, còn phải sản xuất và đơn vị CTĐH khớp snapshot sản phẩm. Không có quy đổi đơn vị đã xác minh thì từ chối giữ thay vì đoán.
- Một nguồn giữ cho nhiều CTĐH, một CTĐH giữ từ nhiều nguồn hoặc nhiều khoản; không tự nhân bản toàn bộ lượng tồn theo từng đơn. Tăng phần giữ phải kiểm tra khả dụng lại. Sửa/release yêu cầu version mới nhất và lý do; held=0 là giải phóng toàn bộ chưa cấp, không xóa dòng/lịch sử cấp.
- Mọi thao tác ghi khóa `legacy_state.id=1 FOR UPDATE` trước, dùng chung với nhập/trả/đặt nhựa cũ; kiểm tra khả dụng còn khóa các receipt theo mã tăng dần. Đọc tổng giữ trong cùng transaction sau khóa; hai người không thể giữ vượt cùng tồn qua các API này. Không dùng khóa trong RAM.
- Khi ghi legacy làm tồn < tổng giữ, hoặc đổi vật liệu nguồn đang được giữ, guard từ chối và rollback. Guard chỉ kích hoạt khi bảng phân bổ đã được cài; không làm hỏng nhận/trả cũ khi migration còn chưa áp dụng.

### Cấp, trả và chuyển

- Cấp phải có phân bổ, version và LSX đúng CTĐH/sản phẩm. Cùng transaction: trừ held, thêm `CẤP NVL` trong film_movements, thêm liên kết và audit. Sổ tồn trừ giao dịch cấp đúng một lần; không trừ tiếp kg đã cấp khỏi held vì held đã giảm trong cùng nghiệp vụ.
- Lần cấp có thể chia nhỏ. Không sửa ngược số kg/nguồn/LSX của lần cấp có truy vết; sửa sai phải theo trả/chuyển có audit.
- Trả nhập kg kiểm đếm + lý do, gắn lần cấp gốc/phân bổ, tạo `TRẢ NVL` chờ kho nhận. Chưa có receiver_id thì không tăng tồn. Kho xác nhận cần NVL_RECEIVE + NVL_STOCK_VIEW, kiểm tra số kg gửi khớp phiếu mới nhất; xác nhận lại không tăng tồn lần hai.
- Đồng bộ trả từ nhật ký giữ quy tắc hiện có: dùng sheet_weight **g/bìa** × (good + ng) / 1000. Giai đoạn 1 lưu kg/bìa, vì vậy không dùng nhầm đơn vị hai nguồn; chưa có chức năng ghi nhật ký mới chuyển đổi tự động. Có nhật ký thiếu trường/số lượng không nguyên/trọng lượng không hợp lệ thì yêu cầu đối soát. Không có nhật ký → chưa xác định, không tự tạo phiếu trả từ toàn bộ kg đã cấp.
- Số dư tại máy chỉ là **ước tính** khi nhật ký đủ dữ liệu, không có cảm biến/kiểm kê liên tục. Khi chưa có nhật ký, số đã cấp chỉ là giới hạn sổ; trả thủ công phải nhập kg đã kiểm đếm và được kho xác nhận thực nhận, không tự cho rằng số dư bằng toàn bộ lượng cấp. Khoản trả chờ không được dùng lại để trả/chuyển lần nữa.
- Chuyển yêu cầu số dư thực tế kiểm đếm, lý do, CTĐH/định mức/LSX đích hợp lệ và đủ quyền kho vì thao tác xác nhận vật lý. Cùng transaction: trả đã nhận từ nguồn cấp cũ + giữ/cấp đích **cùng N_NVL_ID**, cùng transfer_id. Hai giao dịch đối ứng có truy vết, tổng tồn kho và phần giữ cũ không thay đổi sau toàn bộ nghiệp vụ. Lỗi bất kỳ bước nào rollback cả nhóm. Không sinh kiểu “CHUYỂN” mới mà công thức tồn hiện tại không hiểu.
- RPC `confirmFilmReturn` / `syncFilmReturnFromJournal` hiện có được chuyển sang service native khi movement có link; phiếu trả native vẫn xuất hiện trong danh sách trả/tồn hiện có. RPC trên giao dịch cũ không có link đi luồng JS cũ. Không suy diễn LSX từ trường DH_ID của CAT/EB.
- Ghi sử dụng Idempotency-Key 16–64 ký tự; retry cùng key/payload/user trả kết quả cũ, không ghi lần hai; dùng key lại cho nội dung khác → 409. Audit cấp/giữ/sửa/trả/xác nhận/chuyển nằm cùng transaction.

### Danh sách CTĐH và nhu cầu

Đã xác minh từ `orders/legacy_adapter.py`, `legacy_schema.json`, code sửa số đặt trong `orders/legacy/service.js`: produced ↔ So_Luong_Da_Chay, delivered ↔ SL_Da_Giao, remaining_source ↔ SL_Con_Lai, trong đó SL_Con_Lai được tính theo **số đặt − đã giao**. Danh sách mới dùng `max(quantity − produced,0)`, không dùng remaining_source/delivered, không cộng thêm số lượng các công đoạn để tránh đếm trùng.

- Trả khách hàng, PO, CTĐH, sản phẩm, ngày giao dòng (fallback đầu đơn), còn phải sản xuất, các phiên bản định mức lựa chọn.
- Một định mức active mới nhất phù hợp thì tự tính theo bản đó; nhiều cấu hình thì hiển thị cần chọn, không tự chọn máy/cavity. API nhận standard_id để tính cụ thể. Thiếu định mức/khác đơn vị thì nhu cầu null và lý do rõ ràng.
- Bìa = ceil(còn phải sản xuất / cavity riêng của sản phẩm). Kg cơ sở = kg/bìa snapshot × số bìa; kg hao hụt hiển thị riêng; tổng = cơ sở + hao hụt. Không lấy làm tròn bội 10kg của lượng đặt nhựa cho nhu cầu sản xuất. Đây là nhu cầu từng CTĐH chạy riêng theo cấu hình; ghép nhu cầu nhiều CTĐH trong cùng lần chạy thuộc giai đoạn 3, không cộng trùng kg rồi tự chia ở giai đoạn 2.
- Hiển thị tổng giữ, giữ đủ điều kiện/đúng vật liệu, tổng đã cấp, số tại máy ước tính hoặc null/chưa xác định, nguồn chưa nhận dự kiến, thừa/thiếu theo phần giữ và thiếu ước tính sau số tại máy khi có dữ liệu.
- Phân loại `none/partial/enough/unknown`: “Đủ phần giữ” chỉ khi giữ đủ điều kiện >= tổng nhu cầu; số dư máy ước tính không được nâng thành đủ chắc chắn. Dữ liệu cấp lịch sử chưa có link vẫn hiển thị đã cấp qua LSX→CTĐH, số tại máy chưa xác định; không tự gán phân bổ.
- Lọc q (khách/PO/CTĐH/sản phẩm), customer_id, khoảng ngày giao, có/không đang giữ, standard_id, line_id; phân trang SQL 1–100. Nguồn, LSX và truy vết cũng phân trang. Thông tin các CTĐH trên trang được gom đọc theo tập, không query từng CTĐH trong vòng lặp.

### API cho giai đoạn 3

| Method/path | Sử dụng |
|---|---|
| GET `/api/production/preparation` | Danh sách và nhu cầu; q/customer_id/start/end/has_hold/standard_id/line_id/page/size |
| GET `/api/production/materials/sources?order_line_id=...&standard_id=...` | Nguồn thực nhận phù hợp, tồn/giữ/khả dụng; q/page/size |
| GET `/api/production/materials/allocations?order_line_id=...` | Các khoản giữ, version; page/size |
| POST `/api/production/materials/allocations` | receipt_id, order_line_id, standard_id, kg, note |
| PUT `/api/production/materials/allocations/{id}` | version, held_kg, note (bắt buộc lý do) |
| POST `/api/production/materials/allocations/{id}/issue` | version, production_order_id, kg, note |
| GET `/api/production/materials/allocations/{id}/movements` | Truy vết cấp/trả/chuyển, page/size |
| POST `/api/production/materials/issues/{movement_id}/return` | kg kiểm đếm, note → trả chờ |
| POST `/api/production/materials/issues/{movement_id}/sync-return` | Tính trả từ nhật ký hợp lệ |
| POST `/api/production/materials/returns/{movement_id}/confirm` | kg khớp phiếu, quyền nhận/trả kho |
| POST `/api/production/materials/issues/{movement_id}/transfer` | CTĐH/định mức/LSX đích, kg, measured_remaining_kg, note; quyền sản xuất và kho |
| GET `/api/production/materials/production-orders?order_line_id=...` | LSX đã có để chọn khi cấp/chuyển; q/page/size |

Service `ensure_available(db, {receipt_id: Decimal(kg)}, own_allocation_ids=(), order_line_id=None)` cho bước lưu kế hoạch: lấy cùng khóa ERP/receipt và kiểm tra phần khả dụng. Chỉ bù held của đúng CTĐH/receipt khi caller cung cấp allocation ID đã kiểm quyền. Caller phải kiểm quyền, tính vật liệu/cấu hình đúng và **lưu kế hoạch/giữ nhựa trong cùng transaction**, không gọi kiểm tra rồi commit rời trước khi lưu. Service này không tự ghi khoản giữ hoặc thay thế `reserve/issue`.

## 3. Giao diện

[materials.html](frontend/production/materials.html), [materials.js](frontend/production/materials.js); URL `/production/materials`, menu “Kế hoạch sản xuất → Chuẩn bị nhựa”. Tái dùng CSS/navigation hiện có, không tải CTĐH/nguồn khi vừa mở.

Tìm CTĐH → Phân bổ/cấp/trả → chọn định mức (nếu nhiều) → Tính theo định mức đã chọn → Tìm nguồn phù hợp → Giữ ngay. Mỗi khoản giữ có Sửa/giải phóng, Cấp từ phần giữ và Truy vết. Cấp chỉ chọn LSX hiện có; giai đoạn 2 chưa tạo LSX/lần chạy. Phiếu trả nằm trong Truy vết hoặc danh sách trả cũ để kho nhận. Chuyển có kiểm đếm chỉ hiện khi có quyền kho. Thao tác được gửi kèm idempotency key, giữ key khi retry lỗi mạng cùng nội dung.

## 4. Kiểm tra thực tế và trạng thái

- Đã truy vấn chỉ đọc schema/revision, nhóm trạng thái nhận và giao dịch, đối chiếu model/adapter/công thức SQL và JS có sẵn; không ghi database.
- Đã chuẩn bị [test_material_allocations.py](backend/tests/test_material_allocations.py), dùng SQLite RAM: giữ không vượt tồn, retry không lặp, giải phóng/version, cấp giảm giữ đúng một lần, trả chỉ tăng tồn khi xác nhận, phân biệt sản xuất/giao hàng, nhu cầu/hao hụt, nhật ký g→kg, chuyển nguyên tử và rollback lỗi giữa chừng, quyền và guard ghi legacy.
- **Chưa chạy test** theo chỉ dẫn “không test vội”; chưa kiểm tra chức năng browser/API trên source mới. SQLite chưa chạy và dù có chạy cũng không chứng minh khóa FOR UPDATE của MySQL.
- Đã sao lưu trước migration: `backups/napaco-pre-planning-20261114-194018.sql.gz`, kèm SHA-256; file backup quyền 0600, không in nội dung hoặc mật khẩu.
- Đã build image `napaco-local-backend`, chạy migration 009 → 011 thành công, force-recreate riêng backend. MySQL không bị restart/xóa volume; QC worker giữ nguyên.
- Kiểm tra triển khai chỉ đọc: backend Up, log “Application startup complete”; MySQL healthy; revision 011; cả sáu bảng mới tồn tại; 5 máy nguồn giữ nguyên mã; `material_allocations` có 0 dòng. Chưa tạo giao dịch giả trong dữ liệu thật.
- Editor không báo lỗi ở các file backend/giao diện đã kiểm tra; git diff --check không báo lỗi. Đây là rà soát tĩnh, không phải test nghiệp vụ.

## 5. Đầu vào và việc còn lại

- Local đã cập nhật 010+011. Người dùng có thể xem `/production/planning` và `/production/materials`; kiểm thử nghiệp vụ chỉ thực hiện khi được yêu cầu tiếp. Không deploy production.
- Giai đoạn 1 vẫn cần dữ liệu máy/định mức/lịch thực tế. Hiện chưa có LSX thực tế để thử cấp; không tự tạo LSX nghiệp vụ giả trong database thật. Bản test cô lập tạo LSX giả chỉ trong RAM.
- Trước giai đoạn 3 phải chọn phiên bản định mức cụ thể, gom nhu cầu ghép theo cavity từng sản phẩm, kiểm khả dụng và giữ trong cùng transaction khi lưu lần chạy; không tự tiêu hao lượng tại máy chưa đo.
- Chưa có Gantt, lưu lịch chạy, cơ chế cảm biến/tự kiểm kê tại máy, nhập tiêu hao mới hoặc tự liên kết lịch sử cấp/trả chưa có nguồn tin cậy. Không suy diễn số dư thực tế từ toàn bộ lượng đã cấp. Không tự thêm workflow IQC hay thay đổi trạng thái QC/LSX/CTĐH.

# Giai đoạn 3 — lần chạy, nhóm ghép, nhật ký ca và thiết lập giờ nghỉ

## Trạng thái bàn giao

Source đã bổ sung vào module sản xuất hiện có. **Migration 012 mới chuẩn bị, chưa áp dụng; image giai đoạn 3 đã build, chưa recreate container đang chạy, chưa chạy test**. Yêu cầu “không test vội” từ giai đoạn trước tiếp tục được giữ. Các phần local đã lên 011 ở trên là giai đoạn 1–2, không phải xác nhận giai đoạn 3 đã vận hành.

## 1. Đối chiếu và migration cụ thể

Đã kiểm tra trực tiếp MySQL local revision 011: production_orders / production_setups / forming_logs / production_wip đều 0 dòng; cutting_logs và eb_logs mỗi bảng 1 dòng có ID nhưng DH_ID và WIP_ID trống. Source snapshot v004 chỉ lưu DH_ID thành order_ref, chưa có FK hay code chứng minh nguồn. **Không đủ dữ liệu lịch sử để kết luận DH_ID cũ trỏ đâu**. Theo nghiệp vụ người dùng chốt ở giai đoạn 3, API ghi mới bắt buộc DH_ID là ID nhật ký hút tồn tại. Không sửa/đoán/backfill DH_ID các dòng cũ.

Không tạo production_runs hoặc bảng lệnh thứ hai. **ProductionOrder / production_orders.ID_Lenh_SX chính là ID lần chạy** ổn định. Migration [012_production_runs.py](backend/alembic/versions/012_production_runs.py), nối 011:

- ALTER production_orders: thêm standard_id (FK phiên bản định mức), run_snapshot JSON, version mặc định 1, parent_run_id (FK lệnh trước); index Ma_Nhom_Ghep.
- ALTER forming_logs: thêm shift_start / shift_end datetime đầy đủ (hỗ trợ qua ngày), shift_snapshot JSON, version mặc định 1; index LSX + shift_end. Không sửa tên/kiểu cột cũ hoặc snapshot migration v004.
- Tạo production_order_items: PK run_id + order_line_id, sản phẩm, planned_qty, completed_qty, cavity, snapshot. Index CTĐH kiểm tra phần đã bố trí.
- Tạo production_run_materials: PK run_id + allocation_id, planned_kg và issued_kg; khoanh phần giữ đã dùng cho lần chạy, không phải sổ tồn mới.
- Tạo production_shift_items: PK nhật ký hút + CTĐH, sản lượng tốt/NG theo CTĐH.
- Tạo production_shift_materials: PK nhật ký hút + N_NVL_ID; đầu/cấp/trả-tiêu hao/cuối ca, danh sách ID giao dịch đã ghi nhận.
- Tạo production_downstream_items: FK nhật ký hút, CTĐH và một trong CUT_ID / EB_ID (CHECK đúng một loại), stage, input/good/ng, snapshot; index nguồn + CTĐH + công đoạn. Các header nhật ký vẫn ở cutting_logs / eb_logs.

Tổng: thêm cột/index/FK trên **2 bảng hiện có** và **5 bảng chi tiết**. Không đổi trạng thái/mã/dữ liệu lịch sử; không tự tạo LSX/ca nghiệp vụ mẫu. MySQL DDL không rollback nguyên khối; phải sao lưu và áp dụng khi được duyệt. Downgrade tự xóa bị chặn.

Cần duyệt migration 012 sau khi đọc bản cụ thể. Sau khi được duyệt, sao lưu local, build image mới và chạy `alembic upgrade 012`, rồi recreate backend; không chạy migration hoặc đưa image mới vào backend khi database còn thiếu cột. Không production.

## 2. API/service và quy tắc lần chạy

[run_service.py](backend/app/modules/production/run_service.py), [run_schemas.py](backend/app/modules/production/run_schemas.py), [run_models.py](backend/app/modules/production/run_models.py), [run_api.py](backend/app/modules/production/run_api.py).

- Dùng quyền backend PRODUCTION_EDIT, khóa legacy_state và transaction/idempotency/audit hiện có. Version chống ghi đè lệnh và nhật ký. Các giao dịch cấp/trả mới tăng version lần chạy để màn hình ca không chốt dựa dữ liệu cũ.
- ID lệnh/nhật ký mới do người dùng nhập; source không có hàm sinh mã LSX/NKH hiện hành để tái sử dụng, nên không tự áp đặt định dạng mã mới. ID không đổi khi sửa/chuyển máy. Ma_Nhom_Ghep nhập riêng và giữ nguyên qua liên kết lệnh cha khi phù hợp.
- Header cũ giữ CTĐH/sản phẩm đại diện đầu tiên; quantity/good/ng của header là của CTĐH đại diện, không cộng sản lượng khác sản phẩm vào một đơn vị giả. Toàn bộ nhóm nằm ở production_order_items. Thời gian dùng planned_sheets/chu kỳ chung và snapshot.
- Một lệnh có nhiều CTĐH, một CTĐH có thể tách nhiều lệnh trong giới hạn còn phải làm. Kiểm tra `quantity - produced - SUM(planned_qty - completed_qty)` của các lần chạy chưa kết thúc dưới khóa; không dùng remaining_source (còn giao). Nếu gặp lệnh cũ chưa có chi tiết và chưa xác định kết thúc thì yêu cầu đối soát, không bỏ qua để bố trí trùng.
- Người lập kế hoạch phải xác nhận ghép khi có nhiều CTĐH. Cavity theo sản phẩm; cùng sản phẩm trên nhiều CTĐH không nhân cavity. Cùng sản phẩm phải nhập cavity giống nhau. Cấu hình chung chụp định mức, máy, tuyến, vật liệu/khuôn và các điều chỉnh riêng (cavity, bước kéo, giây/chu kỳ, trọng lượng bìa, setup và ghi chú).
- Không cộng thời gian từng CTĐH. Chu kỳ dự kiến chung = **min** ceil(tổng mục tiêu từng sản phẩm / cavity sản phẩm), vì nhóm phải dừng khi sản phẩm đầu tiên đủ. Giờ chạy = chu kỳ chung × giây/chu kỳ / 3600; setup lưu riêng. Đây là thời lượng dự kiến, chưa có thuật toán xếp lịch/Gantt.
- Nhu cầu kg cho đoạn cấu hình đến điểm dừng chung lấy trọng lượng bìa snapshot × chu kỳ chung, hao hụt snapshot riêng. Không dùng công thức lượng đặt nhựa làm tròn 10kg. Nếu điều chỉnh bước kéo mà không nhập trọng lượng riêng, dùng lại hàm trọng lượng bìa của đặt nhựa. Trọng lượng nhập riêng được chụp cùng lý do, không sửa định mức gốc.
- Có thể lưu lần chạy còn thiếu bố trí nhựa (hiển thị material_shortage_kg), để chuẩn bị kế hoạch rồi bổ sung/cấp/chuyển nguồn. Những nguồn đã bố trí phải là phần giữ thực, đúng vật liệu, đúng CTĐH trong nhóm; gọi lại ensure_available, đồng thời kiểm tổng phần bố trí chưa cấp ở các lần chạy khác <= held_kg. Không biến nguồn dự kiến thành tồn dùng được.
- Khi giai đoạn 2 cấp vào lệnh ghép, kiểm CTĐH qua production_order_items và phần nhựa đã bố trí cho run, giảm phần bố trí chưa cấp cùng lúc giảm held. Không được giải phóng held đang ràng buộc vào lần chạy chưa kết thúc. Chuyển từ lần cấp khác sang lần chạy mới tạo liên kết nguồn đích trước khi cấp, cùng transaction giai đoạn 2.
- Có API/màn hình bổ sung hoặc điều chỉnh bố trí nguồn khi đang chạy mà không sửa cấu hình nhóm/máy: planned_kg là tổng đã bố trí kể cả đã cấp, không được giảm dưới issued_kg; phần chưa cấp phải nằm trong held chưa bị lần chạy khác sử dụng. Hỗ trợ cấp thêm qua ca, không giới hạn người dùng vào nguồn đã chọn lúc tạo lệnh.
- Trạng thái chuẩn của lệnh mới: Chưa chạy → Đang chạy → Đã kết thúc. Một máy chỉ có một lần chạy mới ở trạng thái Đang chạy. Sửa/chuyển máy chỉ khi Chưa chạy và chưa có giao dịch cấp/trả; đã cấp cần đối soát vật lý, không âm thầm đổi máy. Đã chạy không đổi cấu hình/máy, phải chốt ca và kết thúc rồi tạo lệnh nối tiếp (parent_run_id).
- Kết thúc giải phóng phần sản lượng chưa hoàn thành để tạo lần chạy mới; phần giữ nhựa vẫn thuộc CTĐH, không tự trả kho hoặc giải phóng giữ. Sau khi kết thúc có thể giải phóng held không còn dùng hoặc chuyển số dư theo giao dịch có kiểm đếm.

## 3. Nhật ký ca, nguồn và sửa lịch sử

- Mỗi ca chính là một forming_logs có ID_Nhat_Ky ổn định; có thời gian bắt đầu/kết thúc đủ ngày, thông số thực tế được chụp riêng. good/ng của forming_logs vẫn là bìa, sheet_weight vẫn **g/bìa** để tương thích nguồn cũ; UI/API ca nhận kg/bìa rồi lưu ×1000. Chi tiết nguồn mới ghi tiêu hao thực tế, không suy lại bằng công thức trọng lượng lý thuyết.
- Chi tiết sản phẩm ghi tốt/NG theo CTĐH. Tổng tốt+NG của mỗi sản phẩm = chu kỳ × cavity sản phẩm, không nhân cavity theo số CTĐH. Không ghi tốt vượt phần CTĐH đã bố trí.
- Chốt ca tăng order_lines.produced bằng sản phẩm tốt đã chạy và cập nhật completed_qty, giữ nguyên delivered/remaining_source/trạng thái đơn hàng. Với quy ước nguồn hiện hành produced là “đã chạy”, không phải “đã giao” hay kết quả QC cuối; nhật ký công đoạn sau không tăng produced lần hai. Sản phẩm chờ cắt/ép biên vẫn truy vết riêng qua tuyến và nhật ký công đoạn.
- Backend lấy đầu ca từ cuối ca trước theo đúng receipt; cấp thêm/trả/chuyển ra từ ID giao dịch của cùng lệnh chưa ghi ở ca trước, tới thời điểm chốt. Không cho nhập lại thủ công giao dịch để cộng/trừ hai lần. Nguồn đã hết 0 và không có giao dịch mới không phải mang một dòng 0 vô hạn.
- **Đầu ca + cấp thêm − trả/chuyển ra − tiêu hao = cuối ca**, từng N_NVL_ID, số không âm. Nhập tiêu hao hoặc cuối ca để tính trường kia; nếu cả hai cùng nhập thì kiểm chính xác. Không chấp nhận có sản lượng nhưng thiếu nguồn/không có tiêu hao.
- Trả chờ kho nhận đã được tách khỏi phần nhựa dùng ở máy từ lúc lập trả; tồn kho chỉ tăng khi kho nhận trả như giai đoạn 2. Xác nhận sau không trừ ra máy lần hai vì cùng ID giao dịch đã được chốt. Không tự sửa số kg trả đã chụp vào ca.
- Cuối ca là số dư được chốt **tại thời điểm ca**, không khẳng định số dư hiện tại giữa ca. Nguồn ghép dùng chung không tự gán toàn bộ số dư nguồn cho từng CTĐH/lần cấp. Giai đoạn 2 vẫn hiển thị chưa xác định nếu không có căn cứ phân riêng theo CTĐH; chi tiết lần chạy có số dư theo nguồn.
- Chốt ca **không tự kết thúc lần chạy**. Khi một sản phẩm đã đủ, can_continue=false và API chặn ca có sản lượng tiếp; người dùng kết thúc cấu hình rồi tạo lần chạy mới cho phần thiếu. Có thể chốt ca 0 chu kỳ để hoàn tất giao dịch trả/chuyển/cân đối trước khi kết thúc.
- Chỉ sửa **ca mới nhất**, khi run còn Đang chạy, version hợp lệ và ca chưa có downstream sử dụng. Sửa tính lại delta sản lượng và số dư trong một transaction. Ca đã có ca sau hoặc đã được cắt/ép biên sử dụng trả 409, yêu cầu đối soát; không cascade ngầm làm sai ca sau. Giai đoạn này không có workflow đảo hàng loạt ca/công đoạn đã xác nhận.

## 4. Cắt/ép biên và WIP

- API mới bắt buộc DH_ID = ID_Nhat_Ky của forming_logs và chụp version nguồn. Một nhật ký hút được sử dụng nhiều lần; tổng đầu vào từng CTĐH/công đoạn không vượt sản lượng tốt nguồn còn lại.
- Bán tự động: cắt lấy tốt từ ca hút; ép biên (nếu sản phẩm có) lấy tốt đã cắt của cùng ca/CTĐH. Tự động: đã cắt liền, không cho tạo cắt lại; ép biên lấy tốt từ ca hút. Mỗi dòng tốt+NG chính là đầu vào công đoạn đó.
- Nguồn/nhóm/sản phẩm/CTĐH chụp trong production_downstream_items. Không suy LSX từ mã CTĐH; truy LSX qua DH_ID→nhật ký hút→LSX. Phụ thuộc QC object_query/resolve_object được bổ sung đúng đường này khi CAT/EB có DH_ID trỏ nhật ký hút, giữ fallback SETUP hiện có.
- Nhật ký công đoạn có nhiều CTĐH dùng chi tiết theo CTĐH làm nguồn sản lượng; good/ng tổng trên header để trống để không cộng lẫn các sản phẩm/đơn vị khác nhau. Nhật ký một CTĐH vẫn lưu good/ng header như trường hiện hữu.
- WIP không bắt buộc. Nếu nhập WIP, phải thuộc đúng nhật ký hút nguồn; không tự tạo WIP cho hàng bình thường. Không sửa dữ liệu DH_ID lịch sử đang trống.

## 5. Thiết lập giờ nghỉ riêng, dùng lại

[calendar_settings.py](backend/app/modules/production/calendar_settings.py) tái sử dụng bảng system_settings, chỉ key PRODUCTION_WEEKLY_DEFAULT_V1; không đọc/ghi cấu hình Google/Drive hoặc các key khác. Không cần bảng thiết lập lịch trùng chức năng.

- Trang riêng `/production/calendar-settings`: nhập một lần ca làm và các khoảng nghỉ trưa/nghỉ tối/nghỉ giữa giờ theo tuần. Có version chống ghi đè; quyền PRODUCTION_EDIT.
- Máy chưa có lịch riêng dùng mặc định chung. Khi thay đổi mặc định, các máy đang kế thừa tự dùng bản mới cho các lần tính khoảng giờ sau này; không sửa snapshot lịch sử ca/lần chạy. Máy có lịch riêng giữ nguyên lịch riêng.
- Trang dữ liệu nền có “Cho máy đã chọn dùng mặc định chung”. PUT calendars thêm inherit_default=true, vẫn kiểm versions từng máy. Lịch riêng được đánh dấu _explicit; đặt lịch riêng rỗng nghĩa là không chạy, khác với kế thừa mặc định. Ngoại lệ theo ngày vẫn ưu tiên cao nhất và có thể chạy xuyên giờ nghỉ.
- Không chụp/nhập lại giờ nghỉ ở từng lần chạy. available_windows của giai đoạn 1 lấy mặc định/lịch riêng rồi áp dụng ngoại lệ. Settings chưa được người dùng lưu thì lịch chung rỗng; không tự áp giờ ăn/nghỉ chưa được chấp thuận.

## 6. API và sử dụng

| Method/path | Chức năng |
|---|---|
| GET/POST `/api/production/runs` | Tìm/phân trang hoặc tạo LSX/lần chạy |
| GET/PUT `/api/production/runs/{id}` | Chi tiết/sửa khi chưa chạy, version |
| POST `/api/production/runs/{id}/start` hoặc `/finish` | version + note |
| POST `/api/production/runs/{id}/materials` | version, allocation_id, planned_kg (gồm đã cấp), note; bổ sung/giải phóng phần bố trí nguồn |
| GET `/api/production/runs/{id}/shift-context` | Số nguồn mang sang/giao dịch chưa ghi nhận, run_version |
| GET/POST `/api/production/runs/{id}/shifts` | Danh sách ca phân trang/chốt ca |
| GET `/api/production/shifts/{id}` | Thông số/sản lượng/cân đối từng nguồn |
| PUT `/api/production/runs/{run_id}/shifts/{shift_id}` | Sửa ca cuối theo version ca và run |
| POST `/api/production/downstream` | Ghi cắt/ép biên, DH_ID là forming_log_id, tốt/NG theo CTĐH |
| GET `/api/production/shifts/{id}/downstream` | Truy vết các lần xử lý nguồn, phân trang |
| GET/PUT `/api/production/calendar-default` | Nạp/lưu version + weekly mặc định chung |

Các thao tác lệnh/ca/công đoạn dùng Idempotency-Key và lưu trong cùng transaction với audit. GET preparation của giai đoạn 2 bổ sung scheduled_remaining_qty / available_to_schedule cho lựa chọn giai đoạn 3. Chọn LSX ở màn hình cấp/trả hỗ trợ thành viên nhóm, không chỉ CTĐH đại diện.

UI: [runs.html](frontend/production/runs.html), [runs.js](frontend/production/runs.js); tạo/sửa lệnh, CTĐH nhóm, nguồn giữ, bắt đầu/kết thúc, ca, cắt/ép biên và truy vết. [calendar-settings.html](frontend/production/calendar-settings.html), [calendar-settings.js](frontend/production/calendar-settings.js) quản lý giờ nghỉ mặc định. Danh mục/lần chạy chỉ tải khi bấm tìm/nạp, các danh sách có phân trang. Chưa có Gantt.

## 7. Kiểm tra và phần chưa hoàn thành

- Đã đọc model/source và truy vấn chỉ đọc schema/record counts/DH_ID thực tế trước khi sửa. Chưa ghi dữ liệu nghiệp vụ.
- Đã chuẩn bị [test_production_runs.py](backend/tests/test_production_runs.py) cho chu kỳ ghép, chống bố trí trùng, khóa phần giữ, cân đối/mang nguồn, ngăn sửa ca cũ, điểm dừng sản phẩm, mặc định lịch và công đoạn lặp. Chỉ là test đã viết; **chưa chạy** theo yêu cầu người dùng.
- Rà soát tĩnh: editor không báo lỗi ở các file mới đã kiểm tra; git diff --check không báo lỗi. Đã build image backend chuẩn bị triển khai; chưa đưa image đó vào container phục vụ ứng dụng vì còn chờ migration 012. Không coi build thành công là test nghiệp vụ/API.
- Chưa áp dụng migration 012; chưa nghiệm thu API/browser giai đoạn 3. Khóa đồng thời MySQL, workflow nhiều ca và cân đối vật lý cần được kiểm thử khi người dùng cho phép.
- Chưa có Gantt, thuật toán xếp lịch hoặc bản chụp kế hoạch. Giai đoạn sau dùng chính ID_Lenh_SX + version + run_snapshot và nguồn ca, không tạo ID run cạnh tranh.
- Không có quy trình tự đảo ca đã có ca sau/downstream; trả 409 để người dùng đối soát thay vì sửa lan ngầm. Lần chạy chưa bắt đầu nhưng đã cấp nhựa không tự chuyển máy, cần xử lý vật lý có truy vết.

## Giai đoạn 4 — bộ tính lịch backend

### Trạng thái bàn giao

Đã bổ sung source bộ tính, API và migration **chưa áp dụng**. Local vẫn ở revision 011; migration 012 (lần chạy/ca của giai đoạn 3) và 013 (bộ tính lịch) phải được duyệt trước khi cập nhật backend đang phục vụ. Build image không đồng nghĩa API đã hoạt động trên database hiện tại. Chưa chạy test, chưa thao tác nghiệp vụ trên dữ liệu thật, chưa production. Không có Gantt kéo thả.

### 1. Schema và migration

[013_production_scheduler.py](backend/alembic/versions/013_production_scheduler.py) nối revision 012, thêm đúng hai bảng:

- `production_schedule_plans`: ID UUID, `version` duy nhất, JSON đầu vào chuẩn hóa và kết quả tính, hash nguồn, người/thời điểm lưu. Chỉ phiên bản lớn nhất là bố trí hiện hành. Các bản cũ là lịch sử, không giữ máy/nhựa thêm lần nữa.
- `production_run_stops`: ID do client cấp, FK vào `production_orders.ID_Lenh_SX`, phiên bản, thời điểm, thời lượng có thể chưa biết, cờ giữ/giải phóng máy, bật/tắt, ghi chú. Index `(run_id, enabled)` phục vụ đối chiếu dừng của lần chạy.

Không thêm model lệnh sản xuất khác, không tự chuyển đổi nhật ký lịch sử. FK ORM dùng khóa Python `production_orders.id`; migration dùng tên cột vật lý `ID_Lenh_SX`. Migration không có downgrade xóa lịch sử tự động. Không có DML sửa/xóa dữ liệu nghiệp vụ trong migration 013.

**Cần duyệt cụ thể cả [012](backend/alembic/versions/012_production_runs.py) và [013](backend/alembic/versions/013_production_scheduler.py)**. Sau duyệt: sao lưu local, áp dụng `alembic upgrade 013` (đi qua 012), rồi recreate riêng backend. Chưa thực hiện các bước này cho giai đoạn 3–4; không chạy `down -v`.

### 2. Service, API và quy tắc

File chính:

- [schedule_engine.py](backend/app/modules/production/schedule_engine.py): bộ tính thuần không I/O. `requirements()` là công thức chung của kiểm tra nhựa và xếp lịch; `calculate()` trả cùng cấu trúc cho preview và lưu.
- [schedule_service.py](backend/app/modules/production/schedule_service.py): ghép dữ liệu LSX, thành viên nhóm, nguồn nhập/phân bổ, nhật ký ca/cắt/ép biên và lịch máy hiện có; kiểm tra trạng thái cuối cùng sau chen/tách/chuyển.
- [schedule_schemas.py](backend/app/modules/production/schedule_schemas.py): contract đầu vào, giới hạn kích thước, đơn vị, múi giờ và các thao tác mâu thuẫn.
- [schedule_api.py](backend/app/modules/production/schedule_api.py): kiểm tra quyền `PRODUCTION_EDIT` ở backend, chặn 503 khi thiếu migration.
- [run_service.py](backend/app/modules/production/run_service.py): tái sử dụng kiểm tra tạo/sửa/kết thúc lần chạy qua chế độ preview chỉ đọc; thêm đối chiếu dừng máy và chồng ca thực tế.
- [allocation_service.py](backend/app/modules/materials/inventory/allocation_service.py): `ensure_available(..., lock=False)` dành riêng tính thử; lưu dùng khóa giao dịch, không tạo phép tính tồn khác.

API:

| API | Ý nghĩa |
| --- | --- |
| `POST /api/production/schedule/preview` | Chỉ SELECT, không ghi tạm rồi rollback. Trả `preview_hash`, `base_version`, cảnh báo và `result`. |
| `POST /api/production/schedule/save` | Cùng input cộng `preview_hash`, `confirmations`; bắt buộc `Idempotency-Key`. Kiểm tra lại toàn bộ, thực hiện thay đổi LSX/dừng và lưu snapshot trong một transaction. |
| `GET /api/production/schedule/latest` | Bản đã lưu mới nhất; chưa có trả version 0. Đây là snapshot, không tự biến thành dự báo mới khi nhật ký thay đổi. |
| `GET /api/production/schedule/history?page=1&size=25` | Danh sách metadata có phân trang, tối đa 100 dòng/trang. |
| `GET /api/production/schedule/history/{id}` | Mở bản lịch sử cố định. |

Lưu dùng transaction/idempotency/audit và khóa ERP hiện có, khóa các lần chạy, CTĐH, máy, phân bổ và nguồn nhập liên quan. So sánh `base_version` và hash tính lại gồm cấu hình, phiên bản ca, số dư nguồn, lịch mặc định/ngoại lệ, dừng, trạng thái máy và đầu vào. Nguồn thay đổi trả 409, không ghi một phần. Thiếu xác nhận cảnh báo cũng trả 409 và rollback. Không tin kết quả thời gian/nhu cầu từ frontend.

Quy tắc thời gian và số lượng:

- Một chu kỳ = một bìa; sản phẩm = bìa × cavity của sản phẩm. Nhiều CTĐH cùng sản phẩm dùng chung cavity, chia sản lượng theo `line_order`.
- Chu kỳ mỗi sản phẩm = ceil(phần còn được bố trí / cavity). Chạy ghép dừng ở sản phẩm đủ trước: số chu kỳ chung là **min** các kết quả; không cộng thời gian từng CTĐH. Trả `rounding_surplus_qty` và `requires_next_run_qty` riêng; phần thiếu cần lần chạy/cấu hình mới.
- Chạy thuần = chu kỳ × giây/chu kỳ. Setup tính một lần khi chưa có thực tế, không cộng lại vào phần chạy tiếp. `base_kg` và `waste_kg` tách riêng; hao hụt giai đoạn 1 là phần dự phòng vật liệu theo %, không tự diễn giải thành tỷ lệ NG để tăng chu kỳ. Dự báo công đoạn giả định chưa có NG tương lai và nêu rõ trong kết quả.
- Dùng lịch chung và lịch riêng máy của giai đoạn 1–3; ngoại lệ ngày thay thế lịch tuần trong đúng máy/ngày, vì vậy có thể chạy xuyên nghỉ đúng phạm vi. Thời gian chặt qua các khoảng nghỉ/dừng và công việc đã chiếm máy; dùng khoảng nửa mở `[start,end)`.
- Cùng máy và cùng CTĐH ở công đoạn định hình không được chạy đồng thời, kể cả hai máy khác nhau. Thứ tự đầu vào là ưu tiên hàng đợi máy; các phần tương lai được tính lại, nhật ký thực tế được ghim nguyên vẹn.
- Thiếu/không hợp lệ tốc độ, cavity, setup, trọng lượng bìa, hao hụt, đơn vị hoặc công đoạn sau trả lỗi nghiệp vụ, không thay bằng 0. Không đủ giờ trong kỳ trả lỗi để người dùng mở rộng khoảng ngày.
- Đối chiếu cả nhật ký hiện hành và nhật ký cũ trên máy trong kỳ. Nhật ký cũ thiếu giờ cần đối soát, không giả định máy trống.

Nhựa và sản lượng:

- Kiểm tra tổng phần còn bố trí của tất cả lần chạy còn hiệu lực + `OrderLine.produced` không vượt `OrderLine.quantity`; không lấy số còn phải giao.
- Kiểm tra tổng claim của nhiều lần chạy trên từng phân bổ, bao gồm các lần mới tạo trong cùng thao tác tách/chen. Cấp rồi chỉ tính phần giữ chưa cấp và số dư theo nguồn ở máy, không cộng lại cả phần đã cấp vào tồn khả dụng.
- Số dư theo từng nguồn = số chốt ca cuối + cấp/trả chưa vào ca. Không có ca chốt mà lần chạy đang chạy có nhựa đã cấp thì từ chối kết luận đủ nhựa. Lần chạy đang chạy có số chốt cũ trả cảnh báo phải đối chiếu và xác nhận; kết quả nêu `machine_balance_as_of` và mức chắc chắn, không khẳng định đó là số đo hiện tại.
- Kiểm tra số dư âm từng nguồn, không chỉ tổng kg. Dữ liệu cấp/trả/tiêu hao thật tiếp tục thuộc service giai đoạn 2–3.

Thao tác:

- `order`: thứ tự ưu tiên mới; các lần đã có trong bản hiện hành mà không nhắc lại vẫn giữ trong hàng đợi, không bị rơi khỏi lịch.
- `jobs`: policy theo lần chạy (`ready_at`, `line_order`, `stages`, `waiting`). `waiting=true` giữ phần còn lại ở chờ xếp.
- `changes`: mỗi phần tử chứa `config` theo contract `RunInput` giai đoạn 3. Sửa chỉ lần chưa chạy, có `version`; lần mới dùng ID mới. `split_from` bắt buộc CTĐH thuộc nhóm gốc, bố trí gốc phải được sửa/kết thúc cùng transaction.
- `end_runs`: ID/version/ghi chú. Lần đã chạy phải chốt ca và hết giao dịch cấp/trả chưa chốt trước khi kết thúc; giữ nguyên thực tế. Lần tiếp theo dùng `parent_run_id` và cấu hình phù hợp.
- `moves`: ID/version/máy đích/ghi chú. Chỉ lần chưa chạy và chưa cấp/trả; tái kiểm tra loại máy/kích thước/định mức. Preview trả mã `CONFIRM_MOVE:...`; save phải gửi mã đó trong `confirmations`. Cùng ID chỉ có một bố trí trong bản hiện hành, thay máy gỡ bố trí cũ tương ứng. Các bản cũ chỉ là lịch sử.
- `unschedule`: gỡ lần chưa chạy hoặc đã kết thúc khỏi hàng đợi hiện hành, không xóa lệnh, nhật ký hay claim sản lượng. Lần đang chạy phải chốt/kết thúc hoặc giải phóng máy.
- `stops`: ID/phiên bản, thời điểm có múi giờ, `duration_seconds`, `hold_machine`, `enabled`, ghi chú. Biết thời lượng + giữ máy: trừ khoảng dừng rồi tính lại. Chưa biết + giữ máy: phần sau trả `unknown` và mốc null. Giải phóng máy: phần còn lại `released_waiting`, cho đơn khác dùng máy. Muốn xếp lại phải kết thúc/tắt dừng và bỏ `waiting`. Không sửa dừng nằm trong phần đã chốt; không chốt ca có sản lượng chồng khoảng dừng còn hiệu lực.

Bàn giao công đoạn:

- Mỗi policy `stages` chỉ rõ CTĐH, `cutting`/`edge`, `unit`, tốc độ giây/đơn vị, setup phút, khoảng chờ phút và máy tùy chọn.
- `mode=all` đợi toàn bộ phần chưa xử lý; `mode=rolling` dùng `handoff_quantity` đều hoặc `handoff_quantities` từng lần (tổng phải khớp). Không suy đoán quy đổi giữa bìa và sản phẩm; bàn giao dùng đúng đơn vị của CTĐH, cavity dùng để quy đổi bìa ở định hình.
- Cộng trừ nguồn thực tế theo ID ca hút và CTĐH, không dùng vượt ca nguồn; số đã xử lý thực tế không được dùng nguồn dự kiến tương lai. Bàn giao dự kiến không tiêu hao WIP thực tế và không tạo nhật ký.
- Có máy: `scheduled`; chưa chọn máy: `estimated`, không giữ tài nguyên máy. Thời gian chưa xác định: `unknown`. Có thể chọn giữ máy trong khoảng chờ bằng `hold_machine_while_waiting`.
- Trả các mốc từng lô, `first_output_at`, `first_planned_finished_at`, `all_finished_at` theo CTĐH và PO. Đủ đơn xét mọi CTĐH của PO, không chỉ dòng đang xếp; thiếu sản lượng hoặc thời điểm chưa xác định không trả nhầm mốc đủ toàn bộ.

### 3. Cách gọi dành cho giai đoạn 5

1. Đọc `/latest` để lấy version và policy đã lưu; lấy dữ liệu lần chạy, định mức, chuẩn bị nhựa qua API giai đoạn trước.
2. Gửi preview. Ví dụ tối thiểu cho tuyến tự động không ép biên:

```json
{
  "base_version": 0,
  "start": "2026-11-16T08:00:00+07:00",
  "end": "2026-11-22T23:59:00+07:00",
  "order": ["ID_LSX_CO_THAT"],
  "jobs": [{"run_id": "ID_LSX_CO_THAT", "line_order": [], "stages": []}]
}
```

ID chỉ minh họa, phải thay bằng LSX giai đoạn 3 và nguồn nhựa thực đủ. Tuyến cần cắt/ép biên phải gửi policy từng công đoạn, không để mặc định tốc độ 0.

3. Render trực tiếp `result.jobs[].setup_segments/forming_segments/stages`, sản lượng dư/thiếu, `result.lines/orders` và cảnh báo. Các timestamp có múi giờ. Không viết công thức tại frontend.
4. Gửi cùng input tới `/save`, thêm `preview_hash` từ preview, `confirmations` là các mã cảnh báo đã được người dùng xác nhận và header `Idempotency-Key` mới. Lỗi 409 phải tính thử lại/hiển thị yêu cầu xác nhận, không tự xác nhận chuyển máy.
5. Lấy `result` trả từ save làm bản chính thức; preview không tạo giữ máy và không thay đổi phân bổ. Lưu sẽ kiểm tra lại nguồn hiện tại và thay thế bố trí hiện hành bằng bản mới.

Giới hạn bảo vệ hiện tại: tối đa 92 ngày tính, 100 máy theo calendar service, 200 lần chạy trong một bản, 1000 lô bàn giao mỗi công đoạn và tối đa 1000 LSX native trong phạm vi nạp. Vượt giới hạn trả lỗi rõ ràng; không phân trang ngầm rồi bỏ công việc đang chiếm máy. Snapshot cũ không tự cập nhật khi có nhật ký mới; giai đoạn 5 cần gọi tính lại trước khi lưu.

### 4. Kiểm tra thực tế

- Đã đọc source/schema và bàn giao giai đoạn trước; database hiện tại revision 011, chưa có bảng giai đoạn 3–4.
- Đã build image backend local; đã kiểm tra cú pháp trong image và import/router/liên kết ORM bằng cấu hình giả, network tắt, không kết nối MySQL. Lần compile đầu không ghi được cache vào thư mục source trong image; đã đổi cache sang `/tmp` và kiểm tra lại thành công, không sửa quyền source.
- Editor diagnostics của các file bộ tính đã kiểm tra không báo lỗi. `git diff --check` không báo lỗi tại lần rà soát.
- [test_production_schedule.py](backend/tests/test_production_schedule.py) chuẩn bị các ca chạy ghép/dư/thiếu, nghỉ, dừng biết/chưa biết thời lượng, giải phóng máy, chống cùng CTĐH hai máy, cuốn chiếu/ước tính, chống dùng nguồn tương lai, thiếu thông số và đổi thứ tự giữ thực tế. **Chưa chạy**, theo yêu cầu không test vội. Không coi đó là bằng chứng nghiệp vụ đã qua test.

### 5. Chưa hoàn thành và đầu vào tiếp theo

- Chưa áp dụng 012/013, chưa recreate backend đang chạy, chưa kiểm thử API/transaction đồng thời trên MySQL hoặc nghiệm thu UI; cần duyệt migration và cho phép test sau.
- Giai đoạn 5 xây giao diện hiển thị/chỉnh thứ tự, hộp xác nhận chuyển máy, cấu hình bàn giao/dừng và gọi API ở trên. Chưa có Gantt kéo thả trong phạm vi này.
- Cần dữ liệu thật đã đối soát đơn vị, cavity/tốc độ/setup, phân bổ đủ, số dư ca đúng nguồn và giờ nhật ký cũ. Không tự thêm số liệu mẫu vào database thật.
- Cần targeted tests trước nghiệm thu: cạnh tranh giữ nhựa/sản lượng khi save, rollback toàn bộ khi tách/chuyển thất bại, preview không ghi, xác nhận chuyển máy, dữ liệu thay đổi sau preview, nhiều ca và nhiều lần bàn giao trên cùng nguồn.

Ghi chú tích hợp cuối giai đoạn 4:

- Tách CTĐH sang ID mới/máy khác từ lần chưa chạy cũng trả `CONFIRM_TRANSFER_PART:...`; không thể tránh hộp xác nhận bằng thao tác kết thúc bố trí cũ rồi tạo mới trong cùng yêu cầu.
- API sửa lần chạy giai đoạn 3 từ chối sửa cấu hình lần đã nằm trong bản lịch hiện hành; phải qua preview/save của bộ tính để giữ xác nhận và thay thế bố trí nguyên tử. Sửa lần chạy cần version hiện tại.
- Kết quả trả thêm `working_windows` và `stops` (kèm version, bật/tắt, giữ máy) để giai đoạn 5 hiển thị đúng lịch nghỉ/dừng và chỉnh bằng phiên bản thật. Lịch sử snapshot giữ các thông tin này; audit lưu các dừng đã thay đổi và ID lần chạy liên quan.
- Image cuối đã kiểm tra import, ORM và sinh OpenAPI 5 đường dẫn của router lịch; đó là kiểm tra đóng gói, chưa gọi endpoint nghiệp vụ và chưa chạy test.

## Giai đoạn 5 — giao diện lập kế hoạch và Gantt

### Trạng thái và schema

Đã bổ sung source giao diện và các API projection phục vụ màn hình. **Không có migration mới cho giai đoạn 5.** Migration 012/013 của giai đoạn 3–4 vẫn chưa được duyệt/applied; local trước lần bàn giao này còn revision 011. Vì vậy chưa coi luồng API/Gantt đã vận hành trên database local và chưa recreate backend phục vụ bằng source mới. Không production.

Không thêm bảng, không tạo lệnh sản xuất khác, không thêm dependency hoặc thư viện Gantt; dùng DOM/CSS/JavaScript và HTML drag-and-drop có sẵn. Không phát sinh điều kiện giấy phép thư viện mới.

### File chính và API

- [schedule.html](frontend/production/schedule.html), [schedule.css](frontend/production/schedule.css), [schedule.js](frontend/production/schedule.js): màn hình `/production/schedule`, chung một bản nháp/kết quả cho hai khung nhìn.
- [be-dan.html](frontend/production/be-dan.html): `/production/be-dan`, chỉ thông báo **Chưa triển khai**, không có nút hay API tạo/lưu luồng giả.
- [navigation.js](frontend/shared/navigation.js): menu **Kế hoạch → Định Hình**, **Kế hoạch → Bế Dán · Chưa triển khai**; giữ các màn hình dữ liệu nền, nghỉ mặc định, phân bổ và nhật ký.
- [schedule_view.py](backend/app/modules/production/schedule_view.py): projection và dữ liệu editor, tái sử dụng model hiện có; không tính lại thời gian/nhu cầu.
- [schedule_api.py](backend/app/modules/production/schedule_api.py): thêm `GET /api/production/schedule/view` và `GET /api/production/schedule/editor/{run_id}`; preview/save nhận các query tùy chọn `view_start`, `view_end`, `machine_id`, `customer_id`, `q` để trả kết quả trong phạm vi xem. Contract cũ không truyền query vẫn giữ kết quả đầy đủ như giai đoạn 4.
- [planning_api.py](backend/app/modules/production/planning_api.py): hai route trang và thêm reference khách hàng phân trang dưới cùng quyền sản xuất hiện có.
- [schedule_engine.py](backend/app/modules/production/schedule_engine.py): bổ sung metadata `machine_kind`, `planned_items` vào kết quả; công thức vẫn ở backend.
- [schedule_service.py](backend/app/modules/production/schedule_service.py): trả cảnh báo chuyển phần công đoạn sau giữa máy, bổ sung metadata CTĐH/công đoạn cho các thanh thực tế. Metadata này không biến cắt/ép biên thành khóa tài nguyên định hình của CTĐH, vẫn cho cuốn chiếu đúng.

Các API/trang dùng quyền `PRODUCTION_EDIT` tại backend. Khi thiếu migration trả 503 rõ ràng; frontend không thay bằng dữ liệu giả. Save scoped projection nằm **trong transaction** trước commit; lỗi tạo projection cũng rollback toàn bộ thay đổi. Nội dung scope tham gia checksum idempotency cho save có scope.

### Nghiệp vụ giao diện

1. Chọn từ/đến ngày, mã máy tùy chọn, khách hàng qua picker và từ khóa CTĐH/PO/sản phẩm; bấm **Tải phạm vi**. Không tự tải sản xuất khi mở trang hay khi gõ lọc. Danh sách chờ có tìm kiếm riêng, lọc giữ nhựa và phân trang 20 CTĐH. Mốc ngày của danh sách chờ là **ngày giao**, mốc Gantt là thời gian máy.
2. Trạng thái nhựa, kg giữ đủ điều kiện, kg tại máy chưa xác định/ước tính, nhu cầu cơ sở/hao hụt và nguồn chưa nhận lấy từ API chuẩn bị nhựa. Không dùng tổng đã cấp làm số dư tại máy và không tự tính nhu cầu ở JavaScript.
3. Chọn một hoặc nhiều CTĐH, **Tạo lần chạy / Ghép CTĐH**. Nhập ID ổn định, chọn định mức có phân trang, thông số và máy. Cavity đi theo sản phẩm của định mức, người dùng được điều chỉnh theo contract giai đoạn 3; khả năng ghép phải xác nhận. Chọn số kg từ từng phân bổ đã giữ; không tự cấp/giữ thêm khi tạo bản nháp.
4. Chọn chờ toàn bộ/cuốn chiếu ở từng CTĐH/công đoạn sau, lượng đều hoặc danh sách từng lần, đơn vị rõ ràng, khoảng chờ, setup, tốc độ và máy. Không chọn máy nghĩa là ước tính. Không suy diễn tốc độ còn thiếu thành 0. Có picker máy riêng để chọn máy ngoài hàng đang lọc.
5. **Đưa vào bản nháp → Tính thử → xem cảnh báo → Lưu kế hoạch**. Kéo thả, đổi máy và sửa số liệu không gọi API ghi. Save gửi lại chính payload/hash đã tính thử; cảnh báo backend phải được người dùng đánh dấu xác nhận từng dòng. Hủy thay đổi trở lại bản đã tải; thoát trang có nhắc khi còn bản nháp.
6. Chuyển máy cả nhóm qua kéo thả hoặc editor; tách CTĐH cần ID mới/cấu hình mới và xác nhận. Nhóm chưa chạy được giảm bố trí cũ tương ứng; nếu tách toàn bộ thì kết thúc bố trí cũ. Nhóm đã chạy phải chốt ca, kết thúc lần cũ trong transaction; thực tế không thay đổi, các CTĐH khác chưa bố trí trở về chờ. Backend quyết định tính hợp lệ cuối cùng.
7. Dừng biết/chưa biết thời lượng, giữ/giải phóng máy và kết thúc dừng được đưa vào bản nháp, kiểm tra lại bằng bộ tính. ID/version khoảng dừng đọc từ kết quả server. Việc đổi phút sang giây trong form chỉ là quy đổi đơn vị nhập, không phải công thức xếp lịch.
8. Lỗi nguồn/version 409 không tự ghi đè hoặc tự retry với dữ liệu mới. Giữ bản nháp, hiển thị vùng xung đột, cho tải JSON để đối chiếu và tải lại bản mới (có xác nhận bỏ nháp). Lỗi nghiệp vụ khác hiển thị nội dung backend; không tự kết luận thanh kéo là hợp lệ.

### Hai khung nhìn

**Theo máy:** nhóm máy tự động, bán tự động, cắt và ép biên; mỗi lần chạy/nhóm trên một máy là một thanh, các đoạn setup/chạy và khoảng gián đoạn giữ đúng timestamp server. Công đoạn sau có thể nhiều lô trong cùng thanh nhóm. Bấm thanh để mở editor, có thao tác ưu tiên lên/xuống ngoài drag-and-drop. Đổi thứ tự là đổi ưu tiên lần chạy của bộ tính chung, không tạo một công thức/thứ tự tài nguyên riêng ở frontend.

**Theo CTĐH:** dùng cùng trục thời gian/kết quả, thể hiện định hình, cắt, ép biên và các lô cuốn chiếu; máy tự động ghi “Định hình + Cắt liền”. Thanh có nhãn máy, CTĐH/sản phẩm, sản lượng bố trí và giờ. Ước tính dùng nét đứt/nhãn, khác phần đã xếp máy. Mốc thành phẩm đầu/đủ CTĐH/đủ PO lấy trực tiếp `result.lines/orders`; chưa xác định thì không vẽ mốc chắc chắn. Khung CTĐH phân trang 25 CTĐH để giới hạn DOM.

Phần thực tế có khóa, không draggable. Phần còn lại của lần đang chạy không cho chuyển cấu hình định hình trực tiếp; dùng kết thúc/tạo tiếp theo. Các đoạn công đoạn sau chưa thực hiện được sửa policy, nhật ký đã chốt giữ nguyên.

Lịch nghỉ là nền xám ngoài `working_windows`; ngoại lệ được phép chạy có nền xanh. Dừng không rõ thời lượng + giữ máy tô xám vùng bị ảnh hưởng đến hết khoảng xem, ghi “Chưa xác định”, không tự tạo giờ kết thúc. Kết quả tính thử cũ được ghi rõ nếu bản nháp tiếp tục thay đổi, không hiển thị nhầm là bản đã lưu mới.

### Phạm vi dữ liệu và kiểm tra

- Projection chỉ trả công việc giao với khoảng xem/bộ lọc; với nhóm ghép trúng một CTĐH thì giữ đủ thành viên để không che tác động lên nhóm. Metadata labels/version lấy theo ID trong bản kế hoạch, không nạp toàn bộ catalog đơn hàng.
- Gửi queue ID đầy đủ (tối đa 200) để reorder giữ vị trí các ID ngoài khung lọc. Không gửi toàn bộ snapshot ngoài khoảng xem về trình duyệt. Hiển thị số lần chạy ngoài khung lọc vẫn được backend kiểm tra.
- Kỳ tính toàn bản kế hoạch tách khỏi khoảng xem. Đổi bộ lọc không tự đổi kỳ; nút **Đổi kỳ tính** cảnh báo tác động lên toàn bộ phần tương lai. Bộ tính giai đoạn 4 vẫn kiểm tra các tài nguyên/claim liên quan ngoài phạm vi hiển thị.
- Giới hạn projection: 92 ngày, 100 máy, 500 CTĐH hiển thị (gồm đủ nhóm); editor tối đa 500 phân bổ. Vượt giới hạn trả lỗi yêu cầu thu hẹp, không âm thầm bỏ dữ liệu đang chiếm máy.
- Đã rà soát diff và editor diagnostics, Node `--check` cho JavaScript mới; chưa chạy test nghiệp vụ/browser theo yêu cầu “không test vội”. Build/kiểm tra đóng gói được ghi nhận ở phần chốt bên dưới; không coi các kiểm tra tĩnh là nghiệm thu kéo thả hay transaction MySQL.

### Chưa hoàn thành / bước tiếp theo

- Cần duyệt và áp dụng migration 012/013 trước khi recreate backend mới. Chưa có nghiệm thu API/Gantt trên dữ liệu local sau migration; không báo màn hình đã vận hành hoàn chỉnh chỉ vì source/build đã xong.
- Cần cho phép targeted tests/browser ở lượt sau: tạo nhóm từ phân bổ thật, hủy nháp không ghi, kéo đổi thứ tự/chuyển máy có xác nhận, tách nhóm nguyên tử, xung đột hai người, ca thực tế khóa, ngoại lệ xuyên nghỉ, dừng chưa biết/giải phóng máy và mốc thành phẩm cuốn chiếu.
- Chuyển/trả nhựa thực tế giữa các lần chạy tiếp tục phải qua nghiệp vụ cấp/trả/chuyển giai đoạn 2–3 có truy vết; Gantt không tự tạo giao dịch kho để làm cho lịch hợp lệ.
- Bế Dán vẫn chưa triển khai; không có lịch giả, dữ liệu mẫu hay API ghi cho mục này.

Chốt kiểm tra giai đoạn 5 (14/11/2026):

- Truy vấn chỉ đọc trên MySQL thực xác nhận `alembic_revision = 011`; trong bốn bảng đối chiếu `production_orders`, `production_order_items`, `production_schedule_plans`, `production_run_stops` hiện chỉ có `production_orders`. Không áp dụng migration hoặc tạo dữ liệu nghiệp vụ trong lượt này.
- Backend image cuối build thành công: `sha256:5998b3b834f0a8ef7804a87e79ca17b9ddc09e340c9075c6f8c5a0d7a5f0acd2`. Không recreate container đang phục vụ.
- Cú pháp Python/import/ORM và sinh OpenAPI của router lịch + dữ liệu nền thành công (21 đường dẫn). Cấu hình giả, network tắt, không kết nối DB trong kiểm tra đóng gói.
- Node kiểm tra cú pháp JavaScript thành công; kiểm tra tĩnh HTML/JS xác nhận 81 ID markup không trùng và các tham chiếu literal đều có đích (kể cả ID tạo động). Editor không báo lỗi ở các file đã kiểm tra. `git diff --check` không báo lỗi tại lần rà soát.
- Thêm xem số chu kỳ, chạy thuần/setup, kg cơ sở/hao hụt, dư làm tròn và phần cần lần chạy mới bằng chính dữ liệu backend; bảng chi tiết chỉ dựng khi mở để hạn chế DOM.
- **Chưa chạy test tự động, chưa mở trình duyệt nghiệm thu hoặc thử ghi API.** Không coi build/cú pháp/OpenAPI là chứng minh luồng nghiệp vụ hoặc drag-and-drop đã qua test thực tế.

## Giai đoạn 6 — chốt theo ngày và đối chiếu thực tế

### Trạng thái

Đã bổ sung source vào màn hình hiện có, không tạo module lệnh hoặc Gantt khác. **Migration 014 mới chuẩn bị, chưa áp dụng. Local đã kiểm tra chỉ đọc vẫn revision 011**, chưa có schema 012–014; không recreate backend đang phục vụ và không production. Chưa chạy test nghiệp vụ/browser theo yêu cầu trước đó. Không coi source/build là chứng minh quy trình đã vận hành trên MySQL.

### 1. Schema, migration và phạm vi kế hoạch

[014_daily_production_plans.py](backend/alembic/versions/014_daily_production_plans.py), nối 013:

- Thêm cột JSON nullable `context` vào **production_schedule_plans hiện có** để chụp dữ liệu nền; không backfill bằng dữ liệu hiện tại rồi giả là lịch sử cũ.
- Thêm `production_schedule_days`, PK `(day, scope)`, version, FK `initial_plan_id`/`update_plan_id` tới snapshot đã có, người/giờ chốt, người/giờ cập nhật. `scope` hiện là `forming`, tương ứng phạm vi module Định Hình với toàn bộ hàng đợi/kỳ tính; bộ lọc máy/khách hàng/CTĐH chỉ là phạm vi xem, không tạo kế hoạch cạnh tranh.
- Bản cập nhật là một con trỏ được thay thế trong transaction. Snapshot nguồn vẫn bất biến và giữ trong lịch sử, không sinh thêm claim nhựa hoặc sản lượng. Bản đầu ngày là con trỏ riêng, không có API ghi đè sau khi chốt.
- Không thêm timestamp nhật ký khác trùng audit; dùng `audit_log.created_at` hiện có cho giờ ghi nhận/cập nhật. Ngày giờ sản xuất vẫn từ nhật ký. Không đổi cột nhật ký để lưu trường chạy thuần: tận dụng JSON snapshot sẵn có.
- Downgrade tự xóa lịch sử bị chặn. Không có DML xóa/sửa dữ liệu cũ trong 014.

**Cần duyệt 012, 013 và 014 trước khi áp dụng vào local**. Migration 014 phải chạy sau schema lần chạy/ca và kế hoạch ở hai migration trước. Sau duyệt: sao lưu local, nâng đến 014, rồi mới cập nhật container backend. Chưa thực hiện các bước ghi DB/triển khai này.

### 2. Snapshot và thao tác theo ngày

File chính:

- [schedule_daily.py](backend/app/modules/production/schedule_daily.py): điều hành theo ngày Việt Nam, phiên bản ngày, đọc nháp chuyển ngày, chốt chủ động và cập nhật con trỏ.
- [schedule_service.py](backend/app/modules/production/schedule_service.py): chụp toàn bộ context sau khi kiểm tra/lưu bằng bộ tính chung; cập nhật con trỏ ngày trong cùng transaction.
- [schedule_models.py](backend/app/modules/production/schedule_models.py), [schedule_schemas.py](backend/app/modules/production/schedule_schemas.py): model và contract bổ sung.
- [schedule_view.py](backend/app/modules/production/schedule_view.py): projection từ context đã chụp; chế độ lịch sử không nạp nhãn/lịch hiện tại để thay lịch sử.

`SchedulePlan.context` giữ đầy đủ run ID/phiên bản, parent/group, thành phần và sản lượng nhóm/cavity, frozen định mức và thông số điều chỉnh, liên kết nguồn, metadata CTĐH/PO/khách hàng/sản phẩm/đơn vị; thông tin máy, lịch máy/lịch mặc định/ngoại lệ theo ngày trong **toàn kỳ tính**. `request/result` giữ thứ tự, khoảng tính, thời gian, setup/chạy/ước tính, dừng, policy/lượng bàn giao từng lần và các mốc. Không chỉ chụp phần Gantt đang lọc/đang nhìn trên màn hình.

Luồng:

- Lưu kế hoạch vẫn qua preview/hash/transaction của giai đoạn 4–5. Lưu nhiều lần trong ngày thay `update_plan_id`, tăng version ngày; không đổi `initial_plan_id`.
- Ngày mới đọc bản cập nhật gần nhất làm nháp. GET không INSERT ngày mới, không chốt, không thêm LSX/giữ nhựa. Người dùng có thể tiếp tục sửa/lưu hoặc chủ động chốt nguyên bản nháp đã lưu từ ngày trước nếu không thay đổi; thao tác chốt mới tạo bản ghi ngày trong transaction.
- **Chốt bản đầu ngày** là nút riêng. Chỉ chốt ngày điều hành hiện tại, kiểm tra version ngày và version kế hoạch; ngày lịch sử được chọn độc lập để xem/so sánh, không được chốt ngược hoặc thay bản đầu ngày. Nếu có thay đổi nháp chưa lưu phải lưu hoặc hủy trước.
- Bản cũ trước 014 không có context đầy đủ được xem là thiếu snapshot; không cho chốt nó bằng cách ghép dữ liệu mới. Cần tính thử/lưu bản mới trước.
- Chốt chỉ trỏ tới snapshot đầy đủ đã lưu, không gọi tạo/sửa LSX, không cấp/giữ nhựa thêm. Bản sao kế hoạch theo ngày có thể dùng chung cùng snapshot bất biến nếu nội dung kế hoạch chưa đổi.
- Lưu cập nhật/chốt dùng kiểm tra quyền `PRODUCTION_EDIT`, khóa ERP/transaction hiện có, version lạc quan, audit và `Idempotency-Key`. Qua ngày khi còn nháp cũ phải tải lại; không tự đổi ngày hoặc tự chốt trong nền.

API bổ sung:

| API | Ý nghĩa |
| --- | --- |
| `GET /api/production/schedule/view` | Điều hành: bản cập nhật hôm nay hoặc nháp lấy từ ngày trước; trả thêm `day`, `snapshot_id`. |
| `POST /api/production/schedule/preview` và `/save` | Thêm `planning_day`, `day_version` tùy chọn; UI gửi chúng để chống stale/ngày đã chuyển. Contract cũ vẫn được tiếp nhận, hash cũng chứa trạng thái ngày. |
| `POST /api/production/schedule/daily/close` | `{day, day_version, plan_version, note}`, bắt buộc Idempotency-Key; chỉ chốt chủ động một lần. |
| `GET /api/production/schedule/daily/compare?day=YYYY-MM-DD&mode=actual\|update&view_start=...&view_end=...` | Ngày chốt độc lập khoảng sản xuất, cùng bộ lọc máy/khách hàng/từ khóa; GET chỉ đọc, không gọi bộ xếp lịch để tính lại lịch sử. |
| `GET /api/production/schedule/actual?view_start=...&view_end=...` | Nhật ký thực tế hiện ghi nhận, mức đầy đủ và timestamp audit/đọc dữ liệu. |

Ví dụ chốt (ID/version phải lấy từ dữ liệu thật, ngày là ngày Việt Nam hiện tại):

```json
{"day":"2026-11-16","day_version":3,"plan_version":12,"note":"Chốt sau họp điều hành"}
```

Không có bản đầu ngày của ngày chọn thì API so sánh trả thông báo chưa chốt; không thay bằng kế hoạch mới nhất và giả là bản đầu ngày.

### 3. Gantt thực tế và quy tắc đối chiếu

- [schedule_actual.py](backend/app/modules/production/schedule_actual.py) đọc nhật ký định hình và chi tiết ca; cắt/ép biên truy ngược nhật ký hút theo ID, kèm CTĐH và đơn vị. Truy vấn được khoanh theo khoảng sản xuất/máy và điều kiện CTĐH/khách hàng, nạp theo lô; không query từng ca.
- [schedule_compare.py](backend/app/modules/production/schedule_compare.py) đối chiếu theo `(run_id, stage)` và lượng từng CTĐH, không tạo hoặc sửa kế hoạch. Khung theo CTĐH vẫn dùng liên kết thành viên thực tế và ID ổn định; lần mới ngoài bản chốt được đánh dấu ngoài bản chốt, không gộp giả vào ID cũ.
- Thời gian native lấy `shift_start/shift_end` hoặc ngày giờ đầy đủ trong snapshot công đoạn. Nhật ký cũ chỉ ghép ngày + giờ khi cùng ngày được xác minh bằng giờ kết thúc > bắt đầu; ca qua ngày thiếu datetime rõ ràng được đánh dấu thiếu/không rõ, không tự đoán. Audit time **không dùng làm khoảng sản xuất**.
- Nhật ký nhập muộn/sửa được phép chỉ đổi nguồn nhật ký và audit như nghiệp vụ hiện có; màn hình so sánh đọc mới theo ngày sản xuất. Không ghi lại snapshot hoặc con trỏ bản chốt/cập nhật khi đọc nhật ký.
- Thiếu nhật ký: **Chưa có dữ liệu**. Có nhật ký thiếu giờ/liên kết/đơn vị/sản lượng: đánh dấu thiếu, không vẽ thanh có thời gian giả. Số bìa ở header lịch sử không tự đổi thành số sản phẩm theo cavity hiện tại.
- Khoảng trống nhật ký giữ nền trung tính, không lấy lịch nghỉ kế hoạch hoặc phần giữa hai ca làm thời gian máy nghỉ. Ở chế độ thực tế không tô lịch nghỉ kế hoạch lên phần thực tế; các đoạn chưa xác định của bản chốt có nhãn/phạm vi lớp kế hoạch riêng.
- Trả máy, bắt đầu, kết thúc đã ghi nhận, lượng tốt theo CTĐH/đơn vị, trạng thái chưa hoàn thành hoặc đủ theo bản chốt trong phạm vi xem. Kết thúc đã ghi nhận không tự coi là kết thúc cuối cùng nếu lần chạy còn mở.
- Chỉ so chạy thuần khi có số liệu thuần rõ ràng và phạm vi dữ liệu đủ. Không lấy độ dài ca, giây/chu kỳ × số chu kỳ hay khoảng trống lịch làm số đo thực tế. Lần đã kết thúc nhưng thiếu lượng đối chiếu vẫn hiện số đo đã ghi nhận; chưa kết luận đủ phạm vi/hoàn thành để tính sai lệch thuần.
- Khoảng xem cắt một phần nhật ký/lô: giữ thanh theo giờ thật, cắt hiển thị ở biên; không chia tỷ lệ sản lượng hoặc thời gian thuần để cho ra con số giả. Trả phạm vi dữ liệu không đầy đủ và bỏ giá trị so không xác định.
- Thời điểm cập nhật thực tế từ audit của **các nhật ký đang đọc**, tách khỏi `retrieved_at` (lúc truy vấn). Nhật ký lịch sử không có audit phù hợp trả null và cờ thiếu timestamp, không lấy ngày sản xuất giả làm giờ nhập liệu.
- Giới hạn thực tế: 2000 nhật ký/dòng native theo truy vấn; so sánh tối đa 100 máy/500 CTĐH. Vượt phạm vi yêu cầu thu hẹp, không âm thầm bỏ các thanh/ràng buộc.

### 4. Giao diện và cách sử dụng

[schedule.js](frontend/production/schedule.js), [schedule.css](frontend/production/schedule.css) thêm ngay trên màn hình giai đoạn 5:

- Chế độ **Điều hành · bản cập nhật**.
- **So sánh · đầu ngày với thực tế**: viền cam là bản chốt, thanh xám là thực tế đang ghi nhận. Nhật ký đã có trong bản chụp được ghi nhãn riêng, khác nhật ký đọc trực tiếp.
- **So sánh · đầu ngày với cập nhật**: viền cam là bản chốt, viền xanh là bản cập nhật của đúng ngày chọn.
- Ngày chốt tách khỏi từ/đến ngày sản xuất; bấm Tải chế độ để đọc, không query khi gõ/chọn điều kiện. Có cả Theo máy và Theo CTĐH cho ba chế độ. So sánh chỉ đọc, không kéo sửa/mở editor để thay lịch sử.
- Nút **Chốt bản đầu ngày** có xác nhận nội dung toàn kỳ và ghi chú. Chưa có snapshot đầy đủ hoặc còn thay đổi nháp thì cần lưu/hủy trước. Không có tự chốt lúc sang ngày.
- Bảng đối chiếu hiện máy/giờ/lượng tốt, sai lệch giây, chạy thuần chỉ khi so được, mức thiếu dữ liệu và trạng thái hoàn thành. Thời điểm audit cập nhật và thời điểm đọc hiện riêng trên đầu màn hình.

Chạy thuần đo được nhập tùy chọn tại màn hình nhật ký giai đoạn 3, [runs.js](frontend/production/runs.js). Backend [run_schemas.py](backend/app/modules/production/run_schemas.py)/[run_service.py](backend/app/modules/production/run_service.py) nhận `pure_seconds`, kiểm tra hữu hạn/không âm/không vượt khoảng sản xuất và lưu vào JSON snapshot ca/công đoạn. Bỏ trống là **chưa biết**, không chuyển thành 0. Chỉ sửa ca theo quy tắc ca cuối/chưa dùng ở công đoạn sau hiện có; không mở lại ca cũ để điền số đo.

### 5. Setting giờ chung T2–CN

[calendar-settings.html](frontend/production/calendar-settings.html), [calendar-settings.js](frontend/production/calendar-settings.js): nạp thiết lập, nhập một lần giờ làm/nghỉ chung, bấm **Áp dụng vào T2–CN** để điền cả 7 dòng trong nháp. Sau đó sửa thủ công từng thứ và bấm Lưu. Một ngày cụ thể khác lịch tuần vẫn dùng ngoại lệ ngày/máy trong Dữ liệu nền.

Tận dụng `system_settings`/calendar service hiện có; không thêm bảng hoặc nguồn lịch khác. Nút áp dụng tuần chưa ghi DB; chỉ nút Lưu mới kiểm tra version và ghi. Máy có lịch riêng và ngoại lệ theo ngày giữ ưu tiên cũ. Sửa lịch hiện tại không đổi `context`/lịch nghỉ của snapshot đã chốt.

### 6. Kiểm tra thực tế và phần còn chờ

- Đã đọc source/AGENTS mới và bàn giao trước; đã kiểm tra schema MySQL chỉ đọc: revision **011**, `audit_log.created_at` là datetime và `entity_id` hiện hữu; chưa có schema snapshot ngày/context mới. Không đọc/in secret.
- Đã build image backend chuẩn bị triển khai; kiểm tra tĩnh cú pháp Python/JavaScript, import/ORM/OpenAPI trong container network tắt với cấu hình giả. Editor diagnostics ở các file giai đoạn 6 đã kiểm tra không báo lỗi. Chi tiết bản build cuối được chốt dưới đây.
- [test_production_comparison.py](backend/tests/test_production_comparison.py) chuẩn bị targeted cases thiếu nhật ký, không nội suy phần ca, thiếu chạy thuần, lần đang mở, kết thúc nhưng thiếu lượng và ID ổn định/máy đổi; **chưa chạy**.
- Chưa chạy test tự động, chưa nghiệm thu browser/API/MySQL concurrency; không tuyên bố các luồng đã pass test. Cần cho phép targeted tests sau.
- Chưa áp dụng 012–014 hoặc cập nhật backend đang phục vụ. Cần duyệt các migration cụ thể và sao lưu trước khi thực hiện. Không production.
- Đầu vào nghiệm thu: dữ liệu thật có ca/datetime sản xuất đúng, liên kết CTĐH/nguồn rõ ràng; số đo chạy thuần chỉ nhập khi có. Dữ liệu lịch sử thiếu ca/đơn vị/audit vẫn hiển thị thiếu, không được tự sửa để làm biểu đồ đầy.
- Cần kiểm thử sau duyệt: chốt một lần/không ghi đè, thay bản cập nhật nhiều lần nguyên tử, chuyển ngày không ghi/chốt tự động, snapshot nguyên vẹn sau sửa định mức/lịch/nhật ký muộn, hai người lưu/chốt đồng thời, so sánh theo ngày chốt độc lập kỳ sản xuất và cả hai khung Gantt.

Ghi chú phạm vi so sánh:

- Khi một lần chạy trong bản chốt chuyển sang máy khác/thay thành phần nhóm, đọc thêm nhật ký của chính ID lần chạy liên quan trong khoảng sản xuất để không báo nhầm “không có dữ liệu” chỉ vì máy thực tế khác bộ lọc. Không nạp thêm đơn không liên quan; vẫn giữ giới hạn số bản ghi/máy/CTĐH.
- Nếu thanh kế hoạch và thanh đối chiếu nằm ở hai khoảng ngày khác nhau, bảng giữ ngày giờ nguyên gốc của bản chụp làm ngữ cảnh và ghi **Bản chụp xếp ngoài khoảng đang xem**, thay vì coi lần chạy chưa từng được lập kế hoạch. Muốn xem đủ thanh, mở rộng khoảng sản xuất.
- Timestamp audit đối chiếu cả loại công đoạn, tránh gán giờ cập nhật của phiếu Cắt cho phiếu Ép biên nếu hai bảng có ID trùng nhau. Thiếu audit đúng loại vẫn là chưa xác định.

Bằng chứng build/kiểm tra tĩnh cuối giai đoạn 6:

- Image local `napaco-local-backend`: `sha256:d929bc651aa03f4c48904de4c2cc2f75cf01ee828321decae69e1fe631263190`.
- Compile Python module sản xuất, migration 014 và file test so sánh; import registry, cấu hình ORM và sinh OpenAPI ba router liên quan: thành công, 38 paths. Chạy trong container `--network none` với cấu hình giả, không truy cập database.
- Node `--check` và đối chiếu tĩnh ID HTML/JavaScript cho schedule, calendar-settings, runs: thành công.
- `git diff --check` trên phần tracked: không báo lỗi. Các file module mới hiện là untracked trong working tree, đã nằm ở source thật và được đưa vào image build; chưa tạo commit.
- Các kết quả trên là kiểm tra build/tĩnh, không phải kết quả test chức năng. Không chạy các targeted tests đã chuẩn bị; không thao tác tạo/chốt kế hoạch thật. Backend đang phục vụ chưa recreate; MySQL vẫn revision 011, migration 012–014 chưa áp dụng.

## Giai đoạn 7 — gợi ý thông số và nghiệm thu tích hợp local

### 1. Schema, migration và dữ liệu

- Không thêm bảng hoặc migration 015. Gợi ý đọc trực tiếp `production_orders`, chi tiết lần chạy, `forming_logs`, chi tiết ca/vật liệu và nhật ký Cắt/Ép biên hiện hành. Nguồn được chọn lưu vào `run_snapshot.history_applied`; công đoạn sau lưu vào policy/snapshot kế hoạch. Setup đo được dùng JSON ca/công đoạn sẵn có.
- Bổ sung trường input `approved` cho lưu **phiên bản** định mức; snapshot phiên bản mới lưu `approval={approved,by,at}` khi người có quyền chủ động chọn duyệt. Không sửa phiên bản cũ, không suy `active` thành đã duyệt, không tạo workflow/bảng quyền song song. Bản sao định mức trong lần chạy/bản kế hoạch cũ không đổi.
- Yêu cầu mới của người dùng đã cho phép test, tạo dữ liệu giả và build/deploy đầy đủ local, thay thế chỉ dẫn “chưa test” trước đó trong phạm vi này. Đã sao lưu MySQL local tại `backups/napaco-pre-phase7-20261114.sql.gz` kèm SHA256, quyền 0600, kiểm tra gzip thành công; không in dữ liệu hoặc bí mật.
- Đã áp dụng `alembic upgrade 014`, đi qua migration [012](backend/alembic/versions/012_production_runs.py), [013](backend/alembic/versions/013_production_scheduler.py), [014](backend/alembic/versions/014_daily_production_plans.py). Đã xác nhận revision MySQL là **014**. Đây là migration đã áp dụng local, không còn là bản đề xuất chờ duyệt.
- Kiểm kê trước khi dọn: Định hình 0, Cắt 1, Ép biên 1, WIP/setup/lần chạy/cấp nhựa/phân bổ 0. Đã xóa đúng nhật ký Cắt và Ép biên có ID cũ `CUT_261020_01`, DH_ID null, trong transaction sau sao lưu; ghi audit danh sách ID/backup. Không xóa audit hệ thống, đơn hàng, nhận màng hoặc master. Không dùng TRUNCATE/FK-disable.
- Dữ liệu giả giữ lại có prefix/ghi chú **DEMO7**. Tái sử dụng CTĐH `CT_261101_14`/`SP0006`, `CT_261106_08`/`SP0002`, nguồn nhận `N_NVL_261110_01`, `N_NVL_261110_06`, vật liệu `VL0001`, khuôn nguồn `CC0001`. Khả năng ghép/chạy trên khuôn này là giả định kiểm thử, không phải xác nhận kỹ thuật sản xuất.
- Tại thời điểm chốt báo cáo: **12 lần chạy, 11 nhật ký Định hình, 5 nhật ký Cắt, 4 nhật ký Ép biên, 7 snapshot kế hoạch, 1 ngày chốt**. Produced local của hai CTĐH lần lượt **435** và **44** (ban đầu 0); giữ nguyên lượng đơn và nhận màng, tồn khả dụng thay đổi đúng theo giao dịch mẫu. Các dữ liệu này được để nguyên cho người dùng kiểm tra.

### 2. API/service và quy tắc gợi ý

[history_schemas.py](backend/app/modules/production/history_schemas.py), [history_service.py](backend/app/modules/production/history_service.py), route trong [run_api.py](backend/app/modules/production/run_api.py):

`POST /api/production/run-suggestions` là thao tác đọc, được bảo vệ bởi **PRODUCTION_EDIT** tại backend. Không tạo lần chạy, phân bổ, nhật ký hoặc sửa định mức. Payload:

```json
{
  "standard_id": "ID phiên bản định mức thật",
  "machine_id": "DEMO7-DH-A",
  "items": [{"order_line_id":"CT_261101_14","cavity":5}],
  "stage": "forming",
  "pull_mm": 500
}
```

Với Cắt/Ép biên, gửi `stage=cutting|edge`, máy đúng công đoạn và `unit` đúng đơn vị năng suất, ví dụ `Cái`. Các thành viên trong `items` mô tả **cấu hình ghép định hình đầy đủ**; chỉ sản phẩm có tuyến áp dụng công đoạn mới được tính ở công đoạn đó. Một sản phẩm cần ép biên không bắt buộc sản phẩm khác trong nhóm cũng ép biên.

Response gồm `criteria`, `approved_standard`, `standard`, `latest`, `statistics`, `sample_runs`, `near_latest`, `excluded`, `warnings`, `context_hash`. Định mức đã duyệt chỉ chọn phiên bản được xác nhận chủ động và phù hợp sản phẩm/cavity/khuôn/vật liệu/đơn vị của cấu hình; khác máy/bước kéo được cảnh báo. Khi chưa có bản đã duyệt, trả null và cảnh báo, không gắn nhãn đã duyệt cho `active`.

- Khớp: tập sản phẩm + cavity + đơn vị (không dùng CTĐH thay sản phẩm), loại máy, khuôn, grade/màu nhựa, độ dày, khổ, bước kéo và máy. Chạy lẻ khác nhóm ghép; khác cavity/tập sản phẩm/khuôn/vật liệu không thành mẫu gần giống. Chỉ khác máy/bước kéo được tách vào gần giống.
- Đọc tối đa 200 lần chạy gần nhất có sản phẩm liên quan, lịch sử sản xuất 365 ngày, tối đa 4000 ca/8000 chi tiết downstream; có cảnh báo/giới hạn, không nạp toàn bộ bảng. Thống kê tối đa 30 lần phù hợp gần đây; lấy một aggregate cho mỗi lần chạy để ca nhiều không tăng giả số mẫu. Dữ liệu nạp theo lô; resolve công đoạn cùng cấu hình được dùng lại trong một lần prepare.
- Tốc độ Định hình = tổng **chạy thuần đã đo / chu kỳ đã ghi nhận**; Cắt/Ép biên = chạy thuần / tổng đầu vào đúng đơn vị của nhật ký. Không lấy tổng thời gian ca, nghỉ/chờ, khoảng trống nhật ký hoặc tốc độ danh nghĩa thay số đo. Header group không bị cộng giờ theo mỗi CTĐH.
- Kiểm tra nguồn native, ngày giờ, hữu hạn/dương, quan hệ sản lượng/cavity, cân đối tiêu hao từng nguồn, đơn vị và tập sản phẩm công đoạn. Không gán sản lượng header lịch sử thành sản phẩm. Chỉ sản phẩm cần công đoạn được dùng cho mẫu năng suất công đoạn; chữ ký nhóm gốc vẫn giữ đầy đủ.
- Mức thường đạt là **trung vị** aggregate theo lần chạy, dao động min/max, số mẫu riêng từng chỉ tiêu. Cần ít nhất **3 lần phù hợp đã kết thúc** mới cho áp dụng thống kê mặc định. Lần còn mở có thể xem riêng với cảnh báo dữ liệu một phần. Mẫu gần giống không được gộp vào thống kê.
- Khi ít nhất 5 mẫu, lọc tốc độ theo `abs(value-median) > max(3×1.4826×MAD, 0.5×median)`; tốc độ Định hình ngoài 0.05–3600 giây/chu kỳ bị loại ngay. Danh sách ID loại và lý do được trả rõ. Đây là chính sách nhận diện dữ liệu bất thường, không tự chỉnh nhật ký.
- Setup chỉ dùng `setup_seconds` đã nhập, cộng theo các ca của lần chạy; không suy phần thời gian còn lại là setup. Tiêu hao kg/chu kỳ và hao hụt chỉ khi số nguồn cân đối; hao hụt âm hoặc >100% không thành gợi ý hao hụt. Tỷ lệ đạt từ lượng tốt/tổng theo cùng đơn vị; không cộng đơn vị khác nhau. Chỉ tiêu thiếu dữ liệu trả thiếu, không biến thành 0.
- `history_selection={kind,context_hash,run_id?}` hỗ trợ `approved_standard|latest|statistics|near_latest`. Khi lưu lần chạy/công đoạn, backend tính lại tiêu chí/hash, kiểm tra nguồn chưa đổi và chụp nguồn + giá trị gợi ý + thông số thực sự áp dụng + người chọn. Chỉnh riêng được phép, nguồn gợi ý vẫn phân biệt với giá trị cuối. Đổi cấu hình/nhật ký khiến hash không còn khớp trả 409; bỏ nguồn để nhập thủ công hoặc tìm lại. Không cập nhật ngược định mức.
- `waste_percent` là override riêng có kiểm tra 0–100, được tính nhu cầu nhựa lại bằng service hiện có và giữ khi chuyển máy. Công thức kg/bìa vẫn dùng service đặt nhựa chung; kg tiêu hao/chu kỳ **không** được dùng thay công thức trọng lượng bìa vật lý.

### 3. File và giao diện

- [history.js](frontend/production/history.js): component dùng chung trong editor [schedule.js](frontend/production/schedule.js) và [runs.js](frontend/production/runs.js). Chỉ query sau bấm Tìm, hiển thị nguồn/tiêu chí/số mẫu/cảnh báo, áp dụng vào nháp bằng lựa chọn chủ động; frontend không tính công thức/statistics.
- [planning.html](frontend/production/planning.html), [planning.js](frontend/production/planning.js): xác nhận duyệt khi lưu phiên bản mới. Không tự check duyệt từ bản cũ. Backend [planning_service.py](backend/app/modules/production/planning_service.py) lưu người/thời điểm trong snapshot phiên bản.
- [run_schemas.py](backend/app/modules/production/run_schemas.py), [run_service.py](backend/app/modules/production/run_service.py): số đo setup/thuần, nguồn áp dụng, override hao hụt, chuẩn hóa độ chính xác nhật ký và kiểm tra chồng công đoạn.
- [schedule_schemas.py](backend/app/modules/production/schedule_schemas.py), [schedule_service.py](backend/app/modules/production/schedule_service.py): kiểm tra và freeze nguồn gợi ý công đoạn trong policy/context dùng cho cả tính thử/lưu; backend quyết định tính hợp lệ.
- Quyền duyệt/lập/sửa/gợi ý tiếp tục dùng **PRODUCTION_EDIT** hiện có, LOCAL_ADMIN theo quy tắc sẵn có. Không thay role matrix hoặc tạo quyền song song. Test tài khoản không có quyền bị 403, không xác thực bị 401.
- [KE_HOACH_SAN_XUAT_VAN_HANH.md](./KE_HOACH_SAN_XUAT_VAN_HANH.md): trình tự từ lịch/định mức → phân bổ → lần chạy/Gantt → nhật ký → chốt/so sánh và cách xem từng mã DEMO7.

### 4. Lỗi tích hợp đã khắc phục

- Test phase 3 trước đây thiếu import fixture và mang lệnh legacy chưa kết thúc từ fixture phase 2, khiến bài test không vào được luồng native. Sửa fixture đúng nghiệp vụ, không nới guard lệnh cũ trong source.
- MySQL DATETIME/TIME hiện có chính xác giây có thể làm tròn microseconds sang giây sau. Backend nay truncate trước validate/lưu, dùng cùng mốc trong JSON công đoạn, kiểm tra khoảng tối thiểu 1 giây và tổng setup/thuần sau chuẩn hóa. Không đổi kiểu cột hoặc sửa thời gian nhật ký đã lưu.
- Cắt/Ép biên nay kiểm tra actual trên cùng máy trong transaction chung, từ chối nhật ký chồng giờ hoặc nguồn lịch sử thiếu giờ cần đối soát; cùng lô ghép ghi một header nhiều sản phẩm. Bàn giao nhiều lần vẫn được phép ở các khoảng không chồng và không vượt nguồn.
- Giữ override hao hụt khi chuyển máy/sửa nháp thay vì rơi về giá trị định mức. Chữ ký lịch sử công đoạn giữ cấu hình ghép đầy đủ nhưng chỉ tính sản phẩm thực sự áp dụng công đoạn; tránh chặn sai nhóm chỉ một sản phẩm ép biên.

### 5. Kiểm tra thực tế và tái hiện

Các kiểm tra dưới đây đã thực hiện trên local, không production:

- Targeted pytest cho sáu file production planning/material allocations/runs/schedule/comparison/history; có kiểm thử quyền, source/hash, không tự cập nhật định mức, mẫu thiếu/bất thường, giây chính xác, ca sau, nhóm tùy ép biên. Kết quả lần cuối và image ở ghi chú cuối mục này.
- [production_demo.py](backend/scripts/production_demo.py): tạo dữ liệu có checkpoint qua API/service hiện hành, chốt bản đầu ngày, lưu cập nhật, cảnh báo/chấp thuận chuyển máy, đổi thứ tự, chen đơn/chạy phần thiếu, stop preview, exception xuyên nghỉ và nhật ký nhập muộn. API harness dùng tài khoản LOCAL_ADMIN hiện có qua dependency override trong tiến trình test riêng; không thay xác thực/role của backend phục vụ.
- [production_acceptance.py](backend/scripts/production_acceptance.py): cấp–trả chờ/nhận kho–chuyển nguồn–cân đối ca; nháp ngày mới không INSERT/không tự chốt; gợi ý Cắt đóng băng trong policy; lưu trạng thái hold/release mẫu để người dùng xem.
- [production_concurrency.py](backend/scripts/production_concurrency.py): cấp đồng thời chốt ca. Lần thực hiện nhận `[201,409]`, chốt cũ bị từ chối do run version; retry version mới thành công, số dư đúng **1 kg**, chốt cân đối về 0 và kết thúc. Không mất/nhân đôi lượng cấp.
- Hai thread giữ 75% khả dụng trên cùng nguồn: **một 201, một 409**; giải phóng phần giữ phát sinh riêng của bài race. Hai thread lưu cùng base/hash: **một 201, một 409**, không ghi đè phiên bản của người khác.
- [production_verify.py](backend/scripts/production_verify.py): duyệt chủ động bản mới giữ nguyên bản cũ; apply-preview có snapshot nguồn nhưng không tạo lệnh; một ca hút ghép được Cắt hai lần và Ép biên riêng sản phẩm cần ép biên; chồng máy bị 409 với lý do chồng máy, mẫu nhóm một lần có cảnh báo ít mẫu.
- So sánh cả `actual`/`update` chạy trên MySQL và kiểm tra serialized request/result/context bản đầu ngày trước/sau chỉnh kế hoạch, ghi actual muộn: giữ nguyên. Nguồn thực tế thay đổi không rewrite bản chốt.
- Bộ dữ liệu dựa trên đơn hàng/nhận màng thật local, phần sản xuất/định mức DEMO7 là giả. Các movement **do script vừa tạo** được ghi ngày giả theo ngày sản xuất, có audit `PRODUCTION_DEMO_MOVEMENT_DATE`; không backdate nhận màng hoặc chứng từ gốc. Audit vẫn là lúc nhập, phục vụ kiểm tra nhập muộn.
- Báo cáo [production-phase7-demo.json](reports/production-phase7-demo.json) lưu từng checkpoint và kết quả, nguồn/snapshot/ID để truy vết. Script yêu cầu `--local-demo`, kiểm tra DB host compose `mysql`, giữ dữ liệu, không tự xóa khi chạy lại; checkpoint tránh cấp/sản xuất hai lần. Không chạy các script này trên production hoặc xóa report rồi chạy lại trên DB đã có DEMO7.

### 6. Triển khai và giới hạn bàn giao

- Đã build và recreate backend + qc-worker local; MySQL giữ volume hiện hữu, không dùng `down -v`. Frontend mount theo compose. Worker kiểm tra healthy; API bị bảo vệ vẫn trả 401 khi chưa đăng nhập, trang kế hoạch chuyển tới đăng nhập.
- Không thêm dependency hoặc thư viện Gantt mới. Chưa tạo commit; toàn bộ source mới ở working tree thật và được đưa vào image build.
- **Chưa nghiệm thu UI tương tác sau đăng nhập**: trình duyệt tích hợp mở tới login; không đọc mật khẩu, không lấy token/session để vượt đăng nhập. Các kiểm tra API/MySQL dùng harness và kiểm tra HTTP boundary nêu trên; không gọi chúng là browser end-to-end.
- Dữ liệu cũ thiếu đo thuần/ngày giờ/đơn vị/liên kết vẫn không có gợi ý đáng tin; không tự backfill hoặc sửa để làm mẫu. Khả năng cấu hình/khuôn DEMO7 cần xưởng xác minh trước dùng thực tế. Chưa có Bế Dán.
- Không triển khai production. Nếu triển khai môi trường khác, cần backup, đối chiếu revision/schema và kiểm thử dữ liệu riêng; không mang dữ liệu DEMO7 hoặc kết quả đồng thời local thành chứng nhận production.

Đối chiếu loại nhựa ở bản cuối:

- Schema thực tế có `film_order_lines.resin` (PP/PET/...), còn `film_materials.grade` là NS/A/B...; hai trường không bị dùng thay nhau. Signature nhật ký bao gồm mã vật liệu, grade, màu, ESD, kích thước và polymer truy qua N_NVL_ID → dòng đặt màng. Ví dụ nguồn DEMO7 là **PP**, grade **NS**.
- `HistoryQuery.allocation_ids` tùy chọn cho phép đối chiếu đúng phần giữ được chọn trong editor; nếu chưa chọn thì chỉ xét các nguồn đang giữ cho CTĐH/vật liệu. Chưa xác minh đúng một loại nhựa sẽ cảnh báo và không tạo mẫu tốc độ mặc định; nguồn khác PP/PET dù cùng material/grade/kích thước không bị trộn.
- Khi lưu, backend dựng lại query từ các binding allocation của lần chạy. Các nhật ký native được đối chiếu loại nhựa từ nguồn thực tế ghi trong `production_shift_materials`, không từ tên sản phẩm hoặc tỷ trọng. Tiêu chí/source tại lúc áp dụng được freeze; bản chụp đã lưu không đọc lại master để đổi lịch sử.
- Định mức hiện hữu chỉ chụp mã vật liệu, chưa có trường polymer riêng: API ghi rõ `resin_verification=selected_receipts_only_not_standard_snapshot` và cảnh báo. Không giả rằng phiên bản đã duyệt đã từng chụp polymer; người lập kế hoạch phải đối chiếu nguồn. Xác nhận duyệt phiên bản vẫn giữ nguyên và riêng với lịch sử nhật ký đo được.

Bằng chứng bàn giao cuối giai đoạn 7:

- Image đang triển khai: `sha256:e5e2f72c4615d16122a212986438511be9896bb53193a27948d270c5e1109487`.
- **39 targeted tests passed** trong chính image này, SQLite cô lập/network none. Có cảnh báo deprecation sẵn có từ thư viện; không chạy toàn bộ suite ngoài module.
- Cú pháp JavaScript cho history/schedule/runs/planning/calendar-settings và static HTML/JS IDs đạt; editor diagnostics các source chính không báo lỗi. `git diff --check` tracked đạt. Không dùng các kết quả này thay cho browser nghiệm thu.
- Recreate backend + qc-worker bằng image cuối, MySQL revision **014**. Đã xác nhận HTTP `/login` 200, trang kế hoạch khi chưa login 303 và API kế hoạch 401.
- Sau toàn bộ dữ liệu nhập muộn, trên chính backend đang phục vụ: tính thử trả **5 jobs**, so sánh actual **23 dòng**, update **11 dòng**; chỉ đọc/tính thử, không lưu kế hoạch mới. Query gợi ý xác minh polymer **pp**, máy A có **4** mẫu, máy B có **1** mẫu (cảnh báo ít mẫu), định mức được duyệt phiên bản **3**.
- Toàn bộ dữ liệu DEMO7 và bản chốt/cập nhật vẫn giữ nguyên để người dùng xem. Handoff và báo cáo JSON phân biệt rõ script/API/MySQL, HTTP boundary, static checks và UI sau đăng nhập chưa nghiệm thu.
