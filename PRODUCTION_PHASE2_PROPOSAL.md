# Giai đoạn 2 — cấp NVL theo LSX và ký bàn giao

Trạng thái: người dùng đã duyệt phương án và migration 016; đã viết source giai đoạn 2. Theo chỉ đạo mới nhất, chỉ hoàn thiện code và tạm hoãn toàn bộ test để kiểm tra tập trung sau. Chưa áp dụng migration 016, chưa recreate dịch vụ hoặc deploy production. Xem [bàn giao source](./PRODUCTION_PHASE2_HANDOFF.md).

## Kết quả kiểm tra thực tế

- Đã đọc AGENTS.md, đối chiếu model và schema MySQL local: revision 015.
- Giai đoạn 1: 12 LSX hiện có đều legacy, chưa có mã chính thức; source đã có require_released, kiểm tra thành phần ghép còn hiệu lực, giới hạn bố trí NVL, version và khóa ERP. Bộ 10 test giai đoạn 1 vẫn chưa được xác nhận chạy; chưa tuyên bố nghiệm thu nghiệp vụ.
- film_movements dùng cột native id, moved_at, kind, production_order_id, receipt_id, quantity, issuer_id, receiver_id, source; không dùng tên cột sheet cũ.
- material_allocations giữ lượng chưa cấp trong held_kg; production_run_materials giữ tổng bố trí/issued_kg. material_allocation_movements liên kết phiếu với phân bổ, phiếu cấp gốc và nhóm chuyển.
- issue hiện gọi before_issue, giảm held_kg, tăng issued_kg và tạo một CẤP NVL trong cùng transaction. new_movement đang tự gán receiver_id=user.id cho mọi phiếu cấp.
- stock_expression và màn hình tồn qua lớp tương thích cùng tính: nhập thực nhận − toàn bộ CẤP NVL + TRẢ NVL đã có kho xác nhận. Trả chờ kho nhận không tăng tồn.
- Hiện có 10 CẤP NVL và 2 TRẢ NVL; tất cả đều có receiver_id. Không có cơ sở coi đây là chữ ký bàn giao theo luồng mới.
- shift_context và schedule_service đang cộng toàn bộ phiếu cấp vào nguồn tại máy; phải đổi điều kiện nhận nguồn, không chỉ sửa giao diện hoặc bỏ receiver_id tự điền.
- Cơ chế ký QC hiện có: nét ký giới hạn số điểm, xác minh tài khoản Google gắn phiên ERP, dấu xác nhận mã hóa có TTL, nonce, hash nội dung và dấu vết người/thời điểm/phương thức. Tái sử dụng identity/cipher/digest và cấu trúc dấu vết, giữ nguyên hành vi ký QC.

## Mô hình tồn và thời điểm ghi sổ đề nghị duyệt

| Bước | Sổ film_movements | Giữ/phân bổ | Tồn kho | Nguồn cho sản xuất |
| --- | --- | --- | --- | --- |
| Lập phiếu | Chưa tạo movement | Giữ nguyên held_kg; đánh dấu phần thuộc phiếu nháp để không lập trùng | Không đổi | 0 |
| Ký cấp | Tạo đúng một CẤP NVL và link hiện có; issuer_id lấy từ người ký, receiver_id trống | Giảm held_kg, tăng issued_kg đúng một lần | Trừ đúng một lần tại bước này | 0; toàn bộ ở chờ bàn giao |
| Ký nhận | Giữ nguyên movement/lô/số lượng; ghi đúng receiver_id và bằng chứng ký | Không trừ phân bổ lần nữa | Không đổi | Bắt đầu được ghi nhận từ thời điểm nhận |
| Trả NVL | Tái sử dụng TRẢ NVL và link tới cấp gốc | Theo luồng hiện có | Chỉ tăng khi kho xác nhận trả | Trừ phần đang trả khỏi lượng sử dụng để không dùng hai lần |

Phiếu mỗi lần cấp tiếp tục gắn một phân bổ/lô như API hiện tại; một LSX có nhiều phiếu và nhiều lô. Không bổ sung giới hạn một LSX một phiếu hoặc một lô.

Không ghi phiếu nháp vào film_movements: các đường tính tồn hiện có sẽ coi mọi CẤP NVL là đã xuất. Việc giữ nháp ở chứng từ bàn giao giúp giữ nguyên định nghĩa sổ kho và lớp tương thích.

## Migration 016 đề nghị duyệt

Thêm đúng một bảng material_handovers làm hồ sơ lập phiếu và chữ ký; film_movements vẫn là sổ biến động NVL duy nhất.

| Trường | Kiểu/quan hệ | Mục đích |
| --- | --- | --- |
| id | VARCHAR(36), PK | ID hồ sơ bàn giao nội bộ |
| run_id | VARCHAR(100), FK production_orders.ID_Lenh_SX | LSX đích, giữ ID nội bộ hiện có |
| allocation_id | VARCHAR(36), FK material_allocations.id, nullable | Phân bổ của cấp thông thường; chuyển có thể tạo phân bổ đích khi ký cấp |
| source_issue_id | VARCHAR(100), FK film_movements.id, nullable | Cấp gốc khi chuyển NVL |
| mode | VARCHAR(20), NOT NULL | issue hoặc transfer |
| quantity | DECIMAL(24,8), NOT NULL | Kg cần bàn giao |
| state | VARCHAR(24), NOT NULL | draft, awaiting_receipt, received, cancelled |
| version | INTEGER, NOT NULL | Chống ghi đè/ký nội dung cũ |
| movement_id | VARCHAR(100), FK film_movements.id, NULL, UNIQUE | Một hồ sơ gắn đúng một phiếu cấp khi ký cấp thành công |
| snapshot | JSON, NOT NULL | LSX chính thức, CTĐH, lô, vật liệu, số lượng, lý do và ngữ cảnh chuyển được ký |
| created_by / created_at | FK users.id / DATETIME, NOT NULL | Người/thời điểm lập |
| issued_by / issued_at | FK users.id / DATETIME, NULL | Người/thời điểm ký cấp |
| received_by / received_at | FK users.id / DATETIME, NULL | Người/thời điểm ký nhận |
| issue_signature / receipt_signature | JSON, NULL | Nét ký và bằng chứng danh tính, thời điểm, nonce, hash nội dung/phương thức |

Index theo (run_id,state), (allocation_id,state), (source_issue_id,state) phục vụ danh sách và kiểm tra phần nháp đã cam kết. UNIQUE movement_id bảo vệ liên kết một–một với phiếu cấp. Không thay kiểu dữ liệu, khóa hoặc quan hệ hiện hữu.

Migration chỉ tạo bảng rỗng và index/FK mới. Không tạo hồ sơ ký cho 12 giao dịch cũ, không sửa receiver_id, không chuyển số dư hoặc tạo movement lịch sử.

## Quy tắc backend và chữ ký

- Quyền cấp/ký nhận dùng quyền PRODUCTION_EDIT đang bảo vệ luồng cấp; chuyển vẫn cần thêm NVL_RECEIVE và NVL_STOCK_VIEW như hiện tại. Không thay ma trận quyền hay tự cấp thêm quyền tài khoản.
- Người nhận được ghi từ tài khoản thực hiện Ký nhận; không lấy danh tính người cấp để tự điền.
- Nét ký và dấu xác nhận phải ràng buộc ID phiếu, version, vai trò ký, LSX, lô, số lượng và nội dung đã ký cấp. Không dùng dấu QC để ký bàn giao hoặc dùng dấu ký cấp cho ký nhận.
- Sau ký cấp, nội dung phiếu bất biến. Ký nhận chỉ bổ sung chữ ký nhận; chưa hỗ trợ nhận một phần trong một phiếu. Muốn bàn giao nhiều lần thì lập nhiều phiếu đúng số thực giao.
- Mọi bước ghi dùng khóa ERP, khóa LSX/phân bổ/phiếu cần thiết, transaction, rollback và Idempotency-Key hiện có. Kiểm tra lại LSX đã phát/còn hiệu lực, CTĐH còn được thực hiện, lô OK, đúng vật liệu, bố trí và tồn trước ký cấp.
- Tổng phiếu nháp không được vượt held_kg hoặc phần bố trí chưa cấp. Sửa giữ nhựa/cập nhật kế hoạch không được làm thiếu phần đã cam kết cho phiếu đang mở. Cho hủy phiếu draft để giải phóng cam kết; hủy draft không tạo trả kho.
- Không cho kết thúc LSX khi còn phiếu ký cấp chờ nhận; không cho dùng phiếu chưa nhận để chốt ca, trả từ máy hoặc chuyển tiếp.
- Chuyển NVL tái sử dụng transaction trả xác nhận → giữ đích → cấp đích hiện có tại bước Ký cấp; phiếu cấp đích chờ người nhận ký. Tồn kho tổng không bị cộng/trừ lặp. Không tự gán người nhận ở bước chuyển.
- Bước Ký nhận không trừ tồn hoặc tăng issued_kg lần nữa. Kiểm tra chữ ký, phiên, version và sự khớp bất biến trước khi ghi người nhận thực sự.
- Không cho backend nhận user_id, thời điểm ký hoặc cờ đã ký do trình duyệt tự khai.

## API và giao diện sẽ triển khai sau duyệt

- Lập/danh sách/chi tiết/hủy nháp phiếu bàn giao; phiếu luôn hiển thị mã LSX chính thức, ID nội bộ chỉ dùng trong request/liên kết.
- Xác nhận nét ký và Ký cấp/Ký nhận trên cùng phiếu; hiển thị hai vùng ký, người và thời điểm từng bước; có danh sách chờ ký nhận để tài khoản người nhận mở phiếu của mình.
- Endpoint dữ liệu NVL theo LSX và N_NVL_ID: lượng đã ký cấp, đang bàn giao, đã ký nhận, trả chờ/đã xác nhận, tiêu hao đã chốt, lượng còn dùng được và mức chắc chắn của số dư.
- Nhật ký dùng thời điểm Ký nhận làm thời điểm đủ điều kiện nguồn. Ca kết thúc trước lúc nhận không được dùng phiếu vừa nhận sau đó. Phiếu được gán vào ca đúng một lần, không cộng lại ở ca tiếp theo.
- Scheduler/readiness tách nguồn chờ bàn giao với nguồn đã nhận. Có thể hiển thị lượng chờ là nguồn kế hoạch, không coi là lượng sản xuất sử dụng được.
- Tái sử dụng source_position, ShiftMaterial, phương trình số dư theo lô và liên kết cấp–trả; không tạo sổ tồn thứ hai.

## Tương thích dữ liệu cũ đề nghị duyệt

- 10 phiếu cấp cũ không có hồ sơ ký mới được gắn nhãn legacy_unverified khi đọc; receiver_id chỉ là thông tin lịch sử.
- Giữ nguyên tác động tồn kho, cấp/trả, số dư và nhật ký đã ghi. Hai phiếu trả đã xác nhận vẫn tăng tồn như trước, không yêu cầu ký lại.
- Không đưa số cấp cũ vào received_signed_kg. Số dư đã đo ở ca cũ được trình bày riêng là legacy_measured_carry_kg, không giả thành chữ ký nhận.
- API nguồn sử dụng mới không tự mở lượng lịch sử chưa có bằng chứng nhận theo cơ chế mới. Muốn tiếp tục dùng số dư cũ cần bước đối soát/xác nhận chuyển tiếp rõ ràng; không tự thực hiện bước này hoặc tự hồi tố chữ ký trong migration.
- Trả/đối soát lô cũ vẫn đi theo đường hiện tại và kiểm soát kho xác nhận; không bắt người dùng sửa lại chứng từ lịch sử.
- Hệ quả cần biết: môi trường local hiện chỉ có dữ liệu legacy; danh sách nguồn đã ký nhận theo cơ chế mới ban đầu sẽ rỗng, không phải mất tồn kho.

## Phạm vi file và kiểm tra

- Model/migration mới cho hồ sơ; service/API bàn giao tái sử dụng allocation_service.issue/transfer và signing.identity.
- Điều chỉnh điểm cấp trực tiếp và giao diện materials để không có đường bỏ qua chữ ký; giữ endpoint/lógica trả hiện tại.
- Điều chỉnh shift_context, scheduler/readiness và API số dư theo lô để loại pending khỏi lượng dùng sản xuất, đồng thời giữ số liệu lịch sử với provenance riêng.
- Sau sửa sẽ kiểm tra diff, hỏi trước khi chạy test theo AGENTS.md. Test dự kiến: ký sai tài khoản/phiên/nội dung/vai trò, ký lại/retry, hai người cấp đồng thời, nhiều lô/nhiều lần, lượng pending không dùng được, nhận không trừ kho hai lần, ràng buộc thời gian ca, chuyển/ trả và dữ liệu legacy.
- Không deploy production hoặc ghi thử dữ liệu thật.
